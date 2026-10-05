# Classification

SpectraSherpa includes several classification workflows.

## KNN

K-nearest neighbors classifies samples by distance in the selected feature space. It is easy to explain and useful as a baseline, but scaling and preprocessing matter.

## PLS-DA

PLS-DA uses PLS2 latent variables to predict a 0/1 dummy response for each
class, then assigns the class with the largest response. Inspect confusion
matrices, class-response scores, and fold-local CV metrics. The response scores
are not probabilities and should never be reported as calibrated confidence.

## SIMCA Classification

SIMCA builds class models and accepts samples based on distance to each class model. It is especially useful when class boundaries are better understood as acceptance regions rather than hard discriminant boundaries.

## What to Report

Always report the class order, confusion-matrix orientation, validation split, and whether any samples were unassigned.
