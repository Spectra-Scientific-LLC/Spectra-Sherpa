<template>
  <section class="detail-section">
    <div class="section-header" @click="$emit('toggle')">
      <div class="section-title">
        <i :class="expanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
        <h2>Execution Log</h2>
      </div>
      <span class="section-badge" v-if="logs.length">{{ logs.length }} entries</span>
    </div>
    <Transition name="collapse">
      <div v-if="expanded" class="section-content log-content">
        <div v-if="logs.length === 0" class="empty-section">
          <i class="pi pi-list" />
          <p>No execution logs yet</p>
          <small>Click "Run Node" to execute and see logs here.</small>
        </div>
        <div v-else class="log-entries">
          <div
            v-for="(log, idx) in logs"
            :key="idx"
            class="log-entry"
            :class="log.type"
          >
            <span class="log-time">{{ log.time }}</span>
            <span class="log-icon">
              <i :class="getLogIcon(log.type)" />
            </span>
            <span class="log-message">{{ log.message }}</span>
            <span v-if="log.details" class="log-details">{{ log.details }}</span>
          </div>
        </div>
        <div v-if="logs.length > 0" class="log-actions">
          <Button
            label="Clear Log"
            icon="pi pi-trash"
            class="p-button-sm p-button-text p-button-secondary"
            @click="$emit('clear')"
          />
        </div>
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import Button from "primevue/button";
import type { LogEntry } from "../composables/useNodeLog";

defineProps<{
  logs: LogEntry[];
  expanded: boolean;
  getLogIcon: (type: LogEntry["type"]) => string;
}>();

defineEmits<{
  (e: "toggle"): void;
  (e: "clear"): void;
}>();
</script>

<style scoped>
/* Section chrome (shared pattern; will be deduped in plan step 6) */
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

/* Log-specific */
.log-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.log-entries {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
}
.log-entry {
  display: grid;
  grid-template-columns: 70px 24px 1fr;
  align-items: start;
  gap: 10px;
  padding: 10px 14px;
  background: #0f172a;
  border-radius: 8px;
  border-left: 3px solid #334155;
  font-size: 0.85rem;
}
.log-entry.success {
  border-left-color: #22c55e;
  background: rgba(34, 197, 94, 0.05);
}
.log-entry.error {
  border-left-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
}
.log-entry.warn {
  border-left-color: #f59e0b;
  background: rgba(245, 158, 11, 0.05);
}
.log-entry.info {
  border-left-color: #3b82f6;
  background: rgba(59, 130, 246, 0.05);
}
.log-time {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.75rem;
  color: #64748b;
}
.log-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}
.log-entry.success .log-icon i { color: #22c55e; }
.log-entry.error .log-icon i { color: #ef4444; }
.log-entry.warn .log-icon i { color: #f59e0b; }
.log-entry.info .log-icon i { color: #3b82f6; }
.log-message {
  font-weight: 500;
  color: #f8fafc;
}
.log-details {
  grid-column: 3;
  font-size: 0.8rem;
  color: #94a3b8;
  margin-top: 2px;
}
.log-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
  border-top: 1px solid #334155;
}
</style>
