# Interface and scientific plot themes

!!! abstract "Summary"
    For developers: the single color and theme authority shared by the app, exports, and hosted modules.

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

Detailed View and Quick Plot opt into `ss-panel-theme`, the shared dark context
in `controls.css`. It aliases interface roles to the existing panel tokens for
fields, buttons, tables and labels; teleported dropdown menus carry that same
class. Do not add embedded-view light overrides or individual control palettes.
Both views provide the typed `PLOT_SURFACE` context as `panel`, including nested
and legacy charts. Other pages retain their existing light context.

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

`themedPlotLayout()` supplies explicit paper and readable title, axis and legend
text for the declared surface. `PANEL_PLOT_THEME` derives dark paper and text
from the panel tokens, without changing categorical colors, numeric scales or
reference geometry. Full renders, layout-only redraws and direct PNG downloads
retain that surface. Report capture stays light; standalone print and static SVG
figures use `PRINT_PLOT_THEME`, independent of the current workspace panel.

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
The high-contrast categorical palette keeps the same category colors across
dark panels and light reports, with at least 3:1 against both plot papers.
It must not silently remap category identity when a figure is exported.
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

## Compact plot context

PlotlyChart combines retained population metadata and display-setting limits
into one collapsed MethodHelp control. Quick Plot and Detailed View use that
same renderer. Matching Original/Preprocessed counts are stated once; different
counts and exclusions remain distinct. Independent-axis/color-scale context
stays in the help text, not a second permanent banner.

Optional metadata-styling unavailability belongs in that context when no
styling was requested. Failed requested styling, missing comparison input and
plot refusals remain visible. Never infer population identity from equal row
counts: the disclosure says only that the counts match. Data-table pagination
and actual execution errors are not replaced by a working plot or hidden help.
