<template>
  <Dialog :visible="true" modal header="Portfolio workflow" :style="{width:'32rem'}" @update:visible="emit('close')">
    <p>{{ portfolio.name }}</p>
    <label for="portfolio-average">Average</label>
    <select id="portfolio-average" v-model="mode">
      <option value="step">By step, independently per day and wafer</option>
      <option value="phase_across_cycles">By phase across cycles, per day and wafer</option>
      <option value="cycle_phase">By phase within each cycle</option>
    </select>
    <label for="portfolio-statistic">Statistic</label>
    <select id="portfolio-statistic" v-model="statistic"><option value="median">Median by wavelength</option><option value="mean">Mean by wavelength</option></select>
    <label for="portfolio-peaks">Reference peaks (nm)</label>
    <InputText id="portfolio-peaks" v-model="positions" placeholder="Comma-separated positions" />
    <p title="All parameters remain editable in Workflow. No averaging across wafers. Zero additional transition trim. Missing detected peaks export as blank cells.">
      Load → Average → Smooth → Normalize → Peaks → Combine → CSV
    </p>
    <small>Savitzky–Golay (7 points, order 2), SNV, peak matching ±0.5 nm. Review parameters before running.</small>
    <p v-if="error" role="alert">{{ error }}</p>
    <template #footer><Button label="Open workflow" :loading="busy" :disabled="busy || !positions.trim()" @click="create" /></template>
  </Dialog>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { useRouter } from "vue-router";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import api from "@/api/client";
import type { components } from "@/types/api/v1";
import { portfolioWorkflow, type AveragingMode } from "@/utils/portfolioWorkflow";
import { getErrorMessage } from "@/utils/errors";
const props = defineProps<{portfolio: components['schemas']['PortfolioOut']}>();
const emit = defineEmits<{close: []}>();
const router = useRouter();
const statistic = ref<'mean' | 'median'>('median');
const mode = ref<AveragingMode>('step'), positions = ref(''), busy = ref(false), error = ref('');
const controller = new AbortController();
onBeforeUnmount(() => controller.abort());
async function create() {
  if (busy.value) return;
  busy.value = true; error.value = '';
  try {
    const pieces = positions.value.split(',').map(x => x.trim());
    if (pieces.some(x => !x)) throw new Error('Enter comma-separated reference peak positions.');
    const body = portfolioWorkflow(props.portfolio, mode.value, pieces.map(Number), statistic.value);
    const result = await api.post<components['schemas']['WorkflowDetail']>('/workflows', body, {signal: controller.signal});
    if (!controller.signal.aborted) await router.push({path:'/workflow',query:{project_id:props.portfolio.project_id,workflow_id:result.data.id}});
  } catch (e) { if (!controller.signal.aborted) error.value = getErrorMessage(e,'Workflow could not be created.'); }
  finally { busy.value = false; }
}
</script>
<style scoped>
label { display: block; margin: 1rem 0 .4rem; }
select { width: 100%; padding: .5rem; background: var(--ss-surface); color: var(--ss-text); border: 1px solid var(--ss-border-strong); }
small { color: var(--ss-text-muted); }
</style>
