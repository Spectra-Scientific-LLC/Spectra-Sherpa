# SIMCA QC

SIMCA models whether a sample is consistent with one or more reference classes.

## Use SIMCA QC For

- acceptance testing
- outlier screening
- reference-class monitoring
- detecting samples that do not belong to known classes

## Core Diagnostics

SIMCA decisions usually combine:

- score-space distance, often Hotelling T2
- residual distance, often Q residual or DModX-style distance
- class-specific critical limits

## Interpretation

A sample can be accepted by one class, multiple classes, or no class. For QC, an unassigned sample is often scientifically important and should not be forced into the nearest class without review.
