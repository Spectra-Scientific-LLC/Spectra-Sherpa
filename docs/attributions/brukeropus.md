# brukeropus

SpectraSherpa's bounded native Bruker OPUS reader adapts the read-only binary
file layout and data/status pairing from **brukeropus 1.4.3**, tag `v1.4.3`,
commit `af5a508cef7de8089acd27a215d644ab451257dd`.

- Upstream: <https://github.com/joshduran/brukeropus>
- Copyright: © 2024 Josh Duran
- License: MIT
- Source distribution SHA-256:
  `0e67c27d6dcc8fbe06e8c56eec616aec9d55457ae06666520e7bcdc5c91b59cb`

Only the read-only file-parser concepts needed for one-dimensional OPUS data
are adapted. SpectraSherpa does not include the upstream DDE control surface.
Its parser independently adds bounded reads, checked offsets and allocation
limits, typed multi-asset results, exact source digests, ambiguity rejection,
and explicit refusal of series/3-D blocks.

## Conformance-corpus boundary

Nine redistribution-qualified OPUS acquisitions are bundled and therefore run
in every checkout: one from Open Specy (`open-specy.md`) and eight from
opusreader2 (`opusreader2.md`), covering singular, duplicate-pairing, and
several out-of-scope block-type layouts. Three additional exact-hash OPUS
acquisitions cover the two-asset reference and six-asset sample layouts, but
their upstream corpus does not state redistribution terms; SpectraSherpa
records them as external qualification inputs and does not ship their bytes.
Tests that need those three files may skip in ordinary CI, but the files
remain mandatory under `MONO-2026-08-13-051` for C8/M4.20 release
qualification. This is not evidence for unlisted OPUS layouts.
