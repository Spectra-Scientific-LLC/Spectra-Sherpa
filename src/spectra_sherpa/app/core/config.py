from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from spectra_sherpa._paths import (
    get_default_data_dir,
    get_package_root,
    get_project_root,
    load_layered_env_files,
)
from spectra_sherpa.app.contracts.capabilities import (
    ALL_SHERPA_CAPABILITIES,
    CHAT_ASSISTANT,
)
from spectra_sherpa.app.contracts.llm_catalog import provider_core_config_dicts
from spectra_sherpa.app.core.app_paths import AppDataPaths, get_app_data_paths


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_retention_limit(name: str, maximum: int) -> int:
    value = _get_int(name, maximum)
    if not 0 < value <= maximum:
        raise ValueError(f"{name} must be between 1 and the qualified maximum {maximum}")
    return value


PROJECT_ROOT = get_project_root() or get_package_root().parent.parent
BACKEND_ROOT = get_package_root()  # spectra_sherpa/ contains app/, libs/, etc.

# Load shared ~/.env first, then allow repo/local .env files to override it.
load_layered_env_files()

DATA_DIR = get_default_data_dir()
APP_DATA_PATHS = get_app_data_paths(DATA_DIR)

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite+aiosqlite:///{APP_DATA_PATHS.database}"
APP_API_KEY = os.getenv("APP_API_KEY", "local-key")

_PREVIOUS_SETTINGS: Settings | None = globals().get("settings")
_PREVIOUS_APP_CONFIG: AppConfig | None = globals().get("app_config")


@dataclass(frozen=True)
class Settings:
    app_name: str = "Spectra Scientific Platform"
    app_version: str = "0.2.1"  # Increment when node definitions change
    project_root: Path = PROJECT_ROOT
    backend_root: Path = BACKEND_ROOT
    data_dir: Path = DATA_DIR
    app_data_paths: AppDataPaths = APP_DATA_PATHS
    database_url: str = DATABASE_URL
    api_key: str = APP_API_KEY

    # JWT Authentication
    secret_key: str = os.getenv("SECRET_KEY", "local-dev-key")
    algorithm: str = "HS256"
    # Token lifetime: 60 min default for all modes.  Local mode bypasses JWT
    # entirely (implicit user identity), so this only matters for managed.
    # Override with ACCESS_TOKEN_EXPIRE_MINUTES env var.
    access_token_expire_minutes: int = _get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)

    max_spectra_per_job: int = _get_int("MAX_SPECTRA_PER_JOB", 1000)  # Increased for MCR-ALS datasets
    max_wavenumbers: int = _get_int("MAX_WAVENUMBERS", 20000)
    max_memory_mb: int = _get_int("MAX_MEMORY_MB", 4096)
    max_concurrent_jobs: int = _get_int("MAX_CONCURRENT_JOBS", 5)
    max_concurrent_jobs_per_user: int = _get_int("MAX_CONCURRENT_JOBS_PER_USER", 1)
    max_nist_downloads_per_hour: int = _get_int("MAX_NIST_DOWNLOADS_PER_HOUR", 50)
    max_llm_requests_per_hour: int = _get_int("MAX_LLM_REQUESTS_PER_HOUR", 100)

    max_file_size_mb: int = _get_int("MAX_FILE_SIZE_MB", 200)
    max_job_duration_sec: int = _get_int("MAX_JOB_DURATION_SEC", 3600)
    ws_idle_timeout_sec: int = _get_int("WS_IDLE_TIMEOUT_SEC", 120)
    dag_worker_pool_size: int = _get_int("DAG_WORKER_POOL_SIZE", min(4, os.cpu_count() or 2))
    parallel_threshold: int = _get_int("PARALLEL_THRESHOLD", 100)  # min spectra to enable multi-core preprocessing
    max_export_size_mb: int = _get_int("MAX_EXPORT_SIZE_MB", 1024)
    run_output_retention_enabled: bool = _get_bool("RUN_OUTPUT_RETENTION_ENABLED", True)
    run_output_max_bytes: int = _get_retention_limit("RUN_OUTPUT_MAX_BYTES", 8 * 1024 * 1024)
    run_output_run_max_bytes: int = _get_retention_limit("RUN_OUTPUT_RUN_MAX_BYTES", 64 * 1024 * 1024)
    run_output_user_max_bytes: int = _get_retention_limit("RUN_OUTPUT_USER_MAX_BYTES", 512 * 1024 * 1024)
    folder_watch_files_per_poll: int = _get_retention_limit("FOLDER_WATCH_FILES_PER_POLL", 16)
    prediction_upload_max_files: int = _get_retention_limit("PREDICTION_UPLOAD_MAX_FILES", 16)
    prediction_upload_max_request_bytes: int = _get_retention_limit(
        "PREDICTION_UPLOAD_MAX_REQUEST_BYTES", 32 * 1024 * 1024
    )
    prediction_upload_max_user_bytes: int = _get_retention_limit("PREDICTION_UPLOAD_MAX_USER_BYTES", 512 * 1024 * 1024)
    prediction_upload_timeout_seconds: int = _get_retention_limit("PREDICTION_UPLOAD_TIMEOUT_SECONDS", 60)
    log_buffer_size: int = _get_int("LOG_BUFFER_SIZE", 1000)
    log_file_path: Optional[str] = os.getenv("LOG_FILE_PATH")  # e.g., "logs/audit.log"
    log_file_max_bytes: int = _get_int("LOG_FILE_MAX_BYTES", 10 * 1024 * 1024)  # 10 MB default
    log_file_backup_count: int = _get_int("LOG_FILE_BACKUP_COUNT", 5)
    sanitize_paths: bool = _get_bool("SANITIZE_PATHS", False)
    campaign_review_publisher_trust_anchors_path: Optional[str] = os.getenv(
        "CAMPAIGN_REVIEW_PUBLISHER_TRUST_ANCHORS_PATH"
    )


def _refresh_settings_singleton() -> Settings:
    fresh = Settings()
    existing = _PREVIOUS_SETTINGS
    if existing is not None and all(hasattr(existing, field_name) for field_name in Settings.__dataclass_fields__):
        for field_name in Settings.__dataclass_fields__:
            object.__setattr__(existing, field_name, getattr(fresh, field_name))
        return existing
    return fresh


# ============================================================================
# Multi-Mode Configuration (Local, Enterprise and explicit extensions)
# ============================================================================


class LLMConfig(BaseModel):
    """Configuration for an LLM provider"""

    provider: str
    api_key: Optional[str] = None
    model: str
    base_url: Optional[str] = None  # For custom endpoints

    @property
    def is_configured(self) -> bool:
        """Check if this LLM has an API key configured"""
        return self.api_key is not None and len(self.api_key) > 0


class AppMode(str, Enum):
    """Built-in runtime identifiers; private products register their own policy."""

    LOCAL = "local"
    ENTERPRISE = "enterprise"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Valid mode strings — the canonical set for input validation."""
        return tuple(m.value for m in cls)


class ExecutionConfig(BaseModel):
    """Execution and compute settings"""

    mode: Literal["local", "remote"] = "local"


class AppConfig(BaseModel):
    """Main application configuration for core and explicitly composed product runtimes."""

    mode: str = Field(default="local", description="Core or explicitly registered product runtime mode")

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        from spectra_sherpa.app.contracts.runtime_mode import validate_runtime_mode

        return validate_runtime_mode(value)

    egress_enabled: bool = Field(
        default=False, description="Enable network egress (external API calls). Defaults to False in local mode."
    )
    audit_enabled: bool = Field(
        default=False,
        description=(
            "Enable the structured audit-log subsystem (ISO 17025 readiness). "
            "Default False; turned on per deployment via SHERPA_AUDIT_ENABLED. "
            "OSS provides the event-capture layer; commercial audit pipeline "
            "(chain, retention, admin UI) gates on additional entitlement keys."
        ),
    )
    api_base_url: str = Field(default="http://localhost:8000", description="Backend API base URL")

    # Integration fields for commercial server extensions (managed).
    # These are None in OSS mode but can be injected by an extension package.
    site_profile: Optional[str] = Field(
        default=None,
        description="Product profile (demo, pro, org, or extension-defined) used by server extensions",
    )
    rate_limit_executions: Optional[int] = Field(
        default=None,
        description="Max executions per hour per user (managed mode) - used by server extensions",
    )
    session_expiry_hours: Optional[int] = Field(
        default=None, description="Session expiry in hours (managed mode) - used by server extensions"
    )

    # LLM configurations
    llms: Dict[str, LLMConfig] = Field(default_factory=dict)

    # Execution settings
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from environment variables using registry defaults.

        Reads APP_MODE to determine operational mode (local or enterprise, or an explicitly installed product mode).
        """
        # Determine app mode from environment
        raw_mode = os.getenv("APP_MODE", "local").strip().lower()
        from spectra_sherpa.app.contracts.runtime_mode import validate_runtime_mode

        mode = raw_mode
        from spectra_sherpa.app.core.desktop_policy import is_desktop

        if is_desktop():
            # The signed desktop product is always the local workbench.
            mode = "local"
        validate_runtime_mode(mode)

        # Provider metadata comes from the injectable LLM provider
        # catalog contract (spectra_sherpa.app.contracts.llm_catalog).
        # OSS uses the static default; the commercial server replaces it
        # via set_llm_provider_catalog() at startup so provider-selection
        # policy can change without the OSS tree churning. The default is
        # byte-identical to the historical inline dict.
        PROVIDERS: dict[str, dict[str, Any]] = provider_core_config_dicts()

        # Build LLM configs from registry
        llm_configs: dict[str, LLMConfig] = {}
        for provider_id, provider_meta in PROVIDERS.items():
            model_env = f"{provider_id.upper()}_MODEL"
            llm_configs[provider_id] = LLMConfig(
                provider=provider_id,  # type: ignore[arg-type]
                api_key=os.getenv(provider_meta.get("env_var", f"{provider_id.upper()}_API_KEY")),
                model=os.getenv(model_env, provider_meta["default_model"]),
                base_url=provider_meta.get("base_url"),
            )

        # Egress: disabled by default in local (privacy-first), enabled in managed
        egress_enabled = _get_bool("EGRESS_ENABLED", mode != "local")

        # Audit subsystem: off by default everywhere. Operators opt in via
        # SHERPA_AUDIT_ENABLED. Managed Team-tier deployments turn this on;
        # the commercial server's entitlement check then gates the full pipeline.
        audit_enabled = _get_bool("SHERPA_AUDIT_ENABLED", False)

        # Managed extension integration fields
        site_profile = os.getenv("SITE_PROFILE", "").strip() or None
        rate_limit_raw = _get_int("RATE_LIMIT_EXECUTIONS", 0) if mode != "local" else 0
        rate_limit_executions = rate_limit_raw if rate_limit_raw else None
        session_expiry_raw = _get_int("SESSION_EXPIRY_HOURS", 0) if mode != "local" else 0
        session_expiry_hours = session_expiry_raw if session_expiry_raw else None

        return cls(
            mode=mode,  # type: ignore[arg-type]
            egress_enabled=egress_enabled,
            audit_enabled=audit_enabled,
            api_base_url=os.getenv("API_BASE_URL", "http://localhost:8000"),
            site_profile=site_profile,
            rate_limit_executions=rate_limit_executions,
            session_expiry_hours=session_expiry_hours,
            llms=llm_configs,
            execution=ExecutionConfig(
                mode="remote" if mode != "local" else "local",
            ),
        )

    @classmethod
    def from_file(cls, path: str = "config.json") -> "AppConfig":
        """Load configuration from JSON file"""
        config_path = Path(path)
        if not config_path.exists():
            return cls.from_env()

        with open(config_path) as f:
            data = json.load(f)
            return cls(**data)

    def get_configured_llms(self) -> Dict[str, LLMConfig]:
        """Get only LLMs that have API keys configured"""
        return {name: llm_config for name, llm_config in self._live_llm_configs().items() if llm_config.is_configured}

    def _live_llm_configs(self) -> dict[str, LLMConfig]:
        """LLM configs projected from the current provider catalog.

        ``app_config`` is created at module import, while commercial
        extensions inject provider policy during startup. Read the catalog
        live here so newly injected providers appear in client config
        without reloading this module.
        """
        configs: dict[str, LLMConfig] = {}
        for provider_id, provider_meta in provider_core_config_dicts().items():
            env_var = str(provider_meta.get("env_var") or f"{provider_id.upper()}_API_KEY")
            model_env = f"{provider_id.upper()}_MODEL"
            existing = self.llms.get(provider_id)
            configs[provider_id] = LLMConfig(
                provider=provider_id,
                api_key=os.getenv(env_var) or (existing.api_key if existing is not None else None),
                model=os.getenv(model_env, str(provider_meta["default_model"])),
                base_url=str(provider_meta.get("base_url") or ""),
            )
        return configs

    def to_client_safe(self) -> dict:
        """Return client-safe configuration (no secrets).

        ``registrationEnabled`` is a server-owned flag. The commercial server declares its value
        at startup via ``spectra_sherpa.app.contracts.auth_policy``; OSS
        reads them here. In OSS-only installs both default to ``False``
        — the base shape carries those defaults, which is the correct
        behavior for distributions without managed auth. If the server
        overlay provider overrides them in its payload, the config
        route merges those values on top.
        """
        live_llms = self._live_llm_configs()
        has_llm = any(llm.is_configured for llm in live_llms.values())

        from spectra_sherpa.app.core.desktop_policy import is_desktop
        from spectra_sherpa.app.core.mode_policy import allows_registration
        from spectra_sherpa.app.lib.data_formats import client_data_formats
        from spectra_sherpa.app.services.encryption import (
            credential_storage_available as _credential_storage_available,
        )

        # ``allows_registration()`` layers the multi-user mode check on
        # top of the server-registered flag.
        registration_enabled = allows_registration()

        # User-facing quota model: one Sherpa/LLM hourly limit plus optional
        # session expiry metadata. Execution throttling is no longer exposed.
        if settings.max_llm_requests_per_hour or self.session_expiry_hours:
            _limits: dict[str, Any] = {
                "maxFileSizeMB": settings.max_file_size_mb,
                "maxSherpaRequestsHour": settings.max_llm_requests_per_hour,
                "adminBypass": True,
            }
            if self.session_expiry_hours:
                _limits["sessionExpiryHours"] = self.session_expiry_hours
            limits: dict[str, Any] | None = _limits
        else:
            limits = None

        # Phase 4 — unified audit entitlement block per
        # ``the audit-subsystem design specification §3``
        # ("Entitlement model — single capability source"). Frontend
        # gating reads this block; the legacy top-level ``auditEnabled``
        # field stays for backwards-compat but new UI code paths must
        # use ``audit.localQuery`` instead.
        #
        #   localQuery     — OSS deployment-level (governed by
        #                    SHERPA_AUDIT_ENABLED). Server cannot
        #                    override; OSS users get this for free.
        #   fullPipeline   — server-only capability (audit.full
        #                    entitlement). Defaults False at OSS base;
        #                    server overlay elevates when entitled.
        #   reportPack     — server-only capability (audit.report_pack).
        #                    Same shape as fullPipeline.
        #   exportAudited  — when localQuery is true, audit-export
        #                    actions emit their own audit rows. Mirrors
        #                    localQuery in OSS today; server overlay
        #                    may set this independently in future.
        audit_block: dict[str, bool] = {
            "localQuery": self.audit_enabled,
            "fullPipeline": False,
            "reportPack": False,
            "exportAudited": self.audit_enabled,
        }

        result: dict[str, Any] = {
            "mode": self.mode,
            "egressEnabled": self.egress_enabled,
            # Legacy field — kept for existing frontend code paths.
            # Phase 4 introduces ``audit{}`` (above) as the new
            # single-source-of-truth for audit-pack gating.
            "auditEnabled": self.audit_enabled,
            "audit": audit_block,
            "apiBaseUrl": self.api_base_url,
            "registrationEnabled": registration_enabled,
            "siteProfile": self.site_profile,
            # Desktop builds have no Hybrid enrollment or hosted connection.
            "desktop": is_desktop(),
            "capabilities": {
                "llmByok": self.mode == "local",
                "managedLlm": False,
                "governedTools": False,
                "hostedFolderWatch": False,
                "workbenchDeploy": False,
            },
            "features": {
                "apiTokenSettings": self.mode == "local",
                # False only in the desktop app without OS credential protection.
                "credentialStorage": _credential_storage_available(),
                CHAT_ASSISTANT: has_llm,
                "nistDownloads": self.egress_enabled,
                # Sherpa capabilities default to False; server overlay enables them.
                **{cap: False for cap in ALL_SHERPA_CAPABILITIES},
            },
            "llms": {
                name: {"provider": llm.provider, "model": llm.model, "enabled": llm.is_configured}
                for name, llm in live_llms.items()
            },
            "limits": limits,
            "dataFormats": client_data_formats(),
        }

        # Demo metadata is injected by server overlay, not OSS.
        result["demo"] = None

        return result


def _refresh_app_config_singleton() -> AppConfig:
    fresh = AppConfig.from_env()
    existing = _PREVIOUS_APP_CONFIG
    if existing is not None and all(hasattr(existing, field_name) for field_name in AppConfig.model_fields):
        for field_name in AppConfig.model_fields:
            setattr(existing, field_name, getattr(fresh, field_name))
        return existing
    return fresh


# Global config singletons. Preserve object identity across importlib.reload()
# so modules/tests holding older references still observe refreshed values.
settings = _refresh_settings_singleton()
app_config = _refresh_app_config_singleton()
