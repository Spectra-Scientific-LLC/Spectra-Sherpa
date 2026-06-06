# SpectroChemPy

SpectroChemPy is an optional SpectraSherpa dependency and an important spectroscopy software foundation. It provides readers, example datasets, coordinate-aware data structures, and scientific algorithms for spectroscopic analysis.

```bash
pip install "spectra-sherpa[scp]"
```

SpectraSherpa uses the extra for selected spectroscopy readers, example datasets, and coordinate-aware spectral algorithms.

## Supported Version

The current SpectraSherpa package declares optional support for [SpectroChemPy](https://www.spectrochempy.fr/) `>=0.8.1,<0.9.0`. SpectraSherpa itself currently supports Python `>=3.11,<3.13`. The lockfile pins [SpectroChemPy 0.8.1](https://www.spectrochempy.fr/0.8.1/), also available on [PyPI](https://pypi.org/project/spectrochempy/).

## How to Cite SpectroChemPy

When SpectroChemPy materially supports an import, preprocessing step, dataset, or algorithm in your analysis, cite it alongside SpectraSherpa. Follow the project's own [citing guidance](https://www.spectrochempy.fr/credits/citing.html) and **cite the version you actually used**. For a local Python environment, check the installed SpectroChemPy version before finalizing a report or publication.

Recommended citation pattern, adapted from the upstream guidance:

```text
Travert, A., & Fernandez, C. (YEAR). SpectroChemPy, a framework for processing,
analyzing and modeling spectroscopic data for chemistry with Python (version X.Y.Z).
Zenodo. DOI: 10.5281/zenodo.3823841. URL: https://www.spectrochempy.fr
```

BibTeX:

```bibtex
@software{SpectroChemPy_YEAR,
  author    = {Travert, Arnaud and Fernandez, Christian},
  license   = {CECILL-B},
  title     = {{SpectroChemPy, a framework for processing, analyzing and
               modeling spectroscopic data for chemistry with Python}},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.3823841},
  url       = {https://www.spectrochempy.fr},
  version   = {X.Y.Z},
  year      = {YEAR},
}
```

SpectroChemPy is developed by Arnaud Travert and Christian Fernandez (ENSICAEN, Université de Caen Normandie, CNRS). The project's [credits page](https://www.spectrochempy.fr/credits/) lists its full author and contributor record; treat the upstream [citing page](https://www.spectrochempy.fr/credits/citing.html) as the authoritative source if its wording changes.

## License

SpectroChemPy is distributed under the [CeCILL-B Free Software License Agreement](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html). CeCILL-B is a permissive, BSD-style license; users should preserve upstream notices and attribution when SpectroChemPy contributes to their work. SpectraSherpa keeps SpectroChemPy as an opt-in extra so users can make an explicit installation choice for vendor readers, optional algorithms, upstream dependency behavior, and citation/license responsibilities (see [Boundary](#boundary)).

## Links

- Project site: <https://www.spectrochempy.fr/>
- Citing guidance: <https://www.spectrochempy.fr/credits/citing.html>
- DOI (concept): <https://doi.org/10.5281/zenodo.3823841>
- Source: <https://github.com/spectrochempy/spectrochempy>
- PyPI: <https://pypi.org/project/spectrochempy/>

## Boundary

SpectroChemPy must remain opt-in for SpectraSherpa. Do not move it into core dependencies without a deliberate release decision that considers dependency footprint, supported reader behavior, upstream license and citation obligations, and the AGPLv3 distribution boundary for SpectraSherpa OSS.
