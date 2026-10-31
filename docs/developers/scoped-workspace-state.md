# Scoped workspace state

!!! abstract "Summary"
    For developers: how asynchronous work stays bound to the user, project, and object that started it — no stale responses overwriting current work.

Asynchronous work belongs to the user session, project and object that started
it. Changing selection must not let an older response restore another dataset,
sheet or run. The frontend uses the existing Pinia stores and one request
lifecycle primitive, `frontend/src/extension-contract/requests-v1.ts`.
`composables/useScopedRequest.ts` preserves the host import path by re-exporting
that implementation. Independently built Pro views import the versioned module;
it depends only on Vue, with no host stores, permissions or private routes.

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

Advisor conversation state also belongs to the selected project in OSS, Demo
and Pro. An admitted Dashboard project selection clears the previous displayed
conversation, pending replies and in-memory fallback snapshots immediately,
without waiting for another page to establish a memory scope. This does not
delete retained history: returning to a project reloads its authorized topic
through that profile's existing transport. A same-project refresh preserves the
current conversation.

### Renewal is not a new login

Use `auth.sessionRevision`, not the bearer-token string, in workspace identity.
An acknowledged renewal of the same validated actor preserves this revision:
project, sheet, Inspector, drafts, retained results and live connections remain
owned by the same login. Logout, account change, and unclassified credential
replacement still invalidate it synchronously, including A → B → A changes.

`extension-contract/session-v1.ts` owns the browser credential envelope. A
random login marker and renewal generation distinguish login from renewal;
they do not authenticate the user. Web Locks serialize credential commits.
Receiving tabs validate the exact renewed credential with `/auth/me` before
new protected work. Network errors and 429/5xx responses preserve the workspace
but refuse dispatch until validation succeeds. Rejection or an actor mismatch
clears the old workspace. HTTP clients bind headers and expiry handling to the
checked credential snapshot; a delayed response cannot expire a newer login.

Legacy `token` storage is read only until the first envelope is committed.
After deployment, reload existing tabs to load the same frontend protocol;
already-loaded older JavaScript is not upgraded by this storage migration.
Session events and diagnostics must never record bearer tokens or API keys.

Data page entry admits an explicit `project` or `project_id` query before
restoring dataset state. Remembered/recent project selection is a fallback only
when neither is present. Conflicting, malformed or unavailable project links
must not silently restore another project's datasets. Admission uses the
project store's latest-selection rule; leaving the page invalidates the
component's pending bootstrap.

Data subtab selection is presentation intent, not a new scientific owner.
It must not cancel project admission, restore a different dataset, discard a
saved file subset, or abandon sheet-context hydration. Keep those reads scoped
to their original user/project/source; guard delayed tab activation and URL
replacement separately. A newer dataset choice still supersedes the old reads.

Capture a write's destination and payload before awaiting. A selection change
does not undo a server write already accepted. It does prevent stale UI effects
and any subsequent writes that have not started. Never reread the current
project inside a multi-step write and silently move its remaining steps there.

Use `abortOnInvalidate: false` for accepted mutations. A store-owned pending
write stays single-flight until acknowledgment and required inventory refresh
finish; editing a form cannot re-enable a duplicate save. Use `capture()` for
concurrent mutations sharing the same owner, and `begin()` for latest-wins
reads. A protocol request ID correlates websocket messages; it is not a
replacement for session/project ownership.

Refresh inventories after acknowledged writes using the current permitted
inventory scope. Do not condition that refresh on the old dataset still being
selected, and do not reselect the old dataset. Unknown write acknowledgment
requires an explicit warning before retry, not an automatic duplicate write.

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

## Temporary workflow loading diagnostics

The opt-in GUI trace can distinguish the Workflow loading predicate's three
inputs: context readiness, workbook loading and workflow loading. Snapshots
run after Vue's render flush and deduplicate equal inputs and owner IDs.
Full-workflow execution adds exact-request transport, store application and
ownership-finalizer transitions. HTTP `ok` means the awaited client response
arrived; application `ok` means the store finished applying it, not that a plot
rendered or scientific validation passed. A finalizer snapshot reports the
existing ownership decision and loading flag without changing either. Run Node
and stored-workflow execution are not instrumented by these new attempt events.

Events contain only closed operation/state values, bounded diagnostic IDs,
booleans and existing timing fields. Attempt numbers are page-local diagnostic
correlation, never API payload or execution authority. Captured page/session
ownership suppresses both queued observations and delayed completions after a
credential or actor/session change. The trace POST rechecks this captured scope
in a synchronous per-request transform immediately before adapter dispatch,
after the client's asynchronous interceptors and normal JSON serialization;
queue-time validation alone cannot prevent cross-login misattribution. This
local dispatch guard is not serialized in the body or headers. Same-session sheet changes can report a
superseded attempt, but cannot authorize result application or loading changes.
The strict backend trace schema, authentication, opt-in gate, queue/rate limits
and OpenAPI exclusion remain in force. No result values, names, URLs, tokens or
exception text belong in these events. Trace gaps do not establish absence of a
UI issue; qualification still requires a timestamped observation on the candidate.

## Remaining extraction checkpoints

The request helper does not make every component small. Synthesis generation
controls now form a display-only section; the parent retains acquisition and
save orchestration. DataContentsPanel and DataContent still have substantial
layout/wiring, and migration of older request lanes is tracked separately.
Do not claim that moving a helper completes their decomposition.

Before the next change to an unmigrated pipe, extract its coherent state/action
interface and add its delayed-response test in that same PR. Before 0.6.4
release-prep review, inventory outstanding lanes and component responsibilities
in the release checklist; classify remaining debt explicitly rather than
silently advancing a size baseline.
