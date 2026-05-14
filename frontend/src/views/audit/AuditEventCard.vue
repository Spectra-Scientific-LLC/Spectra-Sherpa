<template>
  <li class="event-row">
    <div class="event-marker" aria-hidden="true"></div>
    <div class="event-body">
      <div class="event-main">
        <div>
          <p class="event-action">{{ event.action }}</p>
          <p class="event-target">{{ event.target_type }} {{ event.target_id }}</p>
        </div>
        <time :datetime="event.ts_app_utc">{{ formatDate(event.ts_app_utc) }}</time>
      </div>
      <dl class="event-meta">
        <div>
          <dt>Actor</dt>
          <dd>{{ event.actor_kind }}{{ event.actor_id ? `:${event.actor_id}` : "" }}</dd>
        </div>
        <div>
          <dt>Request</dt>
          <dd>{{ shortId(event.request_id, 10) }}</dd>
        </div>
        <div>
          <dt>Event</dt>
          <dd>#{{ event.id }}</dd>
        </div>
      </dl>
      <details v-if="hasEventState(event)" class="state-details">
        <summary>State snapshot</summary>
        <pre>{{ renderEventState(event) }}</pre>
      </details>
    </div>
  </li>
</template>

<script setup lang="ts">
import { formatDate, hasEventState, renderEventState, shortId } from "./auditFormatters";
import type { AuditEventRecord } from "./types";

defineProps<{
  event: AuditEventRecord;
}>();
</script>

<style scoped>
.event-row {
  display: grid;
  gap: 12px;
  grid-template-columns: 14px minmax(0, 1fr);
  padding: 12px 0;
}

.event-marker {
  background: #2563eb;
  border-radius: 999px;
  height: 10px;
  margin-top: 5px;
  width: 10px;
}

.event-main {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.event-action {
  font-weight: 800;
  margin: 0;
}

.event-target {
  color: #475569;
  margin: 3px 0 0;
}

.event-main time {
  color: #64748b;
  font-size: 0.84rem;
  text-align: right;
}

.event-meta {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 10px;
}

.event-meta dt {
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 700;
  margin-bottom: 4px;
  text-transform: uppercase;
}

.event-meta dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.state-details {
  margin-top: 10px;
}

.state-details summary {
  color: #1d4ed8;
  cursor: pointer;
  font-weight: 700;
}

.state-details pre {
  background: #0f172a;
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 0.78rem;
  max-height: 260px;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
}

@media (max-width: 980px) {
  .event-main {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }

  .event-main time {
    text-align: left;
  }

  .event-meta {
    grid-template-columns: 1fr;
  }
}
</style>
