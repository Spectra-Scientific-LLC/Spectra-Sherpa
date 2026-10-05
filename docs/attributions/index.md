# Scientific and Software Attributions

SpectraSherpa builds on open-source scientific software and public scientific data resources. Attribution is part of scientific traceability: if a reader, algorithm, reference spectrum, or synthetic spectrum materially supports an analysis, cite the upstream resource as well as SpectraSherpa when appropriate.

## Software

- SpectraSherpa OSS: AGPLv3.0
- SpectroChemPy: `spectra-sherpa[scp]` support for EFA, MCR-ALS, and SIMPLISMA through a private matrix-only adapter
- NumPy, SciPy, pandas, scikit-learn, FastAPI, Vue, Plotly, and related infrastructure packages
- Native Thermo OMNIC reader: independently implemented bounded parser, cross-checked against `spectrochempy-omnic` 0.2.1
- Native Renishaw WiRE WDF reader: bounded parser adapted from `renishawWiRE` 0.1.16 under its bundled MIT notice; its conformance files are redistributed in-tree under that same MIT notice
- Open Specy: two CC-BY-4.0 vendor instrument files bundled as OMNIC and OPUS conformance fixtures (see `open-specy.md`)
- opusreader2: eight MIT-licensed real Bruker OPUS instrument files bundled as conformance fixtures (see `opusreader2.md`)

## Scientific Data

- NIST Chemistry WebBook and NIST Quantitative Infrared data for reference and synthetic infrared workflows
- HITRAN and HAPI for line-by-line gas-phase synthesis when the optional extra and API key are configured
- Eigenvector Research example datasets for recommended NIR/OES chemometrics onboarding and validation examples when users download or cache the upstream files locally

## Practical Rule

When generated, downloaded, or reference spectra are used in a report, validation record, publication, or customer-facing analysis, cite the upstream scientific data source. This includes HITRAN-derived synthetic benchmark files and user-downloaded Eigenvector Research datasets. When SpectroChemPy materially affects EFA, MCR-ALS, or SIMPLISMA, cite that project too.
