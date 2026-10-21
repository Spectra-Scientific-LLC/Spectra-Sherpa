# Compare calibration workflows in local OSS

!!! abstract "Summary"
    A seven-step recipe for comparing preprocessing or model choices fairly in
    the local app (one duplicated sheet per alternative, identical folds) and
    what to record with each metric.

Compare a small number of scientifically motivated alternatives while keeping
the dataset, target and validation design fixed. Local OSS uses workflow sheets
and saved runs for this task; hosted Optimize campaigns are a separate service.

## Manual comparison in local OSS

1. Import the data and confirm the selected spectra, target, sample identities
   and units in **My Dataset**.
2. Create a calibration workflow with a reserved test population. Keep related
   specimens together when the study requires groups.
3. Save the baseline sheet with a meaningful name and run it.
4. Duplicate the sheet. Change one choice, such as SNV versus a derivative or
   the number of PLS components. Keep the same training population, split seed
   and CV folds.
5. Fit any learned preprocessing and variable selection inside the training
   folds used for comparison. Applying a transform once before CV does not
   establish fold-local fitting.
6. Review each saved run's CV error, bias, residuals and model interpretation.
   Use **Runs** and **Report** to retain the comparison and its scope.
7. Select the recipe before inspecting the reserved test result. Repeatedly
   choosing settings from test performance turns that population into
   development data.

## What to record

Keep the source selection, response and units, exclusions, split/fold design,
preprocessing, component count and evaluated population with each metric.
Compare like-for-like errors; calibration RMSE, RMSECV and held-out RMSEP do
not answer the same question.

A smaller CV error is not by itself a useful improvement. Consider reference
method precision, residual structure, model stability and the intended use.
Do not copy benchmark scores from another dataset or validation design as
expected results for your study.

See [PLS calibration](../chemometrics/pls.md),
[Designing validation](../chemometrics/validation-design.md) and
[Reports and exports](reports-exports.md).
