from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.security import (
    llm_egress_defaults_enabled,
    llm_egress_defaults_forced,
)
from spectra_sherpa.app.db.init_db import init_db
from spectra_sherpa.app.db.seeder import seed_data
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.data_egress import UserEgressDefaults
from spectra_sherpa.app.models.user import PRINCIPAL_KIND_HUMAN, User
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate

logger = logging.getLogger(__name__)

# Default local-mode sentinel that should NOT be used in production.
DEFAULT_SECRET_KEY = "local-dev-key"
DEFAULT_API_KEY = "local-key"
MIN_SECRET_KEY_LENGTH = 32
MIN_SECRET_KEY_UNIQUE_CHARS = 8
# Minimum length for an APP_API_KEY that is actually accepted as a credential
# (ALLOW_SYSTEM_API_KEY_AUTH). Short keys are brute-forceable; the issued form
# is ``secrets.token_urlsafe(32)`` (~43 chars), so 32 is a comfortable floor.
MIN_SYSTEM_API_KEY_LENGTH = 32
# Minimum distinct characters, mirroring MIN_SECRET_KEY_UNIQUE_CHARS. Catches
# length-padding mistakes ("0"*32, "password"*4) that clear the length floor
# but carry almost no entropy. A real token_urlsafe(32) has far more.
MIN_SYSTEM_API_KEY_UNIQUE_CHARS = 8
INSECURE_SECRET_KEY_PLACEHOLDERS = {
    "",
    DEFAULT_SECRET_KEY,
    "your-super-secret-key-change-in-production",
    "change-me",
    "changeme",
    "secret",
    "password",
    "default",
    "<generate-new-key>",
    "<paste your generated secret key>",
}
# Well-known / shipped placeholder APP_API_KEY values. ``DEFAULT_API_KEY`` is the
# runtime default when the env var is unset; ``default-local-key`` is the value
# the packaged ``.env.example`` ships. Both are published and therefore unsafe
# to accept as a real credential. Kept separate from the SECRET_KEY set because
# the two have different provenance and may diverge.
INSECURE_API_KEY_PLACEHOLDERS = {
    "",
    DEFAULT_API_KEY,
    "default-local-key",
    "your-api-key",
    "your-app-api-key",
    "change-me",
    "changeme",
    "secret",
    "password",
    "default",
    "<generate-new-key>",
    "<paste your generated api key>",
}


def system_api_key_security_issue(api_key: str | None) -> str | None:
    """Return a startup-blocking issue for a weak APP_API_KEY that is being
    accepted as a request credential (ALLOW_SYSTEM_API_KEY_AUTH enabled).

    Returns ``None`` when the key is acceptable. Non-local startup validation
    treats any returned issue as fatal. Local mode bypasses request
    authentication and returns before this system-key check.
    """
    value = (api_key or "").strip()
    normalized = value.lower()
    if normalized in INSECURE_API_KEY_PLACEHOLDERS or (normalized.startswith("<") and normalized.endswith(">")):
        return (
            "APP_API_KEY is a published default/placeholder while "
            "ALLOW_SYSTEM_API_KEY_AUTH is enabled. Set a strong random value with: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    if len(value) < MIN_SYSTEM_API_KEY_LENGTH:
        return (
            f"APP_API_KEY must be at least {MIN_SYSTEM_API_KEY_LENGTH} characters when "
            "ALLOW_SYSTEM_API_KEY_AUTH is enabled. Generate a fresh random value."
        )
    if len(set(value)) < MIN_SYSTEM_API_KEY_UNIQUE_CHARS:
        return (
            "APP_API_KEY appears too low-entropy (a long but repetitive value does not "
            "count as strong). Generate a fresh random value."
        )
    return None


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

    local_key_file = get_app_data_paths(get_default_data_dir()).secret_key
    if local_key_file.exists():
        persisted = local_key_file.read_text(encoding="ascii").strip()
        if persisted:
            object.__setattr__(settings, "secret_key", persisted)
            logger.debug("Loaded persisted local auth secret from app data storage")
            return

    new_key = secrets.token_hex(32)
    local_key_file.parent.mkdir(parents=True, exist_ok=True)
    local_key_file.write_text(new_key, encoding="ascii")
    # Restrict read permissions to owner only
    try:
        local_key_file.chmod(0o600)
    except OSError:
        pass  # Windows; best-effort
    object.__setattr__(settings, "secret_key", new_key)
    logger.info(
        "Generated and persisted a new local auth secret. "
        "For network-exposed deployments, configure a stable externally managed auth secret.",
    )


def secret_key_security_issue(secret_key: str | None) -> str | None:
    """Return a startup-blocking issue for weak network-deployment secrets."""
    value = (secret_key or "").strip()
    normalized = value.lower()
    if normalized in INSECURE_SECRET_KEY_PLACEHOLDERS or (normalized.startswith("<") and normalized.endswith(">")):
        return (
            "Cannot start with a placeholder/default SECRET_KEY. "
            "Generate a stable random value with: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    if len(value) < MIN_SECRET_KEY_LENGTH:
        return f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters for network-exposed modes."
    if len(set(value)) < MIN_SECRET_KEY_UNIQUE_CHARS:
        return "SECRET_KEY appears too low-entropy. Generate a fresh random value."
    return None


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
                    "Using default SECRET_KEY in local mode. This is acceptable for development but not recommended.",
                )
            )
        from spectra_sherpa.app.core.mode_policy import is_loopback, local_network_access_allowed

        bind_host = os.getenv("HOST") or os.getenv("UVICORN_HOST") or "127.0.0.1"
        if not is_loopback(bind_host):
            if local_network_access_allowed():
                issues.append(
                    ConfigIssue(
                        "warning",
                        "security",
                        f"Local mode is bound to '{bind_host}' and local network access is explicitly allowed. "
                        "Only use this behind a trusted access-control layer.",
                    )
                )
            else:
                issues.append(
                    ConfigIssue(
                        "error",
                        "security",
                        f"Local mode is bound to non-loopback host '{bind_host}'. Local mode has no login barrier; "
                        "bind to 127.0.0.1 or set SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK=true only behind a trusted "
                        "access-control layer.",
                    )
                )
        return issues

    # Non-local modes: strict security validation
    secret_key_issue = secret_key_security_issue(settings.secret_key)
    if secret_key_issue:
        issues.append(
            ConfigIssue(
                "error",
                "security",
                f"Cannot start in '{app_config.mode}' mode. {secret_key_issue}",
            )
        )

    system_key_auth_enabled = os.getenv("ALLOW_SYSTEM_API_KEY_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if system_key_auth_enabled:
        # When APP_API_KEY is accepted as a request credential, a published
        # default/placeholder (or a short, brute-forceable value) exposes
        # every endpoint to anyone who knows it. This is a hard failure in
        # managed modes. Local mode bypasses auth and returns before this
        # check. Covers the runtime default ("local-key") AND the value formerly
        # shipped in .env.example ("default-local-key"), which the previous
        # exact-match check silently let through.
        api_key_issue = system_api_key_security_issue(settings.api_key)
        if api_key_issue:
            issues.append(
                ConfigIssue(
                    "error",
                    "security",
                    f"{api_key_issue} (mode: {app_config.mode})",
                )
            )

    if os.getenv("TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}:
        trusted_proxy_cidrs = os.getenv("TRUSTED_PROXY_CIDRS", "").strip()
        if not trusted_proxy_cidrs:
            level = "error" if app_config.mode == "enterprise" else "warning"
            issues.append(
                ConfigIssue(
                    level,
                    "security",
                    "TRUST_PROXY is enabled but TRUSTED_PROXY_CIDRS is not set. "
                    "Only loopback proxy peers are trusted by default.",
                )
            )

    if not os.getenv("MASTER_ENCRYPTION_KEY") and app_config.mode != "local":
        level = "error" if app_config.mode == "enterprise" else "warning"
        issues.append(
            ConfigIssue(
                level,
                "security",
                "MASTER_ENCRYPTION_KEY not set — auto-generating. Stored API keys "
                "will be lost on container restart. Set this env var explicitly.",
            )
        )
    else:
        from spectra_sherpa.app.core.env_validation import EnvValidationWarning, validate_encryption_env

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", EnvValidationWarning)
            encryption_errors = validate_encryption_env()

        for error in encryption_errors:
            issues.append(ConfigIssue("error", "security", error))
        for warning_item in caught:
            issues.append(ConfigIssue("warning", "security", str(warning_item.message)))

    return issues


def _validate_concurrency() -> list[ConfigIssue]:
    """Check concurrency-related settings (refactored from validate_concurrency_settings)."""
    issues: list[ConfigIssue] = []

    if app_config.mode != "local":
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
    # (commercial server or equivalent), not the core application.
    return []


def _validate_site_profile() -> list[ConfigIssue]:
    """Validate profile-specific deployment requirements."""
    issues: list[ConfigIssue] = []

    if app_config.site_profile == "demo":
        if app_config.mode != "enterprise":
            issues.append(
                ConfigIssue(
                    "error",
                    "mode",
                    f"site_profile=demo requires APP_MODE=enterprise, but current mode is '{app_config.mode}'.",
                )
            )
        if os.getenv("ENTERPRISE_PASSWORD", "").strip():
            issues.append(
                ConfigIssue(
                    "error",
                    "mode",
                    "ENTERPRISE_PASSWORD is retired for site_profile=demo; use six-digit email verification.",
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
    if app_config.mode != "local":
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
    paths = get_app_data_paths(settings.data_dir)
    paths.experiments_dir.mkdir(parents=True, exist_ok=True)
    paths.calibrations_dir.mkdir(parents=True, exist_ok=True)
    paths.nist_downloads_dir.mkdir(parents=True, exist_ok=True)
    paths.user_dir.mkdir(parents=True, exist_ok=True)
    paths.references_dir.mkdir(parents=True, exist_ok=True)
    paths.python_exports_dir.mkdir(parents=True, exist_ok=True)
    paths.jupyter_exports_dir.mkdir(parents=True, exist_ok=True)
    paths.llm_dialogs_dir.mkdir(parents=True, exist_ok=True)
    paths.rate_limits_dir.mkdir(parents=True, exist_ok=True)
    paths.demo_dir.mkdir(parents=True, exist_ok=True)


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
                session.add(User(username="local", principal_kind=PRINCIPAL_KIND_HUMAN))
                await session.commit()
    except OperationalError:
        logger.warning("Skipping default user creation; database not initialized.")


# Cloud activation removed - local-only mode


async def ensure_egress_defaults() -> None:
    """
    Ensure all users have default egress settings.

    Local/non-demo: missing rows default to privacy-first conservative values.
    Demo mode: AI chat + Sherpa workflow context are forced on for all users.
    Non-demo rows are also normalized so workflow context cannot remain enabled
    when AI chat itself is disabled.
    """
    try:
        async with async_session() as session:
            force_llm_defaults = llm_egress_defaults_forced()
            enable_llm_defaults = llm_egress_defaults_enabled()
            force_demo_data_defaults = app_config.site_profile == "demo"
            result = await session.execute(
                select(User).outerjoin(UserEgressDefaults).where(UserEgressDefaults.user_id.is_(None))
            )
            users_missing = cast(list[User], result.scalars().all())

            # Local & demo: LLM chat/context on by default. Demo also enables
            # NIST/HITRAN/export because the hosted onboarding flow needs
            # managed Sherpa plus user-managed HITRAN without exposing the
            # generic BYOK settings surface.
            for user in users_missing:
                session.add(
                    UserEgressDefaults(
                        user_id=user.id,
                        allow_llm_chat=enable_llm_defaults,  # On by default in local & demo
                        allow_export=force_demo_data_defaults,
                        allow_nist_queries=force_demo_data_defaults,
                        allow_hitran_queries=force_demo_data_defaults,
                        allow_llm_context=enable_llm_defaults,  # On by default in local & demo
                        allow_spectrasherpa_sync=force_llm_defaults,  # On in demo mode
                    )
                )

            normalized_users = 0
            defaults_rows = cast(
                list[UserEgressDefaults],
                (await session.execute(select(UserEgressDefaults))).scalars().all(),
            )
            for defaults in defaults_rows:
                mutable_defaults = cast(object, defaults)
                allow_llm_chat = bool(getattr(mutable_defaults, "allow_llm_chat"))
                allow_llm_context = bool(getattr(mutable_defaults, "allow_llm_context"))
                allow_export = bool(getattr(mutable_defaults, "allow_export", False))
                allow_nist = bool(getattr(mutable_defaults, "allow_nist_queries", False))
                allow_hitran = bool(getattr(mutable_defaults, "allow_hitran_queries", False))
                created_at = getattr(mutable_defaults, "created_at", None)
                updated_at = getattr(mutable_defaults, "updated_at", None)
                untouched_row = created_at is not None and updated_at == created_at
                if force_llm_defaults:
                    allow_sync = bool(getattr(mutable_defaults, "allow_spectrasherpa_sync", False))
                    if not allow_llm_chat or not allow_llm_context or not allow_sync:
                        setattr(mutable_defaults, "allow_llm_chat", True)
                        setattr(mutable_defaults, "allow_llm_context", True)
                        setattr(mutable_defaults, "allow_spectrasherpa_sync", True)
                        normalized_users += 1
                    if force_demo_data_defaults and (not allow_export or not allow_nist or not allow_hitran):
                        setattr(mutable_defaults, "allow_export", True)
                        setattr(mutable_defaults, "allow_nist_queries", True)
                        setattr(mutable_defaults, "allow_hitran_queries", True)
                        normalized_users += 1
                elif enable_llm_defaults and untouched_row and not allow_llm_chat and not allow_llm_context:
                    setattr(mutable_defaults, "allow_llm_chat", True)
                    setattr(mutable_defaults, "allow_llm_context", True)
                    normalized_users += 1
                elif not allow_llm_chat and allow_llm_context:
                    setattr(mutable_defaults, "allow_llm_context", False)
                    normalized_users += 1

            if users_missing or normalized_users:
                await session.commit()
            if users_missing:
                logger.info("Created egress defaults for %d user(s).", len(users_missing))
            if normalized_users:
                logger.info("Normalized LLM egress defaults for %d user(s).", normalized_users)
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
                .where(BackgroundJob.created_at < stale_cutoff)
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
                .where(BackgroundJob.last_heartbeat.is_(None))
                .where(BackgroundJob.created_at < stale_cutoff)
                .values(
                    status="failed",
                    error_message="Server restarted (job did not complete)",
                    completed_at=now,
                )
            )
            from spectra_sherpa.app.services.run_reconciliation import reconcile_job_runs

            await reconcile_job_runs(session)
            await session.commit()
    except OperationalError:
        logger.warning("Skipping job reconciliation; database not initialized.")


async def reconcile_orphan_model_artifacts() -> None:
    """GC on-disk model artifacts left with no DB row by a hard crash.

    Orphan-reconciliation backstop.  ``store.save()`` writes the artifact files
    before the ``ModelArtifact`` row is committed; caught failures get a
    compensating delete at the call site, but a hard process kill (OOM /
    pod eviction / SIGKILL) between the two leaves an orphan file with
    no DB row and no exception handler.  This leader-only, idempotent
    sweep (a sibling of :func:`reconcile_stale_jobs`) removes such
    orphans and abandoned promote scratch dirs, but only those older
    than the grace window so an in-flight concurrent save is never
    reaped.
    """
    try:
        from spectra_sherpa.app.services.model_store import reconcile_orphan_artifacts

        async with async_session() as session:
            await reconcile_orphan_artifacts(session)
    except OperationalError:
        logger.warning("Skipping orphan-artifact reconciliation; database not initialized.")
    except Exception as exc:  # pragma: no cover - best-effort janitor
        logger.warning("Orphan-artifact reconciliation failed: %s", exc)


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
