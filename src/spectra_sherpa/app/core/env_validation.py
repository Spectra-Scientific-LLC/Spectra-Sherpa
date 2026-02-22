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
        # Key is set - validate it
        if len(master_key) < 32:
            errors.append("MASTER_ENCRYPTION_KEY must be at least 32 characters for security")
        elif len(master_key) < 64:
            warnings_list.append("MASTER_ENCRYPTION_KEY should be at least 64 characters for optimal security")

    for warning_msg in warnings_list:
        warnings.warn(warning_msg, EnvValidationWarning)

    return errors


def validate_scp_env() -> List[str]:
    """
    Validate SpectroChemPy environment variables.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    warnings_list = []

    # SCP_DATADIR - optional but if set should be valid path
    scp_datadir = os.getenv("SCP_DATADIR")
    if scp_datadir:
        from pathlib import Path

        path = Path(scp_datadir)
        if not path.exists():
            warnings_list.append(f"SCP_DATADIR is set but directory doesn't exist: {scp_datadir}")
        elif not path.is_dir():
            errors.append(f"SCP_DATADIR must be a directory, got: {scp_datadir}")

    # SCP_DATA_TIMEOUT - optional but if set should be numeric
    timeout = os.getenv("SCP_DATA_TIMEOUT")
    if timeout is not None:
        try:
            timeout_val = int(timeout)
            if timeout_val < 0:
                errors.append(f"SCP_DATA_TIMEOUT must be non-negative, got: {timeout}")
        except ValueError:
            errors.append(f"SCP_DATA_TIMEOUT must be an integer, got: {timeout}")

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
                results.append((provider, f"⚠️  Set but looks invalid (too short)"))
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
    all_errors.extend(validate_scp_env())

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
