# Native Galactic SPC reader

SpectraSherpa's read-only Galactic/Thermo GRAMS SPC parser implements the
published *Galactic Universal Data Format Specification*, revision 4.50
(1997). Its implementation structure was cross-checked against two
independent permissively licensed parser projects:

- `spc-io` 0.2.1, commit
  `855cf9bf08e847dc62759608b7b387e410af79ed`, Copyright © 2023 CHARISMA
  H2020 project and IDEAconsult Ltd., MIT;
- `spc-parser` 2.1.0, commit
  `f770e788bd553ac8ebe6c831b4619280d083016e`, Copyright © 2021 cheminfo,
  MIT.

The complete notices are bundled at
`THIRD_PARTY_LICENSES/spc-io-MIT.txt` and
`THIRD_PARTY_LICENSES/spc-parser-MIT.txt`. The parser does not import or
execute either upstream project at runtime. SpectraSherpa owns the bounded
source, allocation, typed dataset, multi-asset selection, provenance, and
fail-closed qualification boundaries.

The independent fixture corpus and exact expected-science checks are recorded
in `docs/evidence/native-spc-reader-conformance.json`.
