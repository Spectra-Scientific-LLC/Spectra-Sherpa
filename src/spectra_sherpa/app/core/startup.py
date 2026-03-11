from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.db.init_db import init_db
from spectra_sherpa.app.db.seeder import seed_data
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.data_egress import UserEgressDefaults
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.experiments import (
    create_experiment,
    metadata_path_for,
    write_metadata,
)

logger = logging.getLogger(__name__)

# Default secret key that should NOT be used in production
DEFAULT_SECRET_KEY = "your-super-secret-key-change-in-production"
DEFAULT_API_KEY = "default-local-key"

# Filename where the auto-generated local secret key is persisted
_LOCAL_KEY_FILENAME = ".secret_key"


def _ensure_local_secret_key() -> None:
    """Auto-generate and persist a SECRET_KEY for local mode deployments.

    If the user has not set SECRET_KEY in their environment and the default
    placeholder is still in use, we generate a cryptographically random key
    and store it in the Sherpa data directory so it survives restarts.

    This keeps JWTs and session cookies stable across server restarts without
    requiring manual configuration for local-first users.

    No-op when SECRET_KEY has already been set explicitly.
    """
    if settings.secret_key != DEFAULT_SECRET_KEY:
        return  # Explicitly set — nothing to do.

    from spectra_sherpa._paths import get_default_data_dir

    key_path = get_default_data_dir() / _LOCAL_KEY_FILENAME
    if key_path.exists():
        persisted = key_path.read_text(encoding="ascii").strip()
        if persisted:
            settings.secret_key = persisted
            logger.debug("Loaded persisted local SECRET_KEY from %s", key_path)
            return

    new_key = secrets.token_hex(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(new_key, encoding="ascii")
    # Restrict read permissions to owner only
    try:
        key_path.chmod(0o600)
    except OSError:
        pass  # Windows; best-effort
    settings.secret_key = new_key
    logger.info(
        "Generated a new local SECRET_KEY and saved to %s. "
        "Set the SECRET_KEY environment variable to use a custom key.",
        key_path,
    )


# ---------------------------------------------------------------------------
# Unified config validation
# ---------------------------------------------------------------------------


@dataclass
class ConfigIssue:
    """A single configuration validation issue."""

    level: str  # "error" or "warning"
    category: str  # "security", "database", "mode", "llm", "cors", "concurrency"
    message: str


@dataclass
class ConfigValidationResult:
    """Structured result from unified configuration validation."""

    issues: list[ConfigIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    @property
    def errors(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.level == "warning"]


def _validate_security() -> list[ConfigIssue]:
    """Check security-critical settings (refactored from validate_security_settings)."""
    issues: list[ConfigIssue] = []

    if app_config.mode == "local":
        if settings.secret_key == DEFAULT_SECRET_KEY:
            issues.append(
                ConfigIssue(
                    "warning",
                    "security",
                    "Using default SECRET_KEY in local mode. "
                    "This is acceptable for development but not recommended.",
                )
            )
        return issues

    # Non-local modes: strict security validation
    if settings.secret_key == DEFAULT_SECRET_KEY:
        issues.append(
            ConfigIssue(
                "error",
                "security",
                f"Cannot start in '{app_config.mode}' mode with default SECRET_KEY. "
                f"Set a secure SECRET_KEY environment variable.",
            )
        )

    system_key_auth_enabled = os.getenv("ALLOW_SYSTEM_API_KEY_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if settings.api_key == DEFAULT_API_KEY and system_key_auth_enabled:
        issues.append(
            ConfigIssue(
                "warning",
                "security",
                "APP_API_KEY is set to the default value while ALLOW_SYSTEM_API_KEY_AUTH "
                "is enabled. Set a strong random APP_API_KEY.",
            )
        )

    if os.getenv("TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}:
        trusted_proxy_cidrs = os.getenv("TRUSTED_PROXY_CIDRS", "").strip()
        if not trusted_proxy_cidrs:
            issues.append(
                ConfigIssue(
                    "warning",
                    "security",
                    "TRUST_PROXY is enabled but TRUSTED_PROXY_CIDRS is not set. "
                    "Only loopback proxy peers are trusted by default.",
                )
            )

    if not os.getenv("MASTER_ENCRYPTION_KEY") and app_config.mode != "local":
        issues.append(
            ConfigIssue(
                "warning",
                "security",
                "MASTER_ENCRYPTION_KEY not set — auto-generating. Stored API keys "
                "will be lost on container restart. Set this env var explicitly.",
            )
        )

    if app_config.mode == "hybrid":
        bind_host = os.getenv("HOST", "127.0.0.1")
        loopback = {"127.0.0.1", "::1", "localhost"}
        if bind_host not in loopback:
            issues.append(
                ConfigIssue(
                    "warning",
                    "security",
                    f"Hybrid mode is bound to '{bind_host}'. Non-loopback clients "
                    "must authenticate with a valid JWT or API key.",
                )
            )

    return issues


def _validate_concurrency() -> list[ConfigIssue]:
    """Check concurrency-related settings (refactored from validate_concurrency_settings)."""
    issues: list[ConfigIssue] = []

    if app_config.mode in ("hybrid", "enterprise"):
        web_concurrency = os.getenv("WEB_CONCURRENCY", "").strip()
        if web_concurrency:
            try:
                workers = int(web_concurrency)
            except ValueError:
                workers = 1
            if workers > 1:
                issues.append(
                    ConfigIssue(
                        "error",
                        "concurrency",
                        f"WEB_CONCURRENCY={workers} is not supported with in-memory WebSocket "
                        "channels — realtime events will be silently dropped across workers. "
                        "Set WEB_CONCURRENCY=1.",
                    )
                )

    return issues


def _validate_database_mode() -> list[ConfigIssue]:
    """Check database configuration for the current mode."""
    # The OSS layer is database-agnostic (SQLAlchemy handles the abstraction).
    # Database-engine enforcement (e.g. requiring a production-grade backend
    # for multi-user deployments) is the responsibility of the deployment layer
    # (spectra-server or equivalent), not the core application.
    return []


def _validate_site_profile() -> list[ConfigIssue]:
    """site_profile=demo requires enterprise mode."""
    issues: list[ConfigIssue] = []

    if app_config.site_profile == "demo" and app_config.mode != "enterprise":
        issues.append(
            ConfigIssue(
                "error",
                "mode",
                f"site_profile=demo requires APP_MODE=enterprise, " f"but current mode is '{app_config.mode}'.",
            )
        )

    return issues


def _validate_llm_config() -> list[ConfigIssue]:
    """Warn if LLM keys are configured but egress is disabled."""
    issues: list[ConfigIssue] = []

    configured_llms = app_config.get_configured_llms()
    if configured_llms and not app_config.egress_enabled:
        providers = ", ".join(configured_llms.keys())
        issues.append(
            ConfigIssue(
                "warning",
                "llm",
                f"LLM API keys configured ({providers}) but egress is disabled. "
                "Set EGRESS_ENABLED=true to allow LLM API calls.",
            )
        )

    return issues


def _validate_cors() -> list[ConfigIssue]:
    """Warn if CORS_ORIGINS is not explicitly set in non-local modes."""
    issues: list[ConfigIssue] = []

    if app_config.mode != "local" and not os.getenv("CORS_ORIGINS"):
        issues.append(
            ConfigIssue(
                "warning",
                "cors",
                f"CORS_ORIGINS not explicitly set for {app_config.mode} mode — "
                "using localhost defaults. Set CORS_ORIGINS for production.",
            )
        )

    return issues


def validate_config() -> ConfigValidationResult:
    """Run all configuration validation checks.

    Returns structured results. Errors should prevent startup; warnings are logged.
    Called from lifespan Phase 1 (before DB initialization).
    """
    if app_config.mode == "local":
        _ensure_local_secret_key()

    issues: list[ConfigIssue] = []
    issues.extend(_validate_security())
    issues.extend(_validate_concurrency())
    issues.extend(_validate_database_mode())
    issues.extend(_validate_site_profile())
    issues.extend(_validate_llm_config())
    issues.extend(_validate_cors())
    return ConfigValidationResult(issues=issues)


def validate_concurrency_settings() -> None:
    """
    Validate concurrency-related settings and warn about multi-worker deployments.

    Thin wrapper around the unified config validation for backward compatibility.
    """
    for issue in _validate_concurrency():
        if issue.level == "error":
            logger.critical(issue.message)
            sys.exit(1)
        else:
            logger.warning(issue.message)

    # Additional logging not covered by structured validation
    if app_config.mode in ("hybrid", "enterprise"):
        try:
            import fcntl  # noqa: F401

            has_fcntl = True
        except ImportError:
            has_fcntl = False

        if not has_fcntl:
            logger.warning(
                "File locking (fcntl) not available on this platform. "
                "Rate limiting in multi-worker deployments may not be accurate. "
                "Consider using Redis-backed rate limiting for production."
            )

        logger.info(
            f"Concurrency model: "
            f"rate_limiter=file-locked, job_manager=database-backed, "
            f"max_concurrent_jobs={settings.max_concurrent_jobs}"
        )


def validate_security_settings() -> None:
    """
    Validate security-critical settings at startup.

    Thin wrapper around the unified config validation for backward compatibility.

    Raises:
        SystemExit: If critical security settings are invalid
    """
    for issue in _validate_security():
        if issue.level == "error":
            logger.critical(issue.message)
            sys.exit(1)
        else:
            logger.warning(issue.message)


def ensure_data_dirs() -> None:
    (settings.data_dir / "experiments").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "calibrations").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "nist_library" / "downloaded").mkdir(parents=True, exist_ok=True)
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

    raise RuntimeError(f"Database was not ready within {timeout_seconds} seconds.") from last_error


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


# Cloud activation removed - local-only mode


async def ensure_egress_defaults() -> None:
    """
    Ensure all users have default egress settings.

    Local mode: everything disabled by default (privacy-first).
    Existing explicit preferences are never overridden.
    """
    try:
        async with async_session() as session:
            result = await session.execute(
                select(User).outerjoin(UserEgressDefaults).where(UserEgressDefaults.user_id.is_(None))
            )
            users_missing = result.scalars().all()
            if not users_missing:
                return

            for user in users_missing:
                session.add(
                    UserEgressDefaults(
                        user_id=user.id,
                        allow_export=False,  # Local file export disabled by default
                        allow_nist_queries=False,  # NIST queries disabled by default
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
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

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
            result = await session.execute(select(Experiment).where(Experiment.name == "SpectrochemPy Test Data"))
            experiment = result.scalar_one_or_none()

            # Count available test files and subdirectories (optimized single pass)
            subdirs = [d for d in spectrochempy_dir.iterdir() if d.is_dir()]
            allowed_extensions = {".csv", ".jdx", ".dx", ".spc", ".spa", ".spg"}
            test_files = [f for f in spectrochempy_dir.rglob("*") if f.is_file() and f.suffix in allowed_extensions]

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
                "instructions": "Files are accessible from ~/.spectrochempy/. Do not load all files into database.",
            }

            # Create or update experiment
            if not experiment:
                logger.info("Creating SpectrochemPy Test Data reference")
                experiment = await create_experiment(
                    session=session,
                    user_id=user.id,
                    name="SpectrochemPy Test Data",
                    description=(
                        f"Reference to test datasets in ~/.spectrochempy/ "
                        f"({len(test_files)} files in {len(subdirs)} subdirectories)"
                    ),
                    metadata=metadata,
                )
                logger.info(
                    f"SpectrochemPy reference created: {len(test_files)} files, {len(subdirs)} subdirs, PDF: {has_pdf}"
                )
            else:
                # Update metadata with current file counts
                metadata_file = metadata_path_for(experiment.id)
                write_metadata(metadata_file, metadata)
                logger.info(
                    f"SpectrochemPy reference updated: {len(test_files)} files, {len(subdirs)} subdirs, PDF: {has_pdf}"
                )

    except OperationalError:
        logger.warning("Skipping SpectrochemPy test data setup; database not initialized.")
    except Exception as e:
        logger.error(f"Error setting up SpectrochemPy test data: {e}", exc_info=True)


async def ensure_workflow_templates() -> None:
    """
    Seed or update the database with common workflow templates.

    Uses the declarative YAML template set as the canonical source of truth.
    Existing records are upserted by slug/name, and templates removed from YAML
    are deactivated rather than deleted so historical workflow provenance
    remains intact.
    """
    try:
        from spectra_sherpa.app.core.template_loader import TemplateLoader

        loader = TemplateLoader()
        validation_errors = loader.validate_all()
        if validation_errors:
            raise RuntimeError("Template validation failed:\n" + "\n".join(f"  • {err}" for err in validation_errors))

        workflow_templates = loader.load_all()

        async with async_session() as session:
            result = await session.execute(select(WorkflowTemplate))
            existing_templates = list(result.scalars().all())

            inserted = 0
            updated = 0
            deactivated = 0
            seen_slugs: set[str] = set()
            seen_names: set[str] = set()
            chosen_existing_ids: set[int] = set()

            def _match_priority(template: WorkflowTemplate, *, slug: str, name: str) -> tuple[int, int, int]:
                exact_slug = getattr(template, "slug", None) == slug
                exact_name = getattr(template, "name", None) == name
                score = 3 if exact_slug and exact_name else 2 if exact_slug else 1 if exact_name else 0
                return (score, 1 if getattr(template, "is_active", False) else 0, int(getattr(template, "id", 0) or 0))

            for template_data in workflow_templates:
                slug = template_data["slug"]
                name = template_data["name"]
                seen_slugs.add(slug)
                seen_names.add(name)

                candidates = [
                    template
                    for template in existing_templates
                    if getattr(template, "slug", None) == slug or getattr(template, "name", None) == name
                ]

                existing = (
                    max(candidates, key=lambda template: _match_priority(template, slug=slug, name=name))
                    if candidates
                    else None
                )
                if existing is None:
                    session.add(WorkflowTemplate(**template_data))
                    inserted += 1
                else:
                    chosen_existing_ids.add(existing.id)
                    # Refresh mutable fields (name, description, category, template_data, is_active, slug)
                    changed = False
                    for key in ("slug", "name", "description", "category", "template_data", "is_active"):
                        if key in template_data and getattr(existing, key) != template_data[key]:
                            setattr(existing, key, template_data[key])
                            changed = True

                    for duplicate in candidates:
                        if duplicate.id == existing.id:
                            continue
                        if duplicate.is_active:
                            duplicate.is_active = False
                            deactivated += 1
                            changed = True
                    if changed:
                        updated += 1

            for existing in existing_templates:
                if not existing.is_active:
                    continue

                if existing.id in chosen_existing_ids:
                    continue

                should_deactivate = (
                    not existing.slug or existing.slug not in seen_slugs or existing.name not in seen_names
                )

                if should_deactivate:
                    existing.is_active = False
                    deactivated += 1

            if inserted or updated or deactivated:
                await session.commit()

            total = await session.scalar(select(func.count(WorkflowTemplate.id)))
            logger.info(
                "Workflow templates: %s total, %s new, %s updated, %s deactivated",
                total,
                inserted,
                updated,
                deactivated,
            )

    except RuntimeError:
        raise
    except OperationalError:
        logger.warning("Skipping workflow template seeding; database not initialized.")
    except Exception as e:
        logger.error(f"Error seeding workflow templates: {e}", exc_info=True)
