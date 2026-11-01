# SpectroChemPy

SpectroChemPy is an optional SpectraSherpa dependency and an important spectroscopy software foundation. Upstream provides readers, example datasets, coordinate-aware data structures, and scientific algorithms. SpectraSherpa uses it only behind a private matrix adapter for EFA, MCR-ALS, and SIMPLISMA. The extra exposes no upstream readers, example-data catalog, or public dataset conversion API.

> **Installation target.** These guides describe v0.6.4. Commands below install
> the latest *published* package. For source qualification, install the exact
> reviewed checkout with the required extras using
> [Local onboarding](../onboarding/local-30-minutes.md).

```bash
pip install "spectra-sherpa[scp]"
```

SpectraSherpa uses the extra only for those three specialized algorithms.

## Supported Version

The current SpectraSherpa release pins exactly
[SpectroChemPy 0.8.1](https://pypi.org/project/spectrochempy/0.8.1/).
Cite the version installed in the environment that produced your results.
SpectraSherpa supports Python `>=3.11,<3.13`. See the
[upstream project](https://www.spectrochempy.fr/) for its own release history;
an upstream version is not automatically a qualified Sherpa dependency.

## How to Cite SpectroChemPy

When EFA, MCR-ALS, or SIMPLISMA materially supports your analysis, cite SpectroChemPy alongside SpectraSherpa. Follow the project's own [citing guidance](https://www.spectrochempy.fr/credits/citing.html) and **cite the version you actually used**. For a local Python environment, check the installed SpectroChemPy version before finalizing a report or publication.

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

SpectroChemPy is distributed under the [CeCILL-B Free Software License Agreement](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html). CeCILL-B is a permissive, BSD-style license; users should preserve upstream notices and attribution when SpectroChemPy contributes to their work. SpectraSherpa keeps SpectroChemPy as an opt-in extra so users can make an explicit installation choice for the three retained algorithms, upstream dependency behavior, and citation/license responsibilities (see [Boundary](#boundary)).

## Links

- Project site: <https://www.spectrochempy.fr/>
- Citing guidance: <https://www.spectrochempy.fr/credits/citing.html>
- DOI (concept): <https://doi.org/10.5281/zenodo.3823841>
- Source: <https://github.com/spectrochempy/spectrochempy>
- PyPI: <https://pypi.org/project/spectrochempy/>

## Boundary

SpectroChemPy must remain opt-in for SpectraSherpa. Do not move it into core dependencies without a deliberate release decision that considers dependency footprint, admitted algorithm behavior, upstream license and citation obligations, and the AGPLv3.0 distribution boundary for SpectraSherpa OSS. Native file-reader availability remains a separate registry decision.
