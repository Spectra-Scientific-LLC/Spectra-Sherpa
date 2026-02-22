import copy
from concurrent.futures import ProcessPoolExecutor
from spectra_sherpa.app.services.dag.executor import DAGExecutor

pool = ProcessPoolExecutor()
executor = DAGExecutor(process_pool=pool)
try:
    copy.deepcopy(executor)
    print("Success")
except Exception as e:
    print(f"Failed: {e}")
