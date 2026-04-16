"""
SklearnLoader - scikit-learn dataset loader.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_sherpa.app.lib.scp_compat import HAS_SCP, scp

from .base_loader import BaseLoader

logger = logging.getLogger(__name__)


class SklearnLoader(BaseLoader):
    """Scikit-learn dataset loader."""

    async def load_raw(self) -> Any:
        """Load raw data from scikit-learn dataset."""
        from sklearn import datasets as sk_datasets

        dataset_name = self.context.parameters.get("sklearn_dataset", "iris")

        _loaders = {
            "iris": sk_datasets.load_iris,
            "wine": sk_datasets.load_wine,
            "breast_cancer": sk_datasets.load_breast_cancer,
            "digits": sk_datasets.load_digits,
        }

        if dataset_name not in _loaders:
            raise ValueError(
                f"Unsupported sklearn dataset: {dataset_name}\n" f"Supported datasets: {', '.join(_loaders)}"
            )

        if HAS_SCP:
            # Rich path: SpectroChemPy wrappers return NDDataset with metadata
            logger.debug("[DATA] Loading sklearn dataset via SpectroChemPy: %s", dataset_name)
            try:
                scp_loader = getattr(scp, f"load_{dataset_name}", None)
                if scp_loader is None:
                    raise AttributeError(f"scp.load_{dataset_name} not found")
                dataset = scp_loader()
                if dataset is None:
                    raise ValueError(f"SpectroChemPy returned None for {dataset_name}")
                logger.debug("[DATA] Loaded %s: %s", dataset_name, dataset.shape)
                return dataset
            except (AttributeError, Exception) as e:
                logger.warning(
                    "[DATA] SCP loader failed for %s, falling back to sklearn: %s",
                    dataset_name,
                    e,
                )
                # Fall through to direct sklearn path

        # Direct sklearn path -- no SCP required
        logger.debug("[DATA] Loading sklearn dataset directly: %s", dataset_name)
        bunch = _loaders[dataset_name]()
        # Store target on the context so it can be used later
        self.context.sklearn_bunch = bunch
        logger.debug(
            "[DATA] Loaded %s: %d samples x %d features",
            dataset_name,
            bunch.data.shape[0],
            bunch.data.shape[1],
        )
        return bunch.data  # numpy array

    def get_extracted_targets(self) -> tuple[Any, Any]:
        """Return sklearn target data."""
        if hasattr(self.context, "sklearn_bunch") and self.context.sklearn_bunch:
            bunch = self.context.sklearn_bunch
            return bunch.target, bunch.target_names
        return None, None
