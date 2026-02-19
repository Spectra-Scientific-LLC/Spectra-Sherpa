from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from spectra_sherpa._paths import (
    get_default_data_dir,
    get_env_file_search_paths,
    get_package_root,
    get_project_root,
)


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

# Load .env from the first location that exists
for _env_candidate in get_env_file_search_paths():
    if _env_candidate.is_file():
        load_dotenv(_env_candidate)
        break

DATA_DIR = get_default_data_dir()

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite+aiosqlite:///{DATA_DIR / 'spectra_platform.db'}"
APP_API_KEY = os.getenv("APP_API_KEY", "default-local-key")


@dataclass(frozen=True)
class Settings:
    app_name: str = "Spectra Scientific Platform"
    app_version: str = "1.3.3"  # Increment when node definitions change
    project_root: Path = PROJECT_ROOT
    backend_root: Path = BACKEND_ROOT
    data_dir: Path = DATA_DIR
    database_url: str = DATABASE_URL
    api_key: str = APP_API_KEY

    # JWT Authentication
    secret_key: str = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
    algorithm: str = "HS256"
    # Token lifetime: 8 days for local convenience, 60 min for internet-facing modes.
    # Override with ACCESS_TOKEN_EXPIRE_MINUTES env var.
    access_token_expire_minutes: int = _get_int(
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        60 if os.getenv("APP_MODE", "local") != "local" else 60 * 24 * 8,
    )

    max_spectra_per_job: int = _get_int("MAX_SPECTRA_PER_JOB", 1000)  # Increased for MCR-ALS datasets
    max_wavenumbers: int = _get_int("MAX_WAVENUMBERS", 20000)
    max_memory_mb: int = _get_int("MAX_MEMORY_MB", 4096)
    max_concurrent_jobs: int = _get_int("MAX_CONCURRENT_JOBS", 5)
    max_concurrent_jobs_per_user: int = _get_int("MAX_CONCURRENT_JOBS_PER_USER", 1)
    max_nist_downloads_per_hour: int = _get_int("MAX_NIST_DOWNLOADS_PER_HOUR", 50)
    max_llm_requests_per_hour: int = _get_int("MAX_LLM_REQUESTS_PER_HOUR", 100)

    max_file_size_mb: int = _get_int("MAX_FILE_SIZE_MB", 200)
    max_job_duration_sec: int = _get_int("MAX_JOB_DURATION_SEC", 3600)
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


settings = Settings()


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


class DemoContract(BaseModel):
    """Configuration for the demo experience profile."""

    featured_datasets: list[str] = [
        "diesel_nir",
        "corn_m5",
        "nir_shootout_cal1",
        "nir_shootout_test1",
        "metal_etch_oes",
    ]
    featured_templates: list[str] = [
        "pca",
        "project1",
        "pls_regression",
        "ir_opus_analysis",
        "preprocessing",
    ]

    max_executions_per_session: int = 25
    max_sherpa_interactions: int = 20

    disabled_capabilities: list[str] = [
        "data_upload",
        "project_import",
        "llm_config",
        "api_key_management",
    ]

    upgrade_url: str = os.getenv("UPGRADE_URL", "")
    upgrade_message: str = os.getenv("UPGRADE_MESSAGE", "")
    available_plans: list[str] = []


class AppConfig(BaseModel):
    """Main application configuration for multi-mode operation"""

    mode: Literal["local", "hybrid", "enterprise"] = Field(
        default="local", description="Application mode: local, hybrid, or enterprise (cloud/SaaS)."
    )
    egress_enabled: bool = Field(
        default=False, description="Enable network egress (external API calls). Defaults to False in local mode."
    )
    api_base_url: str = Field(default="http://localhost:8000", description="Backend API base URL")
    cloud_compute_url: Optional[str] = Field(
        default=os.getenv("CLOUD_COMPUTE_URL"), description="URL for offloading compute in hybrid mode"
    )
    cloud_api_key: Optional[str] = Field(
        default=os.getenv("CLOUD_API_KEY"), description="API Key for the remote cloud instance"
    )
    spectrasherpa_log_url: Optional[str] = Field(
        default=os.getenv("SPECTRASHERPA_LOG_URL"), description="URL for remote audit logging (Hybrid mode)"
    )

    # LLM configurations
    llms: Dict[str, LLMConfig] = Field(default_factory=dict)

    # Execution settings
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    # Rate limiting (hybrid + enterprise modes)
    rate_limit_executions: Optional[int] = None
    session_expiry_hours: Optional[int] = None

    # Marketing / UI label (independent of runtime mode)
    site_profile: Optional[Literal["demo", "production", "internal"]] = None

    # Demo experience contract (active when site_profile == "demo")
    demo_contract: DemoContract = Field(default_factory=DemoContract)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from environment variables using registry defaults"""
        # Import registry to get provider metadata
        try:
            from spectra_sherpa.app.core.llm_registry import PROVIDERS
        except ImportError:
            # Fallback if registry not available (shouldn't happen)
            PROVIDERS = {
                "openai": {
                    "default_model": "gpt-4o",
                    "base_url": "https://api.openai.com/v1",
                    "env_var": "OPENAI_API_KEY",
                },
                "anthropic": {
                    "default_model": "claude-3-5-sonnet-20241022",
                    "base_url": "https://api.anthropic.com",
                    "env_var": "ANTHROPIC_API_KEY",
                },
                "deepseek": {
                    "default_model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                    "env_var": "DEEPSEEK_API_KEY",
                },
                "gemini": {
                    "default_model": "gemini-1.5-pro",
                    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "env_var": "GEMINI_API_KEY",
                },
                "custom_llm": {"default_model": "custom-model", "base_url": "", "env_var": "CUSTOM_LLM_API_KEY"},
            }

        # Build LLM configs from registry
        llm_configs = {}
        for provider_id, provider_meta in PROVIDERS.items():
            model_env = f"{provider_id.upper()}_MODEL"
            llm_configs[provider_id] = LLMConfig(
                provider=provider_id,
                api_key=os.getenv(provider_meta.get("env_var", f"{provider_id.upper()}_API_KEY")),
                model=os.getenv(model_env, provider_meta["default_model"]),
                base_url=provider_meta.get("base_url"),
            )

        # Determine egress enabled default based on mode
        # Local mode: egress disabled by default (privacy-first)
        # Hybrid/Enterprise: egress enabled by default (cloud features require it)
        import logging

        _logger = logging.getLogger(__name__)

        raw_mode = os.getenv("APP_MODE", "local")
        if raw_mode == "demo":
            _logger.warning(
                "APP_MODE=demo is no longer valid. Use APP_MODE=enterprise " "with SITE_PROFILE=demo instead."
            )
            app_mode = "enterprise"  # graceful fallback for one release cycle
        else:
            app_mode = raw_mode

        egress_default = app_mode != "local"
        egress_enabled = _get_bool("EGRESS_ENABLED", egress_default)

        # Resolve site profile (defaults to "production" for enterprise mode).
        # Demo profile must be explicitly opted-in via SITE_PROFILE=demo.
        site_profile_raw = os.getenv("SITE_PROFILE")
        if site_profile_raw and site_profile_raw in ("demo", "production", "internal"):
            site_profile = site_profile_raw
        elif app_mode == "enterprise":
            site_profile = "production"
        else:
            site_profile = None

        # Build demo contract from env overrides
        demo_contract = DemoContract(
            max_executions_per_session=_get_int("DEMO_MAX_EXECUTIONS", 25),
            max_sherpa_interactions=_get_int("DEMO_MAX_SHERPA_INTERACTIONS", 20),
            upgrade_url=os.getenv("UPGRADE_URL", ""),
        )

        return cls(
            mode=app_mode,
            egress_enabled=egress_enabled,
            api_base_url=os.getenv("API_BASE_URL", "http://localhost:8000"),
            llms=llm_configs,
            execution=ExecutionConfig(
                mode=os.getenv("EXECUTION_MODE", "local"),
                gradient_api_key=os.getenv("GRADIENT_API_KEY"),
                auto_offload_threshold=int(os.getenv("AUTO_OFFLOAD_THRESHOLD", "10000")),
            ),
            # Enterprise mode: default to 100 executions/hour and 24-hour sessions
            # unless explicitly overridden.  In other modes these stay None
            # (disabled) unless the operator sets the env var.
            rate_limit_executions=(
                _get_int("RATE_LIMIT_EXECUTIONS", 100)
                if (os.getenv("RATE_LIMIT_EXECUTIONS") or app_mode == "enterprise")
                else None
            ),
            session_expiry_hours=(
                _get_int("SESSION_EXPIRY_HOURS", 24)
                if (os.getenv("SESSION_EXPIRY_HOURS") or app_mode == "enterprise")
                else None
            ),
            site_profile=site_profile,
            demo_contract=demo_contract,
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
        """Return client-safe configuration (no secrets)"""
        has_llm = len(self.get_configured_llms()) > 0

        # Pull subscription-derived feature flags from the advisor cache.
        # These are populated during hybrid activation / startup.
        sub_features: dict = {}
        sub_plan: str = "none"
        try:
            from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

            advisor = get_sherpa_advisor()
            sub_features = advisor._subscription_features or {}
            sub_plan = advisor._subscription_plan
        except Exception:
            pass

        # Registration requires the full auth module (spectra-server) + mode policy.
        try:
            from spectrasherpa_server.routes import auth as _auth_mod  # noqa: F401

            _has_register = hasattr(_auth_mod, "router")
        except ImportError:
            _has_register = False
        from spectra_sherpa.app.core.mode_policy import allows_registration

        registration_enabled = _has_register and allows_registration()

        # Registration gating: only relevant in enterprise mode where
        # spectra-server actually enforces the password check.
        registration_requires_code = self.mode == "enterprise" and bool(os.getenv("ENTERPRISE_PASSWORD", "").strip())

        return {
            "mode": self.mode,
            "egressEnabled": self.egress_enabled,
            "apiBaseUrl": self.api_base_url,
            "siteProfile": self.site_profile,
            "registrationEnabled": registration_enabled,
            "registrationRequiresCode": registration_requires_code,
            "features": {
                "apiTokenSettings": self.mode in ["local", "hybrid"],
                "cloudOffload": self.execution.mode == "hybrid",
                "chatAssistant": has_llm,
                "nistDownloads": self.egress_enabled,
                "sherpaAdvisor": bool(sub_features.get("sherpa_sync", False)),
                "pluginSystem": True,  # Always available (local discovery)
                # Subscription-gated Sherpa capabilities
                "sherpaPeakId": sub_features.get("identify_peaks", False),
                "sherpaCodeGen": sub_features.get("generate_code", False),
                "sherpaWriteReport": sub_features.get("write_report", False),
                "sherpaAgenticTools": sub_features.get("agentic_tools", False),
                "sherpaFullContext": sub_features.get("full_dag_context", False),
            },
            "subscription": (
                {
                    "plan": sub_plan,
                }
                if sub_features
                else None
            ),
            "llms": {
                name: {"provider": llm.provider, "model": llm.model, "enabled": llm.is_configured}
                for name, llm in self.llms.items()
            },
            "limits": (
                {
                    "maxExecutions": self.rate_limit_executions,
                    "maxFileSizeMB": settings.max_file_size_mb,
                    "sessionExpiryHours": self.session_expiry_hours,
                }
                if self.mode == "enterprise"
                else None
            ),
            "demo": self.demo_contract.model_dump() if self.site_profile == "demo" else None,
        }


# Global app config instance
app_config = AppConfig.from_env()
