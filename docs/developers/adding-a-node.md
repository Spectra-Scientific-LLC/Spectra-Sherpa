# Adding a Scientific Node

A SpectraSherpa node is a reviewed scientific contract, not a dynamically
loaded plugin. This guide uses a moving-median despiking operation as a small,
real example. The operation replaces each ordinate with the median inside an
odd-width window; its purpose, edge rule, and effect on metadata must be fixed
before implementation.

## 1. State the scientific purpose

Write down the question the node answers and cite the method you implement.
For a moving median, define whether it is a general nonlinear smoother or a
spike-removal step, cite the algorithm or standard used, and disclose that it
can alter narrow real peaks. A citation is not a substitute for an executable
oracle.

## 2. Declare typed ports

Use `SherpaDataset`/spectral ports rather than an untyped array:

```text
input  default: SpectralDataset
output default: SpectralDataset
```

State whether the feature axis must be ordered, whether n-D inner modes are
accepted, and whether sample and feature masks are honored. The output port
must describe what the node really returns.

## 3. Bound every parameter

For `window_size`, require an odd integer with an explicit minimum and maximum.
Reject booleans, even values, windows longer than the feature axis, NaN, and
unknown parameters. Do not silently repair `4` to `5`.

## 4. Refuse invalid scientific input

Before computing, check dimensionality, shape, finiteness, axis compatibility,
and minimum support. Follow the family's missing-data policy. A preprocessing
node must not turn one NaN into a whole row of NaNs or invent values outside a
qualified gap-handling contract.

## 5. Preserve the dataset contract

Build the output from the input dataset so sample labels, target context,
class sets, alternate axes, inclusion masks, domain context, and unrelated
metadata survive. Change only the array and fields the operation actually
changes. If shape changes, update the feature axis under the same authority.

## 6. Append provenance

Record the canonical operation ID, admitted parameters, input/output shape,
implementation identity, and state effects. Provenance is append-only; do not
rewrite the source history or store a free-text approximation of parameters.

## 7. Give execution one stable identity

Declare the node metadata, explicit execution policy, citations, and stable
execution contract. Workbench, SDK, saved graphs, Python export, and model
reproduction must call the same implementation rather than parallel wrappers.

Start from the maintained scaffold:

```bash
make node-scaffold
```

The scaffold is a starting structure, not qualification. Review every generated
port, parameter, policy, and refusal.

## 8. Register it in source

Add the node to the built-in reviewed registry and its documentation family.
The installed application intentionally does not discover arbitrary entry
points or user-directory Python. Scientific execution is a trust boundary: a
new operation enters through source review, closed contracts, and tests.

## 9. Test against an independent oracle

At minimum, test:

- hand-calculated values on a short matrix;
- an independent NumPy/SciPy calculation where appropriate;
- boundaries and invalid parameter types;
- NaN/Inf and insufficient-shape refusal;
- axis, target, mask, metadata, and provenance preservation;
- deterministic replay and export behavior;
- a realistic consumer workflow rather than only a direct unit call.

Name the canonical operation ID in the test, then run:

```bash
make test-node NODE=preprocess.moving_median
```

Unknown node IDs fail with the accepted dotted syntax and examples.

## 10. Declare presentation behavior

Apply the [Scientific Result Surface Contract](scientific-result-surface-contract.md)
to every plot, table, statistics panel, result view, and export the node exposes.
It is the canonical guide for authority, claim scope, transformation disclosure,
lifecycle fidelity, explicit refusal, and the minimum five-case test matrix.

Decide which output is essential in the Inspector, which plot/table contract
renders it, and what belongs under technical details. Do not send arbitrary
renderer payloads from the node. If no special plot is warranted, say so.

## 11. Run focused qualification

Inside the integration monorepo:

```bash
make qualify-node NODE=preprocess.moving_median
```

This runs the evidence files assigned to the node, then checks the retained
node-readiness and qualification authorities. In a standalone public checkout,
the focused tests still run before the command explains that a maintainer must run the retained
paired-platform authority. A local pass never awards five stars by itself.

## 12. Review generated evidence

An implementation or contract change reopens its source identity. Regenerate
only the affected census, readiness, scientific-value, presentation, and
qualification projections. Review their semantic diff; do not accept generated
changes merely because a script produced them.

## Pull-request checklist

- [ ] Purpose, limitations, and scientific citation are explicit.
- [ ] Ports, parameters, policy, and execution contract are closed.
- [ ] Invalid shape, non-finite input, and unknown parameters refuse.
- [ ] Axes, targets, masks, metadata, and provenance behave deliberately.
- [ ] One implementation serves direct, DAG, export, and replay paths.
- [ ] The [canonical artifact lifecycle](scientific-result-surface-contract.md#canonical-node-artifact-acceptance) disposition is explicit; model tests cover fit → saved Run → Artifacts → reopen → Deploy → application, or an explicit cohort-only outcome.
- [ ] Independent oracle and realistic consumer tests pass.
- [ ] Presentation is compact and renderer-neutral.
- [ ] Nodes, plots, statistics, and result views satisfy the [Scientific Result Surface Contract](scientific-result-surface-contract.md), with its minimum dissimilar test cases and population/denominator assertions.
- [ ] `make test-node NODE=<type>` passes.
- [ ] `make qualify-node NODE=<type>` obligations are resolved by a maintainer.
- [ ] Generated evidence is reviewed and platform qualification is current.

## Computational boundaries and retained state

Apply the [computational boundary obligations](scientific-result-surface-contract.md#computational-boundary-obligations)
to the node's execution contract as well as its presentation. Check actual sample
effects on partially missing inputs. Fitted state must bind applicable feature and
response identity, and validate reference/input compatibility before arithmetic.
Validate labeled X/Y alignment before converting either input to a bare array.
If the operation filters samples, retain an exclusion receipt; if it emits metrics,
use declared per-response definitions and test unit transformations independently.
A registry identity or serializer digest alone does not prove those properties.
