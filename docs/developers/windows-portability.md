# Windows portability for scientific files and evidence

This is the reusable developer contract for code that runs on Windows, macOS
and Linux. It was established while correcting the Windows failures found by
the v0.6 cohesion qualification. A passing Unix suite does not establish Windows
behavior, and a successful installer build does not establish backend correctness.

## Preserve scientific authority across operating systems

Portability corrections must retain exact input identity, byte limits, link
refusal, scientific comparisons, provenance and ownership checks. Do not make a
failing platform green by regenerating expected science, accepting either hash,
broadly skipping tests, or disabling an authority check.

| Failure class | Why it happens | Required practice | Existing regression surface |
| --- | --- | --- | --- |
| Checkout changes a source, fixture or lockfile hash | Git can translate LF to CRLF before the application reads a file. | Respect the checked-in `.gitattributes` exact-byte policy; retain the explicit LF rule for `poetry.lock`. Compare actual Git blob/checkout bytes before changing any expected digest. | `test_canonical_node_qualification.py`; metadata-profile contract checks |
| JSON or source text decodes differently | An implicit text encoding can use the Windows locale instead of UTF-8. Unicode corruption can change registry descriptions and contract digests without a syntax error. | Use `encoding="utf-8"` for known UTF-8 text, including production registry loaders and source scanners. | `test_node_catalog_contract.py`; presentation census and source-contract tests |
| A generated fixture does not match its precomputed hash | Text output can translate newlines; a binary descriptor can accidentally use Windows text mode. | For a byte-bound fixture, use `write_bytes(payload)`. For bounded scientific snapshots, use the shared binary reader below. | `test_canonical_output_export.py`; notebook export tests; `test_portable_file_io.py` |
| Snapshot rename fails, or a replacement/link is read | POSIX flags and Windows handle sharing/reparse behavior differ. A path check followed by another open can race. | Validate the opened handle, refuse leaf reparse points, and preserve the already-opened snapshot through rename. Do not reopen the path to obtain the bytes. | `test_portable_file_io.py`; Avatar corpus snapshot/publication tests |
| Permission tests fail or create false security assurance | `fchmod` and POSIX mode bits do not represent Windows ACL authority. | Keep POSIX owner-only checks on POSIX. Windows storage uses the restricted parent/profile ACL; require that prerequisite explicitly. Never claim `chmod(0600)` proves a Windows ACL is private. | Collection-definition and Avatar private-workspace tests |
| A serialized path changes a manifest | Windows filesystem paths use backslashes. | Use `Path.as_posix()` for repository-relative identifiers in cross-platform manifests. Keep native paths for filesystem operations. | Canonical qualification; native vendor conformance guards |
| Numeric fixture shape/type metadata differs | Platform or dependency defaults can choose different integer widths. | Declare the intended scientific fixture dtype, such as `np.int64`, when the contract requires that width. Do not relax the serialized type assertion. | `test_native_matlab_dso.py` |
| An offline test breaks the event loop | A Windows standard-library socketpair may create a loopback connection for local wakeup. | Permit only the standard-library constructor scope in the shared offline guard. Continue to refuse application `connect` and `connect_ex`, including ordinary loopback connections. | `test_portable_file_io.py`; portable and campaign folder-watch tests |
| Exact-source inventories become stale after a harmless import/edit | Closed inventories bind callsite coordinates and source hashes as well as semantic classes. | Regenerate using the owning tool and review the diff. Preserve classifications/counts unless the code intentionally changes them. Update moved callsites to their actual AST locations; do not remove the closed inventory. | `test_phase7_classification_authority.py`; `test_scp_ingestion_reachability.py` |

Test filenames in this table are under `tests/`; implementation and tool paths
below are relative to the OSS package root.

## Use the shared snapshot reader

`src/spectra_sherpa/core/file_io.py::open_regular_readonly` returns an owned
binary descriptor for a regular file. The caller must close it:

```python
from pathlib import Path
import os

from spectra_sherpa.core.file_io import open_regular_readonly

# Establish allowed-parent authority and a positive byte limit before this step.
def read_bounded_snapshot(path: Path, limit: int) -> bytes:
    if limit <= 0:
        raise ValueError("A positive byte limit is required")
    descriptor = open_regular_readonly(path)
    with os.fdopen(descriptor, "rb") as source:
        payload = source.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("Snapshot exceeds the byte limit")
    return payload
```

The helper checks the opened leaf rather than trusting an earlier pathname
inspection. On Windows it opens the reparse point itself, rejects reparse
attributes, permits rename through handle sharing, and transfers ownership to
a CRT descriptor in binary mode. On POSIX it uses `O_NOFOLLOW` and checks the
opened descriptor. It does **not** establish parent-directory custody, enforce
byte ceilings, freeze concurrent writes, or establish file ACLs. Callers retain
those responsibilities and any required size/identity/digest consistency checks.

A Windows private workspace must already be restricted to its intended user by
its ACL. The inherited-ACL policy and its tests do not certify arbitrary folders.

## How to investigate a platform-only failure

1. Save the exact source commit, runner/profile, test ID and bounded failure
   excerpt. Group symptoms by cause, without counting every failed test as an
   independent product defect.
2. Reproduce the relevant OS behavior: encoding, raw bytes, open-handle lifetime,
   path serialization, permissions or socket construction. Separate a production
   bug from an invalid test assumption; both need a correction and explanation.
3. Add a behavioral regression at the shared boundary. Include refusal cases,
   not just successful opening, formatting or rendering.
4. Run the complete affected modules on Ubuntu, then Windows. Compare original
   failing **test IDs**, including parameterization, against retained JUnit.
   Aggregate pass counts cannot prove that the failing cases still execute.
5. Independently review evidence changes. Record which hashes/coordinates
   changed and whether classifications, scientific expectations or ratings changed.
6. Run the applicable full matrix before merge. A focused pass does not waive
   unrelated failures. Keep signed-installer and clean-machine acceptance
   separate from unsigned native CI.

For a quick local regression from the OSS package root:

```bash
poetry run pytest -q -o addopts='' tests/test_portable_file_io.py
```

In the monorepo, `windows-portability.yml` defines the focused Ubuntu-then-Windows
qualification. During its introduction, the registered dispatch entry was:

```bash
gh workflow run desktop-native.yml --ref YOUR_REVIEW_BRANCH -f windows_portability=true
```

That manual diagnostic choice does not replace normal native/release gates.

## Where this knowledge belongs

- **This guide:** durable implementation rules and the review checklist. Link it
  from contributor and release guidance so future contributors can find it.
- **Regression tests:** executable enforcement at the actual boundary. A note
  alone cannot prevent a recurrence.
- **Versioned incident evidence:** exact source/run IDs, failing cases, reviewed
  changes and JUnit/artifact hashes. Retain old failures as history, then link
  the verified resolution; do not rewrite historical evidence into a pass.
- **An ADR, when needed:** a new architectural choice with meaningful alternatives
  and tradeoffs. A routine portability incident does not need a second competing
  design document or a private agent-memory file as its only record.
