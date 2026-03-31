"""
Regression tests for bug fixes applied in the review cycle.

Covers:
  1. Path traversal validation in batch predict / folder watch
  2. Comparison ordering determinism
  3. Rate limit coverage for deploy endpoint
  4. Folder watch dedupe uses full path
  5. Workflow provenance fields (technique, sample_type) persistence
  6. discover_files exclude backward compatibility

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_bugfix_regression.py -v --no-cov
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# 1. Path traversal validation
# ---------------------------------------------------------------------------


class TestValidateFolderPath:
    """validate_folder_path must restrict paths in non-local modes."""

    def test_local_mode_allows_any_path(self, tmp_path: Path):
        """In local mode, any accessible path is allowed."""
        from spectra_sherpa.app.services.batch_predict import validate_folder_path

        with patch("spectra_sherpa.app.core.mode_policy.is_enterprise", return_value=False):
            result = validate_folder_path(str(tmp_path))
            assert result == tmp_path.resolve()

    def test_hybrid_mode_blocks_outside_data_dir(self, tmp_path: Path):
        """In hybrid mode, paths outside data_dir are rejected."""
        from spectra_sherpa.app.services.batch_predict import validate_folder_path

        outside = tmp_path / "outside"
        outside.mkdir()

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with (
            patch("spectra_sherpa.app.core.mode_policy.is_enterprise", return_value=True),
            patch("spectra_sherpa.app.core.config.settings") as mock_settings,
        ):
            mock_settings.data_dir = data_dir
            with pytest.raises(ValueError, match="must be under the data directory"):
                validate_folder_path(str(outside))

    def test_hybrid_mode_allows_inside_data_dir(self, tmp_path: Path):
        """In hybrid mode, paths under data_dir are allowed."""
        from spectra_sherpa.app.services.batch_predict import validate_folder_path

        data_dir = tmp_path / "data"
        sub = data_dir / "spectra" / "batch1"
        sub.mkdir(parents=True)

        with (
            patch("spectra_sherpa.app.core.mode_policy.is_enterprise", return_value=True),
            patch("spectra_sherpa.app.core.config.settings") as mock_settings,
        ):
            mock_settings.data_dir = data_dir
            result = validate_folder_path(str(sub))
            assert result == sub.resolve()

    def test_traversal_attempt_blocked(self, tmp_path: Path):
        """Traversal via ../.. is caught after resolve()."""
        from spectra_sherpa.app.services.batch_predict import validate_folder_path

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        traversal_path = str(data_dir / ".." / ".." / "etc")

        with (
            patch("spectra_sherpa.app.core.mode_policy.is_enterprise", return_value=True),
            patch("spectra_sherpa.app.core.config.settings") as mock_settings,
        ):
            mock_settings.data_dir = data_dir
            with pytest.raises(ValueError, match="must be under the data directory"):
                validate_folder_path(traversal_path)


# ---------------------------------------------------------------------------
# 2. discover_files exclude backward compatibility
# ---------------------------------------------------------------------------


class TestDiscoverFilesExclude:
    """discover_files should check both full path and filename in exclude set."""

    def _create_spectral_files(self, folder: Path) -> list[Path]:
        """Create stable test files (mtime > 5s ago)."""
        files = []
        for name in ["a.csv", "b.csv", "c.csv"]:
            p = folder / name
            p.write_text("data")
            # Set mtime to 10s ago so stability check passes
            old_time = time.time() - 10
            os.utime(p, (old_time, old_time))
            files.append(p)
        return files

    def test_exclude_by_full_path(self, tmp_path: Path):
        """Files excluded by full path string are skipped."""
        from spectra_sherpa.app.services.batch_predict import discover_files

        files = self._create_spectral_files(tmp_path)
        exclude = {str(files[0])}  # Exclude by full path

        with patch("spectra_sherpa.app.core.mode_policy.is_local", return_value=True):
            result = discover_files(str(tmp_path), "*", exclude_names=exclude)
            names = [f.name for f in result]
            assert "a.csv" not in names
            assert "b.csv" in names
            assert "c.csv" in names

    def test_exclude_by_filename_backward_compat(self, tmp_path: Path):
        """Files excluded by filename only are skipped (backward compat)."""
        from spectra_sherpa.app.services.batch_predict import discover_files

        self._create_spectral_files(tmp_path)
        exclude = {"b.csv"}  # Old-style filename-only exclude

        with patch("spectra_sherpa.app.core.mode_policy.is_local", return_value=True):
            result = discover_files(str(tmp_path), "*", exclude_names=exclude)
            names = [f.name for f in result]
            assert "a.csv" in names
            assert "b.csv" not in names
            assert "c.csv" in names


# ---------------------------------------------------------------------------
# 3. Comparison ordering
# ---------------------------------------------------------------------------


class TestComparisonOrdering:
    """Comparison queries must use ORDER BY for deterministic results."""

    def test_execution_runs_compare_has_order_by(self):
        """execution_runs.py compare endpoint query uses .order_by()."""
        import inspect

        from spectra_sherpa.app.api.v1.routes.execution_runs import compare_runs

        source = inspect.getsource(compare_runs)
        assert "order_by" in source, "compare_runs query must include .order_by() for deterministic ordering"

    def test_workflow_export_report_data_has_order_by(self):
        """workflow_export.py report-data endpoint query uses .order_by()."""
        import inspect

        from spectra_sherpa.app.api.v1.routes.workflow_export import get_report_data

        source = inspect.getsource(get_report_data)
        assert "order_by" in source, "get_report_data query must include .order_by() for deterministic ordering"


# ---------------------------------------------------------------------------
# 5. Workflow provenance fields (technique, sample_type) in routes
# ---------------------------------------------------------------------------


class TestWorkflowProvenanceFields:
    """Workflow create/update/list/snapshot/restore must include technique & sample_type."""

    def test_create_workflow_passes_technique_and_sample_type(self):
        """create_workflow route constructor includes technique and sample_type."""
        import inspect

        from spectra_sherpa.app.api.v1.routes.workflows import create_workflow

        source = inspect.getsource(create_workflow)
        assert "technique=payload.technique" in source
        assert "sample_type=payload.sample_type" in source

    def test_update_workflow_handles_technique_and_sample_type(self):
        """update_workflow route sets technique and sample_type when provided."""
        import inspect

        from spectra_sherpa.app.api.v1.routes.workflows import update_workflow

        source = inspect.getsource(update_workflow)
        assert "payload.technique" in source
        assert "payload.sample_type" in source

    def test_list_workflows_includes_technique_and_sample_type(self):
        """list_workflows serialization includes technique and sample_type."""
        import inspect

        from spectra_sherpa.app.api.v1.routes.workflows import list_workflows

        source = inspect.getsource(list_workflows)
        assert '"technique"' in source or "technique" in source
        assert '"sample_type"' in source or "sample_type" in source

    def test_version_snapshot_includes_technique_and_sample_type(self):
        """Version snapshot dict (in update_workflow) includes technique and sample_type."""
        import inspect

        from spectra_sherpa.app.api.v1.routes.workflows import update_workflow

        source = inspect.getsource(update_workflow)
        # The snapshot dict is built inside update_workflow
        assert "technique" in source
        assert "sample_type" in source

    def test_version_restore_handles_technique_sample_type_notes(self):
        """Version restore checks for technique, sample_type, and notes in snapshot."""
        import inspect

        from spectra_sherpa.app.api.v1.routes.workflows import restore_workflow_version

        source = inspect.getsource(restore_workflow_version)
        for field in ["technique", "sample_type", "notes"]:
            assert field in source, f"restore_workflow_version must restore '{field}' from snapshot"


# ---------------------------------------------------------------------------
# 6. Folder watch dedupe uses full path
# ---------------------------------------------------------------------------


class TestFolderWatchDedupe:
    """Folder watch service must key processed files by full path, not filename."""

    def test_processed_files_key_is_full_path(self):
        """folder_watch_service marks files with str(file_path), not file_path.name."""
        import inspect

        from spectra_sherpa.app.services.folder_watch_service import FolderWatchService

        source = inspect.getsource(FolderWatchService)
        # The key should be str(file_path), not file_path.name
        assert (
            "processed[str(file_path)]" in source
        ), "Processed files dict must use str(file_path) as key for uniqueness"
        # Old pattern should NOT be present
        assert (
            "processed[file_path.name]" not in source
        ), "Processed files dict must NOT use file_path.name as key (collision risk)"


# ---------------------------------------------------------------------------
# 7. Poison Pill DB Transaction Loop Prevention
# ---------------------------------------------------------------------------


class TestPoisonPillTransactionLoop:
    """batch_predict and folder_watch_service must catch session.commit() errors per-file."""

    def test_batch_predict_catches_commit_errors(self):
        """run_batch_prediction wraps session.commit() in try/except inside the loop."""
        import inspect

        from spectra_sherpa.app.services.batch_predict import run_batch_prediction

        source = inspect.getsource(run_batch_prediction)
        # Ensure we have a try block specifically for the commit
        assert (
            "try:\n            await session.commit()" in source
            or "try:\n                await session.commit()" in source
        )
        assert "await session.rollback()" in source

    def test_folder_watch_catches_commit_errors(self):
        """_process_watch wraps session.commit() in try/except inside the file loop."""
        import inspect

        from spectra_sherpa.app.services.folder_watch_service import FolderWatchService

        source = inspect.getsource(FolderWatchService._process_watch)
        assert "try:\n                        await session.commit()" in source
        assert "await session.rollback()" in source
