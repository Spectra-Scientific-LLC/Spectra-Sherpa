# Native Thermo OMNIC reader

SpectraSherpa's read-only Thermo Nicolet OMNIC parser implements a bounded,
fail-closed grammar for independently qualified SPA single spectra, SPG
compatible spectrum groups, and legacy SRS time series. Thermo's formats are
proprietary; the public block-table and series-marker interpretation was
cross-checked against:

- `spectrochempy-omnic` 0.2.1, commit
  `2eb6b7d3964451d35eeb0c185cb99a0cc147c7cd`, Copyright © 2025 LCS —
  Laboratoire Catalyse et Spectrochimie, Caen, France, CeCILL-B.

SpectraSherpa does not import or execute that project and does not bundle its
source or test data. The native parser is an independent implementation over
SpectraSherpa's immutable snapshot, resource-limit, typed-asset, provenance,
and fail-closed format registry authorities. Exact-hash files from an external
SpectroChemPy data installation may be used by the test suite as local
conformance references; those proprietary instrument files are not copied
into SpectraSherpa's source distribution or wheel.

The parser preserves the feature-axis order declared in the file. For SPG,
sample rows are stably ordered by their explicit acquisition timestamp and
the original directory index is retained as sample metadata. SRS data-point
axes remain data-point axes; SpectraSherpa does not invent an optical-path
conversion or silently reverse a spectrum.

One redistributable OMNIC file is bundled in-tree and always exercised:
`tests/fixtures/omnic/openspecy-polyethylene-reflectance.spa`, published by the
Open Specy project under CC-BY-4.0 (see `open-specy.md`). It covers the SPA
single-spectrum variant with reflectance in percent, and SpectroChemPy 0.8.1
independently decodes identical shape, axis, and values from it.

SPG group and SRS series conformance still runs on Thermo files SpectraSherpa is
not licensed to redistribute, so those cases execute only where that corpus is
installed. Closing that gap requires instrument files SpectraSherpa owns; it is
tracked rather than papered over, because a group or series reader qualified
only on synthesized bytes is qualified against its own assumptions.

The qualified variants and exact expected-science checks are recorded in
`docs/evidence/native-omnic-reader-conformance.json`.
