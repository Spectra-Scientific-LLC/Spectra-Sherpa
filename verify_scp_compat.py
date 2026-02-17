import sys
import os
import asyncio
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'spectra-sherpa', 'src'))

print(f"Python executable: {sys.executable}")

# Mock pydantic
try:
    import pydantic
except ImportError:
    import types
    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = object
    pydantic.Field = lambda *args, **kwargs: None
    sys.modules["pydantic"] = pydantic
    print("Mocked pydantic module.")

try:
    from spectra_sherpa.app.lib import scp_compat
    print("Successfully imported scp_compat.")
except ImportError as e:
    print(f"Failed to import scp_compat: {e}")
    sys.exit(1)

scp = scp_compat.scp
if not scp_compat.HAS_SCP:
    print("SpectroChemPy not found (HAS_SCP=False).")
    sys.exit(1)

# Version check
version = "unknown"
try:
    version = scp.__version__
except AttributeError:
    try:
        version = scp.version
    except AttributeError:
        pass
print(f"SpectroChemPy version: {version}")

# API Stability Check
required_methods = ["read_omnic", "read_jcamp", "read_spc", "read_opus", "read_csv", "read_matlab"]
print("\nAPI Check:")
for method in required_methods:
    if hasattr(scp, method):
        print(f"  [OK] scp.{method} exists")
    else:
        print(f"  [FAIL] scp.{method} MISSING")

# Breaking change verification: download_testdata
print("\nVerifying download_testdata logic...")
try:
    # We don't actually want to download 1GB of data in a CI/test run if we can avoid it,
    # but we want to verify the IMPORT logic works (i.e. that the new 0.8.1 path is valid).
    # scp_compat.download_testdata imports 'spectrochempy.application.testdata'
    
    # We'll simulate what download_testdata does to check if the module exists
    try:
        from spectrochempy.application.testdata import download_full_testdata_directory
        print("  [OK] spectrochempy.application.testdata.download_full_testdata_directory exists")
    except ImportError:
        print("  [FAIL] spectrochempy.application.testdata.download_full_testdata_directory MISSING")
        print("         (This is expected if running on < 0.8.1)")

    # Run the actual function (will fail if < 0.8.1 because of the import check inside it)
    # We catch the error to report it gracefully
    print("  Running scp_compat.download_testdata()...")
    try:
        scp_compat.download_testdata()
        print("  [OK] download_testdata() execution started/finished")
    except Exception as e:
        print(f"  [Error] download_testdata() failed: {e}")

except Exception as e:
    print(f"Verification failed: {e}")

print("\nscp_compat verification complete.")
