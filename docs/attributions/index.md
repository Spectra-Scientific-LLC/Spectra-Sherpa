# Scientific and Software Attributions

SpectraSherpa builds on open-source scientific software and public scientific data resources. Attribution is part of scientific traceability: if a reader, algorithm, reference spectrum, or synthetic spectrum materially supports an analysis, cite the upstream resource as well as SpectraSherpa when appropriate.

## Software

- SpectraSherpa OSS: AGPLv3 or later
- SpectroChemPy: `spectra-sherpa[scp]` support for Thermo OMNIC/OMNICxi `.spa`, `.spg`, `.srs`, Bruker `.opus`, Galactic `.spc`, Renishaw `.wdf`, vendor `.txt`/`.dat`, selected datasets, and coordinate-aware algorithms
- NumPy, SciPy, pandas, scikit-learn, FastAPI, Vue, Plotly, and related infrastructure packages

## Scientific Data

- NIST Chemistry WebBook and NIST Quantitative Infrared data for reference and synthetic infrared workflows
- HITRAN and HAPI for line-by-line gas-phase synthesis when the optional extra and API key are configured
- Eigenvector Research example datasets for recommended NIR/OES chemometrics onboarding and validation examples when users download or cache the upstream files locally

## Practical Rule

When generated, downloaded, or reference spectra are used in a report, validation record, publication, or customer-facing analysis, cite the upstream scientific data source. This includes HITRAN-derived synthetic benchmark files and user-downloaded Eigenvector Research datasets. When optional software such as SpectroChemPy materially affects import, preprocessing, or modeling, cite that project too.
