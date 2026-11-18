# Retained pack evidence

Saved workflows retain the exact pack version, build, dependencies and execution
contract used by each pack node. The inert contracts in
`core/pack_requirements.py` own this representation. The frozen registry supplies
new bindings; opening old evidence does not replace its bindings with today's
installation. An unrelated installed pack adds no requirement to an OSS graph.

Saved definitions, run snapshots, workflow versions, project archives and SDK
workflow version 2 carry these bindings. Legacy OSS-only SDK workflows keep
version 1. Saved-workflow and SDK admission refuse missing or incompatible
bindings before node construction; direct executor checks refuse execution.
Executable restoration and copying also require compatible bindings. Legacy unknown graphs remain
inspectable; absence of a binding is not evidence of compatible implementation.

Typed dataset provenance retains producing-pack identity through copies and
ordinary downstream processing. Reading saved values does not require the pack
that produced them. Replaying a recorded pack transform requires its exact
binding. Existing scientific preprocessing rules still decide which transforms
can replay; a pack binding does not make an unsupported transform replayable.

For ordinary saved models, production dependencies are projected from the
producer's upstream graph. Preprocessing dependencies instead follow the typed
dataset history, including data copied from another graph. These are different
facts and must not be substituted for one another.

`core/pack_model_integrity.py` binds both facts and the preprocessing chain to a
versioned digest stored in the existing checksummed NPZ payload. Readers reject
missing or altered metadata, and fitted-state consumers exclude the validated
custody marker from scientific arrays. This detects alteration relative to
retained custody; it is not a signature proving the history of an independently
supplied artifact. Closed canonical model profiles do not accept this ordinary
model extension without their own explicit qualification.

## Inspection without execution

**Inspect archive** opens a bounded `.sherpa` workflow view without importing a
project. It shows node identities, parameters, connections and recorded pack
references. Unknown nodes cannot supply code, validators or renderers. Uploaded
graph inspection is separate from executable graph admission and does not
create a runnable workflow. Metadata size, hierarchy depth, ZIP expansion and
concurrent parsing are bounded; cancellation retains capacity until parsing ends.

Runs continue to read checksummed retained outputs without consulting pack
implementations. When a saved plotting renderer is unavailable, a generic table
or record shows the values as recorded, including units and population fields.
Missing selected output ports retain their explicit refusal; another port is
not silently substituted. Imported renderer fields are inert text.

In Runs, select completed runs and choose **Download project with runs** to
include the selected records and their saved outputs in a project package.
Open the downloaded package with **Inspect archive** to choose a run and view
its saved results or download the original result JSON. Packages without saved
results still support workflow inspection.

When a saved workflow uses unavailable nodes or pack builds, its settings and
connections remain visible in a read-only view. Open Runs to review its results.

The archive manifest and output checksums establish consistency within the
package. Publisher identity, execution permission and scientific qualification
remain governed by their respective authorities.
