"""Real directory scans must make progress without relaxing per-poll bounds."""

from spectra_sherpa.app.services.watch_discovery import WatchDiscovery


def _scan(scanner, folder, processed, **kwargs):
    return scanner.scan(
        str(folder),
        "*.csv",
        generation=1,
        exclude_names=processed,
        settle_time_seconds=0,
        max_files=16,
        **kwargs,
    )


def test_backlog_over_one_thousand_drains_and_restart_does_not_duplicate(tmp_path):
    for i in range(1001):
        (tmp_path / f"sample-{i:04}.csv").touch()
    processed = set()
    scanner = WatchDiscovery()
    try:
        for poll in range(70):
            batch = _scan(scanner, tmp_path, processed)
            assert len(batch.files) <= 16
            names = {str(p) for p in batch.files}
            assert not names & processed
            processed.update(names)
            if poll == 10:
                scanner.close()
                scanner = WatchDiscovery()  # Durable history, fresh process cursor.
            if len(processed) == 1001:
                break
        assert len(processed) == 1001
    finally:
        scanner.close()


def test_history_over_ten_thousand_does_not_starve_arrivals(tmp_path):
    processed = set()
    for i in range(10001):
        path = tmp_path / f"old-{i:05}.csv"
        path.touch()
        processed.add(str(path))
    fresh = tmp_path / "fresh.csv"
    fresh.touch()
    scanner = WatchDiscovery()
    seen = []
    try:
        for _ in range(4):
            batch = _scan(scanner, tmp_path, processed)
            assert batch.entries_examined <= 10000
            seen.extend(batch.files)
            processed.update(str(p) for p in batch.files)
        assert seen == [fresh]
        later = tmp_path / "later.csv"
        later.touch()
        for _ in range(4):
            batch = _scan(scanner, tmp_path, processed)
            seen.extend(batch.files)
            processed.update(str(p) for p in batch.files)
        assert seen == [fresh, later]
    finally:
        scanner.close()


def test_partial_scan_revisits_unsettled_files_and_honors_filters(tmp_path):
    import time

    for name in (".hidden.csv", "__hidden.csv", "ignore.txt", "old.csv", "NEW.CSV"):
        (tmp_path / name).touch()
    scanner = WatchDiscovery()
    try:
        for _ in range(6):
            batch = scanner.scan(
                str(tmp_path),
                "*.csv",
                generation=1,
                exclude_names={"old.csv"},
                settle_time_seconds=60,
                max_files=16,
                max_entries=2,
            )
            assert not batch.files
            assert batch.entries_examined <= 2
        import os

        os.utime(tmp_path / "NEW.CSV", (time.time() - 120, time.time() - 120))
        found = []
        for _ in range(4):
            batch = scanner.scan(
                str(tmp_path),
                "*.csv",
                generation=1,
                exclude_names={"old.csv"},
                settle_time_seconds=60,
                max_files=16,
                max_entries=2,
            )
            found.extend(batch.files)
            if found:
                break
        assert found == [tmp_path / "NEW.CSV"]
    finally:
        scanner.close()


def test_configuration_change_restarts_scan(tmp_path):
    (tmp_path / "a.csv").touch()
    (tmp_path / "b.txt").touch()
    scanner = WatchDiscovery()
    try:
        assert _scan(scanner, tmp_path, set(), max_entries=1).entries_examined == 1
        batch = scanner.scan(
            str(tmp_path), "*.txt", generation=2, exclude_names=set(), settle_time_seconds=0, max_files=16
        )
        assert batch.files == [tmp_path / "b.txt"]
    finally:
        scanner.close()


def test_directory_replacement_and_scan_error_recover(tmp_path):
    import pytest

    folder = tmp_path / "instrument"
    folder.mkdir()
    (folder / "old.csv").touch()
    scanner = WatchDiscovery()
    try:
        assert _scan(scanner, folder, set(), max_entries=1).files == [folder / "old.csv"]
        folder.rename(tmp_path / "archived")
        with pytest.raises(ValueError, match="Cannot scan watched folder"):
            _scan(scanner, folder, set())
        folder.mkdir()
        (folder / "new.csv").touch()
        assert _scan(scanner, folder, set()).files == [folder / "new.csv"]
    finally:
        scanner.close()


def test_unreadable_entry_does_not_restart_and_starve_following_file(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    healthy = tmp_path / "healthy.csv"
    healthy.touch()
    with os.scandir(tmp_path) as entries:
        entry = next(entries)

    def unreadable():
        raise PermissionError("synthetic denied target")

    def entries(_folder):
        yield SimpleNamespace(name="poison.csv", path=str(tmp_path / "poison.csv"), is_file=unreadable)
        yield entry

    monkeypatch.setattr(os, "scandir", entries)
    scanner = WatchDiscovery()
    try:
        first = _scan(scanner, tmp_path, set(), max_entries=1)
        assert first.files == []
        assert first.entry_error_count == 1
        assert "poison.csv" in first.first_entry_error
        second = _scan(scanner, tmp_path, set(), max_entries=1)
        assert second.files == [healthy]
        assert second.entry_error_count == 0
    finally:
        scanner.close()
