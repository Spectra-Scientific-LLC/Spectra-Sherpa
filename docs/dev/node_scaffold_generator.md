# Node Scaffold Generator

## Overview

`scripts/scaffold_node.py` generates boilerplate for new workflow nodes.

Default path:
1. `ChemometricsNode` (recommended)
2. `TransformSpecNode` / `EstimatorSpecNode` (advanced)
3. Raw `Node` (full control)

## Quick start

Interactive:

```bash
python scripts/scaffold_node.py
```

Non-interactive (recommended default):

```bash
python scripts/scaffold_node.py \
  --name MySNVNode \
  --type chemometrics \
  --category preprocessing \
  --description "Standard normal variate"
```

Advanced options:

```bash
python scripts/scaffold_node.py --name ClipFloorNode --type transform --category preprocessing
python scripts/scaffold_node.py --name MyModelNode --type estimator --category regression
python scripts/scaffold_node.py --name CustomLogicNode --type raw --category preprocessing
```

## Generated files

For `MySNVNode`:

- Node: `src/spectra_sherpa/app/services/dag/nodes/preprocessing/my_snv_node.py`
- Tests: `tests/nodes/test_my_snv_node.py`
- Docs: `docs/dev/generated_nodes/my_snv_node.md`

## Authoring guidance

- Prefer `ChemometricsNode` for most contributions.
- Keep `node_type` namespaced and stable.
- Use `dataset.data`, `dataset.feature_axis`, and `dataset.meta` as the standard API surface.
- Add targeted tests for parameter behavior, shape handling, and diagnostics.
- Scaffolded categories: `data`, `preprocessing`, `exploratory`, `regression`, `classification`, `clustering`, `selection`, `output`.

## Registration

Generated templates use `@register_node`. Ensure your module is imported from the relevant node package/module so registration runs at startup.
