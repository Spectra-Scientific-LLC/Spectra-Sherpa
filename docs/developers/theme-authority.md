# Interface and scientific plot themes

One public theme serves the OSS application and hosted modules. This is a
color-authority migration, not a layout redesign, component-library upgrade,
universal purple rebrand, or change to scientific computation.

## Authorities

| Concern | Owner | Consumers |
| --- | --- | --- |
| Text, surfaces, controls, focus, status and node-category colors | `frontend/src/assets/tokens.css` | Vue styles, application shell, hosted Optimize aliases |
| Installed PrimeVue 3 control states | `frontend/src/assets/controls.css` | Inputs, tables, checkboxes, messages and keyboard focus |
| Resolved interface values and offline CSS | `frontend/src/theme/interfaceTheme.ts` | Canvas export, sheet-color choices, standalone HTML reports |
| Categorical palettes and scientific reference styling | `frontend/src/theme/plotTheme.ts` | Shared projections, source previews, diagnostic workbenches and report capture |
| Reactive category assignment | `frontend/src/utils/colors.ts` | Already-open and newly opened categorical projections |

Import tokens after the installed PrimeVue 3 stylesheet and before application
CSS. PrimeVue 3 is a compiled stylesheet, not a v4 preset. Its public variables
and explicit control-state bridge consume the same tokens. Hosted modules use
the public `--ss-*` properties; `--opt-*` names are compatibility aliases, not
another palette. OSS never imports proprietary code.

Choose a role, not a shade. Light-page text uses `--ss-text-*`; dark panels use
`--ss-panel-*`. A muted label is not disabled text. Node-category gradients,
port types, operational status and user-selected sheet colors have separate
roles. Saved sheet-color selections are not rewritten when plot preferences
change. Existing blue actions and purple workspace accents remain distinct.

## Scientific encoding

`categoricalPalette()` and `seriesPalette()` retain the established default
families and apply the user's colorblind-friendly or high-contrast preference.
Call them inside the projection/computed, not at module initialization, so an
already-open chart changes with the preference. Source spectra, selected
features, synthesis species, classes, clusters, library overlays and saved
diagnostics follow this path.

`SCIENTIFIC_COLORS` names non-categorical roles. Numeric marker arrays,
sequential/diverging scales and their limits, excluded observations, thresholds,
reference lines and evaluation-role colors do not become categories. Never
guess a role from an old hex color, trace name, array size or node label.
As an approved compatibility exception, unannotated server-built traces with explicit colors retain those colors;
`layout.colorway` applies only where a producer has not supplied a color.

Theme application changes no values, axes, sample IDs, masks, selection,
fitted state, units or retained evidence. Palette choice alone does not certify
an arbitrary figure as accessible. Keep labels, symbols, line styles and hover
identification alongside color.

## Screen and offline exports

`themedPlotLayout()` supplies explicit light plot paper and readable title,
axis and legend text. Full renders, layout-only redraws, PNG downloads and
report capture use that same policy. Scientific reference geometry and scale
limits remain unchanged. Static SVG validation figures use `PRINT_PLOT_THEME`.

Standalone HTML embeds the public token stylesheet; it does not fetch a theme
or require an internet connection. `themeToken()` resolves the bundled CSS for
Canvas/SVG consumers, refusing unknown or cyclic aliases. It is not a separate
handwritten color table. Canvas PNG export reads computed node gradients and
surfaces so header colors and the workspace background survive export.

## Enforcement and review

Run `npm run check:theme` and the ordinary frontend unit suite. The inventory
of hex/RGB/HSL and common named colors is empty outside the token
and plot authorities. New colors belong in a reviewed semantic role; do not
raise the baseline to permit a consumer-owned palette. Tests also check token
references, live categorical changes, unchanged numeric scales and reference
traces, layout-only redraws and standalone print values.

Contrast tests require at least 4.5:1 for declared normal-text/surface pairs,
dark-panel text, status messages, primary controls and both gradient stops of
every node header. Disabled controls are distinct from ordinary muted labels.
Input boundaries and focus rings require at least 3:1 against their declared
light surfaces; decorative separators are not control boundaries.
These tests are not a claim of full WCAG conformance: inheritance, overlays,
dynamic backgrounds, keyboard focus and real pixels still need Chrome review.

For theme changes, inspect Data, Workflow/Inspector, Runs, Report and affected
hosted components. Switch accessibility preferences on an existing categorical
plot and reopen it; independently inspect Data View. Download a plot and canvas
PNG and open an offline report. Record which actual datasets, runs and figures
were checked, and separate synthetic component fixtures from live scientific
execution. Do not claim a passing plot as a passing table.

See the [PR 2 qualification record](theme-qualification.md) for observed
coverage, compatibility exceptions and remaining limitations.
