from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from app.core.config import app_config, settings
from app.db.init_db import init_db
from app.db.seeder import seed_data
from app.db.session import async_session
from app.models.background_job import BackgroundJob
from app.models.experiment import Experiment
from app.models.experiment_file import ExperimentFile
from app.models.user import User
from app.models.data_egress import UserEgressDefaults
from app.models.workflow_template import WorkflowTemplate
from app.services.experiments import (
    create_experiment,
    add_experiment_file,
    metadata_path_for,
    write_metadata,
)

logger = logging.getLogger(__name__)

# Default secret key that should NOT be used in production
DEFAULT_SECRET_KEY = "your-super-secret-key-change-in-production"


def validate_concurrency_settings() -> None:
    """
    Validate concurrency-related settings and warn about multi-worker deployments.

    Checks:
    - File locking availability (fcntl on Unix)
    - Rate limiter persistence path
    - Logs info about database-backed job management
    """
    import os

    # Check if we're likely in a multi-worker environment
    # (Gunicorn sets GUNICORN_ARBITER, Uvicorn doesn't have a reliable env var)
    is_gunicorn = "GUNICORN_ARBITER" in os.environ or "gunicorn" in os.environ.get("SERVER_SOFTWARE", "")

    # Check for fcntl (file locking) availability
    try:
        import fcntl
        has_fcntl = True
    except ImportError:
        has_fcntl = False

    if app_config.mode in ("hybrid", "demo"):
        if not has_fcntl:
            logger.warning(
                "File locking (fcntl) not available on this platform. "
                "Rate limiting in multi-worker deployments may not be accurate. "
                "Consider using Redis-backed rate limiting for production."
            )

        # Info about current concurrency model
        logger.info(
            f"Concurrency model: "
            f"rate_limiter=file-locked, job_manager=database-backed, "
            f"max_concurrent_jobs={settings.max_concurrent_jobs}"
        )


def validate_security_settings() -> None:
    """
    Validate security-critical settings at startup.

    In non-local modes (hybrid, demo, cloud), ensures:
    - SECRET_KEY is not the default value
    - MASTER_ENCRYPTION_KEY is set (warning only)

    Raises:
        SystemExit: If critical security settings are invalid
    """
    if app_config.mode == "local":
        # Local mode: security validation is relaxed
        if settings.secret_key == DEFAULT_SECRET_KEY:
            logger.warning(
                "Using default SECRET_KEY in local mode. "
                "This is acceptable for development but not recommended."
            )
        return

    # Non-local modes: strict security validation
    if settings.secret_key == DEFAULT_SECRET_KEY:
        logger.critical(
            f"SECURITY ERROR: Cannot start in '{app_config.mode}' mode with default SECRET_KEY!\n"
            f"Please set a secure SECRET_KEY environment variable.\n"
            f"Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
        sys.exit(1)

    # Check encryption key (warning, not fatal)
    import os
    if not os.getenv("MASTER_ENCRYPTION_KEY"):
        logger.warning(
            "MASTER_ENCRYPTION_KEY not set. A key will be auto-generated, but this "
            "may cause issues if the container is recreated. Set this environment "
            "variable for persistent API key encryption."
        )


def ensure_data_dirs() -> None:
    (settings.data_dir / "experiments").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "calibrations").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "nist_library" / "downloaded").mkdir(
        parents=True, exist_ok=True
    )
    (settings.data_dir / "user").mkdir(parents=True, exist_ok=True)


async def ensure_database_ready() -> None:
    await init_db()
    # Auto-seed if configured or in dev/demo mode
    # For now, we always try to seed if the seed dir exists
    await seed_data()


async def ensure_default_user() -> None:
    try:
        async with async_session() as session:
            result = await session.execute(select(User).limit(1))
            user = result.scalar_one_or_none()
            if user is None:
                session.add(User(username="local", password_hash="local"))
                await session.commit()
    except OperationalError:
        logger.warning("Skipping default user creation; database not initialized.")


async def ensure_egress_defaults() -> None:
    """
    Ensure all users have default egress settings.

    This backfills UserEgressDefaults for existing users so hybrid/demo
    permissions work consistently after upgrades.
    """
    try:
        async with async_session() as session:
            result = await session.execute(
                select(User)
                .outerjoin(UserEgressDefaults)
                .where(UserEgressDefaults.user_id.is_(None))
            )
            users_missing = result.scalars().all()
            if not users_missing:
                return

            for user in users_missing:
                session.add(
                    UserEgressDefaults(
                        user_id=user.id,
                        allow_spectrasherpa_sync=False,
                        allow_llm_context=True,
                        allow_export=True,
                        allow_nist_queries=True,
                    )
                )
            await session.commit()
            logger.info(f"Created egress defaults for {len(users_missing)} user(s).")
    except OperationalError:
        logger.warning("Skipping egress defaults backfill; database not initialized.")


async def reconcile_stale_jobs() -> None:
    try:
        async with async_session() as session:
            now = datetime.now(timezone.utc)
            stale_cutoff = now - timedelta(minutes=5)
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.status == "running")
                .where(BackgroundJob.last_heartbeat.is_not(None))
                .where(BackgroundJob.last_heartbeat < stale_cutoff)
                .values(
                    status="failed",
                    error_message="Job heartbeat stale",
                    completed_at=now,
                )
            )
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.status == "running")
                .values(
                    status="failed",
                    error_message="Server restarted (job did not complete)",
                    completed_at=now,
                )
            )
            await session.commit()
    except OperationalError:
        logger.warning("Skipping job reconciliation; database not initialized.")


async def ensure_spectrochempy_testdata() -> None:
    """
    Ensure SpectrochemPy test data directory is accessible for LLM.
    Scans ~/.spectrochempy/ and creates a reference experiment with directory info.
    """
    try:
        # Define the spectrochempy directory in user home
        spectrochempy_dir = Path.home() / ".spectrochempy"
        if not spectrochempy_dir.exists():
            logger.info("SpectrochemPy directory ~/.spectrochempy not found, skipping")
            return

        async with async_session() as session:
            # Get default user
            result = await session.execute(select(User).limit(1))
            user = result.scalar_one_or_none()
            if not user:
                logger.warning("No default user found, cannot create spectrochempy reference")
                return

            # Check if reference experiment already exists
            result = await session.execute(
                select(Experiment).where(Experiment.name == "SpectrochemPy Test Data")
            )
            experiment = result.scalar_one_or_none()

            # Count available test files and subdirectories (optimized single pass)
            subdirs = [d for d in spectrochempy_dir.iterdir() if d.is_dir()]
            allowed_extensions = {".csv", ".jdx", ".dx", ".spc", ".spa", ".spg"}
            test_files = [
                f for f in spectrochempy_dir.rglob("*")
                if f.is_file() and f.suffix in allowed_extensions
            ]

            # Check for reference PDF
            pdf_ref = spectrochempy_dir / "spectrochempy_testdata_reference.pdf"
            has_pdf = pdf_ref.exists()

            metadata = {
                "source": "spectrochempy",
                "auto_loaded": True,
                "base_path": str(spectrochempy_dir),
                "subdirectories": [d.name for d in subdirs],
                "file_count": len(test_files),
                "reference_pdf": str(pdf_ref) if has_pdf else None,
                "instructions": "Files are accessible from ~/.spectrochempy/. Do not load all files into database."
            }

            # Create or update experiment
            if not experiment:
                logger.info("Creating SpectrochemPy Test Data reference")
                experiment = await create_experiment(
                    session=session,
                    user_id=user.id,
                    name="SpectrochemPy Test Data",
                    description=f"Reference to test datasets in ~/.spectrochempy/ ({len(test_files)} files in {len(subdirs)} subdirectories)",
                    metadata=metadata,
                )
                logger.info(f"SpectrochemPy reference created: {len(test_files)} files, {len(subdirs)} subdirs, PDF: {has_pdf}")
            else:
                # Update metadata with current file counts
                metadata_file = metadata_path_for(experiment.id)
                write_metadata(metadata_file, metadata)
                logger.info(f"SpectrochemPy reference updated: {len(test_files)} files, {len(subdirs)} subdirs, PDF: {has_pdf}")

    except OperationalError:
        logger.warning("Skipping SpectrochemPy test data setup; database not initialized.")
    except Exception as e:
        logger.error(f"Error setting up SpectrochemPy test data: {e}", exc_info=True)


async def ensure_workflow_templates() -> None:
    """
    Seed the database with common workflow templates if they don't exist.
    """
    try:
        from app.core.workflow_templates import WORKFLOW_TEMPLATES

        async with async_session() as session:
            # Check if any templates already exist
            result = await session.execute(select(WorkflowTemplate).limit(1))
            existing_template = result.scalar_one_or_none()

            if existing_template:
                logger.info(f"Workflow templates already seeded ({await session.scalar(select(func.count(WorkflowTemplate.id)))} templates)")
                return

            # Seed templates
            logger.info(f"Seeding {len(WORKFLOW_TEMPLATES)} workflow templates")
            for template_data in WORKFLOW_TEMPLATES:
                template = WorkflowTemplate(**template_data)
                session.add(template)

            await session.commit()
            logger.info(f"Successfully seeded {len(WORKFLOW_TEMPLATES)} workflow templates")

    except OperationalError:
        logger.warning("Skipping workflow template seeding; database not initialized.")
    except Exception as e:
        logger.error(f"Error seeding workflow templates: {e}", exc_info=True)
