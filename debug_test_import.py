import sys
import os
sys.path.insert(0, os.getcwd())
print(f"CWD: {os.getcwd()}")
print(f"Path: {sys.path}")

try:
    # Try to import the test file as a module
    import backend.tests.test_file_loaders
    print("Import successful")
except Exception as e:
    print("Import failed!")
    import traceback
    traceback.print_exc()
