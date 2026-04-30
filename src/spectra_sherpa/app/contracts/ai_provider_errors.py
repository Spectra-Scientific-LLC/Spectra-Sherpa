"""Protocol-contract exception types for the AI service provider boundary.

These exceptions are part of the AIServiceProvider contract: extension
implementations raise them, and OSS callers (e.g. ws_handlers.py) catch them.

Three concrete failure modes share the common base
:class:`SherpaAdvisorUnavailable`. Callers that distinguish between them
(e.g. WebSocket dispatch sends different user-facing messages for
authorization vs. subscription failures) catch the specific subclass;
callers that don't care about the distinction (most non-WS routes)
catch the base class.
"""

from __future__ import annotations


class SherpaAdvisorUnavailable(Exception):
    """Base class for advisor-unavailable conditions.

    Every "the advisor exists but cannot serve this request" error
    inherits from this base, so callers that need uniform handling
    can write::

        try:
            await advisor.identify_peaks(...)
        except SherpaAdvisorUnavailable as exc:
            return error_response(exc.detail)

    Callers that need to distinguish between failure modes should
    still catch the specific subclass (see ``ws_handlers.py`` for an
    example — authorization vs. subscription errors take different
    user-facing paths there).
    """

    def __init__(self, detail: str = "Sherpa advisor unavailable"):
        self.detail = detail
        super().__init__(detail)


class SubscriptionRequiredError(SherpaAdvisorUnavailable):
    """Raised when a feature requires a subscription that the user does not have."""

    def __init__(self, detail: str = "Subscription required"):
        super().__init__(detail)


class SherpaAuthorizationError(SherpaAdvisorUnavailable):
    """Raised when the deployment key is invalid, revoked, or unauthorized."""

    def __init__(self, detail: str = "Sherpa authorization failed"):
        super().__init__(detail)
