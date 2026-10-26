# Preprocessing and Validation

## Scientific rule

Do not learn preprocessing parameters from the observations whose independent
predictive performance you are evaluating. **Splitting before fitting** is the
important boundary; transforming every spectrum before splitting is not
inherently wrong.

[SR-001](index.md) demonstrates that unsupervised preprocessing, including
feature rescaling, can bias validation and affect model selection. Its magnitude
and direction depend on the setting. This does not establish that every
centering operation changes predictions, or that every affected score is
optimistic. Sherpa uses a conservative training-only fitting rule to preserve
the independent-evaluation claim.

## Sample-wise versus fitted preprocessing

| Operation in Sherpa | Before Train/Test Split? | What determines the transformation? |
| --- | --- | --- |
| Normalize: SNV; sample-wise max, area or min–max | Yes | Only the individual spectrum, using fixed settings. |
| Smoothing, derivatives, row-wise baseline correction, clipping, cosmic-ray removal | Yes, under their stateless contracts | Each spectrum and declared settings/axis, not a fitted cohort statistic. |
| Wavenumber Align | Yes, with its required explicit grid | The connected reference coordinates; not a learned mean spectrum. |
| Scale / Center: mean-center, autoscale, Pareto | No | Column statistics learned across the reference rows. |
| MSC, EMSC, OSC, Shared Reference Scale | No under the current fitted-operation contracts | Training-derived reference or fitted state. |
| Calibration transfer: DS, PDS, SWS | No | Paired-cohort fitted transfer state. |
| Moving Window / Trend Removal | Not evidence of independent samples | These stateless time-series operations mix adjacent rows; temporal overlap and grouping require a separate split design. |
| An undeclared/custom operation | Not automatically | Safety must be established by its execution contract. |

For a fixed membership split, normalizing all rows and then selecting training
rows gives the same values as selecting those rows and normalizing them. The
test suite checks both split outputs, sample order and all five Normalize
settings, including both SNV standard-deviation conventions.

That equivalence does **not** mean a distance-based split will select the same
samples before and after normalization. Nor does it permit selecting a
normalization method by repeatedly inspecting held-out performance.
[SR-002](index.md) explicitly explains the row-wise exception and why it does
not remove contamination introduced by an earlier cohort-fitted operation.

## Constructing the workflow

- For exploration without a holdout claim, fitting Scale / Center on the full
  exploration population is valid.
- For held-out evaluation, split first. Fit preprocessing on `X_train` and
  transform `X_test` using that training-derived state. Do not independently
  fit test-set means or scales.
- Scale / Center's **Fit Reference** can explicitly bind the training branch
  while transforming test rows. Where available, use the corresponding
  **Apply Fitted** operation to consume retained fitted state.
- Within cross-validation, repeat fitted preprocessing inside each training
  fold. A scaler fitted on all development rows before CV is not fold-local.

An independently established fixed transformation can be scientifically valid
before partitioning. The current canvas does not infer that qualification from
a node label or from the existence of a reference input; fitted/application
ancestors are conservatively refused before the split. No automatic exception
for externally fitted state is claimed here.

## Contract and verification

**Contract reference: PREPROCESS-SCOPE-1**, defined in
[Workflow Execution](../architecture/workflows.md#preprocessing-and-validation-boundaries).
The live node contract's `lifecycle_kind` is the admission authority, not this
table or the frontend. The mapping is also in [AUTHORITIES](../AUTHORITIES.md).

Source paths below are relative to `src/spectra_sherpa/`; tests are relative to
the OSS repository root.

| Responsibility | Authority / check |
| --- | --- |
| Sample-wise normalization contract and computation | `app/services/dag/nodes/preprocessing/normalize_node.py`: `stateless_transform` |
| Reference-fitted scaling contract and computation | `app/services/dag/nodes/preprocessing/scale_node.py`: `fitted_transform` |
| Full ancestor check, including fitted operations hidden behind stateless ones | `app/services/dag/executor.py`: `_validate_nested_cv_ancestor_fold_safety` |
| Exact split/training lineage and evaluation role | `app/services/dag/population_authority.py`: `analyze_populations` |
| Fixed-split numerical equivalence, identity, retained refusals and deduplication | `tests/test_preprocessing_split_scope.py` |
| Holdout and nested-CV admission, including direct execution | `tests/test_workflow_validation.py` |
| Training/test lineage, reference fitting and independent refusal cases | `tests/test_population_authority.py` |

An invalid placement produces one actionable preflight notification. Its
downstream evaluation remains unqualified; suppressing a duplicate consequence
never permits execution or grants a held-out claim. Actual execution failures
remain errors. A paper citation is not a replacement for these checks or a
release qualification receipt.
