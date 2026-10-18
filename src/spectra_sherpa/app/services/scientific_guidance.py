"""Versioned, provider-free scientific help shared by local and hosted journeys.

These are general method recommendations, never qualification receipts. Licensed
standards are cited rather than distributed. No user data enters this catalogue.
"""

from copy import deepcopy

GUIDANCE_VERSION = "scientific-journey/1"

_ENTRIES = [
    {
        "id": "metric_roles",
        "title": "Keep calibration, training CV and held-out results separate",
        "summary": "RMSEC describes the fitted calibration samples. RMSECV uses predictions made while "
        "each sample was excluded from fitting. RMSEP describes a frozen model applied to a "
        "separate population. A smaller calibration error alone does not establish better "
        "prediction.",
        "action": "Compare the same response, units, population and evaluation role. Inspect each "
        "section independently.",
        "limitations": "A historical result without retained membership or fold evidence cannot "
        "establish a paired comparison. Unknown provenance is not evidence of "
        "independence.",
        "sources": [
            "ASTM E1655, §§15.3.6–15.3.6.3 and 18.1–18.3 (owner-verified passages; edition not " "specified)",
            "https://www.eigenvectordocs.com/index.php?title=Using_Cross-Validation",
        ],
    },
    {
        "id": "fold_isolation",
        "title": "Learn preprocessing inside each fold",
        "summary": "Fit scaling, variable selection and the model using the training part of each fold. "
        "Keep replicates and related specimens together when the intended use is prediction "
        "of new specimens. Select latent-variable complexity using development evidence.",
        "action": "Reevaluate retained recipes under a common protocol when existing evidence is " "incompatible.",
        "limitations": "Grouped k-fold CV needs at least k distinct groups and feasible training data in "
        "every fold. Do not silently lower the fold count or treat identical partitions "
        "as repetitions.",
        "sources": [
            "https://www.eigenvectordocs.com/index.php?title=Using_Cross-Validation",
            "https://www.eigenvectordocs.com/index.php?title=Variable_Selection",
        ],
    },
    {
        "id": "paired_robustness",
        "title": "Use paired partitions to assess development sensitivity",
        "summary": "Evaluate both selected recipes on the same partitions for each seed. Inspect the "
        "distribution of paired error changes and a meaningful difference in response units. "
        "Keep the held-out population outside this exercise.",
        "action": "Optionally check robustness before choosing a recipe; use nested validation when "
        "assessing the entire selection procedure.",
        "limitations": "Repeated CV is development evidence, not independent validation. Overlapping "
        "repetitions are correlated; a naive independent-samples p-value is "
        "inappropriate. A recipe chosen after seeing these results needs fresh "
        "confirmation for an independent claim.",
        "sources": [
            "https://www.eigenvectordocs.com/index.php?title=Using_Cross-Validation",
            "https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html",
        ],
    },
    {
        "id": "final_artifact",
        "title": "Review the exact artifact before operational use",
        "summary": "Reuse an existing fitted artifact when it matches the chosen recipe and declared "
        "development population. Otherwise fit explicitly on that population. Validation "
        "applies the frozen fitted pipeline; it must not relearn preprocessing or "
        "coefficients from validation samples.",
        "action": "Review for promotion, establish the exact artifact, validate to the chosen protocol, "
        "then confirm deploy-ready. Deployment is a separate optional action.",
        "limitations": "Do not add held-out samples to the fitting population silently. Changed models "
        "require new applicable validation. A campaign conclusion, CV-only result or "
        "operational readiness flag is not independent validation or ASTM conformity.",
        "sources": ["ASTM E1655, §§18.1–18.3, 24.2 and 25.1.5.1 (owner-verified passages; edition not " "specified)"],
    },
    {
        "id": "outlier_challenge",
        "title": "Assess outlier detection separately when feasible",
        "summary": "A separately declared outlier challenge set can test whether frozen detection rules "
        "flag problematic samples and what happens when they are predicted. Show detected and "
        "missed samples, exclusions and denominators, and prediction errors where reference "
        "values exist.",
        "action": "Optionally evaluate an outlier challenge after freezing the model and detector. Keep "
        "its results separate from ordinary validation accuracy.",
        "limitations": "Detector flags are not independent truth labels for testing that detector. "
        "Threshold tuning after viewing results is development. Report false alarms only "
        "for samples with a defensible in-domain designation.",
        "sources": ["ASTM E1655, §18.2.5 (owner-supplied official-publication passage; edition not " "specified)"],
    },
    {
        "id": "dataset_use",
        "title": "Record what has been revealed and used",
        "summary": "Record dataset identity, known sample overlap and whether results influenced recipe "
        "or threshold choices. Renaming or exporting a dataset does not erase known exposure. "
        "Distinguish declared use, observed use and unknown history.",
        "action": "Use fresh confirmation for an independence claim after validation results guide "
        "changes. A CV-only campaign can receive a separate later validation record without "
        "reopening its conclusion.",
        "limitations": "Software cannot prove a person has never seen data. A local declaration is not a "
        "protected-benchmark custody guarantee. Shared review does not authorize another "
        "protected consultation.",
        "sources": [
            "ASTM E1655, §§18.1–18.3 and 24.2 (owner-verified passages; edition not specified)",
            "https://www.eigenvectordocs.com/index.php?title=Variable_Selection",
        ],
    },
]


def scientific_basis() -> dict:
    """Return independent values so callers cannot mutate the shared catalogue."""
    return {
        "version": GUIDANCE_VERSION,
        "scope": "General scientific guidance; no claim of conformity to a named standard edition.",
        "journey": (
            "Build and run → Inspect → optionally Compare and check robustness → "
            "Review for promotion → fit or reuse → validate to the chosen protocol → "
            "Confirm deploy-ready → optionally Deploy."
        ),
        "entries": deepcopy(_ENTRIES),
    }
