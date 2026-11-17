<template>
  <section class="inspection-settings">
    <h3>External inspection connections</h3>
    <p>Connect an external client to this project's read-only inspection service. Clients can inspect available analysis nodes and existing dataset/workflow summaries when your privacy settings allow it. They cannot run or change workflows.</p>
    <p v-if="!project.currentProjectId">Select a project to manage its connections.</p>
    <template v-else>
      <p>Project: {{ project.currentProject?.name || project.currentProjectId }}</p>
      <form @submit.prevent="createConnection">
        <label>Client name <input v-model="label" maxlength="80" required :disabled="busy" /></label>
        <label>Expires after
          <select v-model="ttl" :disabled="busy">
            <option :value="3600">1 hour</option>
            <option :value="86400">1 day</option>
            <option :value="604800">7 days</option>
          </select>
        </label>
        <label><input v-model="projectSummaries" name="project_summaries" type="checkbox" :disabled="busy" /> Also allow existing dataset and workflow summaries for this project, subject to my privacy settings.</label>
        <label class="consent"><input v-model="confirmed" name="confirm_external_provider" type="checkbox" :disabled="busy" /> I understand the external client may send inspection results to its AI provider.</label>
        <button type="submit" :disabled="busy || !confirmed || !label.trim()">Create connection</button>
      </form>
      <div v-if="issued" class="credential" role="status">
        <p>Save this credential now. It is shown once and cannot be retrieved later.</p>
        <label>Credential <input :value="issued.credential" readonly autocomplete="off" spellcheck="false" /></label>
        <p>Client ID: <code>{{ issued.client_id }}</code></p>
        <button type="button" @click="copyCredential">Copy credential</button>
        <button type="button" @click="issued = null">Dismiss credential</button>
      </div>
      <p v-if="message" role="status">{{ message }}</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <button type="button" :disabled="busy" @click="refresh">Refresh connections and history</button>
      <ul aria-label="Inspection connections">
        <li v-for="connection in connections" :key="connection.client_id">
          {{ connection.client_label }} — {{ connection.project_summaries ? 'Catalog and project summaries' : 'Catalog only' }} — {{ connection.revoked_at ? 'Revoked' : `Expires ${new Date(connection.expires_at).toLocaleString()}` }}
          <button v-if="!connection.revoked_at" type="button" :disabled="busy" @click="revoke(connection.client_id)">Revoke {{ connection.client_label }}</button>
        </li>
      </ul>
      <h4>Recent inspection calls</h4>
      <p>Local history records the operation and outcome, without credentials or response contents. The latest 100 entries are shown.</p>
      <ul aria-label="Inspection call history">
        <li v-for="call in calls" :key="call.id">{{ new Date(call.created_at).toLocaleString() }} — {{ call.operation }}: {{ call.outcome }}</li>
      </ul>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import api from '@/api/client';
import { useProjectStore } from '@/stores/project';
import { useAuthStore } from '@/stores/auth';
import { useScopedRequest } from '@/composables/useScopedRequest';
import type { components } from '@/types/api/v1';

const project = useProjectStore();
const auth = useAuthStore();
const connections = ref<components['schemas']['InspectionClientInfo'][]>([]);
const calls = ref<components['schemas']['InspectionCallInfo'][]>([]);
const issued = ref<components['schemas']['CreatedInspectionClient'] | null>(null);
const label = ref('');
const ttl = ref(86400);
const confirmed = ref(false);
const projectSummaries = ref(false);
const busy = ref(false);
const error = ref('');
const message = ref('');
const headers = { 'X-Spectra-Workbench': 'inspection' };
const identity = () => [auth.user?.id, auth.sessionRevision, project.currentProjectId];
const scope = useScopedRequest(identity, () => {
  connections.value = []; calls.value = []; issued.value = null;
  confirmed.value = false; projectSummaries.value = false; label.value = ''; busy.value = false; error.value = ''; message.value = '';
}, { abortOnInvalidate: false });

async function refresh() {
  if (project.currentProjectId === null) return;
  const ticket = scope.begin();
  const projectId = project.currentProjectId;
  busy.value = true; error.value = '';
  try {
    const [clients, history] = await Promise.all([
      api.get<components['schemas']['InspectionClientInfo'][]>(`/projects/${projectId}/inspection-clients`, { headers }),
      api.get<components['schemas']['InspectionCallInfo'][]>(`/projects/${projectId}/inspection-calls`, { headers }),
    ]);
    if (ticket.isCurrent()) { connections.value = clients.data; calls.value = history.data; }
  } catch {
    if (ticket.isCurrent()) error.value = 'Could not load inspection connections.';
  } finally { if (ticket.isCurrent()) busy.value = false; }
}

async function createConnection() {
  if (busy.value || !confirmed.value || project.currentProjectId === null) return;
  const ticket = scope.begin();
  const projectId = project.currentProjectId;
  busy.value = true; issued.value = null; error.value = ''; message.value = '';
  const body: components['schemas']['CreateInspectionClient'] = {
    client_label: label.value.trim(), ttl_seconds: ttl.value, confirm_external_provider: true, project_summaries: projectSummaries.value,
  };
  try {
    const { data } = await api.post<components['schemas']['CreatedInspectionClient']>(`/projects/${projectId}/inspection-clients`, body, { headers });
    if (ticket.isCurrent()) {
      issued.value = data; confirmed.value = false; projectSummaries.value = false;
      const { credential: _credential, ...info } = data;
      connections.value.unshift(info);
    }
  } catch {
    if (ticket.isCurrent()) error.value = 'Could not create a connection. Refresh the list before retrying; revoke any connection you did not receive a credential for.';
  } finally { if (ticket.isCurrent()) busy.value = false; }
}

async function revoke(clientId: string) {
  if (busy.value || project.currentProjectId === null) return;
  const ticket = scope.begin();
  const projectId = project.currentProjectId;
  busy.value = true; error.value = '';
  try {
    await api.delete(`/projects/${projectId}/inspection-clients/${clientId}`, { headers });
    if (ticket.isCurrent()) {
      if (issued.value?.client_id === clientId) issued.value = null;
      await refresh();
    }
  } catch {
    if (ticket.isCurrent()) error.value = 'Could not revoke this connection.';
  } finally { if (ticket.isCurrent()) busy.value = false; }
}

async function copyCredential() {
  if (!issued.value) return;
  const ticket = scope.capture();
  try {
    await navigator.clipboard.writeText(issued.value.credential);
    if (ticket.isCurrent()) message.value = 'Credential copied. Keep it private.';
  } catch { if (ticket.isCurrent()) error.value = 'Could not copy. Select the credential and copy it manually.'; }
}

watch(identity, () => { void refresh(); }, { immediate: true });
</script>

<style scoped>
.inspection-settings { margin-top: 2rem; }
form, .credential { display: grid; gap: 0.75rem; margin: 1rem 0; }
label { display: flex; gap: 0.5rem; align-items: center; }
.credential input { flex: 1; min-width: 0; }
button { width: fit-content; }
li { margin: 0.5rem 0; }
</style>
