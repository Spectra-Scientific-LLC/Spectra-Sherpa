"""CLI tests for serve-model command.

Tests Issue #2: Headless CLI command must NOT launch browser.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spectra_sherpa.cli import main


def test_headless_mode_no_browser_launch():
    """Test that serve-model command does NOT launch browser."""
    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("spectra_sherpa.cli.threading.Thread") as mock_thread,
        patch("spectra_sherpa.cli.os.environ", {}) as mock_env,
    ):
        main(["serve-model", "123", "--port", "8001"])
        mock_thread.assert_not_called()
        assert "headless_app" in str(mock_uvicorn.call_args)
        assert mock_env["HEADLESS_WORKFLOW_ID"] == "123"


def test_normal_mode_launches_browser():
    """Test that normal mode launches browser."""
    with patch("uvicorn.run") as mock_uvicorn, patch("spectra_sherpa.cli.threading.Thread") as mock_thread:
        main(["--port", "8000"])
        mock_thread.assert_called_once()
        assert "main:app" in str(mock_uvicorn.call_args)
