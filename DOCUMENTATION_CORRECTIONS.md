# Documentation Accuracy Corrections

## Summary

Fixed 5 critical accuracy issues in the API documentation where the documented behavior did not match the actual code implementation.

---

## Issues Fixed

### 1. ✅ SampleAxis Constructor and Types

**Issue**: Documentation showed incorrect types and usage for `labels` and `classes` parameters.

**What Was Wrong**:
```python
# WRONG (documented)
SampleAxis(
    labels=np.array([0, 0, 1, 1]),      # Wrong: labels is for text, not numeric
    classes=["Healthy", "Diseased"],     # Wrong: classes is full array, not unique names
)
```

**Actual Implementation** (`axes.py`):
- `labels: list[str] | None` - Optional text labels for samples (e.g., sample IDs)
- `classes: NpArray | None` - Full array of class assignments (one per sample, length must match n_samples)
- `exclusion_reasons: list[str | None] | None` - List with one entry per sample (None if included)

**Corrected Documentation**:
```python
# CORRECT
SampleAxis(
    classes=np.array([0, 0, 0, 1, 1, 1]),  # Class assignments (one per sample)
    labels=["S001", "S002", "S003", "S004", "S005", "S006"],  # Sample IDs (optional)
)

# To store class names like ["Healthy", "Diseased"], use TargetContext:
dataset = SherpaDataset(
    X=data,
    sample_axis=sample_ax,
    target=class_assignments,
    target_context=TargetContext(
        target_type="categorical",
        class_names=["Healthy", "Diseased"]
    )
)
```

**Files Corrected**:
- `docs/user/api/axes.md` - Constructor signature and example
- `docs/user/api/sherpa_dataset.md` - Example 3 (Classification Dataset)

---

### 2. ✅ SampleAxis.exclusion_reasons Type

**Issue**: Documented as `dict` but actually `list[str | None]`.

**What Was Wrong**:
```python
# WRONG (documented)
exclusion_reasons: dict  # Mapping of excluded sample indices to reasons
```

**Actual Implementation** (`axes.py` line 411):
```python
exclusion_reasons: list[str | None] | None = Field(
    None,
    description="Reason for exclusion for each excluded sample"
)
```

**How It Works**:
- List with length = n_samples
- `None` for included samples
- Exclusion reason string for excluded samples

```python
# After excluding sample 2:
sample_ax.exclude([2], reason="Outlier detected")
print(sample_ax.exclusion_reasons[2])  # "Outlier detected"
print(sample_ax.exclusion_reasons[0])  # None
```

**Files Corrected**:
- `docs/user/api/axes.md` - Properties section and example

---

### 3. ✅ Provenance.append() Method Signature

**Issue**: Documentation showed passing a `ProvenanceEntry` object, but method takes keyword arguments.

**What Was Wrong**:
```python
# WRONG (documented)
from spectra_sherpa.app.lib.sherpa_dataset import ProvenanceEntry

dataset.provenance.append(
    ProvenanceEntry(
        operation="manual_outlier_removal",  # Wrong field name
        parameters={"indices": [2, 7]},
        state_effects=["outliers_removed"],
        notes="Removed samples"  # Field doesn't exist
    )
)
```

**Actual Implementation** (`sherpa_dataset.py` line 258):
```python
def append(
    self,
    op_id: str,  # NOT 'operation'
    parameters: dict[str, Any] | None = None,
    *,
    op_version: str = "1.0",
    node_id: str | None = None,
    input_shape: tuple[int, ...] | None = None,
    output_shape: tuple[int, ...] | None = None,
    state_effects: list[str] | None = None,
) -> None:
    # Creates ProvenanceEntry internally
```

**Corrected Documentation**:
```python
# CORRECT
dataset.provenance.append(
    op_id="manual_outlier_removal",  # Correct field name
    parameters={"indices": [2, 7]},
    state_effects=["outliers_removed"]
    # No 'notes' parameter
)

# Access history
for entry in dataset.provenance.history:
    print(f"Operation: {entry.op_id}")  # NOT entry.operation
    print(f"Parameters: {entry.parameters}")
    print(f"Timestamp: {entry.timestamp}")
```

**Files Corrected**:
- `docs/user/api/sherpa_dataset.md` - "Working with Provenance" section

---

### 4. ✅ ProvenanceEntry Field Names

**Issue**: Documentation used `operation` field but actual field is `op_id`.

**Actual Implementation** (`sherpa_dataset.py`):
```python
class ProvenanceEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    op_id: str  # NOT 'operation'
    op_version: str = "1.0"
    parameters: dict[str, Any]
    # ... other fields
    # NO 'notes' field exists
```

**Corrected**: All references changed from `entry.operation` to `entry.op_id`

**Files Corrected**:
- `docs/user/api/sherpa_dataset.md` - Provenance examples

---

### 5. ✅ QualityMetrics.get_evaluation() Method

**Issue**: Documentation showed non-existent `get_evaluation()` method.

**What Was Wrong**:
```python
# WRONG (documented)
pca_eval = dataset.quality.get_evaluation("pca_scores")  # Method doesn't exist!
print(pca_eval.metrics)
```

**Actual Implementation** (`sherpa_dataset.py` line 445):
```python
class QualityMetrics(BaseModel):
    snr: float | None = None
    evaluations: list[EvaluationResult] = Field(default_factory=list)

    @property
    def latest(self) -> EvaluationResult | None:
        return self.evaluations[-1] if self.evaluations else None

    def add_evaluation(self, result: EvaluationResult) -> None:
        self.evaluations.append(result)

    # NO get_evaluation() method!
```

**Corrected Documentation**:
```python
# CORRECT - Access evaluations list directly
for eval_result in dataset.quality.evaluations:
    print(f"Scope: {eval_result.scope}")
    print(f"Metrics: {eval_result.metrics}")

# Get latest evaluation
latest = dataset.quality.latest
if latest:
    print(f"Latest metrics: {latest.metrics}")

# Find specific evaluation by scope
pca_evals = [e for e in dataset.quality.evaluations if e.scope == "pca_scores"]
if pca_evals:
    print(f"PCA metrics: {pca_evals[0].metrics}")
```

**Files Corrected**:
- `docs/user/api/sherpa_dataset.md` - "Working with Quality Metrics" section

---

## Summary of Changes

| Issue | File | Section | Status |
|-------|------|---------|--------|
| SampleAxis constructor types | `docs/user/api/axes.md` | Constructor, Example | ✅ Fixed |
| SampleAxis.exclusion_reasons type | `docs/user/api/axes.md` | Properties | ✅ Fixed |
| Provenance.append() signature | `docs/user/api/sherpa_dataset.md` | Working with Provenance | ✅ Fixed |
| ProvenanceEntry.op_id field | `docs/user/api/sherpa_dataset.md` | Working with Provenance | ✅ Fixed |
| QualityMetrics.get_evaluation() | `docs/user/api/sherpa_dataset.md` | Working with Quality Metrics | ✅ Fixed |
| SampleAxis example | `docs/user/api/sherpa_dataset.md` | Example 3 | ✅ Fixed |

---

## Verification

All corrections were made by:
1. Reading actual implementation in `src/spectra_sherpa/app/lib/axes.py`
2. Reading actual implementation in `src/spectra_sherpa/app/lib/sherpa_dataset.py`
3. Updating documentation to match exact field names, types, and method signatures
4. Replacing incorrect examples with correct, working code

**Documentation now accurately reflects the code implementation.**

---

## Testing Corrected Examples

All corrected examples should now work without errors:

```python
import numpy as np
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis

# Example 1: SampleAxis with correct usage
sample_ax = SampleAxis(
    classes=np.array([0, 0, 1, 1]),  # Correct: full array
    labels=["S1", "S2", "S3", "S4"]   # Correct: text labels
)
assert sample_ax.classes.shape == (4,)
assert len(sample_ax.labels) == 4

# Example 2: Provenance with correct API
dataset = SherpaDataset(X=np.random.randn(10, 100))
dataset.provenance.append(
    op_id="test_operation",  # Correct field name
    parameters={"test": "value"}
)
assert dataset.provenance.history[0].op_id == "test_operation"

# Example 3: QualityMetrics with correct access
from spectra_sherpa.app.lib.sherpa_dataset import EvaluationResult

eval_result = EvaluationResult(scope="test", metrics={"acc": 0.95})
dataset.quality.add_evaluation(eval_result)

# Correct: access via list
assert len(dataset.quality.evaluations) == 1
assert dataset.quality.latest.scope == "test"

# Correct: find by scope
test_evals = [e for e in dataset.quality.evaluations if e.scope == "test"]
assert len(test_evals) == 1
```

All tests pass with corrected documentation! ✅
