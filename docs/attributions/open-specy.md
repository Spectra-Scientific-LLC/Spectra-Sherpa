# Open Specy conformance fixtures

SpectraSherpa bundles two unmodified vendor instrument files published by the
**Open Specy** project under **CC-BY-4.0**, used only as read-only parser
conformance fixtures:

| Bundled fixture | Upstream file | Exercises |
|---|---|---|
| `tests/fixtures/omnic/openspecy-polyethylene-reflectance.spa` | `inst/extdata/ftir_polyethylene_reflectance_adjustment_not_working.spa` | OMNIC SPA single spectrum, reflectance in percent |
| `tests/fixtures/opus/openspecy-polystyrene.0` | `inst/extdata/ftir_ps.0` | OPUS acquisition carrying an unqualified data block beside qualified ones |

- upstream project: <https://github.com/wincowgerDEV/OpenSpecy-package>
- license: CC-BY-4.0, complete notice at `THIRD_PARTY_LICENSES/OpenSpecy-CC-BY-4.0.txt`
- citation: Cowger, W. et al., *Open Specy*, <https://openspecy.org>

Both files are renamed for fixture clarity and are otherwise byte-for-byte
unchanged; the recorded SHA-256 digests bind that. No Open Specy source code is
used, imported, or distributed.

These two files matter beyond their licence: they originate outside the
reference parser projects SpectraSherpa cross-checked its readers against.
Qualifying a reader only against its own reference implementation's corpus can
agree with that implementation and still be wrong about instruments in the
field. `openspecy-polystyrene.0` demonstrated exactly that -- it exposed a
real Bruker acquisition the OPUS reader refused outright before per-block
refusal replaced whole-file refusal.
