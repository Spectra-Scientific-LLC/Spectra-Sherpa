# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| Latest  | Yes                |
| Older   | No                 |

## Reporting a Vulnerability

If you discover a security vulnerability in SpectraSherpa, please report it responsibly.

**Email**: info@spectrascientific.ai

Please include:

- A description of the vulnerability
- Steps to reproduce the issue
- The potential impact
- Any suggested fixes (optional)

## Scope

This policy covers the open-source **SpectraSherpa** core (this repository). The commercial server package (a separate repository, not part of this tree) is not in scope for public reports.

## Dependency Scanner Notes

The OSS app installs Starlette's `TrustedHostMiddleware` at startup with an
allowlist derived from `TRUSTED_HOSTS`, `DOMAIN`, `API_BASE_URL`, and configured
CORS origins. Dependency scans should stay on the patched FastAPI/Starlette
line; do not reintroduce a Starlette pre-1.0 pin without a fresh advisory review.

## Response Timeline

- **Acknowledgement**: Within 3 business days
- **Initial assessment**: Within 7 business days
- **Fix or mitigation**: Depends on severity, but we aim for 30 days for critical issues

## Disclosure

We follow coordinated disclosure. Please do not publicly disclose the vulnerability until we have had a chance to address it.
