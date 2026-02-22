import asyncio
import json
import os
from pathlib import Path

import pytest
from httpx import AsyncClient

from spectra_sherpa.app.services.batch_predict import discover_files


@pytest.mark.asyncio
async def test_folder_watch_settle_time(tmp_path):
    """Test that discover_files skips files younger than settle_time_seconds."""
    folder = tmp_path / "watch_dir"
    folder.mkdir()

    file1 = folder / "test1.spa"
    file1.touch()

    # Immediately check with settle_time_seconds=5 (file is 0 seconds old, so it should be skipped)
    found_files = discover_files(str(folder), settle_time_seconds=5)
    assert len(found_files) == 0, "File should be skipped because it hasn't settled"

    # Check with settle_time=0 (file should be found)
    found_files_0 = discover_files(str(folder), settle_time_seconds=0)
    assert len(found_files_0) == 1, "File should be found when settle_time is 0"

    # Wait slightly and test again just to be sure we could theoretically find it (we simulate by changing settle_time)
    await asyncio.sleep(0.1)
    found_files_short = discover_files(str(folder), settle_time_seconds=0.05)
    assert len(found_files_short) == 1, "File should be found after it ages past settle_time"


@pytest.mark.asyncio
async def test_headless_api_predict_missing_executor():
    """Test that headless API returns 500 when _executor is missing."""
    from spectra_sherpa.app.api.headless_app import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/predict", json={"sample": {"data": [[1, 2]]}})
        assert response.status_code == 500
        assert "Model executor not initialized" in response.text
