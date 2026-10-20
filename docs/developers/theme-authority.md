# Interface and scientific plot themes

PR 2 establishes the shared color authority without a layout redesign or a
brand/palette change. This is an incremental migration in one linked
OSS/monorepo PR pair. The initial implementation is **not full GUI coverage**.

## Authorities

| Concern | Owner | Consumers |
| --- | --- | --- |
| Text, surfaces, action/focus, border, disabled and status colors | `frontend/src/assets/tokens.css` | Shared application shell, PrimeVue public variables, hosted Optimize aliases |
| Categorical palettes | `frontend/src/theme/plotTheme.ts` | Category-color maps, shared plot display layout, report capture |
| Standalone print plot background/text | `PRINT_PLOT_THEME` in the same module | Report plot capture |
| Sequential/diverging scales, limits, scientific reference geometry | Scientific presentation producers | Passed through unchanged; not replaced with categorical palettes |
| Remaining literals | `frontend/theme-color-baseline.json` | Migration inventory only, enforced by `theme_authority.test.ts` |

Import the public tokens after the installed PrimeVue 3 stylesheet and before
application CSS. PrimeVue 3 uses a compiled theme; bridging its public variables
does not rewrite literals inside the vendor stylesheet. Do not introduce a
PrimeVue 4 preset or upgrade the component library as part of this migration.

Existing blue actions and purple workspace/Optimize accents remain distinct.
Select semantic roles for new CSS. Do not name tokens after components or hex
values. Hosted modules consume the host's public custom properties; OSS must
not import proprietary code or keep a second Optimize palette.

## Plot policy

`categoricalPalette()` preserves the default palette and offers the existing
colorblind-friendly and high-contrast choices. `createCategoryColorMap()` reads
the reactive preference, so consumers in a computed projection update both
existing and newly opened categorical plots. `themedPlotLayout()` supplies the
same categorical policy for screen and print, with explicit standalone print
colors. It does not recolor explicit trace colors by guessing their meaning.

In particular, numeric marker arrays, heatmap scales and their limits, excluded
sample styling, thresholds and reference geometry are not categorical series.
Neither palette selection nor theme application changes values, sample IDs,
units, selection, fitted results or retained evidence. A categorical palette
is not a replacement for a sequential or zero-centered diverging scale.

## Ratchet and remaining work in this pair

Run `npm run check:theme` in `frontend`. The ordinary unit suite runs the same
check. It counts hex/RGB/HSL literals per file and value outside the two color
authorities, excluding tests. Removing an old literal cannot pay for a new
literal elsewhere. The inventory is deliberately not a source-hash gate.

After a reviewed migration, regenerate with:

```sh
node scripts/theme-colors.mjs src theme-color-baseline.json --write
```

Review the inventory diff. Counts should decrease; do not raise them merely to
silence a failure. The baseline captures legacy debt, including some colors in
scientific producers that require semantic classification before migration.
It is not a contrast certification or a ban on scientifically required scales.

Before this PR pair is ready to merge:

- Complete component-by-component literal migration and the PrimeVue control
  state bridge, preserving layout and checking accessible contrast.
- Classify and migrate remaining explicit categorical trace colors; preserve
  status, reference, sequential and diverging encodings. Verify live preference
  changes rather than assuming `layout.colorway` overrides explicit colors.
- Bring standalone SVG/report styles into the compatible print theme.
- Verify Data, Workflow, Runs, Report and hosted Optimize in Chrome, including
  existing/new plots, independent Data Views, image export and offline reports.
- Record local checks, paired-source parity and remaining exceptions before
  requesting reviewers A/B's approval. No packaging or merge is authorized.
