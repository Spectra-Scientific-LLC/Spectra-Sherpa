<template>
  <main class="prototype">
    <p class="eyebrow">v0.6.5 · Recorded OES coverage · Review</p>
    <h1>Active Dataset</h1>
    <p>Choose wafer numbers within each recorded step. Breaks are excluded. Preview uses original acquisitions, without averaging.</p>
    <p v-if="loading" role="status">Loading retained process alignment…</p><p v-if="error" role="alert">{{ error }}</p>
    <div class="legend"><span class="bosch">BOSCH production</span><span class="clean">Other recorded plasma · protocol identity unconfirmed</span></div>
    <div class="matrix" @scroll="hover?.hide()"><table>
      <thead><tr><th>Day</th><th>Preparation</th><th>Conditioning</th><th v-for="column in columns" :key="column.id">{{ column.label }}</th></tr></thead>
      <tbody><tr v-for="entry in entries" :key="entry.file.id">
        <th>{{ entry.catalog.date }}<small>{{ entry.file.file_path.split('/').pop() }}</small></th>
        <td v-for="stage in ['Preparation', 'Conditioning']" :key="stage"><span class="unavailable" :title="`${stage}: no identified source interval in these wafer recordings`">No identified interval</span></td>
        <td v-for="column in columns" :key="column.id">
          <section v-if="available(entry, column).length" class="step-box" :class="[column.id === 'production' ? 'bosch' : 'clean', { selected: available(entry, column).some(w => chosen.has(key(entry, w, column))) }]">
            <strong>{{ column.recipe }}</strong><small>{{ column.note }}</small>
            <div class="wafers"><button v-for="wafer in available(entry, column)" :key="wafer.asset_id"
              :aria-label="`${entry.catalog.date}, ${column.label}, ${wafer.asset_id}`" :aria-pressed="chosen.has(key(entry, wafer, column))"
              :class="{ picked: chosen.has(key(entry, wafer, column)) }" @click="toggle(entry, wafer, column)"
              @mouseenter="show(entry, wafer, column, $event)" @mousemove="show(entry, wafer, column, $event, true)" @mouseleave="hover?.hidePointer()"
              @focus="show(entry, wafer, column, $event)" @blur="hover?.hide()">{{ wafer.asset_id.replace('Wafer_', '') }}</button></div>
          </section><span v-else>Not recorded</span>
        </td>
      </tr></tbody>
    </table></div>
    <p>Preparation, conditioning and EPD-controlled cleaning are not identified in these recordings. Short Gas1-only and mixed-gas intervals are selectable, without assigning an unsupported cleaning label.</p>
    <details><summary>Coverage and alignment evidence</summary><p>Daily files contain wafer groups. The inspected August 5 and 7 recordings span approximately 638–660 seconds per wafer. A roughly nine-second Gas1-only plasma follows production, including the final wafer. Its EPD status and chemical identity are unconfirmed.</p>
      <p v-for="entry in entries" :key="entry.file.id">{{ entry.catalog.date }}: {{ entry.catalog.warnings.join(' ') }}</p>
      <p v-for="refusal in refusals" :key="refusal">{{ refusal }}</p>
    </details>
    <div class="selection"><strong>{{ chosen.size }} independent wafer / step selections</strong><button :disabled="!chosen.size || plotting || chosen.size > 50" @click="compare">Preview selected spectra</button><small>Up to 50 selections. Production previews retain etch and passivation separately.</small></div>
    <SelectedSpectraPlotPanel :plot-datasets="sources" :plot-dataset-count="sources.length ? 1 : 0" :plot-file-count="sources[0]?.selectedFileCount ?? 0" :plot-datasets-loading="plotting" :plot-datasets-error="plotError" :minimum-trace-count="sources.reduce((n, s) => n + s.members.length, 0)" />
    <section class="branch"><h2>Save an immutable portfolio</h2>
      <label>Name <input v-model="portfolioName" placeholder="Production etch across days" /></label>
      <button :disabled="!chosen.size || !portfolioName.trim() || saving" @click="savePortfolio">Save selected steps</button>
      <p v-if="saveError" role="alert">{{ saveError }}</p>
      <p v-if="saveStatus" role="status">{{ saveStatus }}</p>
      <label v-for="portfolio in portfolios" :key="portfolio.id"><input v-model="workflowPortfolios" type="checkbox" :value="portfolio.id" />{{ portfolio.name }} · {{ portfolio.selection.partitions.length }} wafer / step partitions</label>
    </section>
    <section class="branch"><h2>Create workflow</h2><p>Load Dataset → Average → Smooth → Normalize (optional) → Find peaks → Combine columns → CSV</p>
      <label>Average node mode <select v-model="mode"><option value="step">Whole step</option><option value="phase_across_cycles">Phase across cycles</option><option value="cycle_phase">Per-cycle phase</option></select></label>
      <label><input v-model="normalizeBranch" type="checkbox" /> Normalize each averaged spectrum</label>
      <label>Reference peak positions (nm, comma separated)<input v-model="peakReferences" placeholder="Enter shared peak positions" /></label>
      <label>Matching tolerance (nm)<input v-model.number="peakTolerance" type="number" min="0" step="0.1" /></label>
      <button :disabled="!workflowPortfolios.length || !peakReferences.trim() || creatingWorkflow" @click="createWorkflow">Create independent branches</button>
      <p v-if="workflowError" role="alert">{{ workflowError }}</p>
      <a v-if="workflowId" :href="`/workflow?project_id=${projectId}&workflow_id=${workflowId}`">Open saved workflow {{ workflowId }}</a>
      <p>Each checked portfolio gets an independent Load → Average → Smooth branch. Parameters start shared and remain editable per branch. Missing detected peaks export as blank cells.</p>
    </section><PlateWellHoverCard ref="hover" />
  </main>
</template>
<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { useRoute } from 'vue-router';
import api from '@/api/client';
import type { components } from '@/types/api/v1';
import type { DatasetPlotSource, SherpaDatasetDict } from '@/types';
import { getErrorMessage } from '@/utils/errors';
import PlateWellHoverCard from '@/components/PlateWellHoverCard.vue';
import SelectedSpectraPlotPanel from './SelectedSpectraPlotPanel.vue';
type Catalog = components['schemas']['BoschStepsOut'];
type Wafer = Catalog['wafers'][number];
type Entry = { file: components['schemas']['ExperimentFileOut']; catalog: Catalog };
const columns = [
  { id: 'mixed', label: 'Mixed-gas plasma', recipe: 'Mixed flow', note: 'Brief interval · unassigned protocol step', phases: ['mixed_plasma'] },
  { id: 'production', label: 'Production etch', recipe: 'BOSCH', note: 'SF₆ ⇄ C₄F₈ · repeated phases', phases: ['etch', 'passivation'] },
  { id: 'gas1', label: 'Post-production plasma', recipe: 'Gas1 only', note: 'O₂ tentative · EPD not established', phases: ['gas1_plasma'] },
];
type Column = typeof columns[number];
const experimentId = Number(useRoute().query.experimentId || 4);
const projectId = Number(useRoute().query.project_id || 6);
type Portfolio = components['schemas']['PortfolioOut'];
const portfolioName = ref(''), portfolios = ref<Portfolio[]>([]), saving = ref(false), saveError = ref<string|null>(null), saveStatus = ref('');
const workflowPortfolios = ref<number[]>([]), peakReferences = ref(''), peakTolerance = ref(0.5), normalizeBranch = ref(false);
const creatingWorkflow = ref(false), workflowError = ref<string|null>(null), workflowId = ref<number|null>(null);
async function savePortfolio() {
 saving.value=true;saveError.value=null;saveStatus.value='';
 try {
  const selections = entries.value.flatMap(entry => columns.flatMap(column => available(entry,column).filter(wafer => chosen.value.has(key(entry,wafer,column))).map(wafer => ({ experiment_id: experimentId,file_id:entry.file.id,process_file_id:entry.catalog.process_file_id!,asset_id:wafer.asset_id,step_id:column.id as 'production'|'gas1'|'mixed' }))));
  const response=await api.post<Portfolio>(`/projects/${projectId}/time-series-portfolios`,{name:portfolioName.value,selections},{signal:controller.signal});
  portfolios.value.push(response.data);saveStatus.value=`Saved ${response.data.name}. Its source selection is immutable.`;portfolioName.value='';
 } catch(e) {saveError.value=getErrorMessage(e,'Portfolio could not be saved');} finally {saving.value=false;}
}
async function createWorkflow() {
 creatingWorkflow.value=true;workflowError.value=null;
 try {
  const positions=peakReferences.value.split(',').map(x=>x.trim());
  if(positions.some(x=>!x || !Number.isFinite(Number(x))) || !Number.isFinite(peakTolerance.value) || peakTolerance.value<0) throw new Error('Enter finite peak positions and a nonnegative tolerance');
  const nodes: components['schemas']['WorkflowNodeCreate'][]=[];
  const edges: components['schemas']['WorkflowEdgeCreate'][]=[];
  const connect=(from:string,to:string,port='default')=>edges.push({from_node_id:from,to_node_id:to,from_output:port,to_input:'default'});
  for(const [index,portfolio] of portfolios.value.filter(p=>workflowPortfolios.value.includes(p.id)).entries()) {
   const prefix=`portfolio_${portfolio.id}`;
   const pin={project_id:projectId,portfolio_id:portfolio.id,selection_sha256:portfolio.selection_sha256};
   const sequence=[{id:'load',type:'data.portfolio_load',parameters:pin},
    {id:'average',type:'preprocess.portfolio_average',parameters:{...pin,mode:mode.value,transition_trim_seconds:0}},
    {id:'smooth',type:'preprocess.smooth',parameters:{method:'savitzky_golay',size:7,order:2}},
    ...(normalizeBranch.value ? [{id:'normalize',type:'preprocess.normalize',parameters:{}}] : []),
    {id:'peaks',type:'analysis.partitioned_peaks',parameters:{consensus_tolerance:peakTolerance.value,reference_positions:positions,matching_tolerance:peakTolerance.value}}];
   for(const [j,n] of sequence.entries()) {nodes.push({node_id:`${prefix}_${n.id}`,node_type:n.type,label:`${portfolio.name} · ${n.id}`,parameters:n.parameters,position_x:j*220,position_y:index*200});if(j)connect(`${prefix}_${sequence[j-1].id}`,`${prefix}_${n.id}`);}
   connect(`${prefix}_peaks`,'wide','per_spectrum');
  }
  nodes.push({node_id:'wide',node_type:'data.wide_peak_table',parameters:{reference_positions:positions,tolerance:peakTolerance.value},position_x:1200,position_y:0},
             {node_id:'csv',node_type:'output.peak_csv',parameters:{filename:'peak-intensities.csv'},position_x:1420,position_y:0});connect('wide','csv');
  const response=await api.post<components['schemas']['WorkflowDetail']>('/workflows',{name:'OES peak extraction',project_id:projectId,nodes,edges},{signal:controller.signal});workflowId.value=response.data.id;
 }catch(e){workflowError.value=getErrorMessage(e,'Workflow could not be created');}finally{creatingWorkflow.value=false;}
}
const entries = ref<Entry[]>([]), chosen = ref(new Set<string>()), mode = ref('step');
const loading = ref(true), error = ref<string | null>(null), plotting = ref(false), plotError = ref<string | null>(null);
const sources = ref<DatasetPlotSource[]>([]);
const hover = ref<InstanceType<typeof PlateWellHoverCard> | null>(null);
const controller = new AbortController();
onBeforeUnmount(() => controller.abort());
const steps = (wafer: Wafer, column: Column) => wafer.steps.filter(s => column.phases.includes(s.step_id));
const available = (entry: Entry, column: Column) => entry.catalog.wafers.filter(w => !w.refusal && steps(w, column).length);
const key = (entry: Entry, wafer: Wafer, column: Column) => `${entry.file.id}/${wafer.asset_id}/${column.id}`;
const refusals = computed(() => entries.value.flatMap(e => e.catalog.wafers.filter(w => w.refusal).map(w => `${e.catalog.date} ${w.asset_id}: ${w.refusal}`)));
function toggle(entry: Entry, wafer: Wafer, column: Column) { const id = key(entry, wafer, column); const next = new Set(chosen.value); if (next.has(id)) next.delete(id); else next.add(id); chosen.value = next; sources.value = []; }
onMounted(async () => {
  try {
    portfolios.value=(await api.get<Portfolio[]>(`/projects/${projectId}/time-series-portfolios`,{signal:controller.signal})).data;
    const files = (await api.get<components['schemas']['ExperimentFileOut'][]>(`/experiments/${experimentId}/files`, { signal: controller.signal })).data;
    for (const file of files.filter(f => /Day_\d{4}_\d{2}_\d{2}.*\.nc$/i.test(f.file_path))) {
      const catalog = (await api.get<Catalog>(`/experiments/${experimentId}/files/${file.id}/bosch-steps`, { signal: controller.signal })).data;
      entries.value.push({ file, catalog });
    }
  } catch (e) { if (!controller.signal.aborted) error.value = getErrorMessage(e, 'Coverage could not be loaded'); }
  finally { loading.value = false; }
});
function show(entry: Entry, wafer: Wafer, column: Column, event: MouseEvent | FocusEvent, moved = false) {
 const intervals = steps(wafer, column).flatMap(s => s.intervals).sort((a,b) => a.first_acquisition-b.first_acquisition);
 hover.value?.show({ well_position: entry.catalog.date, label: `${wafer.asset_id} · ${column.label}`, details: [
  { label: 'Recipe / assignment', value: column.note },
  { label: 'UTC start / end', value: `${new Date(intervals[0].start_time*1000).toISOString()} / ${new Date(intervals[intervals.length-1].end_time*1000).toISOString()}` },
  { label: 'Acquisitions', value: intervals.slice(0,8).map(i => `${i.first_acquisition}–${i.last_acquisition}`).join(', ') + (intervals.length > 8 ? ` … (${intervals.length} separate intervals)` : '') },
  { label: 'Observation count', value: String(steps(wafer,column).reduce((n,s) => n+s.acquisition_count,0)) },
  { label: 'Cycle identity', value: 'Not retained in this alignment version; interval count is not a cycle count' },
  { label: 'Clock fit / boundary uncertainty', value: `${Number(wafer.alignment?.correlation).toFixed(3)} / ±${Number(wafer.alignment?.boundary_uncertainty_s).toFixed(2)} s` },
  { label: 'Source', value: entry.file.file_path },
  { label: 'Source SHA-256', value: entry.catalog.source_sha256 },
 ] }, event, moved);
}
async function compare() {
 plotting.value=true; plotError.value=null; sources.value=[];
 const selected = new Set(chosen.value); const members: DatasetPlotSource['members']=[]; const files=new Set<number>();
 try {
  for (const entry of entries.value) for (const column of columns) for (const wafer of available(entry,column)) {
   if (!selected.has(key(entry,wafer,column))) continue;
   for (const step of steps(wafer,column)) {
    const response = await api.post<components['schemas']['BoschStepPreviewOut']>(`/experiments/${experimentId}/files/${entry.file.id}/bosch-step-preview`, { process_file_id: entry.catalog.process_file_id, asset_id: wafer.asset_id, step_id: step.step_id, source_sha256: entry.catalog.source_sha256, process_sha256: entry.catalog.process_sha256, max_rows: 4 }, { signal: controller.signal });
    members.push({ curveGroupLabel: `${entry.catalog.date} · ${wafer.asset_id} · ${step.label}`, fileId: entry.file.id, fileName: entry.file.file_path, dataset: response.data.dataset as unknown as SherpaDatasetDict }); files.add(entry.file.id);
   }
  }
  if ([...selected].join() === [...chosen.value].join()) sources.value=[{ experimentId, name: 'Selected recorded steps', members, selectedFileCount: files.size, totalFileCount: entries.value.length }];
 } catch(e) { if (!controller.signal.aborted) plotError.value=getErrorMessage(e,'Preview could not be loaded'); }
 finally { plotting.value=false; }
}
</script>
<style scoped>
.prototype { min-width: 0; width: 100%; box-sizing: border-box; overflow-x: hidden; padding: 2rem; color: var(--ss-text); max-width: 1250px; margin: auto; }
.eyebrow,.footnote { color: var(--ss-text-muted); font-size: .85rem; }
h1 { margin: .5rem 0; } small { display: block; font-weight: normal; margin-top: .4rem; }
.legend,.selection { display: flex; gap: 1.5rem; align-items: center; margin: 1.5rem 0; flex-wrap: wrap; }
.legend span { padding: .5rem; border-radius: 8px; }
.matrix { overflow: auto; padding: 1rem; border: 1px solid var(--ss-border-strong); border-radius: 12px; background: var(--ss-surface); }
table { width: 100%; border-spacing: 18px; } th { text-align: left; } td { text-align: center; }
.step-box { border: 2px solid var(--ss-border-strong); border-radius: 8px; padding: 1rem; min-width: 220px; transition: transform .15s; }
.step-box:hover,.step-box:focus-visible { border-color: var(--ss-action); outline: 2px solid var(--ss-action-tint); }
.step-box.selected { transform: scale(1.025); border-color: var(--ss-action); box-shadow: 0 0 0 3px var(--ss-action-tint); }
.bosch { background: var(--ss-info-surface); color: var(--ss-info-strong); }.clean { background: var(--ss-success-surface); color: var(--ss-success-strong); }
.wafers { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin: .8rem 0; }
button,input,select { padding: .55rem; border: 1px solid var(--ss-border-strong); border-radius: 6px; background: var(--ss-surface); color: var(--ss-text); }
button { cursor: pointer; } button.picked { background: var(--ss-action); color: var(--ss-surface); } button:disabled { opacity: .5; cursor: default; }
.unavailable { color: var(--ss-text-muted); } .branch { padding: 1.4rem; background: var(--ss-surface-subtle); border-radius: 12px; } label { display: flex; gap: .8rem; align-items: center; }
</style>
