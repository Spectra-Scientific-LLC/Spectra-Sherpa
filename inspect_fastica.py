
import sys
import inspect

try:
    import spectrochempy as scp
    print(f"SpectroChemPy version: {scp.__version__}")
    
    if hasattr(scp, 'FastICA'):
        print("spectrochempy.FastICA exists.")
        target = scp.FastICA
        print(f"Type: {type(target)}")
        print(f"Module: {target.__module__}")
        
        try:
            src_file = inspect.getsourcefile(target)
            print(f"Source file: {src_file}")
        except Exception as e:
            print(f"Could not get source file: {e}")
            
        # Check if it inherits from sklearn
        mro = inspect.getmro(target)
        print(f"MRO: {mro}")
        
        # Check docstring for sklearn references
        doc = target.__doc__
        if doc:
            print(f"Docstring length: {len(doc)}")
            if "scikit-learn" in doc or "sklearn" in doc:
                print("Docstring mentions sklearn/scikit-learn")
    else:
        print("spectrochempy.FastICA does NOT exist.")

except ImportError:
    print("spectrochempy not installed.")

try:
    import sklearn
    print(f"sklearn version: {sklearn.__version__}")
    from sklearn.decomposition import FastICA
    print(f"sklearn.decomposition.FastICA module: {FastICA.__module__}")
except ImportError:
    print("sklearn not installed.")
