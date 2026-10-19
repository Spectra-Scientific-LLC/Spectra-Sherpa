<template>
  <section class="display-preferences" aria-label="Display defaults">
<h3>Display defaults <MethodHelp topic="displayExports" label="Display and export scope" /></h3>
    <div class="preference-grid">
      <label>Maximum rows in plots and tables
        <select v-model.number="prefs.maxRows" aria-label="Maximum display rows">
          <option v-for="count in [100, 300, 500, 1000, 3000]" :key="count" :value="count">{{ count }}</option>
        </select>
      </label>
      <label>Numbers
        <select v-model="prefs.precision" aria-label="Display precision">
          <option value="full">Full precision</option>
          <option value="3">3 significant digits</option>
          <option value="6">6 significant digits</option>
          <option value="9">9 significant digits</option>
        </select>
      </label>
      <label>Palette
        <select v-model="prefs.palette" aria-label="Plot palette">
          <option value="default">Default</option>
          <option value="colorblind">Colorblind-friendly</option>
          <option value="high-contrast">High contrast</option>
        </select>
      </label>
      <label>Lines
        <select v-model.number="prefs.lineScale" aria-label="Line weight">
          <option :value="0.75">Fine</option>
          <option :value="1">Standard</option>
          <option :value="1.5">Bold</option>
        </select>
      </label>
      <label>Points
        <select v-model.number="prefs.markerScale" aria-label="Point size">
          <option :value="0.75">Small</option>
          <option :value="1">Standard</option>
          <option :value="1.5">Large</option>
        </select>
      </label>
      <label>Tables
        <select v-model="prefs.tableDensity" aria-label="Table density">
          <option value="comfortable">Comfortable</option>
          <option value="compact">Compact</option>
        </select>
      </label>
    </div>
  </section>
</template>

<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import { useDisplayPreferences } from "@/composables/useDisplayPreferences";
const prefs = useDisplayPreferences();
</script>

<style scoped>
.display-preferences { padding: 1rem; border: 1px solid var(--surface-border, #dbe3eb); border-radius: .75rem; }
.display-preferences h3 { margin: 0 0 .25rem; }
.display-preferences p { margin: 0 0 1rem; color: var(--text-color-secondary, #64748b); }
.preference-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: .75rem; }
.preference-grid label { display: grid; gap: .3rem; font-weight: 600; }
.preference-grid select { min-height: 2.25rem; padding: .35rem; border: 1px solid var(--surface-border, #cbd5e1); border-radius: .35rem; background: var(--surface-card, white); color: var(--text-color, #334155); }
</style>
