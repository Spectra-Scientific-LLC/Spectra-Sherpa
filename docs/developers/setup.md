# Developer Setup

Use this path for OSS development.

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
poetry install --with dev
poetry run spectra-sherpa
```

For full spectroscopy development:

```bash
poetry install --with dev --extras "scp hitran"
```

## Development Notes

- Keep SpectroChemPy optional.
- Keep cloud-only behavior out of the OSS package.
- Prefer node metadata and typed ports over shape-only assumptions.
- Run tests for any behavior change.
