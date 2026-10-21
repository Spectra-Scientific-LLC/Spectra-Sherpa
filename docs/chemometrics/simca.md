# SIMCA QC

!!! abstract "Summary"
    SIMCA: class-modeling for quality control — "is this sample consistent with the reference material?" Each class gets its own model, and "none of the above" is a valid answer.

SIMCA (Soft Independent Modeling by Class Analogy) models whether a sample is consistent with one or more reference classes. Unlike discriminant methods, each class gets its own PCA model and its own acceptance region — SIMCA can answer "none of the above," which is exactly what QC needs.

## Use SIMCA QC For

- acceptance testing (is this raw material the material we qualified?)
- outlier screening
- reference-class monitoring
- detecting samples that do not belong to known classes

## When to Prefer Something Else

- You want maximum separation between well-sampled, balanced classes: consider PLS-DA and compare held-out performance; it is not universally better.
- Classes are defined by one or two samples: SIMCA class models need enough members to estimate within-class variance; a class built from three spectra is a suggestion, not a model.

## Core Diagnostics

SIMCA decisions usually combine:

- **score-space distance**, often Hotelling T² — how far inside the class model's plane the sample sits
- **residual distance**, often Q residual or DModX-style distance — how poorly the class model reconstructs the sample
- **class-specific critical limits** derived from the calibration members at a chosen confidence level

## Choosing Settings

- **Components**: the current node uses one requested PC count for every class model. It does not choose separate class-specific counts by cross-validation. Compare candidate settings using an explicit validation design; each class needs enough independent calibration members.
- **Confidence level**: 95% is the conventional starting point. Tighter limits catch more deviants and reject more good samples — pick the level from the cost of each error in your process, not from default settings.

## Interpretation

A sample can be accepted by one class, multiple classes, or no class. For QC, an unassigned sample is often scientifically important and should not be forced into the nearest class without review. Multiple acceptance usually means overlapping class models — inspect whether the classes are genuinely distinct before trusting either assignment.

SIMCA reports own-class acceptance sensitivity plus unassigned and multiple-acceptance rates. Specificity is reported as unavailable unless a representative challenge population is bound — without genuine non-members, "how often does it correctly reject?" has no honest answer.

## Further reading

- S. Wold and M. Sjöström, *SIMCA: a method for analyzing chemical data in terms of similarity and analogy*, in *Chemometrics: Theory and Application*, ACS Symposium Series 52 (1977) 243–282.
- S. Wold, *Pattern recognition by means of disjoint principal components models*, Pattern Recognition 8 (1976) 127–139.
