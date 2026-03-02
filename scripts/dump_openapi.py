import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from spectra_sherpa.app.main import create_app

app = create_app()
with open(os.path.join(ROOT, "frontend/openapi.json"), "w") as f:
    json.dump(app.openapi(), f, indent=2)

print("OpenAPI schema dumped successfully.")
