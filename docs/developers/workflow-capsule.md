# Canonical Workflow Capsules

`ss.workflow.load(...)` accepts one portable scientific contract: the current
canonical typed-DAG capsule (`spectra-canonical-workflow-capsule/4`). Prototype
PLS capsules and transitional canonical versions are rejected without
translation.

The capsule binds:

- the exact admitted typed DAG, node contracts, parameters, topology, and
  managed optimization profile;
- the dataset capability, content, reference, and split digests;
- fold-local execution traces, runtime attestation, and recomputable metrics;
- the selected candidate and, when present, the winner-only all-data refit.

Loading is deliberately data-free. It checks the closed schema and digests,
re-admits the graph against the local canonical registry, and verifies the
execution/refit bindings. It does not read a dataset, import managed-server
code, deserialize a model, contact a URL, or execute a node.

```python
from pathlib import Path

import spectra_sherpa.sdk as ss

capsule = ss.workflow.load(Path("canonical-workflow-capsule.json"))
print(capsule.graph.digest)
print(capsule.execution_evidence.metrics.as_dict())
```

The loader accepts an in-memory mapping, bounded canonical JSON bytes, or an
explicit local path. The path is size-checked before reading. Noncanonical
JSON encodings, duplicate fields, URLs, unknown fields, unsupported versions,
and self-rehashed mutations fail closed.

Independent scientific reproduction is performed through the canonical
project/archive verification path with caller-supplied public data. The same
node contracts execute in the workbench, managed Runner, export, import, and
reproduction boundaries. There is no public materializer for the retired
prototype PLS profile.
