"""Structural proofs for the shared canonical-node performance harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import performance_contract
from tests.performance_contract import PerformanceCeiling


@pytest.mark.parametrize(
    ("node_type", "fixture_id", "seconds", "message"),
    [
        ("", "representative", 5.0, "node type"),
        ("model.svr", "", 5.0, "fixture identifier"),
        ("model.svr", "representative", 0.0, "finite and positive"),
        ("model.svr", "representative", float("inf"), "finite and positive"),
    ],
)
def test_performance_ceiling_requires_closed_identity_and_positive_limit(
    node_type: str,
    fixture_id: str,
    seconds: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PerformanceCeiling(node_type=node_type, fixture_id=fixture_id, seconds=seconds)


def test_performance_ceiling_reports_fixture_and_reviewed_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    readings = iter((10.0, 15.5))
    monkeypatch.setattr(performance_contract.time, "perf_counter", lambda: next(readings))

    with pytest.raises(AssertionError, match=r"model\.svr fixture '120x400-default'.*5\.000s"):
        with PerformanceCeiling("model.svr", "120x400-default", 5.0).measure():
            pass


def test_performance_ceiling_does_not_mask_operation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(performance_contract.time, "perf_counter", lambda: 10.0)

    with pytest.raises(RuntimeError, match="scientific operation failed"):
        with PerformanceCeiling("model.svr", "120x400-default", 5.0).measure():
            raise RuntimeError("scientific operation failed")


def test_node_performance_proofs_use_the_shared_harness() -> None:
    tests_root = Path(__file__).parent
    non_node_timing_authorities = {
        Path("performance_contract.py"),
        Path("test_import_sanity.py"),
        Path("test_performance_contract.py"),
        Path("services/audit/test_hot_path_overhead.py"),
    }
    direct_timers = sorted(
        path.relative_to(tests_root)
        for path in tests_root.rglob("*.py")
        if path.relative_to(tests_root) not in non_node_timing_authorities
        and "perf_counter" in path.read_text(encoding="utf-8")
    )

    assert direct_timers == [], (
        "canonical node performance proofs must use tests.performance_contract.PerformanceCeiling: " f"{direct_timers}"
    )
