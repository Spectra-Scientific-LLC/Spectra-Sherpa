from __future__ import annotations


class SubscriptionRequiredError(Exception):
    """Raised when a feature requires a subscription that the user does not have."""

    def __init__(self, detail: str = "Subscription required"):
        self.detail = detail
        super().__init__(detail)


class SherpaAuthorizationError(Exception):
    """Raised when the deployment key is invalid, revoked, or unauthorized."""

    def __init__(self, detail: str = "Sherpa authorization failed"):
        self.detail = detail
        super().__init__(detail)
