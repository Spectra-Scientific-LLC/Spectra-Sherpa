# Classification

SpectraSherpa includes several classification workflows.

## KNN

K-nearest neighbors classifies samples by distance in the selected feature space. It is easy to explain and useful as a baseline, but scaling and preprocessing matter.

## PLS-DA

PLS-DA uses latent variables to classify labeled samples. Inspect confusion matrices, class probabilities, and CV metrics. Treat probabilities cautiously unless calibration is configured and validated.

## SIMCA Classification

SIMCA builds class models and accepts samples based on distance to each class model. It is especially useful when class boundaries are better understood as acceptance regions rather than hard discriminant boundaries.

## What to Report

Always report the class order, confusion-matrix orientation, validation split, and whether any samples were unassigned.
