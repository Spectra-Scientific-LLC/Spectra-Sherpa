"""
Format-specific metadata extractors.

Each extractor handles the unique metadata conventions of a specific
spectral file format.
"""

from .opus import OPUSExtractor
from .spa import SPAExtractor
from .jcamp import JCAMPExtractor
from .spc import SPCExtractor
from .generic import GenericExtractor

__all__ = [
    "OPUSExtractor",
    "SPAExtractor",
    "JCAMPExtractor",
    "SPCExtractor",
    "GenericExtractor",
]
