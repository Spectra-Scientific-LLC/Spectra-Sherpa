from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.db.init_db import init_db
from spectra_sherpa.app.db.seeder import seed_data
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.data_egress import UserEgressDefaults
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.experiments import (
    create_experiment,
    add_experiment_file,
    metadata_path_for,
    write_metadata,
)

logger = logging.getLogger(__name__)

# Default secret key that should NOT be used in production
DEFAULT_SECRET_KEY = "your-super-secret-key-change-in-production"
DEFAULT_API_KEY = "default-local-key"


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

    if app_config.mode in ("hybrid", "enterprise"):
        web_concurrency = os.getenv("WEB_CONCURRENCY", "").strip()
        if web_concurrency:
            try:
                workers = int(web_concurrency)
            except ValueError:
                workers = 1
            if workers > 1:
                logger.critical(
                    "WEB_CONCURRENCY=%s is not supported with in-memory WebSocket "
                    "channels — realtime events will be silently dropped across workers.\n"
                    "Set WEB_CONCURRENCY=1 (sufficient for <20 concurrent users).",
                    workers,
                )
                sys.exit(1)

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

    In non-local modes (hybrid, enterprise, cloud), ensures:
    - SECRET_KEY is not the default value
    - MASTER_ENCRYPTION_KEY is set (warning only)
    - Hybrid mode warns if bound to a non-loopback address

    Raises:
        SystemExit: If critical security settings are invalid
    """
    import os

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

    # APP_API_KEY: when ALLOW_SYSTEM_API_KEY_AUTH is enabled, it becomes a
    # shared authentication secret and must never remain at default value.
    system_key_auth_enabled = os.getenv("ALLOW_SYSTEM_API_KEY_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if settings.api_key == DEFAULT_API_KEY and system_key_auth_enabled:
        logger.warning(
            "APP_API_KEY is set to the default value while ALLOW_SYSTEM_API_KEY_AUTH "
            "is enabled. Set a strong random APP_API_KEY."
        )

    if os.getenv("TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}:
        trusted_proxy_cidrs = os.getenv("TRUSTED_PROXY_CIDRS", "").strip()
        if not trusted_proxy_cidrs:
            logger.warning(
                "TRUST_PROXY is enabled but TRUSTED_PROXY_CIDRS is not set. "
                "Only loopback proxy peers are trusted by default. "
                "Set TRUSTED_PROXY_CIDRS (e.g. 172.18.0.0/16) for container reverse proxies."
            )

    # Check encryption key (warning, not fatal)
    if not os.getenv("MASTER_ENCRYPTION_KEY") and app_config.mode != "local":
        logger.warning(
            "MASTER_ENCRYPTION_KEY not set — auto-generating. Stored API keys "
            "will be lost on container restart. Set this env var explicitly."
        )

    # Hybrid mode: warn if bound to a non-loopback address.
    # The auth middleware enforces loopback-only for unauthenticated hybrid
    # requests, so non-loopback clients will need a JWT or API key.
    if app_config.mode == "hybrid":
        bind_host = os.getenv("HOST", "127.0.0.1")
        loopback = {"127.0.0.1", "::1", "localhost"}
        if bind_host not in loopback:
            logger.warning(
                "SECURITY: Hybrid mode is bound to '%s'. Non-loopback clients "
                "must authenticate with a valid JWT or API key. Unauthenticated "
                "access is restricted to loopback (127.0.0.1) only.",
                bind_host,
            )


def ensure_data_dirs() -> None:
    (settings.data_dir / "experiments").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "calibrations").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "nist_library" / "downloaded").mkdir(
        parents=True, exist_ok=True
    )
    (settings.data_dir / "user").mkdir(parents=True, exist_ok=True)


async def ensure_database_ready(*, include_seed: bool = True) -> None:
    await init_db()
    if include_seed:
        # Auto-seed if configured or in dev/demo mode
        # For now, we always try to seed if the seed dir exists
        await seed_data()


async def wait_for_database_ready(timeout_seconds: int = 300) -> None:
    """Wait for leader worker to finish DB schema setup without mutating DB."""
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    last_error: Exception | None = None
    while datetime.now(timezone.utc) < deadline:
        try:
            async with async_session() as session:
                await session.execute(select(User.id).limit(1))
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)

    raise RuntimeError(
        f"Database was not ready within {timeout_seconds} seconds."
    ) from last_error


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


async def link_hybrid_identity() -> None:
    """Enrich the local user with server-side identity in hybrid mode.

    Calls ``GET /auth/me`` on the spectrasherpa-server using the configured
    ``SPECTRASHERPA_API_KEY``.  On success the default local user is updated
    with the server username and admin flag so that admin features, egress
    controls, and future entitlements work correctly.

    Gracefully degrades: if the server is unreachable the previously-synced
    identity (or the generic "local" user on first-ever offline start) is
    kept as-is.
    """
    if app_config.mode != "hybrid":
        return

    from spectra_sherpa.app.services.spectrasherpa import get_spectrasherpa_service

    service = get_spectrasherpa_service()
    if not service.is_configured:
        logger.info("Hybrid mode: no SPECTRASHERPA_API_KEY configured, using local identity")
        return

    # Verify server connectivity via health check first
    is_healthy, health_msg = await service.health_check()
    if not is_healthy:
        logger.info(
            "Hybrid mode: cloud server not reachable (%s) — using local identity",
            health_msg,
        )
        return

    # Try to link identity via /auth/me (may fail if cloud DB isn't set up)
    try:
        result = await service.validate_api_key()
    except Exception as exc:
        logger.info("Hybrid identity linking skipped: %s — Sherpa sync still works", exc)
        return

    if not result.success:
        logger.info(
            "Hybrid identity linking skipped: %s — Sherpa sync still works via API key auth",
            result.error,
        )
        return

    server_user = result.user
    try:
        async with async_session() as session:
            db_user = (
                await session.execute(select(User).order_by(User.id).limit(1))
            ).scalar_one_or_none()
            if db_user is None:
                return

            db_user.username = server_user.username
            db_user.is_superuser = server_user.is_admin
            await session.commit()

        logger.info(
            "Hybrid identity linked: %s (admin=%s)",
            server_user.username,
            server_user.is_admin,
        )
    except Exception as exc:
        logger.warning("Could not persist hybrid identity: %s", exc)


async def ensure_egress_defaults() -> None:
    """
    Ensure all users have default egress settings.

    This backfills UserEgressDefaults for existing users so hybrid/enterprise
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
                        allow_llm_context=False,
                        allow_export=False,
                        allow_nist_queries=False,
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
                .where(BackgroundJob.status == "pending")
                .values(
                    status="failed",
                    error_message="Server restarted before job execution",
                    completed_at=now,
                )
            )
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


def ensure_spectrochempy_data() -> None:
    """Ensure SpectroChemPy test data is available before DB-dependent setup.

    Controlled by ``SCP_DATA_BOOTSTRAP``:
    - ``auto`` (default): download if missing, warn on failure.
    - ``required``: download if missing, fail startup on failure.
    - ``skip``: never download (use pre-baked images).
    """
    import os
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    policy = os.getenv("SCP_DATA_BOOTSTRAP", "auto").strip().lower()
    if policy not in {"auto", "required", "skip"}:
        logger.warning("Invalid SCP_DATA_BOOTSTRAP=%r, defaulting to 'auto'", policy)
        policy = "auto"

    if policy == "skip":
        logger.info("SCP data bootstrap skipped (SCP_DATA_BOOTSTRAP=skip)")
        return

    from spectra_sherpa.app.lib.scp_compat import HAS_SCP, download_testdata, get_scp_datadirs

    if not HAS_SCP:
        return

    for datadir in get_scp_datadirs():
        try:
            if datadir.exists() and any(d.is_dir() for d in datadir.iterdir() if not d.name.startswith(".")):
                logger.info("SCP test data present at %s", datadir)
                return
        except OSError:
            continue

    timeout_sec = int(os.getenv("SCP_DATA_TIMEOUT", "300"))
    logger.info("Downloading SCP test data (timeout=%ss)...", timeout_sec)

    executor: ThreadPoolExecutor | None = None
    future = None
    try:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(download_testdata)
        future.result(timeout=timeout_sec)
        logger.info("SCP test data download complete")
    except FutureTimeout:
        if future is not None:
            future.cancel()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
            executor = None
        msg = f"SCP data download timed out after {timeout_sec}s"
        if policy == "required":
            raise RuntimeError(msg)
        logger.warning(msg)
    except Exception as exc:
        msg = f"Failed to download SCP test data: {exc}"
        if policy == "required":
            raise RuntimeError(msg) from exc
        logger.warning(msg)
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=False)


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
        from spectra_sherpa.app.core.workflow_templates import WORKFLOW_TEMPLATES

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
