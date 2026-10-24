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

Dependency checks include the complete frontend and Electron shell lockfiles,
including development and optional packages. Run this without installing npm
packages, downloading Electron binaries or building desktop packages:

```sh
python scripts/audit_dependencies.py --repo . --skip-python
```

Both lockfiles are required; scanner failures and unreviewed moderate-or-higher
advisories fail the check. The optional `--frontend-scope runtime` mode is a
diagnostic only and never narrows the desktop audit. CI and publication use
full scope. Existing time-limited, explicitly reviewed npm waivers are enforced
by `scripts/audit-ignore.toml`; the current list is empty. Dependency patches
do not authorize releasing or packaging the desktop application.

## Response Timeline

- **Acknowledgement**: Within 3 business days
- **Initial assessment**: Within 7 business days
- **Fix or mitigation**: Depends on severity, but we aim for 30 days for critical issues

## Disclosure

We follow coordinated disclosure. Please do not publicly disclose the vulnerability until we have had a chance to address it.
