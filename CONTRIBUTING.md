# Contributing to SpectraSherpa

SpectraSherpa is open source. Contributions from analytical scientists,
chemometricians, data analysts, and software engineers are all welcome.

---

## How contributions flow through the project

External contributions happen on the public
[`Spectra-Sherpa`](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa)
repository. Everything a contributor needs (source, tests, CI, issues, and
pull requests) is in this repo.

Practically, this means:

- Open your PR against the public `Spectra-Sherpa` repo.
- Public-repo CI runs the OSS checks (Python tests, frontend tests, lint, type
  checks, and boundary checks).
- A maintainer reviews the PR and may ask for changes.
- Once accepted, your change is included in a future release.

---

## Which guide is right for you?

| I am… | Go here |
|-------|---------|
| A chemometrician, analytical scientist, or data analyst who writes Python — and I want to add or improve an algorithm | **[Scientist Contributor Guide](docs/contributing/scientist-guide.md)** |
| A data scientist or AI/ML researcher who wants to add methods, test integrations, or explore the API | **[Scientist Contributor Guide](docs/contributing/scientist-guide.md)** |
| A software developer focused on infrastructure, performance, UI, or tooling | **[Developer Contributor Guide](docs/contributing/developer-guide.md)** |
| I found a bug, have a suggestion, or want to ask a question | **[Open an issue](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/issues)** |

Not sure which applies to you? Start with the
[Scientist Contributor Guide](docs/contributing/scientist-guide.md) — it is
shorter and does not require any background in web development.

For contributions that touch extension contracts, plugin interfaces, API
specs, or the boundary with the commercial server, read
[docs/dev/governance.md](docs/dev/governance.md) first. It defines what
OSS owns, how conflicts are resolved, and what counts as a stability
surface.

---

## Before any contribution: the CLA

All contributors must sign a **Contributor License Agreement (CLA)** before
their first non-trivial change is merged. This is a short legal document that
confirms you have the right to contribute your code and allows us to include
it in the project.

**How it works:** When you open your first pull request (a change proposal on
GitHub), a bot will post a comment with instructions. Sign by replying to
that comment. It takes about two minutes.

In plain terms:

- **You keep the copyright** on your own code.
- You give Spectra Scientific LLC the right to include your contribution in
  both the open-source (AGPL-3.0) release and any commercial version of the
  product.
- You confirm that you are authorized to submit the code (for example, that
  it is not owned by an employer who has not approved the contribution).
- Read the full [`CLA.md`](CLA.md) (individuals) or
  [`CLA-entity.md`](CLA-entity.md) (organizations) before signing — those
  documents are the authoritative text.

Pull requests are blocked by the bot until the CLA requirement is satisfied.

**Trivial changes** (whitespace, spelling, comments only — no code or
configuration) may be merged without a CLA at a maintainer's discretion.

---

## Code of Conduct

Communicate professionally and constructively in issues, pull requests, and
discussions.

## Security Reports

Do not open public issues for potential vulnerabilities. Report security
issues privately to the maintainers through the project security contact
channel.
