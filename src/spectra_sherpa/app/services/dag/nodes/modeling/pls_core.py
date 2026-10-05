"""Finite-data SIMPLS authority shared by Sherpa PLS model families.

This module owns only partial-least-squares linear algebra.  It deliberately
does not know whether response columns are continuous analytes or encoded
classes, and it does not construct validation folds or calculate model-selection
metrics.  Regression and discriminant-analysis nodes retain separate public
contracts around this numerical authority.

Scientific reference
--------------------
S. de Jong, "SIMPLS: an alternative approach to partial least squares
regression", Chemometrics and Intelligent Laboratory Systems 18 (1993)
251-263, DOI 10.1016/0169-7439(93)85002-X.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ALGORITHM_ID = "sherpa.simpls.de_jong_1993"
ALGORITHM_VERSION = "1"
CITATION = (
    "de Jong, Chemometrics and Intelligent Laboratory Systems 18 (1993) 251-263, " "doi:10.1016/0169-7439(93)85002-X"
)


def _matrix(value: object, *, name: str, rows: int | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 1 and name == "Y":
        array = array.reshape(-1, 1)
    if (
        array.ndim != 2
        or (rows is not None and array.shape[0] != rows)
        or min(array.shape) < 1
        or not np.isfinite(array).all()
    ):
        raise ValueError(f"SIMPLS requires a finite two-dimensional {name} matrix")
    return np.array(array, copy=True, order="C")


def _orient(vector: np.ndarray) -> np.ndarray:
    """Give a latent vector a deterministic sign without changing its model."""

    pivot = int(np.argmax(np.abs(vector)))
    return -vector if vector[pivot] < 0.0 else vector


def _scales(centered: np.ndarray, *, enabled: bool, name: str) -> np.ndarray:
    if not enabled:
        return np.ones(centered.shape[1], dtype=np.float64)
    scale = np.std(centered, axis=0, ddof=1)
    threshold = np.finfo(np.float64).eps * max(1.0, float(np.max(np.abs(centered))))
    if np.any(scale <= threshold):
        indices = np.flatnonzero(scale <= threshold).astype(int).tolist()
        raise ValueError(f"SIMPLS cannot autoscale constant {name} column(s): {indices}")
    return np.asarray(scale, dtype=np.float64)


def apply_pls_affine_state(
    X: object,
    *,
    coefficients: object,
    feature_offset: object,
    prediction_offset: object,
) -> np.ndarray:
    """Apply one finite PLS affine state in its fitted reference frame.

    Regression, discriminant analysis, canonical fitted-state application,
    and saved-model application all delegate here.  Keeping the centred form
    avoids catastrophic cancellation for large raw baselines.
    """

    matrix = _matrix(X, name="X")
    coefficient_matrix = _matrix(coefficients, name="coefficients")
    features, targets = coefficient_matrix.shape
    x_offset = np.asarray(feature_offset, dtype=np.float64)
    y_offset = np.asarray(prediction_offset, dtype=np.float64)
    if x_offset.shape not in {(features,), (1, features)} or not np.isfinite(x_offset).all():
        raise ValueError("PLS feature offset does not match the fitted coefficient matrix")
    if y_offset.shape not in {(targets,), (1, targets)} or not np.isfinite(y_offset).all():
        raise ValueError("PLS prediction offset does not match the fitted coefficient matrix")
    if matrix.shape[1] != features:
        raise ValueError("PLS application feature count does not match the fitted model")
    predictions = (matrix - x_offset.reshape(1, features)) @ coefficient_matrix + y_offset.reshape(1, targets)
    if not np.isfinite(predictions).all():
        raise ValueError("PLS application produced non-finite predictions")
    return np.asarray(predictions, dtype=np.float64)


def _dominant_left_singular_vector(matrix: np.ndarray) -> tuple[np.ndarray, float]:
    """Return the leading left singular vector without feature-wide SVD work.

    Chemometric response matrices normally have far fewer columns than X.  In
    that regime the right Gram matrix is response-sized, while a direct SVD
    repeatedly performs avoidable feature-wide factorization.  The one-response
    case reduces exactly to normalizing the cross-covariance vector.
    """

    rows, columns = matrix.shape
    if columns == 1:
        singular = float(np.linalg.norm(matrix[:, 0]))
        if singular == 0.0:
            return np.zeros(rows, dtype=np.float64), 0.0
        return _orient(np.asarray(matrix[:, 0] / singular, dtype=np.float64)), singular
    if columns <= rows:
        eigenvalues, eigenvectors = np.linalg.eigh(matrix.T @ matrix)
        right = np.asarray(eigenvectors[:, -1], dtype=np.float64)
        left = matrix @ right
    else:
        eigenvalues, eigenvectors = np.linalg.eigh(matrix @ matrix.T)
        left = np.asarray(eigenvectors[:, -1], dtype=np.float64)
    leading = max(0.0, float(eigenvalues[-1]))
    singular = float(np.sqrt(leading))
    norm = float(np.linalg.norm(left))
    if singular == 0.0 or norm == 0.0:
        return np.zeros(rows, dtype=np.float64), 0.0
    return _orient(np.asarray(left / norm, dtype=np.float64)), singular


@dataclass(frozen=True)
class PLSFit:
    """One complete SIMPLS fit in scaled and raw-input coordinates."""

    algorithm_id: str
    algorithm_version: str
    requested_n_components: int
    n_components: int
    scale: bool
    x_offset: np.ndarray
    x_scale: np.ndarray
    y_offset: np.ndarray
    y_scale: np.ndarray
    x_scores: np.ndarray
    x_weights: np.ndarray
    x_loadings: np.ndarray
    y_loadings: np.ndarray
    x_orthonormal_loadings: np.ndarray
    coefficients: np.ndarray
    coefficient_path: np.ndarray
    prediction_offset: np.ndarray
    x_explained_variance: np.ndarray
    y_explained_variance: np.ndarray

    @property
    def features(self) -> int:
        return int(self.coefficients.shape[0])

    @property
    def targets(self) -> int:
        return int(self.coefficients.shape[1])

    def predict(self, X: object, *, n_components: int | None = None) -> np.ndarray:
        matrix = _matrix(X, name="X")
        if matrix.shape[1] != self.features:
            raise ValueError("SIMPLS application feature count does not match the fitted model")
        components = self.n_components if n_components is None else n_components
        if isinstance(components, bool) or not isinstance(components, int) or not 1 <= components <= self.n_components:
            raise ValueError("SIMPLS application component count is outside the fitted path")
        coefficients = self.coefficient_path[components - 1]
        # Evaluate in the training-centred reference frame.  Expanding this
        # into ``X @ B + (y_mean - x_mean @ B)`` is algebraically identical,
        # but catastrophically cancels when raw intensities have a large
        # baseline relative to their chemically meaningful variation.
        return apply_pls_affine_state(
            matrix,
            coefficients=coefficients,
            feature_offset=self.x_offset,
            prediction_offset=self.y_offset,
        )


def fit_simpls(
    X: object,
    Y: object,
    *,
    n_components: int,
    scale: bool = False,
) -> PLSFit:
    """Fit de Jong SIMPLS for one or several finite response columns.

    The implementation works on the cross-covariance matrix and therefore does
    not repeatedly deflate a feature-wide X matrix. ``n_components`` is a
    requested maximum. The fit stops at the last identifiable predictive
    direction and records both counts rather than emitting zero or arbitrary
    latent vectors.
    """

    matrix = _matrix(X, name="X")
    targets = _matrix(Y, name="Y", rows=matrix.shape[0])
    if matrix.shape[0] < 2:
        raise ValueError("SIMPLS requires at least two calibration samples")
    if isinstance(n_components, bool) or not isinstance(n_components, int) or n_components < 1:
        raise ValueError("SIMPLS n_components must be a positive integer")
    if n_components > min(matrix.shape[0] - 1, matrix.shape[1]):
        raise ValueError("SIMPLS n_components exceeds the calibration rank bound")
    if not isinstance(scale, bool):
        raise ValueError("SIMPLS scale must be a boolean")

    x_offset = np.mean(matrix, axis=0, dtype=np.float64)
    y_offset = np.mean(targets, axis=0, dtype=np.float64)
    centered_x = matrix - x_offset
    centered_y = targets - y_offset
    x_scale = _scales(centered_x, enabled=scale, name="X")
    y_scale = _scales(centered_y, enabled=scale, name="Y")
    scaled_x = centered_x / x_scale
    scaled_y = centered_y / y_scale

    cross_covariance = scaled_x.T @ scaled_y
    _initial_weight, cross_scale = _dominant_left_singular_vector(cross_covariance)
    cross_tolerance = np.finfo(np.float64).eps * max(cross_covariance.shape) * cross_scale
    x_total = float(np.sum(np.square(scaled_x)))
    y_total = float(np.sum(np.square(scaled_y)))
    x_scale_tolerance = np.finfo(np.float64).eps * max(scaled_x.shape) * float(np.sqrt(x_total))
    if x_total <= 0.0 or y_total <= 0.0 or cross_scale == 0.0:
        raise ValueError("SIMPLS requires non-constant X and Y with non-zero cross-covariance")

    scores: list[np.ndarray] = []
    weights: list[np.ndarray] = []
    loadings: list[np.ndarray] = []
    y_loadings: list[np.ndarray] = []
    orthonormal_loadings: list[np.ndarray] = []
    coefficient_path: list[np.ndarray] = []
    x_explained: list[float] = []
    y_explained: list[float] = []

    for component in range(n_components):
        raw_weight, singular_value = _dominant_left_singular_vector(cross_covariance)
        if singular_value <= cross_tolerance:
            if component == 0:  # pragma: no cover - initial covariance validation owns this case
                raise ValueError("SIMPLS could not identify a predictive component")
            break
        score = scaled_x @ raw_weight
        score_norm = float(np.linalg.norm(score))
        if score_norm <= x_scale_tolerance:
            if component == 0:  # pragma: no cover - initial covariance validation owns this case
                raise ValueError("SIMPLS could not identify a non-zero X score")
            break
        score /= score_norm
        weight = raw_weight / score_norm
        loading = scaled_x.T @ score
        response_loading = scaled_y.T @ score

        orthonormal = np.array(loading, copy=True)
        if orthonormal_loadings:
            basis = np.column_stack(orthonormal_loadings)
            orthonormal -= basis @ (basis.T @ orthonormal)
        orthonormal_norm = float(np.linalg.norm(orthonormal))
        if orthonormal_norm <= x_scale_tolerance:
            if component == 0:  # pragma: no cover - initial covariance validation owns this case
                raise ValueError("SIMPLS could not identify a non-zero loading")
            break
        orthonormal /= orthonormal_norm
        cross_covariance -= np.outer(orthonormal, orthonormal @ cross_covariance)

        scores.append(score)
        weights.append(weight)
        loadings.append(loading)
        y_loadings.append(response_loading)
        orthonormal_loadings.append(orthonormal)

        rotations = np.column_stack(weights)
        response_loadings = np.column_stack(y_loadings)
        scaled_coefficients = rotations @ response_loadings.T
        raw_coefficients = (scaled_coefficients * y_scale[None, :]) / x_scale[:, None]
        coefficient_path.append(raw_coefficients)

        # SIMPLS scores are orthonormal.  The component reconstructions
        # ``t @ p.T`` and ``t @ q.T`` therefore contribute exactly the squared
        # loading norms to explained X and Y sums of squares.  Rebuilding the
        # full matrices after every component would turn this otherwise linear
        # component loop into avoidable feature-wide quadratic work.
        x_explained.append(float(loading @ loading) / x_total)
        y_explained.append(float(response_loading @ response_loading) / y_total)

    path = np.stack(coefficient_path, axis=0)
    coefficients = np.array(path[-1], copy=True)
    prediction_offset = np.asarray(y_offset, dtype=np.float64)
    return PLSFit(
        algorithm_id=ALGORITHM_ID,
        algorithm_version=ALGORITHM_VERSION,
        requested_n_components=n_components,
        n_components=len(scores),
        scale=scale,
        x_offset=np.asarray(x_offset, dtype=np.float64),
        x_scale=np.asarray(x_scale, dtype=np.float64),
        y_offset=np.asarray(y_offset, dtype=np.float64),
        y_scale=np.asarray(y_scale, dtype=np.float64),
        x_scores=np.column_stack(scores),
        x_weights=np.column_stack(weights),
        x_loadings=np.column_stack(loadings),
        y_loadings=np.column_stack(y_loadings),
        x_orthonormal_loadings=np.column_stack(orthonormal_loadings),
        coefficients=coefficients,
        coefficient_path=path,
        prediction_offset=prediction_offset,
        x_explained_variance=np.asarray(x_explained, dtype=np.float64),
        y_explained_variance=np.asarray(y_explained, dtype=np.float64),
    )


def fit_simpls_exact(
    X: object,
    Y: object,
    *,
    n_components: int,
    scale: bool = False,
) -> PLSFit:
    """Fit exactly the requested number of identifiable SIMPLS components.

    Model-selection, validation, and calibration-transfer algorithms compare
    explicitly declared latent-variable counts.  They must not silently score
    a lower-rank fit when the requested component is not identifiable.
    """

    fit = fit_simpls(X, Y, n_components=n_components, scale=scale)
    if fit.n_components != n_components:
        raise ValueError(f"SIMPLS identified {fit.n_components} of {n_components} requested component(s)")
    return fit


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "CITATION",
    "PLSFit",
    "apply_pls_affine_state",
    "fit_simpls",
    "fit_simpls_exact",
]
