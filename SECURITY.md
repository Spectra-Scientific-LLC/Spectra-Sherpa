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

GitHub may show a Starlette Host-header advisory while FastAPI still constrains
Starlette to the pre-1.0 line (`starlette<0.50.0` in FastAPI 0.120/0.121). The
OSS app mitigates this class at startup by installing Starlette's
`TrustedHostMiddleware` with an allowlist derived from `TRUSTED_HOSTS`,
`DOMAIN`, `API_BASE_URL`, and configured CORS origins. Maintainers should keep
the Dependabot alert open or dismiss it with that mitigation note, then remove
this exception once FastAPI supports the patched Starlette 1.x line.

## Response Timeline

- **Acknowledgement**: Within 3 business days
- **Initial assessment**: Within 7 business days
- **Fix or mitigation**: Depends on severity, but we aim for 30 days for critical issues

## Disclosure

We follow coordinated disclosure. Please do not publicly disclose the vulnerability until we have had a chance to address it.
