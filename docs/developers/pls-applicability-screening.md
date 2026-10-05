# Portable PLS applicability screening

Canonical SIMPLS state serializer 9 retains the numerical basis for provisional
screening of new observations. It does not establish analytical qualification,
independent validation coverage, or an instrument acceptance policy.

## Retained method

For the fitted centered/scaled matrix `Z = (X - x_offset) / x_scale`, the actual
SIMPLS projection `W` and reconstruction loadings `P` define `T = Z W` and
`E = Z - T Pᵀ`. The saved score mean and sample covariance (denominator `n-1`)
define T². Q is the squared Euclidean residual norm, `sum(E²)` per observation.
No calibration rows or score rows are retained.

Both screening limits are calibration 0.95 quantiles using linear interpolation.
An observation is outside a screen only when its statistic is **greater than**
the limit. These empirical thresholds are descriptive: they are not predictive
confidence limits, tolerance intervals, or validated false-alarm probabilities.

T² is unavailable when `n <= k+1` or score covariance rank is less than `k`.
Rank uses eigenvalues greater than `epsilon * k * largest_eigenvalue`. This
is distinct from a fit that produced fewer components than requested; application
reports both requested and effective component counts.

Q is non-discriminating and unavailable when the retained reconstruction spans
all input features, or when the reference has insufficient degrees of freedom
or deficient score covariance rank. Otherwise its limit is the larger of the empirical quantile
and a numerical floor fixed at training time:

`64 * epsilon² * max(n, p, k)² * max_i ||Z_i||²`.

The floor accommodates round-off when reference residuals are numerically zero.
Both the empirical value and floor remain visible. It is not a physical detection
limit, and an application row cannot enlarge it. Unsupported numerical overflow
refuses explicitly.

T² is dimensionless. With autoscaling, Q is in standardized squared residual
units. Without autoscaling it has squared input signal units; absent units remain
unknown. Feature/signal compatibility is checked before application.

## Claim and identity contract

The declared `ApplicabilityScreening/1.0` output records per-row indices,
statistics, flags and screening status, plus the originating prediction identity
receipt (sample labels/values, model custody, shape and prediction digest).
Rows are `within_global_screen`, `outside_global_screen` or `unavailable`.

**Every row's overall applicability remains `unqualified`.** The retained
aggregate state cannot establish local neighborhood support between separated
calibration clusters. `neighborhood_support=unavailable_aggregate_state` is
explicit, including when an observation passes both global screens. Instrument
shifts not represented in input metadata likewise require laboratory evidence;
passing a global screen does not establish instrument equivalence.

Generated Python, canonical package import, saved run output, and folder-watch
execution retain the same declared record. Folder-watch restart must preserve
limits and model identity. Historical PLS serializers without this diagnostic
state require refitting under the current application contract; no missing
reference statistics are reconstructed from a new cohort.

## Acceptance

Tests independently calculate covariance, T², Q and quantiles; exercise high
leverage, projection-null residual changes, a cluster gap, zero reference
residuals, unavailable rank/dimension cases and unit rescaling. Signed-package
import and offline folder-watch tests read the retained record after execution
and restart. Private Diesel checks demonstrate mechanics, not qualification.
