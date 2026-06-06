# HITRAN and HAPI

HITRAN/HAPI support is optional and serves a different role than NIST. NIST supports reference and quantitative infrared workflows around public compiled data. HITRAN/HAPI supports line-by-line gas-phase spectral synthesis when the optional package, API key, and network access are configured.

```bash
pip install "spectra-sherpa[hitran]"
```

HITRAN live synthesis requires a HITRAN API key and network egress permission.

## Supported Versions

The current SpectraSherpa package supports [hitran-api](https://pypi.org/project/hitran-api/) `>=1.3.0.0,<2` and [hitran-api2](https://pypi.org/project/hitran-api2/) `>=0.2.2,<1`. The current lockfile pins `hitran-api 1.3.0.0` and `hitran-api2 0.2.2`. See the official [HITRAN HAPI page](https://hitran.org/hapi/) and [HAPI manual](https://hitran.org/static/hapi/hapi_manual.pdf) for upstream API details.

## Citation

Cite HITRAN and HAPI when HITRAN-generated spectra are used in scientific or customer-facing work. Use the current citation guidance from HITRAN for the database release used by the analysis. HITRAN publishes citation guidance at [hitran.org/citepolicy](https://hitran.org/citepolicy/).

## Practical Note

Start with narrow spectral ranges when testing HITRAN setup. Wide high-resolution line-by-line synthesis can be slow.
