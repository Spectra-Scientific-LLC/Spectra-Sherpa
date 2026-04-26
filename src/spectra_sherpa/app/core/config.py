from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

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


PROJECT_ROOT = get_project_root() or get_package_root().parent.parent
BACKEND_ROOT = get_package_root()  # spectra_sherpa/ contains app/, libs/, etc.

# Load shared ~/.env first, then allow repo/local .env files to override it.
load_layered_env_files()

DATA_DIR = get_default_data_dir()
APP_DATA_PATHS = get_app_data_paths(DATA_DIR)

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite+aiosqlite:///{APP_DATA_PATHS.database}"
APP_API_KEY = os.getenv("APP_API_KEY", "default-local-key")

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
    secret_key: str = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
    algorithm: str = "HS256"
    # Token lifetime: 60 min default for all modes.  Local mode bypasses JWT
    # entirely (implicit user identity), so this only matters for hybrid/enterprise.
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
    log_buffer_size: int = _get_int("LOG_BUFFER_SIZE", 1000)
    log_file_path: Optional[str] = os.getenv("LOG_FILE_PATH")  # e.g., "logs/audit.log"
    log_file_max_bytes: int = _get_int("LOG_FILE_MAX_BYTES", 10 * 1024 * 1024)  # 10 MB default
    log_file_backup_count: int = _get_int("LOG_FILE_BACKUP_COUNT", 5)
    sanitize_paths: bool = _get_bool("SANITIZE_PATHS", False)
    allowed_extensions: tuple[str, ...] = (
        ".csv",
        ".jdx",
        ".dx",
        ".json",  # Kept for backward compatibility (will warn if no explicit reader)
        ".spc",
        ".spa",
        ".spg",
        ".srs",
        ".txt",
        ".wdf",  # Renishaw WiRE Data Format (Raman)
        ".dat",  # Kept for backward compatibility (will warn if no explicit reader)
        ".opus",
        ".mat",
    )


# Extension to SpectroChemPy reader method mapping
# Single source of truth for all file loading operations
EXTENSION_READER_MAP = {
    # Structured formats
    ".csv": "read_csv",
    ".mat": "read_matlab",
    # JCAMP-DX formats (common in IR spectroscopy)
    ".jdx": "read_jcamp",
    ".dx": "read_jcamp",
    # Galactic SPC format
    ".spc": "read_spc",
    # OMNIC formats (both use read_omnic, NOT read_spa/read_spg)
    ".spa": "read_omnic",  # OMNIC single file
    ".spg": "read_omnic",  # OMNIC series file
    ".srs": "read_omnic",  # OMNIC time series file
    # Text-based and proprietary formats (use generic reader)
    ".txt": "read",
    ".wdf": "read",  # Renishaw WiRE Data Format
    # Note: .dat and .json are in allowed_extensions for backward compatibility
    # but have no explicit reader - will fall back to generic read with warning
}


def get_reader_for_extension(ext: str) -> str:
    """
    Get the appropriate SpectroChemPy reader method for a file extension.

    Args:
        ext: File extension (with or without leading dot)

    Returns:
        Name of SpectroChemPy reader method (e.g., 'read_omnic')

    Raises:
        ValueError: If extension is not supported
    """
    import warnings

    ext_lower = ext.lower()
    if not ext_lower.startswith("."):
        ext_lower = f".{ext_lower}"

    # Special case: OPUS files use numeric extensions (.0, .1, .0000, etc.)
    if ext_lower.lstrip(".").isdigit():
        return "read_opus"

    if ext_lower not in EXTENSION_READER_MAP:
        # Check against the allowed_extensions tuple directly (defined above in Settings class)
        # This is safe because Settings is not instantiated until after this function is defined
        allowed_extensions_tuple = (
            ".csv",
            ".jdx",
            ".dx",
            ".json",
            ".spc",
            ".spa",
            ".spg",
            ".txt",
            ".wdf",
            ".dat",
            ".opus",
            ".mat",
        )

        if ext_lower in allowed_extensions_tuple:
            # Fall back to generic reader with a warning
            warnings.warn(
                f"Extension {ext_lower} has no explicit reader. "
                f"Falling back to generic scp.read(). "
                f"This may fail or produce unexpected results.",
                UserWarning,
            )
            return "read"

        # Truly unsupported extension
        supported = ", ".join(sorted(EXTENSION_READER_MAP.keys()))
        raise ValueError(
            f"Unsupported file extension: {ext}\n"
            f"Supported extensions: {supported}, or numeric extensions for OPUS files"
        )

    return EXTENSION_READER_MAP[ext_lower]


def _refresh_settings_singleton() -> Settings:
    fresh = Settings()
    existing = _PREVIOUS_SETTINGS
    if existing is not None and all(hasattr(existing, field_name) for field_name in Settings.__dataclass_fields__):
        for field_name in Settings.__dataclass_fields__:
            object.__setattr__(existing, field_name, getattr(fresh, field_name))
        return existing
    return fresh


# ============================================================================
# Multi-Mode Configuration (Local, Hybrid, Enterprise)
# ============================================================================


class LLMConfig(BaseModel):
    """Configuration for an LLM provider"""

    provider: Literal["openai", "anthropic", "deepseek", "gemini", "custom_llm"]
    api_key: Optional[str] = None
    model: str
    base_url: Optional[str] = None  # For custom endpoints

    @property
    def is_configured(self) -> bool:
        """Check if this LLM has an API key configured"""
        return self.api_key is not None and len(self.api_key) > 0


class ExecutionConfig(BaseModel):
    """Execution and compute settings"""

    mode: Literal["local", "hybrid"] = "local"
    gradient_api_key: Optional[str] = None
    auto_offload_threshold: int = 10000  # Dataset size threshold for GPU offload


class AppConfig(BaseModel):
    """Main application configuration for local, hybrid, and enterprise modes."""

    mode: Literal["local", "hybrid", "enterprise"] = Field(
        default="local", description="Application mode: local, hybrid, or enterprise"
    )
    egress_enabled: bool = Field(
        default=False, description="Enable network egress (external API calls). Defaults to False in local mode."
    )
    api_base_url: str = Field(default="http://localhost:8000", description="Backend API base URL")

    # Integration fields for commercial server extensions (enterprise/hybrid/demo).
    # These are None in OSS mode but can be injected by an extension package.
    site_profile: Optional[str] = Field(
        default=None, description="Site profile (e.g., 'demo', 'internal') - used by server extensions"
    )
    rate_limit_executions: Optional[int] = Field(
        default=None,
        description="Max executions per hour per user (enterprise/hybrid mode) - used by server extensions",
    )
    session_expiry_hours: Optional[int] = Field(
        default=None, description="Session expiry in hours (enterprise/hybrid mode) - used by server extensions"
    )
    spectrasherpa_log_url: Optional[str] = Field(
        default=None, description="Remote audit log URL for hybrid/enterprise mode - used by server extensions"
    )

    # LLM configurations
    llms: Dict[str, LLMConfig] = Field(default_factory=dict)

    # Execution settings
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from environment variables using registry defaults.

        Reads APP_MODE to determine operational mode (local, hybrid, enterprise).
        """
        import logging

        logger = logging.getLogger(__name__)

        # Determine app mode from environment
        raw_mode = os.getenv("APP_MODE", "local").strip().lower()
        if raw_mode not in ("local", "hybrid", "enterprise"):
            logger.warning("Unknown APP_MODE=%r — falling back to 'local'", raw_mode)
            raw_mode = "local"

        mode = raw_mode

        # Provider metadata — inlined for the /config endpoint's availability checks.
        # Previously imported from spectra_sherpa.app.core.llm_registry; the server
        # now owns provider selection policy through its admin routes.
        # OSS keeps a minimal static list here solely to populate AppConfig.llms
        # so that /api/v1/config can report provider availability to the frontend.
        PROVIDERS: dict[str, dict[str, Any]] = {
            "openai": {
                "id": "openai",
                "name": "OpenAI",
                "default_model": "gpt-4o",
                "base_url": "https://api.openai.com/v1",
                "env_var": "OPENAI_API_KEY",
            },
            "anthropic": {
                "id": "anthropic",
                "name": "Anthropic",
                "default_model": "claude-3-5-sonnet-20241022",
                "base_url": "https://api.anthropic.com",
                "env_var": "ANTHROPIC_API_KEY",
            },
            "deepseek": {
                "id": "deepseek",
                "name": "DeepSeek",
                "default_model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "env_var": "DEEPSEEK_API_KEY",
            },
            "gemini": {
                "id": "gemini",
                "name": "Google Gemini",
                "default_model": "gemini-1.5-pro",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "env_var": "GEMINI_API_KEY",
            },
            "custom_llm": {
                "id": "custom_llm",
                "name": "Custom LLM",
                "default_model": "custom-model",
                "base_url": "",
                "env_var": "CUSTOM_LLM_API_KEY",
            },
        }

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

        # Egress: disabled by default in local (privacy-first), enabled in hybrid/enterprise
        egress_enabled = _get_bool("EGRESS_ENABLED", mode != "local")

        # Enterprise/hybrid integration fields
        site_profile = os.getenv("SITE_PROFILE", "").strip() or None
        rate_limit_raw = _get_int("RATE_LIMIT_EXECUTIONS", 0) if mode != "local" else 0
        rate_limit_executions = rate_limit_raw if rate_limit_raw else None
        session_expiry_raw = _get_int("SESSION_EXPIRY_HOURS", 0) if mode != "local" else 0
        session_expiry_hours = session_expiry_raw if session_expiry_raw else None

        return cls(
            mode=mode,  # type: ignore[arg-type]
            egress_enabled=egress_enabled,
            api_base_url=os.getenv("API_BASE_URL", "http://localhost:8000"),
            site_profile=site_profile,
            rate_limit_executions=rate_limit_executions,
            session_expiry_hours=session_expiry_hours,
            llms=llm_configs,
            execution=ExecutionConfig(
                mode="hybrid" if mode != "local" else "local",
                gradient_api_key=os.getenv("GRADIENT_API_KEY"),
                auto_offload_threshold=int(os.getenv("AUTO_OFFLOAD_THRESHOLD", "10000")),
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
        return {name: llm_config for name, llm_config in self.llms.items() if llm_config.is_configured}

    def to_client_safe(self) -> dict:
        """Return client-safe configuration (no secrets).

        ``registrationEnabled`` and ``registrationRequiresCode`` are
        server-owned flags. The commercial server declares their values
        at startup via ``spectra_sherpa.app.contracts.auth_policy``; OSS
        reads them here. In OSS-only installs both default to ``False``
        — the base shape carries those defaults, which is the correct
        behavior for distributions without managed auth. If the server
        overlay provider overrides them in its payload, the config
        route merges those values on top.
        """
        has_llm = len(self.get_configured_llms()) > 0

        from spectra_sherpa.app.contracts.auth_policy import (
            registration_requires_code as _registration_requires_code_flag,
        )
        from spectra_sherpa.app.core.mode_policy import allows_registration

        # ``allows_registration()`` layers the multi-user mode check on
        # top of the server-registered flag.
        registration_enabled = allows_registration()
        # ``registration_requires_code`` is independent of mode: the
        # server declares whether an access code is required; OSS
        # simply surfaces it.
        registration_requires_code = _registration_requires_code_flag()

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

        result: dict[str, Any] = {
            "mode": self.mode,
            "egressEnabled": self.egress_enabled,
            "apiBaseUrl": self.api_base_url,
            "registrationEnabled": registration_enabled,
            "registrationRequiresCode": registration_requires_code,
            "siteProfile": self.site_profile,
            "features": {
                "apiTokenSettings": self.mode in ("local", "hybrid"),
                "cloudOffload": self.execution.gradient_api_key is not None,
                CHAT_ASSISTANT: has_llm,
                "nistDownloads": self.egress_enabled,
                # Sherpa capabilities default to False; server overlay enables them.
                **{cap: False for cap in ALL_SHERPA_CAPABILITIES},
                "pluginSystem": True,
            },
            "llms": {
                name: {"provider": llm.provider, "model": llm.model, "enabled": llm.is_configured}
                for name, llm in self.llms.items()
            },
            "limits": limits,
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
