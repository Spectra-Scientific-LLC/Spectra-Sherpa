<template>
  <section>
    <h3>Instrument QC and maintenance</h3>
    <p>Predictions continue while QC records inform review.</p><details><summary>Details</summary>Declared absolute tolerances are not statistical process control or laboratory certification.</details>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error" type="button" :disabled="busy" @click="refresh">Retry</button>
    <button type="button" :disabled="!history || busy" @click="download">Export complete QC history</button>
    <template v-if="history">
      <p v-if="history.application_refusal" role="alert">Application unavailable: {{ history.application_refusal }}</p>
      <h4>{{ history.snapshot.status }}</h4>
      <p>Evaluated: {{ history.snapshot.evaluated_at }}</p>
      <ul><li v-for="reason in history.snapshot.reasons" :key="reason">{{ reason }}</li></ul>
      <p v-if="history.snapshot.calculation.due_at">Next control due: {{ history.snapshot.calculation.due_at }}</p>
      <p v-if="history.snapshot.policy">Instrument: {{ history.snapshot.policy.instrument_id }} · Material: {{ history.snapshot.policy.control_material_id }} · Lot: {{ history.snapshot.policy.control_material_lot }} · Policy: {{ history.snapshot.policy.policy_version }}</p>
      <details><summary>Exact evaluated policy, residuals and evidence</summary><pre>{{ JSON.stringify(history.snapshot, null, 2) }}</pre></details>
      <article v-for="event in history.events" :key="event.event_id">
        <strong>{{ event.kind }} — {{ event.event_id }}</strong>
        <p>Observed: {{ event.occurred_at }} · Recorded: {{ event.recorded_at }}</p>
        <details><summary>Retained event</summary><pre>{{ JSON.stringify(event, null, 2) }}</pre></details>
      </article>
      <details>
        <summary>Append a control, maintenance or review record</summary>
        <p>Records are immutable. Policy changes do not clear failures. Recovery requires a new passing control and an explicit acknowledgement. Revalidation requires new post-maintenance validation and the current accepted qualification decision.</p>
        <p>Enter the versioned laboratory record as JSON. Values are sent exactly as entered. Response units, reference method, material lot and limits belong to the declared policy; no hidden limits or averaging are applied.</p>
        <label>Record type <select v-model="kind"><option value="policy">Declare policy</option><option value="control">Control observation</option><option value="maintenance">Maintenance</option><option value="recovery">Failure recovery acknowledgement</option><option value="revalidation">Post-maintenance revalidation</option></select></label>
        <label>Unique record ID <input v-model="eventId" /></label>
        <label>Observation/event time (ISO 8601 with timezone; future dates refused) <input v-model="occurredAt" placeholder="2026-09-28T12:00:00Z" /></label>
        <label>Record JSON <textarea v-model="payloadText" rows="12" /></label>
        <button type="button" :disabled="busy || !eventId.trim() || !occurredAt.trim() || !payloadText.trim() || !!history.application_refusal" @click="submit">Append evidence</button>
      </details>
    </template>
  </section>
</template>
<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import api from "@/api/client";
const props = defineProps<{ watchId: number }>();
type History = {snapshot: Record<string, any>; events: Record<string, any>[]; last_event_digest: string | null; application_refusal: string | null};
const history = ref<History | null>(null);
const kind = ref("control");
const eventId = ref(crypto.randomUUID());
const occurredAt = ref("");
const payloadText = ref("");
const error = ref("");
const busy = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;
const syncEvidence = () => { if (!busy.value && !document.hidden) void refresh(); };
onMounted(() => { window.addEventListener("focus", syncEvidence); timer = setInterval(syncEvidence, 15000); });
onBeforeUnmount(() => { window.removeEventListener("focus", syncEvidence); if (timer) clearInterval(timer); });
let generation = 0;
let request = 0;
onBeforeUnmount(() => { generation += 1; request += 1; });
function failure(e: unknown) { const value = e as {response?: {data?: {detail?: unknown}}; message?: string}; error.value = String(value.response?.data?.detail || value.message || e); }
async function refresh() {
  const current = generation; const ticket = ++request;
  try { const response = await api.get<History>(`/deploy/watches/${props.watchId}/qc`); if (current === generation && ticket === request) { history.value = response.data; error.value = ""; } }
  catch (e) { if (current === generation && ticket === request) failure(e); }
}
async function submit() {
  if (busy.value || !history.value) return;
  const current = generation; busy.value = true; error.value = "";
  try {
    await api.post(`/deploy/watches/${props.watchId}/qc`, {event_id: eventId.value.trim(), kind: kind.value,
      occurred_at: occurredAt.value.trim(), expected_last_event_digest: history.value.last_event_digest,
      payload: JSON.parse(payloadText.value)});
    if (current !== generation) return;
    eventId.value = crypto.randomUUID(); occurredAt.value = payloadText.value = "";
    await refresh();
  } catch (e) { if (current === generation) failure(e); }
  finally { if (current === generation) busy.value = false; }
}
function download() {
  const url = URL.createObjectURL(new Blob([JSON.stringify({schema_version: "spectrasherpa.instrument-qc-history/1", watch_id: props.watchId,
    scope: "Retained report-only evidence; imported approval and instrument identity are assertions", ...history.value}, null, 2)], {type: "application/json"}));
  const a = document.createElement("a"); a.href = url; a.download = `qc-watch-${props.watchId}.json`; a.click(); URL.revokeObjectURL(url);
}
watch(() => props.watchId, () => { generation += 1; request += 1; history.value = null; error.value = ""; busy.value = false;
  eventId.value = crypto.randomUUID(); occurredAt.value = payloadText.value = ""; kind.value = "control"; void refresh(); }, {immediate: true});
</script>
<style scoped>
label { display: block; margin: .75rem 0; } textarea { display: block; width: 100%; } pre { white-space: pre-wrap; max-height: 24rem; overflow: auto; }
article { margin-top: 1rem; border-top: 1px solid var(--surface-border); } button { margin: .3rem; }
</style>
