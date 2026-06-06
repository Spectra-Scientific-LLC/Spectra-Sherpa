# Reference Libraries and Synthesis

SpectraSherpa includes reference and synthesis workflows for infrared-oriented analysis.

## NIST Library

The NIST Library workflow is for finding and comparing reference spectra. It is useful when you want to inspect possible identities, compare a sample to known compounds, or build a small library comparison workflow.

## NIST Quantitative IR Synthesis

NIST Quantitative IR synthesis uses quantitative infrared reference records to generate synthetic FTIR datasets with known concentration profiles. This is useful for testing MCR-ALS, PLS, and library-comparison behavior under controlled conditions.

## HITRAN/HAPI Synthesis

HITRAN/HAPI synthesis requires:

- `spectra-sherpa[hitran]`
- a HITRAN API key
- network egress enabled

Use narrow wavenumber ranges first. Wide line-by-line simulations can be slow.

## Citation

NIST and HITRAN data are third-party scientific resources. Cite them when generated or downloaded spectra are used in reports, validation records, or publications.
