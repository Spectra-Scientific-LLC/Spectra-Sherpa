import sys
import os
print(f"Executable: {sys.executable}")
print("Sys Path:")
for p in sys.path:
    print(f"  {p}")
try:
    import pytest
    print(f"pytest imported: {pytest.__file__}")
except ImportError as e:
    print(f"ImportError: {e}")
try:
    import spectrochempy
    print(f"spectrochempy imported: {spectrochempy.__file__}")
except ImportError as e:
    print(f"ImportError spectrochempy: {e}")
