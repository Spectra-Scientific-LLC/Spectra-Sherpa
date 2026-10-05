"""
Environment Variable Validation

Validates critical environment variables at application startup to provide
early, clear error messages instead of cryptic runtime failures.
"""

from __future__ import annotations

import logging
import os
import warnings
from typing import List, Tuple

logger = logging.getLogger(__name__)


class EnvValidationWarning(UserWarning):
    """Warning for non-critical environment variable issues."""

    pass


# Master-key placeholders that must never be accepted as a real encryption key.
# MASTER_ENCRYPTION_KEY roots the Fernet derivation that wraps every stored
# secret (BYOK LLM keys, HITRAN keys, managed system keys, and the per-user
# artifact data keys behind Pro crypto-custody). The runtime derives the Fernet
# key from a non-Fernet secret via a single SHA-256; that is cryptographically
# sound ONLY when the input is high-entropy, so we forbid low-entropy inputs
# here rather than paying for a slow KDF the strong-input case doesn't need.
_INSECURE_MASTER_KEY_PLACEHOLDERS = {
    "changeme",
    "change-me",
    "change_me",
    "default",
    "secret",
    "password",
    "master-key",
    "master_key",
    "masterkey",
    "master-encryption-key",
    "your-master-key",
    "your-master-encryption-key",
}
_MIN_MASTER_KEY_UNIQUE_CHARS = 8


def _looks_like_fernet_key(value: str) -> bool:
    """True when *value* is a raw 32-byte urlsafe-base64 Fernet key.

    Such keys are high-entropy by construction, so they bypass the
    placeholder/uniqueness heuristics below.
    """
    import base64

    try:
        decoded = base64.urlsafe_b64decode(value.encode())
    except Exception:
        return False
    return len(decoded) == 32


def validate_headless_env() -> List[str]:
    """
    Validate environment for headless mode.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    workflow_id = os.getenv("HEADLESS_WORKFLOW_ID")
    if workflow_id is not None:
        # Headless mode is active - validate the ID
        try:
            int(workflow_id)
        except ValueError:
            errors.append(f"HEADLESS_WORKFLOW_ID must be a valid integer, got: {workflow_id}")

    return errors


def validate_encryption_env() -> List[str]:
    """
    Validate encryption environment variables.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    warnings_list = []

    master_key = os.getenv("MASTER_ENCRYPTION_KEY")
    if master_key is not None:
        # Accept either a raw Fernet key or a normal high-entropy secret.
        # The runtime derives a Fernet key from non-Fernet values via a single
        # SHA-256, so the security of the whole scheme rests on the INPUT being
        # high-entropy — enforce that here.
        value = master_key.strip()
        if len(value) < 32:
            errors.append("MASTER_ENCRYPTION_KEY must be at least 32 characters for security")
        elif _looks_like_fernet_key(value):
            # A raw Fernet key is 32 random bytes — always strong enough.
            pass
        else:
            normalized = value.lower()
            if normalized in _INSECURE_MASTER_KEY_PLACEHOLDERS or (
                normalized.startswith("<") and normalized.endswith(">")
            ):
                errors.append(
                    "MASTER_ENCRYPTION_KEY is a placeholder/default value. Generate a strong "
                    'random value with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
                )
            elif len(set(value)) < _MIN_MASTER_KEY_UNIQUE_CHARS:
                errors.append(
                    "MASTER_ENCRYPTION_KEY appears too low-entropy (a long but repetitive value "
                    "does not count as strong). Generate a fresh random value."
                )
            elif len(value) < 64:
                warnings_list.append("MASTER_ENCRYPTION_KEY should be at least 64 characters for optimal security")

    for warning_msg in warnings_list:
        warnings.warn(warning_msg, EnvValidationWarning)

    return errors


def validate_llm_env() -> List[Tuple[str, str]]:
    """
    Validate LLM API key environment variables.

    Returns:
        List of (provider, status) tuples for configured providers
    """
    providers = {
        "OpenAI": "OPENAI_API_KEY",
        "Anthropic": "ANTHROPIC_API_KEY",
        "DeepSeek": "DEEPSEEK_API_KEY",
        "Gemini": "GEMINI_API_KEY",
    }

    results = []
    for provider, env_var in providers.items():
        value = os.getenv(env_var)
        if value:
            # Validate key format (basic check)
            if len(value) < 10:
                results.append((provider, "⚠️  Set but looks invalid (too short)"))
            else:
                results.append((provider, "✓ Configured"))
        else:
            results.append((provider, "Not set"))

    return results


def validate_all_env() -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    Validate all environment variables at startup.

    Returns:
        (errors, llm_status) where:
        - errors: List of critical error messages (will prevent startup if non-empty)
        - llm_status: List of (provider, status) tuples for LLM providers
    """
    all_errors = []

    # Critical validations
    all_errors.extend(validate_headless_env())
    all_errors.extend(validate_encryption_env())

    # Informational LLM status
    llm_status = validate_llm_env()

    return all_errors, llm_status


def log_env_validation_results(errors: List[str], llm_status: List[Tuple[str, str]]):
    """
    Log environment validation results.

    Args:
        errors: List of error messages
        llm_status: List of (provider, status) tuples
    """
    if errors:
        logger.error("=" * 60)
        logger.error("ENVIRONMENT VARIABLE VALIDATION ERRORS")
        logger.error("=" * 60)
        for error in errors:
            logger.error(f"  ❌ {error}")
        logger.error("=" * 60)
        logger.error("Please fix the above errors and restart the application.")
        logger.error("=" * 60)
    else:
        logger.info("Environment variable validation passed ✓")

    if llm_status:
        logger.info("LLM Provider Status:")
        for provider, status in llm_status:
            logger.info(f"  {provider:12} {status}")


def validate_and_raise_on_errors():
    """
    Validate environment variables and raise if critical errors found.

    This should be called early in application startup.

    Raises:
        RuntimeError: If critical environment variable errors are found
    """
    errors, llm_status = validate_all_env()
    log_env_validation_results(errors, llm_status)

    if errors:
        raise RuntimeError(
            f"Environment variable validation failed with {len(errors)} error(s). " "See logs above for details."
        )
