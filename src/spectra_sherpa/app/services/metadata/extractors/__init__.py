"""
Format-specific metadata extractors.

Each extractor handles the unique metadata conventions of a specific
spectral file format.
"""

from .generic import GenericExtractor
from .jcamp import JCAMPExtractor
from .opus import OPUSExtractor
from .spa import SPAExtractor
from .spc import SPCExtractor

__all__ = [
    "OPUSExtractor",
    "SPAExtractor",
    "JCAMPExtractor",
    "SPCExtractor",
    "GenericExtractor",
]
