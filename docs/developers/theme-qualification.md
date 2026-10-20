# Theme migration qualification

PR 2 covers semantic interface colors, PrimeVue 3 states, scientific plot
palette policy and offline export styling. It does not change computation or
remove capabilities. See [the authority guide](theme-authority.md).

## Local checks

- OSS frontend: 247 test files / 2,134 tests passed; TypeScript and production
  build passed; ESLint 0 errors, 219 existing warnings.
- Shared color inventory: zero hex/RGB/HSL or common named-color literals
  outside the token and plot authorities. Token-reference checks pass.
- Contrast: declared normal-text role pairs and node-header gradient stops
  meet 4.5:1; input boundaries and focus rings meet 3:1 on declared surfaces.
- Strict documentation build passed. No backend, model serialization or
  desktop-packaging qualification is claimed for this frontend-only change.

## Chrome acceptance, 2026-10-19

Native Chrome control was used because the extension debugger was unattached.
The existing local deployment and projects were reused on port 8031. Retained
scientific results were inspected without rerunning workflow computation.

| Journey | Observed result |
| --- | --- |
| My Dataset | Lavender project 1 retains 33 source samples and 1,868 features. Previewing CL__B1 and ESL__B1 produces two colorblind-friendly spectra with a descending wavenumber axis in cm-1 and absorbance. Preview checkboxes were restored afterward. |
| Workflow controls | Dark sheet text, category gradients, dropdown labels, light settings popover and checkbox boundaries are readable. Keyboard navigation displays a separate focus ring. No Run action was invoked. |
| Inspector | Lavender workflow 3 PCA colors change with the preference; 33 samples, PC1 85.6%, PC2 9.7% and variance curves remain. Independently, Corn workflow 20 `model_full` Data View contains 60 calibration rows and six fields; first reference/prediction is 10.146 / 10.201366897878797. |
| Runs | History → Inspect opens Lavender retained run 47 / `model_1`, with the same PCA population, selectors and categorical plot. |
| Report | Run 47 generates a report with 17 plot images. The downloaded HTML opens as a local file in Chrome with embedded figures, readable tables, variance ratio 0.8557 and the sentence that calibration/CV do not establish independent test performance. |
| Plot PNG | Corn calibration PNG downloaded through Chrome and opened in Preview; title, reference/predicted axes, observations and diagonal reference line retained. |
| Canvas PNG | Corn workflow 20 export opened in Preview; 11 nodes, category gradients, lavender dotted background, straight edges and labels retained. Empty Sheet 1 correctly refuses export. |

Theme issues discovered visually and corrected: white dropdown-label inset on
dark controls, faint preview-checkbox outlines, inherited gray badge text,
dark-table sorting icons, a light-popover note using dark-panel text, and an
indistinguishable active select-button state. The original high-contrast
preference was restored in the active audit window.

The paired hosted change also qualifies its actual Optimize components in
Chrome using the existing synthetic Corn navigation fixture: ranking, selected
seed, lineage, detail panel, ground rules and keyboard focus. This is **component
presentation coverage**, not hosted account/backend or optimization execution.
Hosted tests: 35 files / 287 tests passed; type-check and production build passed.

## Limits and compatibility

- The maintainer approved preserving explicit colors in legacy server-built
  figures without declared semantic color roles. Consumers must not guess
  whether a color represents a category, threshold or excluded observation.
- Continuous scales, excluded points, reference geometry and evaluation-role
  colors are not categorical preferences. Existing defaults are not universally
  colorblind-safe; users can select an accessible palette and metadata symbols.
- Narrow embedded PCA summaries can crowd their long legend against the plot
  title. This is a separate pre-existing layout limitation, not fixed by tokens.
- These eight planned presentation journeys (seven shared, one hosted) are
  complete; they are not a claim that every application state meets WCAG.
  Automated axe evaluation, screen-reader testing and hosted computational
  qualification were not performed. Disabled controls are contrast exceptions.
- The hosted suite must follow a normal production build: its existing bundle
  test's fallback can inherit Vitest's environment and exceed the unchanged
  305,000-byte budget. Normal production campaign output is 301,800 bytes.

Hosted CI on the pushed heads and independent reviewers A/B remain the review
gates. Neither PR is authorized to merge.
