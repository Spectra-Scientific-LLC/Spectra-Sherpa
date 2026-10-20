# Scoped workspace state

Asynchronous work belongs to the user session, project and object that started
it. Changing selection must not let an older response restore another dataset,
sheet or run. The frontend uses the existing Pinia stores and one request
lifecycle helper, `frontend/src/composables/useScopedRequest.ts`.

## Request ownership

Each request lane declares its identity as primitive values. Include every
selection that changes the meaning of its result; do not include unrelated
display settings. Starting a newer request cancels its predecessor. Changing
identity invalidates the lane synchronously, including a quick A → B → A switch.
Replacing a route object without changing the declared identity is not a switch.

Cancellation is not the correctness guarantee. A client or server may finish
after cancellation. Check `ticket.isCurrent()` before applying success, error,
loading-state, navigation or notification effects:

```ts
const requests = useScopedRequest(
  () => [projectId.value, datasetId.value],
  () => { preview.value = null; },
);

async function refresh() {
  const ticket = requests.begin();
  loading.value = true;
  try {
    const response = await api.get(url, { signal: ticket.signal });
    if (ticket.isCurrent()) preview.value = response.data;
  } catch (error) {
    if (ticket.isCurrent()) failure.value = describeError(error);
  } finally {
    if (ticket.isCurrent()) loading.value = false;
  }
}
```

Use separate lanes for independent operations. Dispose them with their owning
Vue effect scope. Project-scoped stores register their reset with
`projectScopeRegistry`; registration also ends with the owning scope.
Session changes invalidate project-owned state even when object IDs repeat.

Capture a write's destination and payload before awaiting. A selection change
does not undo a server write already accepted. It does prevent stale UI effects
and any subsequent writes that have not started. Never reread the current
project inside a multi-step write and silently move its remaining steps there.

## Component boundaries

Data orchestration lives in `views/data/composables/`: dataset navigation,
definitions, readiness, inspection and synthesis each have an explicit
interface. Scientific values and eligibility still come from their existing
backend authorities. Components own layout and actions, not another acquisition
or persistence implementation.

Inspector orchestration lives in `views/workflow-builder/composables/`:
parameter drafts, execution context and retained evidence have separate owners.
Editable parameters are detached from node metadata and saved results.
Presentation selection delegates to the shared scientific projectors; it does
not recompute the scientific result.

Runs inspection owns its retained-output cache by project and run. A different
run or session cannot reuse that evidence. A table and a plot are distinct
surfaces and must each be checked.

`WorkspaceState` supplies loading, empty, unavailable, refusal and error
semantics. Keep its message specific and short; use an action slot for a scoped
retry or selection. An unavailable retained result is not an empty dataset.

## Review and verification

Budget orchestration changes by responsibility, not a rigid line count. Review
one pipe at a time: its inputs, owned state, reads, writes and teardown should
be understandable without tracing acquisition and presentation together.
Do not introduce a second store framework or combine extraction with changed
scientific behavior.

The helper, store and mounted-component tests exercise ignored cancellation,
late success/error/finally effects, repeated identities and scope disposal.
The scientific browser suite adds delayed dataset inspection and sheet
switches while retained evidence loads, alongside the existing project-switch,
table, plot, persistence and export journeys.

For an affected operation, verify both the old response and the new selection:
the old response must do nothing, and the new selection must remain usable.
Keep existing scientific assertions unchanged when reorganizing orchestration.
