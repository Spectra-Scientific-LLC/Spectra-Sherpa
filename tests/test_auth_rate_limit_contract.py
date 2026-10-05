from spectra_sherpa.app.core.rate_limit_middleware import RateLimitMiddleware


def test_managed_signup_endpoints_have_explicit_per_ip_limits() -> None:
    assert RateLimitMiddleware.AUTH_RATE_LIMITS == {
        "/api/v1/auth/login": (10, 900),
        "/api/v1/auth/register": (5, 3600),
        "/api/v1/auth/verify-signup-email": (20, 3600),
        "/api/v1/auth/resend-signup-code": (5, 3600),
    }
