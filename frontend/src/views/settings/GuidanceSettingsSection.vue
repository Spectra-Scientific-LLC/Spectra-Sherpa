<template>
  <section class="guidance-settings">
    <div class="section-header">
      <div>
        <h3>Guidance</h3>
      </div>
    </div>

    <label class="setting-row">
      <input
        type="checkbox"
        :checked="guidance.settings.guidance_enabled"
        :disabled="guidance.loading"
        @change="toggle('guidance_enabled', $event)"
      />
      <span>
        <strong>Show contextual suggestions</strong>
      </span>
    </label>

    <label class="setting-row child">
      <input
        type="checkbox"
        :checked="guidance.settings.toast_enabled"
        :disabled="guidance.loading || !guidance.settings.guidance_enabled"
        @change="toggle('toast_enabled', $event)"
      />
      <span>
        <strong>Toast notifications</strong>
      </span>
    </label>

    <label class="setting-row child">
      <input
        type="checkbox"
        :checked="guidance.settings.glow_enabled"
        :disabled="guidance.loading || !guidance.settings.guidance_enabled"
        @change="toggle('glow_enabled', $event)"
      />
      <span>
        <strong>Button highlights</strong>
      </span>
    </label>

    <p v-if="guidance.error" class="error-message">{{ guidance.error }}</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import { useGuidanceStore } from "@/stores/guidance";
import type { GuidanceSettingsPatch } from "@/lib/guidanceAdapter";

const guidance = useGuidanceStore();

onMounted(() => {
  void guidance.loadSettings();
});

function toggle(key: keyof GuidanceSettingsPatch, event: Event): void {
  const target = event.target as HTMLInputElement | null;
  if (!target) return;
  void guidance.updateSettings({ [key]: target.checked });
}
</script>

<style scoped>
.guidance-settings {
  display: grid;
  gap: 16px;
  color: var(--text-color);
}

.section-header h3 {
  margin: 0 0 4px;
  font-size: 1rem;
  font-weight: 500;
  color: var(--text-color);
}

.section-header p {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.setting-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-ground);
}

.setting-row.child {
  margin-left: 24px;
}

.setting-row input {
  margin-top: 3px;
}

.setting-row span {
  display: grid;
  gap: 4px;
}

.setting-row small {
  color: var(--text-color-secondary);
  font-size: 13px;
}

.error-message {
  margin: 0;
  color: var(--ss-danger);
  font-size: 14px;
}
</style>
