import sys
import os
import asyncio
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'spectra-sherpa', 'src'))

# Mock dotenv if not available
try:
    import dotenv
except ImportError:
    import types
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv
    print("Mocked dotenv module.")

print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")

try:
    import spectrochempy as scp
    # Graceful version check
    version = "unknown"
    try:
        version = scp.__version__
    except AttributeError:
        try:
            version = scp.version
        except AttributeError:
            pass
    print(f"SpectroChemPy version: {version}")

    # Check for required API methods
    required_methods = ["read_omnic", "read_jcamp", "read_spc", "read_opus", "read_csv", "read_matlab"]
    missing_methods = []
    print("\nAPI Check (SpectroChemPy):")
    for method in required_methods:
        if hasattr(scp, method):
            print(f"  [OK] scp.{method} exists")
        else:
            print(f"  [FAIL] scp.{method} MISSING")
            missing_methods.append(method)

except ImportError:
    print("SpectroChemPy not installed or not found.")
    sys.exit(1)

# Import app components after mocking
try:
    from spectra_sherpa.app.services.dag.nodes.data import DataSourceNode
    from spectra_sherpa.app.lib.scp_compat import download_testdata
except ImportError as e:
    print(f"Failed to import application components: {e}")
    sys.exit(1)

async def main():
    print("\n-- Runtime Verification --")
    print("Checking test data...")
    try:
        download_testdata()
        print("Test data downloaded/verified.")
    except Exception as e:
        print(f"Error downloading test data: {e}")

    node = DataSourceNode("test_node")
    
    # Test 1: Load example dataset (should pick a file from directory)
    print("\nTest 1: Load example dataset 'irdata'...")
    try:
        ds = node._load_spectrochempy_example("irdata")
        print(f"Success! Loaded dataset. Shape: {ds.shape}, Title: {ds.title}")
    except Exception as e:
        print(f"Failed to load 'irdata': {e}")
        
    # Test 2: Load specific file
    file_name = "irdata/CO@Mo_Al2O3.SPG"
    print(f"\nTest 2: Load specific file '{file_name}'...")
    try:
        ds = node._load_spectrochempy_custom_file(file_name)
        print(f"Success! Loaded dataset. Shape: {ds.shape}")
    except Exception as e:
        print(f"Failed to load '{file_name}': {e}")

    # Test 3: Test generic loading with pattern
    print(f"\nTest 3: Loading group with pattern 'irdata/*.SPG'...")
    try:
        ds = node._load_spectrochempy_group("irdata", "*.SPG")
        print(f"Success! Loaded group. Shape: {ds.shape}")
    except Exception as e:
        print(f"Failed to load group: {e}")

if __name__ == "__main__":
    asyncio.run(main())
