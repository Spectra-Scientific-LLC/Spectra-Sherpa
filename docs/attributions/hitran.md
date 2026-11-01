# HITRAN and HAPI

HITRAN/HAPI support is an optional extra for pip users and is included in desktop installers. It serves a different role than NIST. NIST supports reference and quantitative infrared workflows around public compiled data. HITRAN/HAPI supports line-by-line gas-phase spectral synthesis when the clients, API key, and network access are configured.

> **Installation target.** These guides describe v0.6.4. Commands below install
> the latest *published* package. For source qualification, install the exact
> reviewed checkout with the required extras using
> [Local onboarding](../onboarding/local-30-minutes.md).

```bash
pip install "spectra-sherpa[hitran]"
```

Desktop users do not need this pip command: the installer includes both clients, their licenses and matching source archives. See [desktop packaging](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/blob/main/desktop/README.md#included-hitran-clients).

HITRAN live synthesis requires a HITRAN API key and network egress permission.

SpectraSherpa also ships two synthetic FTIR benchmark files, `Synthetic_atmospheric-6.npz` and `Library_atmospheric-9.npz`, whose spectral signatures are derived from HITRAN data. Treat these as HITRAN-derived scientific artifacts: cite HITRAN/HAPI and follow HITRAN terms when using them in reports, validation records, publications, or customer-facing work.

## Supported Versions

The current SpectraSherpa package supports [hitran-api](https://pypi.org/project/hitran-api/) `>=1.3.0.0,<2` and [hitran-api2](https://pypi.org/project/hitran-api2/) `>=0.2.2,<1`. The current lockfile pins `hitran-api 1.3.0.0` and `hitran-api2 0.2.2`. See the official [HITRAN HAPI page](https://hitran.org/hapi/) and [HAPI manual](https://hitran.org/static/hapi/hapi_manual.pdf) for upstream API details.

## Citation

Cite HITRAN and HAPI when HITRAN-generated spectra are used in scientific or customer-facing work. Use the current citation guidance from HITRAN for the database release used by the analysis. HITRAN publishes citation guidance at [hitran.org/citepolicy](https://hitran.org/citepolicy/).

## Practical Note

Start with narrow spectral ranges when testing HITRAN setup. Wide high-resolution line-by-line synthesis can be slow.
