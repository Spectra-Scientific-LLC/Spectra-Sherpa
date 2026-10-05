# Third-Party Notices

SpectraSherpa is released under the GNU Affero General Public License v3.0 (AGPL-3.0) — see `LICENSE`.  The Python and JavaScript distributions ship a number of third-party assets and datasets that retain their own copyright and licence terms.  This file enumerates them and their attribution requirements.

If you redistribute SpectraSherpa (in source or binary form), retain this file alongside `LICENSE`.

---

## Python runtime dependencies

SpectraSherpa's Python runtime dependencies are declared in `pyproject.toml` and installed transitively from PyPI.  Each is governed by its upstream licence; none are bundled inside this distribution's source tree.

- **h5py** — BSD-3-Clause, required for bounded native MATLAB v7.3/HDF5
  container admission. SpectraSherpa uses h5py only as a storage decoder; the
  scientific Eigenvector DataSet Object mapping remains in-tree and shared
  with MATLAB v5.

Notable optional dependency:

- **SpectroChemPy** (`scp` extra) — CeCILL-B Free Software Licence Agreement.  Opt-in only.  SpectraSherpa never bundles SpectroChemPy bytecode or source; the `scp` extra triggers an install from upstream's distribution. It enables the explicitly adapted EFA, MCR-ALS, and SIMPLISMA operations, not vendor-file readers.

Desktop HITRAN clients (pip installs continue to use the optional `hitran` extra):

- **HAPI / hitran-api 1.3.0.0** — MIT, HITRAN team. Desktop installers include
  the upstream notice and original source wheel.
- **HAPI2 / hitran-api2 0.2.2** — GNU GPL v3. Desktop installers include the
  upstream license and matching, unmodified source distribution. GPLv3 section
  13 permits combination with AGPLv3. The licenses of each part still apply.
  Retained sources, notices, version/hash manifest and rebuild directions are
  under the bundled backend's `third_party/hitran/` directory. See
  `desktop/README.md` for platform paths. No personal API key or downloaded
  HITRAN line list is added to the installer by this integration.

Bundled read-only parser source:

- **brukeropus 1.4.3 parser concepts** — Copyright © 2024 Josh Duran, MIT. SpectraSherpa adapts the OPUS directory, parameter, data, and status-block parsing described by upstream tag `v1.4.3`, commit `af5a508cef7de8089acd27a215d644ab451257dd`. The complete retained MIT notice is bundled at `THIRD_PARTY_LICENSES/brukeropus-MIT.txt`; source-tree detail is in `docs/attributions/brukeropus.md`. The DDE control surface is not included.
- **spc-io 0.2.1 parser concepts** — Copyright © 2023 CHARISMA H2020 project and IDEAconsult Ltd., MIT. SpectraSherpa cross-checks its native Galactic SPC layout and exponent handling against commit `855cf9bf08e847dc62759608b7b387e410af79ed`. The complete retained notice is bundled at `THIRD_PARTY_LICENSES/spc-io-MIT.txt`.
- **spc-parser 2.1.0 parser concepts and fixture corpus** — Copyright © 2021 cheminfo, MIT. SpectraSherpa cross-checks its native Galactic SPC layout and retains independently authored conformance fixtures from commit `f770e788bd553ac8ebe6c831b4619280d083016e`. The complete retained notice is bundled at `THIRD_PARTY_LICENSES/spc-parser-MIT.txt`; source-tree detail for both SPC references is in `docs/attributions/native-spc.md`.
- **spectrochempy-omnic 0.2.1 public reverse-engineering reference** — Copyright © 2025 LCS — Laboratoire Catalyse et Spectrochimie, Caen, France, CeCILL-B. SpectraSherpa's independently implemented bounded native OMNIC reader was cross-checked against tag `v0.2.1`, commit `2eb6b7d3964451d35eeb0c185cb99a0cc147c7cd`. No upstream source or binary is bundled or imported at runtime; source-tree detail is in `docs/attributions/native-omnic.md`.
- **renishawWiRE 0.1.16 parser concepts** — Copyright © 2022 T.Tian, MIT. SpectraSherpa adapts the read-only WDF chunk, spectrum, coordinate, and map metadata grammar from tag `0.1.16`, commit `b84cc3c23ee977ffd84d58a49e5a9d94260ed07c`. The complete retained MIT notice is bundled at `THIRD_PARTY_LICENSES/renishawWiRE-MIT.txt`; source-tree detail is in `docs/attributions/native-wdf.md`. The optional image/plot/export surfaces are not included.

---

## Bundled frontend assets (under `src/spectra_sherpa/static/`)

The compiled frontend ships as part of the Python wheel so that `pip install spectra-sherpa` produces a runnable local-first application without a separate Node.js build step.  The bundle includes:

- **Inter typeface** — Copyright (c) 2016–present The Inter Project Authors.  Licensed under the SIL Open Font License v1.1.  Source: <https://github.com/rsms/inter>.
- **PrimeIcons** — Copyright (c) PrimeTek Informatics.  Licensed under the MIT License.  Source: <https://github.com/primefaces/primeicons>.
- **KaTeX fonts** (KaTeX_AMS, KaTeX_Caligraphic, KaTeX_Fraktur, KaTeX_Main, KaTeX_Math, KaTeX_SansSerif, KaTeX_Script, KaTeX_Size, KaTeX_Typewriter) — Copyright (c) Khan Academy and other contributors.  Licensed under the MIT License.  Source: <https://github.com/KaTeX/KaTeX>.
- **Plotly.js** — Copyright (c) Plotly, Inc.  Licensed under the MIT License.  Source: <https://github.com/plotly/plotly.js>.
- **Vue.js, Vite, PrimeVue, Pinia, vue-router, and other JavaScript runtime libraries** — each licensed under the MIT License (or BSD-3-Clause in a small number of cases).  See `frontend/package-lock.json` in the source repository for the full transitive tree and per-package SPDX identifiers.

---

## Example and reference datasets

The wheel includes a small curated set of public-domain or permissively licensed example spectra so that exported workflows and tutorial notebooks run standalone. Other third-party reference datasets are cataloged but downloaded or supplied by the user at runtime.

### Eigenvector Research example data

SpectraSherpa catalogs the following Eigenvector Research, Inc. example datasets, but does **not** redistribute their raw data files in the wheel or source distribution. Users can download them from Eigenvector Research at runtime or place the files in the local SpectraSherpa reference cache:

- `corn_mat/` — Cargill NIR Corn dataset
- `cgl_nir_mat/` — CGL NIR dataset
- `diesel_csv/`, `diesel_nir_mat/` — Southwest Research Institute Diesel NIR
- `metal_etch/` — Metal etching plasma OES dataset
- `nir_shootout_mat/` — IDRC 2002 NIR Shootout dataset

Original data is courtesy of the respective contributors (including Cargill, Southwest Research Institute, IDRC participants, SEMATECH, Texas Instruments, and the contributors named by Eigenvector for each dataset). If you publish results derived from these datasets, please cite the original source per Eigenvector Research's published guidance: <https://eigenvector.com/resources/data-sets/>.

### Bundled samples

- `oes/UVSpectra10.csv` — Optical emission spectra; example data prepared by Spectra Scientific LLC.
- `synthetic/Synthetic_atmospheric-6.npz` and `synthetic/Library_atmospheric-9.npz` — SpectraSherpa synthetic FTIR benchmark files derived from HITRAN spectra. Cite HITRAN/HAPI and follow HITRAN terms when using these datasets in reports, publications, validation records, or customer-facing work.
- `templates/` — Workflow templates authored by Spectra Scientific LLC.

---

## Reporting attribution issues

If you believe an asset bundled here is missing required attribution or has been redistributed in violation of its upstream licence, please open an issue at <https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/issues> with the path and the upstream licence text, and we will remediate promptly.
