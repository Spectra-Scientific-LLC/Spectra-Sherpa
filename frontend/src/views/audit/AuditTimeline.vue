<template>
  <section class="timeline-panel" aria-labelledby="audit-timeline-heading">
    <div class="section-heading">
      <div>
        <p class="eyebrow">Timeline</p>
        <h2 id="audit-timeline-heading">Audit Events</h2>
      </div>
      <span class="row-count">{{ events.length }} rows</span>
    </div>

    <div v-if="isLoadingEvents && events.length === 0" class="timeline-state">
      Loading audit events...
    </div>
    <div v-else-if="!canQuery" class="timeline-state">
      Audit query is not enabled for this deployment.
    </div>
    <div v-else-if="events.length === 0" class="timeline-state">
      No audit events match the current filters.
    </div>

    <ol v-else class="event-list" data-testid="audit-event-list">
      <AuditEventCard v-for="event in events" :key="event.id" :event="event" />
    </ol>

    <button
      v-if="hasMoreEvents"
      class="load-more"
      type="button"
      :disabled="isLoadingEvents"
      @click="$emit('load-more')"
    >
      <i class="pi pi-chevron-down" aria-hidden="true"></i>
      <span>{{ isLoadingEvents ? "Loading" : "Load older events" }}</span>
    </button>
  </section>
</template>

<script setup lang="ts">
import AuditEventCard from "./AuditEventCard.vue";
import type { AuditEventRecord } from "./types";

defineProps<{
  events: AuditEventRecord[];
  canQuery: boolean;
  isLoadingEvents: boolean;
  hasMoreEvents: boolean;
}>();

defineEmits<{
  (e: "load-more"): void;
}>();
</script>

<style scoped>
.timeline-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
}

.section-heading {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.section-heading h2 {
  font-size: 1.35rem;
  letter-spacing: 0;
  margin: 2px 0 0;
}

.eyebrow {
  color: #64748b;
  font-size: 0.76rem;
  font-weight: 700;
  margin: 0;
  text-transform: uppercase;
}

.row-count {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 6px 10px;
}

.timeline-state {
  color: #475569;
  padding: 28px 0 10px;
}

.event-list {
  list-style: none;
  margin: 16px 0 0;
  padding: 0;
}

.event-list :deep(.event-row) + :deep(.event-row) {
  border-top: 1px solid #e2e8f0;
}

.load-more {
  align-items: center;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #0f172a;
  cursor: pointer;
  display: inline-flex;
  font-weight: 700;
  gap: 8px;
  margin-top: 12px;
  min-height: 40px;
  padding: 0 14px;
}

.load-more:disabled {
  background: #e2e8f0;
  color: #64748b;
  cursor: not-allowed;
}

@media (max-width: 980px) {
  .section-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }
}
</style>
