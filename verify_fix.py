
import sys
import packaging.version
import spectrochempy

print(f"SpectroChemPy version: {spectrochempy.__version__}")
print(f"File: {spectrochempy.__file__}")

version = packaging.version.parse(spectrochempy.__version__)

# New constraint: >=0.6.9, <0.9.0, !=0.7.*
is_ge_069 = version >= packaging.version.parse("0.6.9")
is_lt_090 = version < packaging.version.parse("0.9.0")
is_not_07 = not (version.major == 0 and version.minor == 7)

print(f"Meets >=0.6.9: {is_ge_069}")
print(f"Meets <0.9.0: {is_lt_090}")
print(f"Meets !=0.7.*: {is_not_07}")

if is_ge_069 and is_lt_090 and is_not_07:
    print("SUCCESS: Installed version meets new constraints.")
else:
    print("FAILURE: Installed version does NOT meet new constraints.")
