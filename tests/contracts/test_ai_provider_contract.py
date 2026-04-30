"""Contract tests for the AIServiceProvider Protocol.

The same suite is parametrized over two implementations:

  - ``DisabledAIProvider`` — the OSS-side default that ships when no
    commercial server has called ``set_sherpa_advisor()``. This is the
    real OSS implementation; if it ever drifts from the Protocol, OSS
    breaks.

  - ``MockPremiumProvider`` — an inline test fixture standing in for
    a server-side / "premium" implementation. The fixture returns
    plausible non-error responses for every method, exercising the
    streaming-vs-unary distinction. It is NOT a real provider; its only
    job is to prove the Protocol is implementable from outside OSS.

Note on ``basic_chat``: ``app/services/basic_chat.py`` is a BYO HTTP
proxy for OpenAI-compatible chat endpoints. It is intentionally NOT an
``AIServiceProvider`` implementation — it's a separate, narrower
surface. The contract suite therefore exercises the OSS-default
provider (``DisabledAIProvider``) instead, which is the actual
Protocol-conforming code path in OSS-only installs.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any

import pytest

from spectra_sherpa.app.contracts.ai_provider import AIServiceProvider
from spectra_sherpa.app.contracts.ai_provider_errors import (
    SherpaAdvisorUnavailable,
    SherpaAuthorizationError,
    SubscriptionRequiredError,
)
from spectra_sherpa.app.contracts.ai_provider_registry import DisabledAIProvider, FeatureDisabledError


class MockPremiumProvider:
    """Inline stand-in for a server-side AIServiceProvider implementation.

    Every method returns a well-formed, non-error response so the contract
    suite can verify the streaming-vs-unary shapes without depending on
    any real backend.
    """

    is_available: bool = True

    def has_feature(self, feature: str) -> bool:
        return True

    async def sync_workflow(self, sync_msg: Any, *, tier: Any) -> list[Any]:
        return []

    async def send_decision(self, decision: Any) -> bool:
        return True

    async def identify_peaks(self, *, wavenumbers: list[float], absorbance: list[float]) -> dict[str, Any]:
        return {"peaks": []}

    async def generate_code(self, *, task_description: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"code": ""}

    async def write_report(self, *, experiment: dict[str, Any]) -> dict[str, Any]:
        return {"report": ""}

    async def generate_data_story(
        self,
        *,
        dataset_info: dict[str, Any],
        additional_context: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "chunk", "text": ""}

    async def stream_llm_chat(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        workflow_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
        local_user_id: int | None = None,
        project_id: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "start", "conversation_id": conversation_id}
        yield {"type": "done", "conversation_id": conversation_id}

    async def chat_followup(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
        local_user_id: int | None = None,
        project_id: int | None = None,
    ) -> AsyncIterator[str]:
        yield ""

    async def chat_with_tools(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
        local_user_id: int | None = None,
        project_id: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "done"}


PROVIDERS = [
    pytest.param(DisabledAIProvider(), id="DisabledAIProvider"),
    pytest.param(MockPremiumProvider(), id="MockPremiumProvider"),
]

UNARY_METHODS = (
    "sync_workflow",
    "send_decision",
    "identify_peaks",
    "generate_code",
    "write_report",
)

STREAMING_METHODS = (
    "generate_data_story",
    "stream_llm_chat",
    "chat_followup",
    "chat_with_tools",
)

ALL_METHODS = UNARY_METHODS + STREAMING_METHODS


@pytest.mark.parametrize("provider", PROVIDERS)
class TestAIServiceProviderContract:
    """Each provider must satisfy the full Protocol surface."""

    def test_runtime_checkable(self, provider: object) -> None:
        assert isinstance(provider, AIServiceProvider), f"{type(provider).__name__} does not satisfy AIServiceProvider"

    def test_is_available_is_bool(self, provider: object) -> None:
        assert isinstance(provider.is_available, bool)  # type: ignore[attr-defined]

    def test_has_feature_returns_bool(self, provider: object) -> None:
        assert isinstance(provider.has_feature("anything"), bool)  # type: ignore[attr-defined]

    @pytest.mark.parametrize("method_name", ALL_METHODS)
    def test_method_exists_and_is_async(self, provider: object, method_name: str) -> None:
        method = getattr(provider, method_name, None)
        assert method is not None, f"missing method: {method_name}"
        assert callable(method), f"{method_name} is not callable"
        assert inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(
            method
        ), f"{method_name} must be async (coroutine or async generator)"

    @pytest.mark.parametrize("method_name", STREAMING_METHODS)
    def test_streaming_methods_are_async_generators(self, provider: object, method_name: str) -> None:
        method = getattr(provider, method_name)
        assert inspect.isasyncgenfunction(method), (
            f"{method_name} must be an async generator (declared in the Protocol " "as ``AsyncIterator[...]``)"
        )


def test_disabled_provider_is_safe_default() -> None:
    """The OSS default must report unavailable and refuse features."""
    provider = DisabledAIProvider()
    assert provider.is_available is False
    assert provider.has_feature("anything") is False


@pytest.mark.parametrize(
    "subclass",
    [FeatureDisabledError, SherpaAuthorizationError, SubscriptionRequiredError],
)
def test_advisor_unavailable_errors_share_a_common_base(subclass: type[Exception]) -> None:
    """All three advisor-unavailable errors inherit from ``SherpaAdvisorUnavailable``.

    Callers that don't need to distinguish between disabled / unauthorized /
    subscription-gated failures can then write a single
    ``except SherpaAdvisorUnavailable`` block.
    """
    assert issubclass(subclass, SherpaAdvisorUnavailable)


def test_advisor_unavailable_carries_detail_string() -> None:
    """The base class normalizes the ``detail`` attribute used by callers."""
    err = SherpaAdvisorUnavailable("custom message")
    assert err.detail == "custom message"
    assert str(err) == "custom message"


def test_subclass_default_details_are_distinct() -> None:
    """Each subclass's default detail string is recognizably different.

    Callers that want a uniform user-facing message catch the base; callers
    that want specific text dispatch on the subclass and read ``detail``.
    """
    assert FeatureDisabledError().detail == "Sherpa advisor not available"
    assert SherpaAuthorizationError().detail == "Sherpa authorization failed"
    assert SubscriptionRequiredError().detail == "Subscription required"


def test_protocol_method_set_is_documented() -> None:
    """Drift-detector: the Protocol's public method set is the contract.

    If a method is added or removed from ``AIServiceProvider``, this test
    is the canonical place to update the expected set. That forces a
    deliberate decision (and a docs update) rather than silent drift.
    """
    expected = {
        "is_available",
        "has_feature",
        "sync_workflow",
        "send_decision",
        "identify_peaks",
        "generate_code",
        "write_report",
        "generate_data_story",
        "stream_llm_chat",
        "chat_followup",
        "chat_with_tools",
    }
    actual = {name for name in dir(AIServiceProvider) if not name.startswith("_")}
    assert actual == expected, (
        f"AIServiceProvider surface drifted. "
        f"Added: {sorted(actual - expected)}, removed: {sorted(expected - actual)}. "
        f"Update docs/dev/boundaries.md and this test together."
    )


# Properties live on the Protocol but aren't methods — exclude from
# signature-walk. ``has_feature`` is a sync method; everything else
# is async.
_NON_METHOD_PROTOCOL_ATTRS = {"is_available"}


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "method_name",
    sorted(
        name for name in dir(AIServiceProvider) if not name.startswith("_") and name not in _NON_METHOD_PROTOCOL_ATTRS
    ),
)
def test_method_signatures_compatible_with_protocol(provider: object, method_name: str) -> None:
    """Each provider's method must match the Protocol's parameter list.

    ``runtime_checkable`` only verifies attribute presence; it does
    *not* check signatures. This walks every method on the Protocol and
    asserts the implementation has the same named keyword parameters
    in the same kind (positional-or-keyword vs keyword-only). Closes
    the gap between "isinstance() succeeds" and "the call site won't
    blow up at runtime with a TypeError on an unknown kwarg".
    """
    protocol_method = getattr(AIServiceProvider, method_name)
    impl_method = getattr(provider, method_name)

    protocol_sig = inspect.signature(protocol_method)
    impl_sig = inspect.signature(impl_method)

    # The Protocol declares ``self``; bound methods on instances do not.
    # Drop ``self`` from the Protocol side for a like-for-like compare.
    protocol_params = {name: p for name, p in protocol_sig.parameters.items() if name != "self"}
    impl_params = dict(impl_sig.parameters)

    # Implementations may use **kwargs or *args to accept the Protocol's
    # named parameters generically (the OSS ``DisabledAIProvider`` does
    # this). If the impl declares a VAR_KEYWORD or VAR_POSITIONAL slot,
    # the named-parameter check is satisfied.
    has_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in impl_params.values())
    has_var_positional = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in impl_params.values())

    if has_var_keyword and has_var_positional:
        return  # impl accepts anything — Protocol-compatible by construction.

    drift: list[str] = []
    for name, p_param in protocol_params.items():
        if name in impl_params:
            i_param = impl_params[name]
            if p_param.kind != i_param.kind:
                drift.append(f"{method_name}({name}): kind {i_param.kind.name} " f"!= protocol {p_param.kind.name}")
            continue
        if p_param.kind is inspect.Parameter.KEYWORD_ONLY and not has_var_keyword:
            drift.append(
                f"{method_name}({name}): keyword-only Protocol parameter not "
                f"accepted by impl (no matching parameter and no **kwargs)"
            )
        if p_param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and not (has_var_keyword or has_var_positional):
            drift.append(f"{method_name}({name}): Protocol parameter not accepted by impl")

    assert not drift, "\n".join(drift)
