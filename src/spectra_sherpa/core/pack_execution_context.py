"""Task-local producing-pack identity for canonical provenance append only."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from spectra_sherpa.core.pack_requirements import PackNodeBinding

_producer: ContextVar[PackNodeBinding | None] = ContextVar("pack_producer", default=None)


def current_pack_producer(node_id: str | None) -> PackNodeBinding | None:
    binding = _producer.get()
    if binding is not None and node_id is not None and binding.node_id != node_id:
        raise ValueError("Pack provenance must identify the executing processing node")
    return binding


@contextmanager
def recording_pack_producer(binding: PackNodeBinding | None) -> Iterator[None]:
    token = _producer.set(binding)
    try:
        yield
    finally:
        _producer.reset(token)
