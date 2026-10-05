"""One shared absolute performance-ceiling contract for canonical node tests."""

from __future__ import annotations

import math
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class PerformanceCeiling:
    """Identify one representative fixture and its generous wall-clock ceiling."""

    node_type: str
    fixture_id: str
    seconds: float

    def __post_init__(self) -> None:
        if not self.node_type.strip():
            raise ValueError("performance ceiling requires a node type")
        if not self.fixture_id.strip():
            raise ValueError("performance ceiling requires a fixture identifier")
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("performance ceiling seconds must be finite and positive")

    @contextmanager
    def measure(self) -> Iterator[None]:
        """Measure one correctness-neutral execution without masking its errors."""

        started = time.perf_counter()
        yield
        elapsed = time.perf_counter() - started
        assert elapsed < self.seconds, (
            f"{self.node_type} fixture {self.fixture_id!r} took {elapsed:.3f}s; "
            f"reviewed ceiling is {self.seconds:.3f}s"
        )
