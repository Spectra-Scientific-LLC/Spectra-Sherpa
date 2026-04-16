"""
BaseLoader - base class for source-specific raw data loading.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, List
import numpy as np

from .source_context import DataSourceContext


class BaseLoader(ABC):
    """Base class for source-specific raw data loading."""

    def __init__(self, context: DataSourceContext):
        self.context = context

    @abstractmethod
    async def load_raw(self) -> Any:
        """
        Load raw data from source.
        Returns raw data (NDDataset, numpy array, etc.)
        """
        pass

    def get_extracted_targets(self) -> tuple[Optional[np.ndarray], Optional[List[str]]]:
        """
        Return any targets extracted during loading.
        Default returns (None, None).
        """
        return None, None