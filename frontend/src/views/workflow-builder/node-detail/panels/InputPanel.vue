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
            <div class="info-item" v-if="inputData?.source">
              <label>Source</label>
              <span>{{ inputData.source }}</span>
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
  background: #1e293b;
  border-radius: 12px;
  margin-bottom: 24px;
  overflow: hidden;
  border: 1px solid #334155;
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
  background: rgba(51, 65, 85, 0.5);
}
.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.section-title i {
  font-size: 0.85rem;
  color: #64748b;
}
.section-title h2 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}
.section-badge {
  padding: 4px 10px;
  background: #334155;
  border-radius: 12px;
  font-size: 0.75rem;
  color: #94a3b8;
}
.section-content {
  padding: 20px;
  border-top: 1px solid #334155;
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
  color: #64748b;
}
.empty-section i {
  font-size: 2.5rem;
  margin-bottom: 16px;
  color: #475569;
}
.empty-section p {
  margin: 0 0 8px;
  font-size: 1rem;
}
.empty-section small {
  color: #475569;
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
  background: #0f172a;
  border-radius: 8px;
}
.info-item label {
  font-size: 0.75rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.info-item span {
  font-size: 0.95rem;
  color: #f8fafc;
  font-weight: 500;
}
.connections-list h4,
.preview-table h4 {
  margin: 0 0 10px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.connection-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: #0f172a;
  border-radius: 6px;
  margin-bottom: 6px;
}
.conn-icon {
  font-size: 1.1rem;
}
.conn-name {
  flex: 1;
  color: #f8fafc;
  font-size: 0.9rem;
}
.conn-port {
  font-size: 0.75rem;
  color: #64748b;
  font-family: "JetBrains Mono", monospace;
}
</style>
