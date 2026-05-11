# Third-Party Notices

SpectraSherpa is released under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later) — see `LICENSE`.  The Python and JavaScript distributions ship a number of third-party assets and datasets that retain their own copyright and licence terms.  This file enumerates them and their attribution requirements.

If you redistribute SpectraSherpa (in source or binary form), retain this file alongside `LICENSE`.

---

## Python runtime dependencies

SpectraSherpa's Python runtime dependencies are declared in `pyproject.toml` and installed transitively from PyPI.  Each is governed by its upstream licence; none are bundled inside this distribution's source tree.

Notable optional dependency:

- **SpectroChemPy** (`scp` extra) — CeCILL-B Free Software Licence Agreement.  Opt-in only.  SpectraSherpa never bundles SpectroChemPy bytecode or source; the `scp` extra triggers an install from upstream's distribution.  Users wishing to use the SpectroChemPy-backed loaders must accept CeCILL-B independently.

---

## Bundled frontend assets (under `src/spectra_sherpa/static/`)

The compiled frontend ships as part of the Python wheel so that `pip install spectra-sherpa` produces a runnable local-first application without a separate Node.js build step.  The bundle includes:

- **Inter typeface** — Copyright (c) 2016–present The Inter Project Authors.  Licensed under the SIL Open Font License v1.1.  Source: <https://github.com/rsms/inter>.
- **PrimeIcons** — Copyright (c) PrimeTek Informatics.  Licensed under the MIT License.  Source: <https://github.com/primefaces/primeicons>.
- **KaTeX fonts** (KaTeX_AMS, KaTeX_Caligraphic, KaTeX_Fraktur, KaTeX_Main, KaTeX_Math, KaTeX_SansSerif, KaTeX_Script, KaTeX_Size, KaTeX_Typewriter) — Copyright (c) Khan Academy and other contributors.  Licensed under the MIT License.  Source: <https://github.com/KaTeX/KaTeX>.
- **Plotly.js** — Copyright (c) Plotly, Inc.  Licensed under the MIT License.  Source: <https://github.com/plotly/plotly.js>.
- **Vue.js, Vite, PrimeVue, Pinia, vue-router, and other JavaScript runtime libraries** — each licensed under the MIT License (or BSD-3-Clause in a small number of cases).  See `frontend/package-lock.json` in the source repository for the full transitive tree and per-package SPDX identifiers.

---

## Bundled example datasets (under `src/spectra_sherpa/data/`)

The wheel includes a curated set of public-domain or permissively-licensed example spectra so that exported workflows and tutorial notebooks run standalone.

### Eigenvector Research example data — `src/spectra_sherpa/data/eigenvector/`

The following datasets originate from Eigenvector Research, Inc.'s freely-published example data collection and are distributed by SpectraSherpa for educational and demonstration use:

- `corn_mat/` — Cargill NIR Corn dataset
- `cgl_nir_mat/` — CGL NIR dataset
- `diesel_csv/`, `diesel_nir_mat/` — Southwest Research Institute Diesel NIR
- `metal_etch/` — Metal etching plasma OES dataset
- `nir_shootout_mat/` — IDRC 2002 NIR Shootout dataset

Original data is courtesy of the respective contributors (Cargill, SwRI, IDRC participants).  SpectraSherpa redistributes the data unmodified for use as workflow examples.  If you publish results derived from these datasets, please cite the original source per Eigenvector Research's published guidance: <https://eigenvector.com/resources/data/>.

### Other bundled samples

- `oes/UVSpectra10.csv` — Optical emission spectra; example data prepared by Spectra Scientific LLC.
- `templates/` — Workflow templates authored by Spectra Scientific LLC.

---

## Reporting attribution issues

If you believe an asset bundled here is missing required attribution or has been redistributed in violation of its upstream licence, please open an issue at <https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/issues> with the path and the upstream licence text, and we will remediate promptly.
