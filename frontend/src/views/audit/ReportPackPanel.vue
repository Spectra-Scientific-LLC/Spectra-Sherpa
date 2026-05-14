<template>
  <div v-if="lastPack" class="manifest-panel">
    <div class="manifest-head">
      <div>
        <p class="eyebrow">Latest Pack</p>
        <h2>{{ shortId(lastPack.packId) }}</h2>
      </div>
      <span :class="['verify-badge', { ok: lastPack.verificationOk }]">
        {{ lastPack.verificationOk ? "Verified" : "Blocked" }}
      </span>
    </div>

    <dl class="metrics">
      <div>
        <dt>Rows</dt>
        <dd>{{ lastPack.rowCount }}</dd>
      </div>
      <div>
        <dt>Files</dt>
        <dd>{{ lastPack.fileCount }}</dd>
      </div>
      <div>
        <dt>SHA-256</dt>
        <dd>{{ shortId(lastPack.sha256, 12) }}</dd>
      </div>
    </dl>
  </div>

  <div v-else class="empty-panel">
    <p class="eyebrow">Report Pack</p>
    <p>Generate a pack to download manifest, evidence rows, verification proof, and validation templates.</p>
  </div>
</template>

<script setup lang="ts">
import { shortId } from "./auditFormatters";
import type { LastPack } from "./types";

defineProps<{
  lastPack: LastPack | null;
}>();
</script>

<style scoped>
.manifest-panel,
.empty-panel {
  color: #475569;
}

.manifest-head {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.manifest-head h2 {
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

.verify-badge {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 6px 10px;
}

.verify-badge.ok {
  background: #dcfce7;
  border-color: #86efac;
  color: #166534;
}

.metrics {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 16px 0 0;
}

.metrics div {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
}

.metrics dt {
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 700;
  margin-bottom: 4px;
  text-transform: uppercase;
}

.metrics dd {
  font-size: 1rem;
  font-weight: 800;
  margin: 0;
  overflow-wrap: anywhere;
}

.empty-panel {
  line-height: 1.5;
}

@media (max-width: 980px) {
  .metrics {
    grid-template-columns: 1fr;
  }
}
</style>
