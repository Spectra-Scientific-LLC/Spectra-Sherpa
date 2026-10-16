# MCR-ALS and Curve Resolution

Multivariate Curve Resolution by Alternating Least Squares estimates component spectra and concentration-like profiles from mixture data, without reference spectra for the pure components.

MCR-ALS, EFA, and SIMPLISMA run through the optional SpectroChemPy runtime: install with `spectra-sherpa[scp]` (see [Optional SpectroChemPy Nodes](../nodes/spectrochempy.md)).

## Use MCR-ALS For

- evolving mixtures
- overlapping spectral bands
- synthetic benchmark recovery
- reaction or process series where pure spectra are not directly observed

## When It Struggles

- Components with nearly identical spectra or perfectly correlated profiles — no constraint can separate what the data does not distinguish.
- Severe rank-deficient data (one component always hidden behind another).
- Small component counts assumed wrong: if the true system has four components and you fit three, the residuals carry the missing chemistry.

## Choosing Settings

- **Number of components**: estimate rank first with PCA/EFA (scree, evolving structure), then confirm by residuals and lack of fit.
- **Initial estimates**: SIMPLISMA (purest variables) or EFA (evolving profiles) give chemically sensible starts; ALS is a local optimizer, so the start matters.
- **Constraints**: non-negativity on spectra and concentrations is the default expectation for absorbance data; closure (sum-to-one) suits reaction mixtures; unimodality suits elution-like profiles. Each justified constraint shrinks the ambiguity space — apply the ones your chemistry entitles you to, and record them.

## Outputs to Inspect

- resolved spectra
- concentration/profile estimates
- lack of fit
- R2 or explained reconstruction quality
- iteration/convergence behavior

## Ambiguity

MCR solutions can be scaled, permuted, or locally ambiguous. A resolved "component spectrum" is defined only up to these transformations unless constraints and external knowledge pin it down. Interpret recovered profiles with chemical constraints, known references, and residual diagnostics rather than treating a single run as uniquely true. SpectraSherpa checks MCR-ALS against synthetic ground truth precisely because recovered profiles must be compared to something known before they are trusted on unknowns.

## Further reading

- W. H. Lawton and E. A. Sylvestre, *Self modeling curve resolution*, Technometrics 13 (1971) 617–633 — the original curve-resolution formulation.
- R. Tauler, *Multivariate curve resolution applied to second order data*, Chemometrics and Intelligent Laboratory Systems 30 (1995) 133–146.
- A. de Juan and R. Tauler, *Multivariate Curve Resolution (MCR) from 2000: progress in concepts and applications*, Critical Reviews in Analytical Chemistry 36 (2006) 163–176.
