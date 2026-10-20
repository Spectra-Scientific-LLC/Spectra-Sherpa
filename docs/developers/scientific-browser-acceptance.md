# Scientific browser acceptance

These journeys qualify **what a scientist can inspect**, not merely whether a
workflow returned `completed`. They run against the production frontend and a
real disposable local backend. API calls arrange projects, import sources and
instantiate canonical templates; Run, Inspector, Data View, Quick Plot, project
switching and downloads use the browser. They do not claim coverage of every
Import dialog or every template.

## Two deliberately separate lanes

| Lane | Data and journeys | Invocation |
| --- | --- | --- |
| PR smoke | Installed Iris/PCA; original 24 × 13 IR and NIR mixtures/PCA; NIR/PLS; corruption guards | `npm run test:science:smoke` |
| Ordinary qualification | Smoke plus delayed run-list response during project switching/reopen | `npm run test:science` |
| Explicit provider qualification | Bundled Lavender/SIMPLISMA; locally supplied, digest-admitted Corn M5/Moisture/PLS | `npm run test:science:provider` |

Ordinary CI never discovers the provider tests. No journey downloads provider
data. The synthetic mixtures reproduce failure modes, **not** Lavender or Corn
performance. They are original project fixtures under the repository license;
their equations and provenance live in
`scripts/generate_scientific_browser_fixtures.py`. Iris comes from the installed
scikit-learn distribution. Lavender retains its existing bundled attribution.
Corn must be supplied by an authorized operator and accepted by the existing
registered-reference importer.

## Running locally

From the OSS package root, install the normal backend dependencies. Then:

```sh
cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:science:smoke
npm run test:science
```

For an installed Chrome, use `SCIENTIFIC_BROWSER_CHANNEL=chrome`. Set
`SCIENTIFIC_BROWSER_PYTHON` to the backend virtual environment's Python when it
is not on PATH. The launcher owns port **8041** by default, refuses reuse of an
existing server, and deletes its temporary profile on graceful shutdown.
`SCIENTIFIC_BROWSER_PORT` can choose another unused port. It does not reuse a
scientist's database or the interactive audit instance on 8031.

Provider qualification also needs the `scp` extra for SIMPLISMA. Supply Corn
explicitly (the path below is a placeholder, not a repository fixture):

```sh
CORN_ARCHIVE_PATH=/authorized/path/corn.mat_.zip npm run test:science:provider
```

Missing data or an unavailable required capability fails this lane; it is not a
successful skip. Provider traces, downloads and screenshots stay local in ignored
directories. Do not attach them to public CI/PRs without dataset permission.

## Scientific assertions

- Input matrices have a non-square shape and asymmetric spectral features.
  Independent fixture expectations check source values, coordinates, units,
  identities and exclusions before any plot is accepted.
- My Dataset's inclusion controls and retained active rows are checked
  separately. A plot cannot substitute for a nonempty table.
- Data View checks visible rows and downloaded **all-row** CSV. PCA components
  must remain component rows against spectral coordinate columns, with their own
  labels rather than sample labels.
- Quick Plot checks the actual rendered Plotly traces, coordinates and titles
  against retained results. A plausible transposition fails. Null-coordinate
  metadata legend traces are not extra observations.
- PLS checks disjoint training/held-out membership against the active source
  population and retains declared response units. Unknown provider units must
  not be borrowed from synthetic fixtures.
- The PLS starter retains its source → split graph. The canonical split applies
  declared sample inclusion in both live and exported execution; index outputs
  refer to original input rows, while the digest-bound plan indexes its active
  planning population. Connected response identities are checked before slicing.
  Feature exclusions and contradictory response masks remain explicit refusals.
- PLS must retain the graph-verified `held_out_test` role. The browser checks
  report development/test counts against split membership and CSV rows, and
  reported RMSEP against the retained evaluator value with only display-rounding
  tolerance. A reproduced but numerically wrong report fails acceptance.
- Reopen reads retained results, and CSV exports must remain identical. HTML
  report downloads must equal their displayed preview.
- A deliberately delayed old-project run list must not restore old results after
  switching projects. Reload must keep the new project.

Assertions use exact ordered identities and numerical tolerance, not screenshot
similarity. Fitted matrices are compared with the retained computation, not
reimplemented in JavaScript. These tests establish presentation fidelity, not
independent validation of the algorithms or optimal component counts.

## Visual and accessibility boundary

Focused table and component screenshots are compared across reopen on the same
browser, allowing only one 8-bit channel level of SVG rasterization rounding.
Representative component screenshots are retained for review. axe checks the
shared table and plot dialogs against WCAG A/AA rules, including keyboard access
and contrast. They do not establish whole-product accessibility compliance.

The lifecycle screenshot comparisons do **not** constitute a frozen,
cross-release visual baseline. Platform/browser rasterization differs; numeric
and identity assertions remain the release gate. Do not regenerate a screenshot
to hide a scientific assertion failure.

## CI and maintenance

Both repositories run the smoke in their existing Ubuntu frontend job on PRs.
Existing main/weekly/manual qualification paths run the broader ordinary suite.
No new cron, native packaging job, provider download or paid manual run is added.
Failure artifacts contain only ordinary-lane data and expire after seven days.
Hosted Linux results must pass independently of local macOS/Chrome evidence.

Before a release, record the explicit provider-lane result using authorized local
data, as well as ordinary CI and required public platform qualification. A smoke
pass does not waive provider qualification; do not upload provider artifacts to
public CI. Changes to the public workflow must also be mirrored to
`packages/spectra-sherpa/.github/workflows/ci.yml` upstream, separately from the
monorepo's root workflow. Paired parity checks include `.github`.

When changing a scientific surface, extend the appropriate journey and its
independent expected values. Keep each dataset in its own project. Record the
node, presentation, exact failed assertion and observed behavior; execution
success alone is never a passing result.
