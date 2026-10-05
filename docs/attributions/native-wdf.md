# Native Renishaw WiRE WDF reader

SpectraSherpa's bounded native WDF reader adapts the read-only chunk and
metadata grammar published by **renishawWiRE 0.1.16**:

- upstream project: <https://github.com/alchem0x2A/py-wdf-reader>
- exact tag: `0.1.16`
- exact commit: `b84cc3c23ee977ffd84d58a49e5a9d94260ed07c`
- copyright: Copyright (c) 2022 T.Tian
- license: MIT
- complete notice: `THIRD_PARTY_LICENSES/renishawWiRE-MIT.txt`

That implementation cites Alex Henderson's *Renishaw File Reader*
(DOI: [10.5281/zenodo.495477](https://doi.org/10.5281/zenodo.495477)) and
Gwyddion's Renishaw module as its format authorities. SpectraSherpa retains
those citations and implements its own immutable-source, checked-range,
allocation, typed-axis, sample-identity, and fail-closed boundaries.

The section, origin, Y-list, WMAP, and derived-map structures are additionally
cross-checked against **renishaw-wdf 1.4.0**, published by Renishaw
Spectroscopy under Apache-2.0:

- package: <https://pypi.org/project/renishaw-wdf/1.4.0/>
- publisher: Renishaw Spectroscopy
- version: `1.4.0`
- license: Apache-2.0

That package is used only as an independent development comparator; no code is
copied from it and it is not installed at runtime. Its FILETIME projection is
not used as a numerical oracle because it converts 100 ns integers through a
binary float. SpectraSherpa instead retains the exact source tick values and an
exact seven-fractional-digit UTC timestamp.

The qualified release surface is narrower than every code or unit value found
in the upstream implementation. It covers completed count-valued Raman-shift
single spectra, depth series, XY lines, StreamLine maps, and rectangular maps.
Every spectrum remains one chemometric sample; exact per-spectrum X/Y/Z/time
and checksum origins are retained in the sample table, while WMAP topology is
explicit metadata. Absolute FILETIME and checksum integers use decimal strings
so browser JSON cannot round values above 2^53. The qualified corpus carries
zero acquisition-quality flags; nonzero flags fail closed until masking and
adverse-quality semantics are explicitly qualified. The version-1 header,
zero-valued file flags/track/status fields, exact measurement window, and a
neutral physical-instrument field are also bound by conformance. Unknown units,
measurement types, scan types, incomplete acquisitions, and contradictory
chunk/cardinality declarations are rejected rather than guessed.

Five exact files bind the full scientific arrays, Raman axes, ordered sample
labels, complete retained sample tables, map topology, and source digests in
`docs/evidence/native-wdf-reader-conformance.json`.

Four of them -- `sp.wdf`, `depth.wdf`, `line.wdf`, and `streamline.wdf`, plus
the `undefined.wdf` negative case -- are redistributed in-tree under
renishawWiRE's MIT license, whose release archive publishes them, so every
checkout verifies the reader against real Renishaw bytes without installing
anything. `mapping.wdf` is 44 MiB and is referenced but not bundled; its
scientific coverage is a superset of the bundled `line.wdf`, and it is
exercised only where a maintainer has the release archive unpacked locally.
Nothing is downloaded by the application or by tests. The upstream package is
a read-only development comparator and is not a SpectraSherpa runtime
dependency.

WiRE `MAP ` sections contain derived analysis layers, separate from the raw
spectral matrix and physical acquisition origins. This release does not infer
or reproduce the undisclosed analysis that generated those layers. Their UIDs
and bounded section sizes remain visible, the whole-source digest binds their
bytes, and ingestion emits an explicit warning. Raw spectra and qualified
physical coordinates remain available.
