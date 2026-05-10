<template>
  <section class="guidance-settings">
    <div class="section-header">
      <div>
        <h3>Guidance</h3>
        <p>Contextual suggestions are based on action-keyed activity in this app.</p>
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
        <small>Disable this to stop toasts and future highlights.</small>
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
        <small>Show concise next-step suggestions outside the Advisor chat.</small>
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
        <small>Reserved for a later release; this setting is saved now.</small>
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
}

.section-header h3 {
  margin: 0 0 4px;
  font-size: 18px;
}

.section-header p {
  margin: 0;
  color: #64748b;
  font-size: 14px;
}

.setting-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
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
  color: #64748b;
  font-size: 13px;
}

.error-message {
  margin: 0;
  color: #b91c1c;
  font-size: 14px;
}
</style>
