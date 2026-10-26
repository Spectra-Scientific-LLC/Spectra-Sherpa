# Scientific References

Trace a scientific rule from its published rationale to Sherpa's execution
contract and regression tests. A citation explains the method; it does not
certify a particular dataset, model or software release.

| Reference | Supported topic | Sherpa rule and implementation |
| --- | --- | --- |
| **SR-001** — Moscovich & Rosset (2022), *On the Cross-Validation Bias due to Unsupervised Preprocessing*. JRSS B **84**(4), 1474–1502. [DOI](https://doi.org/10.1111/rssb.12537); [open manuscript](https://arxiv.org/abs/1901.08974) | Data-dependent preprocessing can bias validation even without response labels; the bias need not be optimistic. | [Preprocessing and validation](preprocessing-validation.md), contract **PREPROCESS-SCOPE-1** |
| **SR-002** — Eigenvector Research, [preprocessing inside versus outside cross-validation](https://www.eigenvectordocs.com/index.php?title=Faq_get_different_cross_validation_results_when_doing_preprocess_before_crossval_vs_inside_crossval) | Calibration-only preprocessing statistics and the exception for independent row-wise operations. Vendor methodology documentation, not a peer-reviewed paper. | [Sample-wise versus fitted preprocessing](preprocessing-validation.md#sample-wise-versus-fitted-preprocessing), contract **PREPROCESS-SCOPE-1** |

## How to use this section

Each topic names the supported claim, its limits, the governing contract,
implementation owners and executable checks. Node-specific algorithm citations
also remain in the canonical node registry; this section connects cross-node
rules to that authority rather than replacing it.

This initial section covers preprocessing scope. It is not yet a complete
bibliography for all Sherpa methods. New topics should follow the same chain:
**reference → scoped claim → contract → implementation → regression test**.
Changes to methods or admission must update their mapping, not merely add a
paper to a bibliography. See [Where truth lives](../AUTHORITIES.md).
