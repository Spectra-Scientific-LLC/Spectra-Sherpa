# Classification

SpectraSherpa includes several classification workflows. Choose by the shape of your question, not by habit:

| Question | Method |
| --- | --- |
| Which of several known classes does this sample belong to? | PLS-DA or KNN |
| Is this sample consistent with a reference class? | [SIMCA](simca.md) |
| Quick, explainable baseline | KNN |

## KNN

K-nearest neighbors classifies samples by distance in the selected feature space. It is easy to explain and useful as a baseline, but scaling and preprocessing matter — KNN compares distances, so an unscaled, unsmoothed spectrum lets baseline offset and noise dominate the neighborhood.

**Choosing k:** small k (1–3) is sensitive to noise and single mislabeled references; larger k smooths but can erase small classes. For small spectral datasets, 3 or 5 is a reasonable start — confirm by grouped validation, not training accuracy.

## PLS-DA

PLS-DA uses PLS2 latent variables to predict a 0/1 dummy response for each
class, then assigns the class with the largest response. Inspect confusion
matrices, class-response scores, and fold-local CV metrics. The response scores
are not probabilities and should never be reported as calibrated confidence.

Practical cautions:

- **Class balance matters.** With unequal class sizes the largest-response rule is biased toward the majority class. Check per-class sensitivity, not only overall accuracy.
- **Rejection is manual.** Plain PLS-DA always picks a nearest class; if "none of the above" is a real answer for your application, use SIMCA instead.
- Keep the number of latent variables small and validation grouped — PLS-DA overfits quietly when classes are few and components are many.

## SIMCA Classification

SIMCA builds class models and accepts samples based on distance to each class model. It is especially useful when class boundaries are better understood as acceptance regions rather than hard discriminant boundaries. See [SIMCA QC](simca.md).

## Validation for Classifiers

The same split-design rules as regression apply: replicates and specimens must not cross the train/test boundary. The local classification evaluator scores the labels and references supplied to it; it does not verify their training or split lineage. Report accuracy, per-class sensitivity and specificity, or a confusion matrix as validation only when the retained run establishes out-of-fold or held-out predictions. Training-fit class assignments are not validation evidence. See [Designing Validation](validation-design.md).

## What to Report

Always report the class order, confusion-matrix orientation, validation split, and whether any samples were unassigned.

## Further reading

- M. Barker and W. Rayens, *Partial least squares for discrimination*, Journal of Chemometrics 17 (2003) 166–173.
- R. G. Brereton and G. R. Lloyd, *Partial least squares discriminant analysis: taking the magic away*, Journal of Chemometrics 28 (2014) 213–225 — a clear-eyed assessment of PLS-DA's limits.
- T. M. Cover and P. E. Hart, *Nearest neighbor pattern classification*, IEEE Transactions on Information Theory 13 (1967) 21–27.
