# QualityMetrics Convenience Getter Implementation

## Summary

Implemented the `get_evaluation(evaluation_id: str)` convenience method that was assumed in documentation but didn't exist.

---

## The Fix

### Before (Manual Search - 3 lines)

```python
# User had to write this boilerplate every time:
pca_evals = [e for e in dataset.quality.evaluations if e.evaluation_id == 'pca_scores']
if pca_evals:
    result = pca_evals[0]
```

### After (Convenience Method - 1 line)

```python
# Clean, simple API:
result = dataset.quality.get_evaluation('pca_scores')
```

---

## Implementation

**File**: `src/spectra_sherpa/app/lib/sherpa_dataset.py`

**Added Method** (lines 460-476):
```python
def get_evaluation(self, evaluation_id: str) -> EvaluationResult | None:
    """Get evaluation result by evaluation_id.

    Args:
        evaluation_id: The evaluation identifier to search for (e.g., "pca_scores", "cross_validation")

    Returns:
        The first matching EvaluationResult, or None if not found

    Example:
        >>> pca_eval = dataset.quality.get_evaluation("pca_scores")
        >>> if pca_eval:
        >>>     print(f"R2: {pca_eval.r2}")
        >>>     print(f"Components: {pca_eval.n_components}")
    """
    for result in self.evaluations:
        if result.evaluation_id == evaluation_id:
            return result
    return None
```

---

## Usage Example

```python
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, EvaluationResult

# Create dataset
dataset = SherpaDataset(X=data)

# Add PCA evaluation
dataset.quality.add_evaluation(EvaluationResult(
    evaluation_id="pca_scores",
    model_type="PCA",
    n_components=3,
    r2=0.85
))

# Add cross-validation evaluation
dataset.quality.add_evaluation(EvaluationResult(
    evaluation_id="cross_validation",
    model_type="LDA",
    fold=1,
    accuracy=0.92
))

# ✨ NEW: Get specific evaluation with convenience method
pca_eval = dataset.quality.get_evaluation("pca_scores")
if pca_eval:
    print(f"R²: {pca_eval.r2}")              # 0.85
    print(f"Components: {pca_eval.n_components}")  # 3

cv_eval = dataset.quality.get_evaluation("cross_validation")
if cv_eval:
    print(f"Accuracy: {cv_eval.accuracy}")  # 0.92
```

---

## Benefits

### 1. **Reduced Boilerplate** (3 lines → 1 line)
- **Before**: List comprehension + conditional check
- **After**: Single method call

### 2. **Improved Readability**
```python
# Self-documenting intent
pca_eval = dataset.quality.get_evaluation("pca_scores")

# vs cryptic list comprehension
pca_evals = [e for e in dataset.quality.evaluations if e.evaluation_id == 'pca_scores']
```

### 3. **Fewer Errors**
- No risk of forgetting `if pca_evals:` check
- No index errors (`pca_evals[0]`)
- Returns `None` explicitly if not found

### 4. **Jupyter Notebook Friendly**
- Less clutter in analysis notebooks
- Cleaner code cells
- Easier to teach/demo

---

## Documentation Updated

**File**: `docs/user/api/sherpa_dataset.md`

Added example showing the new convenience method:
```python
# Get specific evaluation by ID (convenience method - NEW!)
pca_eval = dataset.quality.get_evaluation("pca_scores")
if pca_eval:
    print(f"PCA R²: {pca_eval.r2}")
    print(f"Components: {pca_eval.n_components}")

# Alternative: manual search through evaluations list (old way)
pca_evals = [e for e in dataset.quality.evaluations if e.evaluation_id == "pca_scores"]
if pca_evals:
    print(f"PCA R²: {pca_evals[0].r2}")
```

---

## Testing

**Test File**: `test_quality_metrics_getter.py`

All tests passing ✓:
- Get evaluation by ID
- Return None for non-existent ID
- Identical results to manual search
- Works with multiple evaluations

---

## Impact on User Experience

**Before this fix**:
- Users faced with boilerplate code in every analysis notebook
- Need to remember list comprehension syntax
- Cognitive overhead for simple operation

**After this fix**:
- Clean, discoverable API
- Matches user mental model ("get me the PCA results")
- **67% less code** for common operation

**Estimated Time Savings**: 30 seconds per usage × 10 uses per analysis = **5 minutes saved per workflow**

---

## Status

✅ **Implemented** in `sherpa_dataset.py`
✅ **Documented** in `docs/user/api/sherpa_dataset.md`
✅ **Tested** with comprehensive test suite
✅ **Backward Compatible** - old list comprehension method still works
