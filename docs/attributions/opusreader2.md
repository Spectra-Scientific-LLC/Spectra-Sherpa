# opusreader2

SpectraSherpa bundles five unmodified real Bruker OPUS instrument files from
the **opusreader2** package-authored test corpus under **MIT**, used only as
read-only parser conformance fixtures. The source is pinned to commit
`96f970beb0ef92ccb3ee62fc3d8b7f27e1587c41`.

- upstream project: <https://github.com/spectral-cockpit/opusreader2>
- license: `MIT + file LICENSE` (standard R-package convention); complete
  notice at `THIRD_PARTY_LICENSES/opusreader2-MIT.txt`
- authors: Philipp Baumann, Thomas Knecht, Pierre Roudier

| Bundled fixture | Structural variant it exercises |
|---|---|
| `617262_1TP_C-1_A5.0` | Singular data/status pairing whose recorded MNY/MXY does not reproduce from the on-disk bytes -- an unambiguous pairing must not be refused for that reason |
| `629266_1TP_A-1_C1.0` | Two absorbance results sharing one OPUS type, disambiguated by decoded value against each candidate's MNY/MXY |
| `BF_lo_01_soil_cal.1` | Same duplicate-absorbance disambiguation; a Bruker ALPHA diffuse-reflectance soil measurement associated with Baumann et al. (2021), <https://doi.org/10.5194/soil-7-717-2021> |
| `MMP_2107_Test1.001` | Library-match and multi-channel result blocks outside this reader's documented scope, refused individually |
| `test_spectra.0` | A reflectance result outside this reader's documented scope, refused individually |

Every file's decoded assets are cross-checked against an independently
installed copy of `brukeropus` 1.4.3 -- the project this reader's own binary
layout is adapted from (see `brukeropus.md`) -- and agree exactly on shape,
values, and, for the duplicate-absorbance files, on which occurrence is
canonical. Exact digests, per-asset shapes, and value checksums are recorded
in `docs/evidence/native-opus-reader-conformance.json`.

`BF_lo_01_soil_cal.1` is authored by an opusreader2 copyright holder and tied
to a published, peer-reviewed dataset. Three other upstream files were
supplied by third-party GitHub issue reporters whose issue threads do not
contain an explicit redistribution grant. SpectraSherpa deliberately does not
bundle or claim those files under the package MIT licence.

These files also motivated a scientific-identity fix: the reader previously
required a data block's single status candidate to reproduce that status
block's recorded value envelope, which `617262_1TP_C-1_A5.0` -- a real,
published acquisition -- does not do, and refused every same-type duplicate
pairing outright rather than attempting to disambiguate it by value, which
`629266_1TP_A-1_C1.0` and `BF_lo_01_soil_cal.1` both exercise. Both are fixed;
see `docs/evidence/native-opus-reader-conformance.json` and the OPUS
implementation record in
`docs/plan/canonical-dag-managed-optimization-plan.md`.
