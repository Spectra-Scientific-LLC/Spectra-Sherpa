<template>
  <section class="detail-section">
    <div class="section-header" @click="$emit('toggle')">
      <div class="section-title">
        <i :class="expanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
        <h2>Input</h2>
      </div>
      <span class="section-badge" v-if="inputSummary">{{ inputSummary }}</span>
    </div>
    <Transition name="collapse">
      <div v-if="expanded" class="section-content">
        <div v-if="!hasInput" class="empty-section">
          <i class="pi pi-inbox" />
          <p>No input data available</p>
          <small>This node has not received input yet. Execute the workflow to see input data.</small>
        </div>
        <div v-else class="input-content">
          <div class="info-grid">
            <div class="info-item" v-if="inputData?.shape">
              <label>Shape</label>
              <span>{{ inputData.shape[0] }} x {{ inputData.shape[1] }}</span>
            </div>
            <div class="info-item" v-if="inputData?.dataType">
              <label>Data Type</label>
              <span>{{ inputData.dataType }}</span>
            </div>
          </div>

          <div v-if="inputConnections.length" class="connections-list">
            <h4>Connected From</h4>
            <div
              v-for="conn in inputConnections"
              :key="conn.nodeId"
              class="connection-item"
            >
              <span class="conn-icon">{{ conn.icon }}</span>
              <span class="conn-name">{{ conn.label }}</span>
              <span class="conn-port">{{ conn.port }}</span>
            </div>
          </div>

          <div v-if="inputPreview.length" class="preview-table">
            <h4>Input Preview ({{ inputDataSummary }})</h4>
            <DataTable
              :value="inputPreview"
              :scrollable="true"
              scrollHeight="200px"
              class="preview-datatable"
              size="small"
            >
              <Column
                v-for="col in inputPreviewColumns"
                :key="col.field"
                :field="col.field"
                :header="col.header"
                :style="{ minWidth: '80px' }"
              />
            </DataTable>
          </div>
        </div>
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import DataTable from "primevue/datatable";
import Column from "primevue/column";

interface InputConnection {
  nodeId: string | number;
  icon: string;
  label: string;
  port: string;
}

defineProps<{
  expanded: boolean;
  hasInput: boolean;
  inputSummary: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  inputData: any;
  inputConnections: InputConnection[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  inputPreview: any[];
  inputDataSummary: string;
  inputPreviewColumns: { field: string; header: string }[];
}>();

defineEmits<{ (e: "toggle"): void }>();
</script>

<style scoped>
.detail-section {
  background: var(--ss-panel);
  border-radius: 12px;
  margin-bottom: 24px;
  overflow: hidden;
  border: 1px solid var(--ss-panel-border);
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  cursor: pointer;
  transition: background 0.15s;
}
.section-header:hover {
  background: color-mix(in srgb, var(--ss-panel-raised) 50%, transparent);
}
.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.section-title i {
  font-size: 0.85rem;
  color: var(--ss-panel-muted);
}
.section-title h2 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}
.section-badge {
  padding: 4px 10px;
  background: var(--ss-panel-raised);
  border-radius: 12px;
  font-size: 0.75rem;
  color: var(--ss-panel-muted);
}
.section-content {
  padding: 20px;
  border-top: 1px solid var(--ss-panel-border);
}
.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.collapse-enter-from,
.collapse-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.empty-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 20px;
  text-align: center;
  color: var(--ss-panel-muted);
}
.empty-section i {
  font-size: 2.5rem;
  margin-bottom: 16px;
  color: var(--ss-text-secondary);
}
.empty-section p {
  margin: 0 0 8px;
  font-size: 1rem;
}
.empty-section small {
  color: var(--ss-text-secondary);
  font-size: 0.85rem;
}

.input-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 14px;
  background: var(--ss-panel-inset);
  border-radius: 8px;
}
.info-item label {
  font-size: 0.75rem;
  color: var(--ss-panel-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.info-item span {
  font-size: 0.95rem;
  color: var(--ss-panel-text);
  font-weight: 500;
}
.preview-datatable :deep(.p-datatable-wrapper) {
  background: var(--ss-panel-inset);
  border-radius: 6px;
  overflow: hidden;
}
.preview-datatable :deep(.p-datatable-thead > tr > th) {
  background: var(--ss-panel);
  color: var(--ss-panel-muted);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--ss-panel-border);
}
.preview-datatable :deep(.p-datatable-tbody > tr) {
  background: var(--ss-panel-inset);
  color: var(--ss-panel-secondary);
}
.preview-datatable :deep(.p-datatable-tbody > tr:nth-child(even)) {
  background: var(--ss-panel-inset);
}
.preview-datatable :deep(.p-datatable-tbody > tr > td) {
  border-bottom: 1px solid var(--ss-panel);
  font-size: 0.85rem;
}
.connections-list h4,
.preview-table h4 {
  margin: 0 0 10px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--ss-panel-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.connection-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--ss-panel-inset);
  border-radius: 6px;
  margin-bottom: 6px;
}
.conn-icon {
  font-size: 1.1rem;
}
.conn-name {
  flex: 1;
  color: var(--ss-panel-text);
  font-size: 0.9rem;
}
.conn-port {
  font-size: 0.75rem;
  color: var(--ss-panel-muted);
  font-family: "JetBrains Mono", monospace;
}
</style>
