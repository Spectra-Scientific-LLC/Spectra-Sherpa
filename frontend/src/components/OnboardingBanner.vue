<template>
  <div v-if="showOnboarding" class="onboarding-banner">
    <div class="banner-header">
      <div class="banner-title">
        <i class="pi pi-sparkles banner-icon"></i>
        <h3>Welcome to SpectraSherpa</h3>
      </div>
      <Button
        icon="pi pi-times"
        class="p-button-text p-button-sm p-button-rounded"
        @click="dismissOnboarding"
        aria-label="Dismiss"
      />
    </div>
    <p class="banner-subtitle">Get started in 3 steps:</p>
    <div class="steps">
      <div class="step" :class="{ completed: state?.steps.hasProject }">
        <i :class="state?.steps.hasProject ? 'pi pi-check-circle' : 'pi pi-circle'" class="step-icon"></i>
        <div class="step-content">
          <strong>1. Create a Project</strong>
          <p>Organize your analysis work</p>
        </div>
      </div>
      <div class="step" :class="{ completed: state?.steps.hasData }">
        <i :class="state?.steps.hasData ? 'pi pi-check-circle' : 'pi pi-circle'" class="step-icon"></i>
        <div class="step-content">
          <strong>2. Load Data</strong>
          <p>Import spectral data files or use demo datasets</p>
        </div>
      </div>
      <div class="step" :class="{ completed: state?.steps.hasWorkflow }">
        <i :class="state?.steps.hasWorkflow ? 'pi pi-check-circle' : 'pi pi-circle'" class="step-icon"></i>
        <div class="step-content">
          <strong>3. Start From a Project Template</strong>
          <p>Open Project to launch a validated workflow template or build your own pipeline</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import Button from "primevue/button";
import { useOnboarding } from "@/composables/useOnboarding";

const { state, showOnboarding, fetchOnboardingState, dismissOnboarding } = useOnboarding();

onMounted(() => {
  fetchOnboardingState();
});
</script>

<style scoped>
.onboarding-banner {
  background: var(--surface-card);
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}

.banner-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.banner-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.banner-title h3 {
  margin: 0;
  font-size: 1.1rem;
}

.banner-icon {
  color: var(--primary-color);
  font-size: 1.2rem;
}

.banner-subtitle {
  margin: 0 0 0.75rem 0;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}

.steps {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.step {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  background: var(--surface-ground);
  transition: opacity 0.2s;
}

.step.completed {
  opacity: 0.6;
}

.step-icon {
  font-size: 1.1rem;
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.step.completed .step-icon {
  color: var(--green-500);
}

.step-content strong {
  font-size: 0.95rem;
}

.step-content p {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}
</style>
