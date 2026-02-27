import sys
import json
import os

sys.path.insert(0, os.path.abspath('src'))
from spectra_sherpa.app.main import create_app

app = create_app()
with open('frontend/openapi.json', 'w') as f:
    json.dump(app.openapi(), f, indent=2)

print("OpenAPI schema dumped successfully.")
