# Validation and Model Application

Validation estimates whether a model generalizes beyond the samples used to fit it.

## Regression Metrics

Common regression outputs include RMSEP, SEP, bias, R2, Q2, and CV predictions.

## Classification Metrics

Common classification outputs include confusion matrices, accuracy, sensitivity/recall, specificity where applicable, and per-class summaries.

## Split Design

Random splits are often not enough for spectra. Consider sample grouping, replicate structure, batches, time order, and instrument changes when interpreting validation results.

## Applying Saved Models

When applying a saved model, confirm that the new spectra match the training contract: preprocessing, spectral axis, feature count, units, and target context. A model can produce numbers for incompatible spectra if the data shape matches but the scientific contract does not.
