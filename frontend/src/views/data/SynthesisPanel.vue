<template>
  <div class="synthesis-panel">
    <div class="synthesis-toolbar">
      <div>
        <h3>FTIR Synthesis</h3>
        <p>Build source-locked Beer-Lambert mixtures and save them as My Dataset entries.</p>
      </div>
      <Button
        label="Guide"
        icon="pi pi-book"
        class="p-button-sm p-button-outlined"
        data-action="synthesis_open_guide"
        @click="openGuide"
      />
    </div>

    <Panel header="Source & Settings" toggleable>
      <div class="synthesis-grid synthesis-grid--source">
        <div class="field">
          <label for="synth-source">Database</label>
          <Dropdown
            inputId="synth-source"
            v-model="settings.source"
            :options="sourceOptions"
            optionLabel="label"
            optionValue="id"
            @change="onSourceChange"
          />
        </div>
        <div class="field">
          <label for="synth-resolution">Resolution</label>
          <Dropdown
            inputId="synth-resolution"
            v-model="settings.resolution_cm1"
            :options="resolutionOptions"
            optionLabel="label"
            optionValue="value"
            @change="onSourceOrGridChange"
          />
        </div>
        <div class="field" v-if="settings.source === 'nist_quant_ir'">
          <label for="synth-apodization">Apodization</label>
          <Dropdown
            inputId="synth-apodization"
            v-model="settings.apodization"
            :options="apodizationOptions"
            optionLabel="label"
            optionValue="value"
            @change="onSourceOrGridChange"
          />
        </div>
        <div class="field" v-if="settings.source === 'hitran'">
          <label for="synth-wmin">Min cm^-1</label>
          <InputNumber
            inputId="synth-wmin"
            v-model="settings.wavenumber_min"
            :min="1"
            :useGrouping="false"
            @input="onSourceOrGridChange"
          />
        </div>
        <div class="field" v-if="settings.source === 'hitran'">
          <label for="synth-wmax">Max cm^-1</label>
          <InputNumber
            inputId="synth-wmax"
            v-model="settings.wavenumber_max"
            :min="2"
            :useGrouping="false"
            @input="onSourceOrGridChange"
          />
        </div>
        <div class="field" v-if="settings.source === 'hitran'">
          <label for="synth-temperature">Temperature (K)</label>
          <InputNumber
            inputId="synth-temperature"
            v-model="settings.temperature_k"
            :min="50"
            :max="5000"
            :maxFractionDigits="2"
            :useGrouping="false"
            @input="onSourceOrGridChange"
          />
        </div>
        <div class="field" v-if="settings.source === 'hitran'">
          <label for="synth-pressure">Pressure (atm)</label>
          <InputNumber
            inputId="synth-pressure"
            v-model="settings.pressure_atm"
            :min="0.000001"
            :maxFractionDigits="6"
            :useGrouping="false"
            @input="onSourceOrGridChange"
          />
        </div>
      </div>
      <div class="synthesis-grid synthesis-grid--generation">
        <div class="field">
          <label for="synth-samples">Samples</label>
          <InputNumber
            inputId="synth-samples"
            v-model="settings.n_samples"
            :min="2"
            :max="1000"
            :useGrouping="false"
            @input="invalidatePreview"
          />
        </div>
        <div class="field">
          <label for="synth-pathlength">Path length (cm)</label>
          <InputNumber
            inputId="synth-pathlength"
            v-model="settings.pathlength_cm"
            :min="0.001"
            :maxFractionDigits="4"
            :useGrouping="false"
            @input="invalidatePreview"
          />
        </div>
        <div class="field">
          <label for="synth-noise">Noise sigma (AU)</label>
          <InputNumber
            inputId="synth-noise"
            v-model="settings.noise_sigma_au"
            :min="0"
            :maxFractionDigits="6"
            :useGrouping="false"
            @input="invalidatePreview"
          />
        </div>
        <div v-if="!isHitranLineByLine" class="field field--wide">
          <label for="synth-snaptol">Wavenumber snap tolerance (cm⁻¹)</label>
          <InputNumber
            inputId="synth-snaptol"
            v-model="settings.snap_tolerance_cm1"
            :min="0"
            :max="5"
            :maxFractionDigits="4"
            :useGrouping="false"
            @input="invalidatePreview"
          />
        </div>
      </div>
      <div class="synthesis-note" :class="{ warn: isHitranSource(settings.source) && !hitranAvailable }">
        <i class="pi pi-info-circle" />
        <span>{{ sourceStatusText }}</span>
      </div>
      <div v-if="persistenceWarning" class="synthesis-note warn">
        <i class="pi pi-exclamation-triangle" />
        <span>{{ persistenceWarning }}</span>
      </div>
    </Panel>

    <Panel header="Components" toggleable>
      <div class="search-row">
        <InputText
          v-model="searchQuery"
          placeholder="Search by name, CAS, formula, or molecule number"
          class="synthesis-search"
          data-action="synthesis_search_components"
        />
      </div>
      <div class="search-summary">
        <span>{{ searchResultSummary }}</span>
      </div>

      <div class="compound-results" role="region" aria-label="Synthesis compound results">
        <table class="compound-results-table">
          <thead>
            <tr>
              <th>
                <button type="button" class="compound-sort" @click="setCompoundSort('name')">
                  Compound <span>{{ sortIndicator("name") }}</span>
                </button>
              </th>
              <th>
                <button type="button" class="compound-sort" @click="setCompoundSort('formula')">
                  Formula <span>{{ sortIndicator("formula") }}</span>
                </button>
              </th>
              <th>
                <button type="button" class="compound-sort" @click="setCompoundSort('cas')">
                  CAS <span>{{ sortIndicator("cas") }}</span>
                </button>
              </th>
              <th>Variant</th>
              <th class="compound-action-col"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="searching && !searchResults.length">
              <td colspan="5" class="compound-empty">Searching...</td>
            </tr>
            <tr v-else-if="!sortedSearchResults.length">
              <td colspan="5" class="compound-empty">No compounds found.</td>
            </tr>
            <tr v-for="component in sortedSearchResults" :key="component.id">
              <td>
                <strong>{{ component.name }}</strong>
              </td>
              <td>{{ component.formula || "—" }}</td>
              <td>{{ component.cas || "—" }}</td>
              <td>
                <select
                  v-if="settings.source === 'hitran_xsec'"
                  class="xsec-native-select"
                  :value="component.selected_xsec_option ?? 0"
                  @change="updateXsecOption(component, $event)"
                >
                  <option
                    v-for="option in hitranXsecOptionChoices(component)"
                    :key="option.value"
                    :value="option.value"
                  >
                    {{ option.label }}
                  </option>
                </select>
                <span v-else>{{ variantLabel(component) }}</span>
              </td>
              <td class="compound-action-col">
                <Button
                  label="Add"
                  icon="pi pi-plus"
                  class="p-button-sm p-button-text"
                  data-action="synthesis_add_component"
                  :disabled="isSelected(component.id)"
                  @click="addComponent(component)"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="selectedComponents.length" class="selected-components">
        <div
          v-for="component in selectedComponents"
          :key="component.id"
          class="selected-component"
        >
          <div>
            <strong>
              {{ component.name }}<sup
                v-if="shiftedById[component.id] != null"
                class="shift-asterisk"
                :title="`Wavenumbers shifted by ${shiftedById[component.id].toFixed(4)} cm⁻¹ onto the median grid. Spacing matches the other compounds, so the absorbance is carried over unchanged — scientifically sound.`"
              >*</sup>
            </strong>
            <small>{{ component.formula || component.cas || component.id }}</small>
            <small v-if="component.native_grid">
              Δ {{ component.native_grid.spacing.toFixed(4) }} cm⁻¹ ·
              {{ component.native_grid.min.toFixed(2) }}–{{ component.native_grid.max.toFixed(2) }}
              ({{ component.native_grid.n }} pts)
            </small>
          </div>
          <Tag :value="component.spectrum ? 'spectrum loaded' : 'manifest only'" :severity="component.spectrum ? 'success' : 'warning'" />
          <Button
            icon="pi pi-cloud-download"
            :label="spectrumLoadButtonLabel(component)"
            class="p-button-sm p-button-outlined"
            data-action="synthesis_load_spectrum"
            :loading="component.loading"
            :disabled="isSpectrumLoadQueued(component)"
            @click="loadSpectrum(component)"
          />
          <Button
            icon="pi pi-times"
            class="p-button-sm p-button-text p-button-danger"
            @click="removeComponent(component.id)"
          />
          <div
            v-if="component.loading && isHitranSource(settings.source)"
            class="spectrum-load-progress"
            aria-live="polite"
          >
            <ProgressBar
              :value="component.load_progress ?? 0"
              :showValue="false"
            />
            <span>{{ component.load_progress ?? 0 }}%</span>
            <small>{{ component.load_message || "Loading HITRAN spectrum" }}</small>
          </div>
        </div>
      </div>
      <p v-else class="empty-synthesis">Search for compounds and add at least one component.</p>
      <div v-if="spacingInconsistent" class="synthesis-note warn">
        <i class="pi pi-exclamation-triangle" />
        <span>
          Loaded compounds have <strong>different native point spacings</strong> (Δ cm⁻¹ above).
          Only a pure sub-wavenumber offset at equal spacing can be snapped onto the median grid;
          differing spacings will be rejected at Preview. Pick compounds with matching spacing or
          re-fetch at a common resolution.
        </span>
      </div>
      <div v-else-if="Object.keys(shiftedById).length" class="synthesis-note">
        <i class="pi pi-info-circle" />
        <span>
          Species marked <span class="shift-asterisk">*</span> were wavenumber-shifted onto the
          median grid (same spacing → absorbance unchanged, scientifically sound). Hover the
          asterisk for the exact shift.
        </span>
      </div>
    </Panel>

    <Panel header="Concentration Profiles" toggleable>
      <div v-if="selectedComponents.length" class="curve-list">
        <div
          v-for="(component, index) in selectedComponents"
          :key="`${component.id}-curve`"
          class="curve-editor"
        >
          <div class="curve-editor__meta">
            <div class="curve-editor-header">
              <strong>
                <span class="curve-swatch" :style="{ background: componentColor(index) }" />
                {{ component.name }}
              </strong>
            </div>
            <div class="curve-multiplier">
              <label :for="`mult-${component.id}`">Peak concentration</label>
              <InputNumber
                :id="`mult-${component.id}`"
                :modelValue="component.concentration_max_ppm"
                :min="0"
                :maxFractionDigits="4"
                :useGrouping="false"
                suffix=" ppm"
                @update:model-value="updateMultiplier(component, $event)"
              />
            </div>
            <div class="curve-point-count">
              <label :for="`points-${component.id}`">Points</label>
              <InputNumber
                :id="`points-${component.id}`"
                :modelValue="component.control_points.length"
                :min="4"
                :max="60"
                :useGrouping="false"
                showButtons
                buttonLayout="horizontal"
                incrementButtonIcon="pi pi-plus"
                decrementButtonIcon="pi pi-minus"
                @update:model-value="updatePointCount(component, $event)"
              />
            </div>
            <div class="curve-actions curve-actions--left">
              <Button
                label="Reset"
                icon="pi pi-refresh"
                class="p-button-sm p-button-text"
                @click="resetCurve(component)"
              />
              <Button
                label="Copy"
                icon="pi pi-copy"
                class="p-button-sm p-button-text"
                @click="copyCurve(component)"
              />
            </div>
            <small class="curve-editor__hint">
              Shape is normalized 0–1; peak ppm sets the physical scale used in synthesis.
            </small>
          </div>
          <div class="curve-editor__canvas">
            <ConcentrationCurveEditor
              :points="component.control_points"
              :color="componentColor(index)"
              :title="component.name"
              hide-toolbar
              hide-hint
              @update:points="updateControlPoints(component, $event)"
            />
          </div>
        </div>
      </div>
      <div class="concentration-preview-bar">
        <span>
          {{ normalizeComposition ? "Relative composition (per-sample fraction)" : "Resolved traces (shape × peak ppm)" }}
        </span>
        <div class="concentration-preview-actions">
          <Button
            :label="normalizeComposition ? 'Show ppm' : 'Show composition'"
            icon="pi pi-percentage"
            class="p-button-sm p-button-text"
            :disabled="!selectedComponents.length"
            @click="normalizeComposition = !normalizeComposition"
          />
          <Button
            :label="logConcentration ? 'Linear scale' : 'Log scale'"
            icon="pi pi-chart-line"
            class="p-button-sm p-button-text"
            :disabled="!selectedComponents.length || normalizeComposition"
            @click="logConcentration = !logConcentration"
          />
          <Button
            label="Save curves"
            icon="pi pi-download"
            class="p-button-sm p-button-text"
            :disabled="!selectedComponents.length"
            @click="saveAllCurves"
          />
          <Button
            label="Load curves"
            icon="pi pi-upload"
            class="p-button-sm p-button-text"
            :disabled="!selectedComponents.length"
            @click="curveFileInput?.click()"
          />
          <input
            ref="curveFileInput"
            type="file"
            accept="application/json,.json"
            class="hidden-file-input"
            @change="loadCurves"
          />
        </div>
      </div>
      <div v-if="invalidMultipliers.length" class="synthesis-note warn">
        <i class="pi pi-exclamation-triangle" />
        <span>
          Set a peak concentration above 0 ppm for:
          {{ invalidMultipliers.map((c) => c.name).join(", ") }}.
        </span>
      </div>
      <PlotlyChart
        :data="concentrationTraces"
        :layout="concentrationLayout"
        :config="plotConfig"
        emptyMessage="Add components to define concentration curves."
      />
    </Panel>

    <Panel header="Component Spectra Review" toggleable>
      <PlotlyChart
        :data="componentPreviewTraces"
        :layout="componentPreviewLayout"
        :config="plotConfig"
        emptyMessage="Load one or more component spectra to preview them."
      />
      <div class="synthesis-note">
        <i class="pi pi-chart-line" />
        <span>Review intensities are normalized 0-1 for visual comparison; synthesis uses the physical coefficients from the downloaded spectra.</span>
      </div>
    </Panel>

    <Panel header="Synthesis Review" toggleable>
      <div v-if="commonOverlapProblem" class="synthesis-note error output-size-note">
        <i class="pi pi-ban" />
        <span>
          Common overlap is empty. The latest starting spectrum is
          <strong>{{ commonOverlapProblem.latestStartName }}</strong>
          at {{ commonOverlapProblem.commonMin.toFixed(2) }} cm⁻¹, but the earliest ending spectrum is
          <strong>{{ commonOverlapProblem.earliestEndName }}</strong>
          at {{ commonOverlapProblem.commonMax.toFixed(2) }} cm⁻¹.
          Use widest range or remove one of those spectra.
        </span>
      </div>
      <div
        v-if="outputSizeEstimate"
        class="synthesis-note output-size-note"
        :class="{ warn: outputSizeEstimate.nearLimit, error: outputSizeEstimate.overLimit }"
      >
        <i :class="outputSizeIcon" />
        <span>
          Generated output:
          <strong>{{ formatInteger(outputSizeEstimate.nSamples) }} samples × {{ formatInteger(outputSizeEstimate.nFeatures) }} wavenumbers</strong>
          = {{ formatInteger(outputSizeEstimate.totalValues) }} values.
          <template v-if="outputSizeEstimate.overLimit">
            This exceeds the interactive limit of {{ formatInteger(outputSizeEstimate.limit) }} values; reduce samples,
            narrow the HITRAN range, increase resolution spacing, or use common overlap.
          </template>
          <template v-else-if="outputSizeEstimate.nearLimit">
            This is close to the interactive limit of {{ formatInteger(outputSizeEstimate.limit) }} values.
          </template>
        </span>
      </div>
      <div class="preview-actions preview-toolbar">
        <Button
          label="Preview"
          icon="pi pi-play"
          class="p-button-sm"
          data-action="synthesis_preview"
          :loading="previewing"
          :disabled="!canPreview"
          :title="previewDisabledReason"
          @click="previewSynthesis"
        />
        <div class="preview-range-mode">
          <label for="synthesis-range-mode">Range</label>
          <Dropdown
            inputId="synthesis-range-mode"
            v-model="settings.range_mode"
            :options="rangeModeOptions"
            optionLabel="label"
            optionValue="value"
            class="p-inputtext-sm"
            @change="invalidatePreview"
          />
          <label for="preview-wmin">Min</label>
          <InputNumber
            inputId="preview-wmin"
            v-model="settings.preview_wavenumber_min"
            :useGrouping="false"
            :maxFractionDigits="4"
            class="preview-range-input"
            @input="invalidatePreview"
          />
          <label for="preview-wmax">Max</label>
          <InputNumber
            inputId="preview-wmax"
            v-model="settings.preview_wavenumber_max"
            :useGrouping="false"
            :maxFractionDigits="4"
            class="preview-range-input"
            @input="invalidatePreview"
          />
          <template v-if="!isHitranLineByLine">
          <label for="preview-winterval">Interval</label>
          <InputNumber
            inputId="preview-winterval"
            v-model="settings.preview_wavenumber_interval_cm1"
            :min="0"
            :useGrouping="false"
            :maxFractionDigits="4"
            class="preview-range-input"
            @input="invalidatePreview"
          />
          </template>
        </div>
        <div class="preview-sampling">
          <label for="preview-start">Start sample</label>
          <InputNumber
            inputId="preview-start"
            v-model="previewStartSample"
            :min="0"
            :max="maxPreviewSample"
            :useGrouping="false"
            :disabled="!previewResult"
            showButtons
            buttonLayout="horizontal"
            incrementButtonIcon="pi pi-plus"
            decrementButtonIcon="pi pi-minus"
          />
          <label for="preview-skip">Skip</label>
          <InputNumber
            inputId="preview-skip"
            v-model="previewSkip"
            :min="1"
            :max="Math.max(1, maxPreviewSample)"
            :useGrouping="false"
            :disabled="!previewResult"
            showButtons
            buttonLayout="horizontal"
            incrementButtonIcon="pi pi-plus"
            decrementButtonIcon="pi pi-minus"
          />
          <span v-if="previewResult" class="preview-sampling__count">
            {{ selectedSampleIndices.length }} of {{ previewSampleCount }} samples
          </span>
        </div>
        <Button
          :label="showTransmittance ? 'Show absorbance' : 'Show transmittance'"
          icon="pi pi-sync"
          class="p-button-sm p-button-outlined"
          :disabled="!previewResult"
          @click="showTransmittance = !showTransmittance"
        />
      </div>
      <div v-if="componentOverlayOptions.length" class="component-overlay-controls">
        <span>Component spectra</span>
        <label
          v-for="option in componentOverlayOptions"
          :key="option.id"
          class="component-overlay-option"
        >
          <Checkbox
            v-model="synthesisReviewComponentIds"
            :value="option.id"
          />
          <span class="curve-swatch" :style="{ background: option.color }" />
          <span>{{ option.name }}</span>
        </label>
        <Button
          label="All"
          class="p-button-sm p-button-text"
          :disabled="activeSynthesisReviewComponentIds.length === componentOverlayOptions.length"
          @click="showAllSynthesisComponents"
        />
        <Button
          label="None"
          class="p-button-sm p-button-text"
          :disabled="activeSynthesisReviewComponentIds.length === 0"
          @click="clearSynthesisComponents"
        />
      </div>
      <PlotlyChart
        :data="synthesisPreviewTraces"
        :layout="synthesisPreviewLayout"
        :config="plotConfig"
        :loading="previewing"
        emptyMessage="Run a synthesis preview after all selected component spectra are loaded."
      />
      <template v-if="previewResult">
        <div class="contour-caption">
          Absorbance contour — hover for the crosshair, click to slice at that point.
        </div>
        <PlotlyChart
          :data="contourTraces"
          :layout="contourLayout"
          :config="plotConfig"
          @hover="onContourHover"
          @click="onContourClick"
        />
        <div v-if="sliceSelection" class="slice-grid">
          <PlotlyChart
            :data="horizontalSliceTraces"
            :layout="horizontalSliceLayout"
            :config="plotConfig"
          />
          <PlotlyChart
            :data="verticalSliceTraces"
            :layout="verticalSliceLayout"
            :config="plotConfig"
          />
        </div>
        <div v-else class="synthesis-note">
          <i class="pi pi-info-circle" />
          <span>Click anywhere on the contour to show the wavenumber and sample slices through that point.</span>
        </div>
      </template>
      <div v-if="blendStats" class="blend-stats" role="status" aria-live="polite">
        <div class="blend-stat">
          <span class="blend-stat__label">Absorbance (a.u.)</span>
          <span>min {{ blendStats.absMin }} · max {{ blendStats.absMax }} · mean {{ blendStats.absMean }}</span>
        </div>
        <div class="blend-stat">
          <span class="blend-stat__label">Wavenumbers (cm⁻¹)</span>
          <span>{{ blendStats.wnCount }} pts · {{ blendStats.wnMin }}–{{ blendStats.wnMax }}</span>
        </div>
        <div class="blend-stat">
          <span class="blend-stat__label">Samples</span>
          <span>{{ blendStats.sampleCount }} frames</span>
        </div>
        <small v-if="previewResult?.truncated">Stats computed over the downsampled preview.</small>
      </div>
      <div v-if="previewResult?.truncated" class="synthesis-note warn">
        <i class="pi pi-exclamation-triangle" />
        <span>Large result preview was downsampled for the browser. The saved dataset retains the full generated array.</span>
      </div>
    </Panel>

    <Panel header="Save" toggleable>
      <div class="save-row">
        <div class="field save-name">
          <label for="synth-name">Dataset name</label>
          <InputText id="synth-name" v-model="datasetName" />
        </div>
        <Button
          label="Add Current to Bundle"
          icon="pi pi-list-plus"
          class="p-button-sm p-button-outlined"
          :disabled="!canPreview"
          @click="addCurrentToBundle"
        />
        <Button
          :label="synthesisBundle.length ? 'Add Bundle to My Dataset' : 'Add to My Dataset'"
          icon="pi pi-plus"
          class="p-button-sm"
          data-action="synthesis_save_dataset"
          :loading="saving"
          :disabled="!canPreview"
          @click="saveSynthesis"
        />
      </div>
      <div v-if="synthesisBundle.length" class="synthesis-bundle-rows">
        <div
          v-for="item in synthesisBundle"
          :key="item.id"
          class="synthesis-bundle-row"
        >
          <span>{{ item.name }}</span>
          <Button
            icon="pi pi-trash"
            class="p-button-text p-button-sm p-button-rounded p-button-danger"
            title="Remove"
            @click="removeBundleItem(item.id)"
          />
        </div>
      </div>
    </Panel>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Panel from "primevue/panel";
import ProgressBar from "primevue/progressbar";
import Tag from "primevue/tag";
import api from "@/api/client";
import PlotlyChart from "@/components/PlotlyChart.vue";
import ConcentrationCurveEditor from "@/components/ConcentrationCurveEditor.vue";
import { downloadBlob } from "@/utils/download";
import {
  defaultDatasetName,
  useSynthesisStore,
  type ComponentSummary,
  type ControlPoint,
  type HitranXsecOption,
  type NativeGrid,
  type SelectedComponent,
  type SpectrumPayload,
  type SynthesisResult,
} from "@/stores/synthesis";
import type { JobInfo } from "@/types";
import {
  resampleConcentrationShape,
  sampleCatmullRomAtIndices,
  seedConcentrationShape,
} from "@/utils/curve";
import { getErrorMessage } from "@/utils/errors";
import { useToast } from "primevue/usetoast";
import { useProjectStore } from "@/stores/project";

const emit = defineEmits<{ saved: [] }>();

const router = useRouter();
const toast = useToast();
const synthesisStore = useSynthesisStore();
const projectStore = useProjectStore();
const {
  sources,
  searchQuery,
  selectedComponents,
  previewResult,
  searching,
  previewing,
  saving,
  showTransmittance,
  previewStartSample,
  previewSkip,
  crosshair,
  sliceSelection,
  datasetName,
  recipeSeed,
  logConcentration,
  normalizeComposition,
  persistenceWarning,
} = storeToRefs(synthesisStore);
const { settings } = synthesisStore;

const resolutionOptions = [
  { label: "1 cm^-1", value: 1 },
  { label: "2 cm^-1", value: 2 },
  { label: "0.5 cm^-1", value: 0.5 },
  { label: "0.25 cm^-1", value: 0.25 },
  { label: "0.125 cm^-1", value: 0.125 },
];

type SpectrumLoadQueueItem = {
  component: SelectedComponent;
  resolve: () => void;
};

const activeSpectrumLoadId = ref<string | null>(null);
const spectrumLoadQueue = ref<SpectrumLoadQueueItem[]>([]);
const synthesisReviewComponentIds = ref<string[]>([]);
let searchDebounceTimer: ReturnType<typeof window.setTimeout> | null = null;
let searchRequestSeq = 0;

const apodizationOptions = [
  { label: "Blackman-Harris", value: "Blackman-Harris" },
  { label: "Triangular", value: "Triangular" },
];

const rangeModeOptions = [
  { label: "Common overlap", value: "common" },
  { label: "Widest + zero fill", value: "widest" },
];

const plotConfig = { responsive: true, displaylogo: false };

const sourceOptions = computed(() =>
  sources.value.length
    ? sources.value.map((source) => ({ id: source.id, label: source.label }))
    : [
        { id: "nist_quant_ir", label: "NIST Quantitative IR" },
        { id: "hitran", label: "HITRAN Line-by-Line" },
        { id: "hitran_xsec", label: "HITRAN Absorption X-section" },
      ],
);

const searchResultSummary = computed(() => {
  const count = searchResults.value.length;
  const source = sourceOptions.value.find((option) => option.id === settings.source)?.label || settings.source;
  const query = searchQuery.value.trim();
  if (searching.value) {
    return query ? `Searching ${source} for "${query}"...` : `Loading ${source} compounds...`;
  }
  if (count === 0) {
    return query ? `No ${source} compounds matched "${query}".` : `No ${source} compounds loaded.`;
  }
  const noun = count === 1 ? "compound" : "compounds";
  return query ? `${count} ${source} ${noun} matched "${query}".` : `${count} ${source} ${noun} loaded.`;
});

const sortedSearchResults = computed(() => {
  const key = compoundSortKey.value;
  const direction = compoundSortDirection.value;
  return [...searchResults.value].sort((a, b) => {
    const left = String(a[key] || "").toLocaleLowerCase();
    const right = String(b[key] || "").toLocaleLowerCase();
    if (left === right) return a.name.localeCompare(b.name);
    return left.localeCompare(right) * direction;
  });
});

function setCompoundSort(key: ComponentSearchSortKey): void {
  if (compoundSortKey.value === key) {
    compoundSortDirection.value = compoundSortDirection.value === 1 ? -1 : 1;
    return;
  }
  compoundSortKey.value = key;
  compoundSortDirection.value = 1;
}

function sortIndicator(key: ComponentSearchSortKey): string {
  if (compoundSortKey.value !== key) return "";
  return compoundSortDirection.value === 1 ? "▲" : "▼";
}

function isHitranSource(source: string): boolean {
  return source === "hitran" || source === "hitran_xsec";
}

const isHitranLineByLine = computed(() => settings.source === "hitran");

const hitranAvailable = computed(() =>
  sources.value.filter((source) => isHitranSource(source.id)).every((source) => source.available !== false),
);
const curveFileInput = ref<HTMLInputElement | null>(null);
const DEFAULT_POINT_COUNT = 11;
const DEFAULT_MAX_PPM = 100;
const CURVE_EXPORT_VERSION = 1;
const MAX_SYNTHESIS_OUTPUT_VALUES = 2_000_000;
const OUTPUT_SIZE_WARNING_FRACTION = 0.8;
type ComponentSearchSortKey = "name" | "formula" | "cas";
type ComponentSearchRow = ComponentSummary & { selected_xsec_option?: number };
type SynthesisPayload = ReturnType<typeof buildRequestPayload>;
interface SynthesisBundleItem {
  id: string;
  name: string;
  payload: SynthesisPayload;
}
interface OutputSizeEstimate {
  nSamples: number;
  nFeatures: number;
  totalValues: number;
  limit: number;
  nearLimit: boolean;
  overLimit: boolean;
}
interface LoadedGridSummary {
  name: string;
  min: number;
  max: number;
  values: number[];
}
interface CommonOverlapProblem {
  commonMin: number;
  commonMax: number;
  latestStartName: string;
  earliestEndName: string;
}
type SavedRecipeRecord = Record<string, unknown>;
const synthesisBundle = ref<SynthesisBundleItem[]>([]);
const searchResults = ref<ComponentSearchRow[]>([]);
const compoundSortKey = ref<ComponentSearchSortKey>("name");
const compoundSortDirection = ref<1 | -1>(1);

// Stable per-species colors so the editor handle, its spline, and the
// preview trace all read as the same species.
const CURVE_PALETTE = [
  "#2563eb",
  "#d62728",
  "#2ca02c",
  "#ff7f0e",
  "#9467bd",
  "#8c564b",
  "#17becf",
  "#e377c2",
];
function componentColor(index: number) {
  return CURVE_PALETTE[index % CURVE_PALETTE.length];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function finiteOr(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function finiteOrNull(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function validSource(value: unknown): "nist_quant_ir" | "hitran" | "hitran_xsec" {
  return value === "hitran" || value === "hitran_xsec" ? value : "nist_quant_ir";
}

function validRangeMode(value: unknown): "common" | "widest" {
  return value === "widest" ? "widest" : "common";
}

function recipeControlPointsToEditor(
  rawPoints: unknown,
  nSamples: number,
  concentrationMaxPpm: number,
): ControlPoint[] {
  if (!Array.isArray(rawPoints)) return seedConcentrationShape(DEFAULT_POINT_COUNT);
  const maxIndex = Math.max(1, nSamples - 1);
  const points = rawPoints
    .map((point) => {
      const item = asRecord(point);
      const xIndex = finiteOr(item.x, NaN);
      const y =
        item.y !== undefined && item.y !== null
          ? finiteOr(item.y, NaN)
          : concentrationMaxPpm > 0
            ? finiteOr(item.y_ppm, NaN) / concentrationMaxPpm
            : NaN;
      return {
        x: Math.min(Math.max((xIndex / maxIndex) * 100, 0), 100),
        y: Math.min(Math.max(y, 0), 1),
      };
    })
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  return points.length >= 2 ? points : seedConcentrationShape(DEFAULT_POINT_COUNT);
}

// The editor works in normalized shape space (x: 0–100 % of run, y: 0–1).
// The backend trace evaluator is sample-index based: map x→sample index and
// keep y as the 0–1 shape. This is the ONE place that x translation happens;
// the payload and the preview both go through it so they cannot drift.
function shapeToSchemaPoints(points: ControlPoint[]) {
  const maxIndex = Math.max(2, Number(settings.n_samples || 2)) - 1;
  return [...points]
    .map((point) => ({
      x: (Math.min(Math.max(Number(point.x), 0), 100) / 100) * maxIndex,
      y: Math.min(Math.max(Number(point.y), 0), 1),
    }))
    .sort((a, b) => a.x - b.x)
    .filter((point, index, all) => index === 0 || point.x > all[index - 1].x);
}

// Same points, resolved to absolute ppm via the per-species multiplier — for
// the local preview, which mirrors what the backend computes from the payload.
function shapeToPpmSamplePoints(component: SelectedComponent) {
  const multiplier = Math.max(0, Number(component.concentration_max_ppm) || 0);
  return shapeToSchemaPoints(component.control_points).map((point) => ({
    x: point.x,
    y: point.y * multiplier,
  }));
}

// Schema requires concentration_max_ppm > 0; surface it here instead of
// letting a blank multiplier turn into a confusing 422 on Preview/Save.
const invalidMultipliers = computed(() =>
  selectedComponents.value.filter((component) => !(Number(component.concentration_max_ppm) > 0)),
);
const loadedGridSummaries = computed<LoadedGridSummary[]>(() =>
  selectedComponents.value
    .map((component) => sortedUniqueNumbers(component.spectrum?.wavenumber))
    .map((grid, index) => ({
      name: selectedComponents.value[index]?.name || selectedComponents.value[index]?.id || `component ${index + 1}`,
      min: grid[0],
      max: grid[grid.length - 1],
      values: grid,
    }))
    .filter((grid) => grid.values.length >= 2),
);
const commonOverlapProblem = computed<CommonOverlapProblem | null>(() => {
  const grids = loadedGridSummaries.value;
  if (
    settings.range_mode !== "common" ||
    !grids.length ||
    grids.length !== selectedComponents.value.length
  ) {
    return null;
  }
  if (isHitranLineByLine.value) {
    const commonMin = Math.max(...grids.map((grid) => grid.min));
    const commonMax = Math.min(...grids.map((grid) => grid.max));
    if (commonMin < commonMax) return null;
    const latestStart = grids.reduce((best, grid) => (grid.min > best.min ? grid : best), grids[0]);
    const earliestEnd = grids.reduce((best, grid) => (grid.max < best.max ? grid : best), grids[0]);
    return {
      commonMin,
      commonMax,
      latestStartName: latestStart.name,
      earliestEndName: earliestEnd.name,
    };
  }
  const interval = settings.preview_wavenumber_interval_cm1;
  const snap = Math.max(Number(settings.snap_tolerance_cm1) || 0, 0);
  const commonMin =
    interval != null
      ? Math.max(...grids.map((grid) => grid.min - snap))
      : Math.max(...grids.map((grid) => grid.min));
  const commonMax =
    interval != null
      ? Math.min(...grids.map((grid) => grid.max + snap))
      : Math.min(...grids.map((grid) => grid.max));
  if (commonMin < commonMax) return null;
  const latestStart = grids.reduce((best, grid) => (grid.min > best.min ? grid : best), grids[0]);
  const earliestEnd = grids.reduce((best, grid) => (grid.max < best.max ? grid : best), grids[0]);
  return {
    commonMin,
    commonMax,
    latestStartName: latestStart.name,
    earliestEndName: earliestEnd.name,
  };
});
const invalidPreviewWavenumberRange = computed(() => {
  const minValue = settings.preview_wavenumber_min;
  const maxValue = settings.preview_wavenumber_max;
  return minValue != null && maxValue != null && Number(minValue) >= Number(maxValue);
});
const invalidPreviewWavenumberInterval = computed(() => {
  if (isHitranLineByLine.value) return false;
  const interval = settings.preview_wavenumber_interval_cm1;
  return interval != null && Number(interval) <= 0;
});
const previewWavenumberRangeOutsideGrid = computed(() => {
  const grids = loadedGridSummaries.value;
  if (!grids.length || grids.length !== selectedComponents.value.length) return false;
  const cropMin = settings.preview_wavenumber_min == null ? null : Number(settings.preview_wavenumber_min);
  const cropMax = settings.preview_wavenumber_max == null ? null : Number(settings.preview_wavenumber_max);
  if (cropMin == null && cropMax == null) return false;

  if (isHitranLineByLine.value) {
    const baseMin =
      settings.range_mode === "widest"
        ? Math.min(...grids.map((grid) => grid.min))
        : Math.max(...grids.map((grid) => grid.min));
    const baseMax =
      settings.range_mode === "widest"
        ? Math.max(...grids.map((grid) => grid.max))
        : Math.min(...grids.map((grid) => grid.max));
    const effectiveMin = cropMin == null ? baseMin : Math.max(baseMin, cropMin);
    const effectiveMax = cropMax == null ? baseMax : Math.min(baseMax, cropMax);
    return effectiveMin >= effectiveMax;
  }

  const interval = settings.preview_wavenumber_interval_cm1;
  const snap = Math.max(Number(settings.snap_tolerance_cm1) || 0, 0);
  const strictCommonMin = Math.max(...grids.map((grid) => grid.min));
  const strictCommonMax = Math.min(...grids.map((grid) => grid.max));
  const snapCommonMin =
    cropMin == null ? strictCommonMin : Math.max(...grids.map((grid) => grid.min - snap));
  const snapCommonMax =
    cropMax == null ? strictCommonMax : Math.min(...grids.map((grid) => grid.max + snap));
  const baseMin =
    settings.range_mode === "widest"
      ? Math.min(...grids.map((grid) => grid.min))
      : interval == null
        ? strictCommonMin
        : snapCommonMin;
  const baseMax =
    settings.range_mode === "widest"
      ? Math.max(...grids.map((grid) => grid.max))
      : interval == null
        ? strictCommonMax
        : snapCommonMax;
  const effectiveMin = cropMin == null ? baseMin : Math.max(baseMin, cropMin);
  const effectiveMax = cropMax == null ? baseMax : Math.min(baseMax, cropMax);
  if (effectiveMin >= effectiveMax) return true;
  return grids.every((grid) => grid.values.filter((value) => value >= effectiveMin && value <= effectiveMax).length < 2);
});
const outputSizeEstimate = computed<OutputSizeEstimate | null>(() => {
  const grids = loadedGridSummaries.value;
  if (!grids.length || grids.length !== selectedComponents.value.length) return null;

  const nSamples = Math.max(2, Math.trunc(Number(settings.n_samples) || 0));
  const cropMin = settings.preview_wavenumber_min == null ? null : Number(settings.preview_wavenumber_min);
  const cropMax = settings.preview_wavenumber_max == null ? null : Number(settings.preview_wavenumber_max);
  const interval =
    isHitranLineByLine.value || settings.preview_wavenumber_interval_cm1 == null
      ? null
      : Number(settings.preview_wavenumber_interval_cm1);
  const snap = Math.max(Number(settings.snap_tolerance_cm1) || 0, 0);
  let nFeatures = 0;
  if (settings.range_mode === "widest") {
    const mins = grids.map((grid) => grid.min);
    const maxs = grids.map((grid) => grid.max);
    const spacings = grids
      .map((grid) => medianSpacing(grid.values))
      .filter((spacing) => Number.isFinite(spacing) && spacing > 0);
    if (spacings.length !== grids.length) return null;
    const unionMin = cropMin == null ? Math.min(...mins) : Math.max(Math.min(...mins), cropMin);
    const unionMax = cropMax == null ? Math.max(...maxs) : Math.min(Math.max(...maxs), cropMax);
    if (unionMin >= unionMax) return null;
    const referenceSpacing =
      isHitranLineByLine.value && Number(settings.resolution_cm1) > 0
        ? Number(settings.resolution_cm1)
        : interval != null && interval > 0
          ? interval
          : medianNumber(spacings);
    nFeatures = Math.max(0, Math.floor((unionMax - unionMin) / referenceSpacing + 1e-9) + 1);
  } else {
    const strictCommonMin = Math.max(...grids.map((grid) => grid.min));
    const strictCommonMax = Math.min(...grids.map((grid) => grid.max));
    const baseMin =
      interval != null && cropMin != null
        ? Math.max(...grids.map((grid) => grid.min - snap))
        : strictCommonMin;
    const baseMax =
      interval != null && cropMax != null
        ? Math.min(...grids.map((grid) => grid.max + snap))
        : strictCommonMax;
    const commonMin = cropMin == null ? baseMin : Math.max(baseMin, cropMin);
    const commonMax = cropMax == null ? baseMax : Math.min(baseMax, cropMax);
    if (commonMin >= commonMax) return null;
    if (interval != null && interval > 0) {
      nFeatures = Math.max(0, Math.floor((commonMax - commonMin) / interval + 1e-9) + 1);
    } else if (isHitranLineByLine.value && Number(settings.resolution_cm1) > 0) {
      nFeatures = Math.max(0, Math.floor((commonMax - commonMin) / Number(settings.resolution_cm1) + 1e-9) + 1);
    } else {
      nFeatures = Math.max(
        ...grids.map((grid) => grid.values.filter((value) => value >= commonMin && value <= commonMax).length),
      );
    }
  }

  if (!Number.isFinite(nFeatures) || nFeatures < 1) return null;
  const totalValues = nSamples * nFeatures;
  return {
    nSamples,
    nFeatures,
    totalValues,
    limit: MAX_SYNTHESIS_OUTPUT_VALUES,
    nearLimit: totalValues >= MAX_SYNTHESIS_OUTPUT_VALUES * OUTPUT_SIZE_WARNING_FRACTION,
    overLimit: totalValues > MAX_SYNTHESIS_OUTPUT_VALUES,
  };
});
const previewDisabledReason = computed(() => {
  if (commonOverlapProblem.value) {
    return "Selected spectra do not share a common wavenumber overlap.";
  }
  if (invalidPreviewWavenumberRange.value) {
    return "Preview min must be lower than preview max.";
  }
  if (invalidPreviewWavenumberInterval.value) {
    return "Preview interval must be greater than zero.";
  }
  if (previewWavenumberRangeOutsideGrid.value) {
    return "Preview wavenumber range does not overlap the aligned synthesis grid.";
  }
  if (outputSizeEstimate.value?.overLimit) {
    return "Generated output exceeds the interactive size limit.";
  }
  return undefined;
});
const outputSizeIcon = computed(() => {
  if (outputSizeEstimate.value?.overLimit) return "pi pi-ban";
  if (outputSizeEstimate.value?.nearLimit) return "pi pi-exclamation-triangle";
  return "pi pi-info-circle";
});
const canPreview = computed(
  () =>
    selectedComponents.value.length > 0 &&
    selectedComponents.value.every((component) => component.spectrum) &&
    invalidMultipliers.value.length === 0 &&
    !commonOverlapProblem.value &&
    !invalidPreviewWavenumberRange.value &&
    !invalidPreviewWavenumberInterval.value &&
    !previewWavenumberRangeOutsideGrid.value &&
    !outputSizeEstimate.value?.overLimit,
);

const sourceStatusText = computed(() => {
  if (settings.source === "nist_quant_ir") {
    return "NIST spectra are downloaded as JCAMP-DX under the NIST egress permission and cached for later reuse.";
  }
  if (!hitranAvailable.value) {
    return "HITRAN requires the optional HAPI package, your own HITRAN key, and HITRAN egress permission before generating spectra.";
  }
  if (settings.source === "hitran_xsec") {
    return "HITRAN absorption cross-sections are measured spectra. Choose a measurement condition per compound; live downloads require your own HITRAN key.";
  }
  return "HITRAN spectra use HAPI line-by-line Voigt coefficients. Use narrow wavenumber windows for live downloads; add your own HITRAN key in Settings > API Keys.";
});

const componentPreviewTraces = computed(() =>
  selectedComponents.value
    .filter((component) => component.spectrum)
    .map((component) => {
      const spectrum = component.spectrum as SpectrumPayload;
      const maxAbs = Math.max(...spectrum.intensity.map((value) => Math.abs(value)), 1e-30);
      const color = componentColor(
        Math.max(
          0,
          selectedComponents.value.findIndex((item) => item.id === component.id),
        ),
      );
      return {
        x: [...spectrum.wavenumber].reverse(),
        y: spectrum.intensity.map((value) => value / maxAbs).reverse(),
        type: "scatter",
        mode: "lines",
        name: component.name,
        line: { color },
        hovertemplate: `${component.name}<br>%{x:.2f} cm^-1<br>normalized=%{y:.4f}<extra></extra>`,
      };
    }),
);

const componentPreviewLayout = computed(() => ({
  height: 320,
  margin: { l: 55, r: 20, t: 20, b: 45 },
  xaxis: { title: "Wavenumber (cm^-1)", autorange: "reversed" },
  yaxis: { title: "Normalized intensity" },
  legend: { orientation: "h" },
}));

// Resolved absolute ppm trace per species (shape × multiplier), sampled on
// the integer grid via the shared backend-matched evaluator.
const resolvedTraces = computed(() => {
  const nSamples = Number(settings.n_samples || 2);
  return selectedComponents.value.map((component, index) => ({
    name: component.name,
    color: componentColor(index),
    maxPpm: Number(component.concentration_max_ppm),
    ppm: sampleCatmullRomAtIndices(shapeToPpmSamplePoints(component), nSamples),
  }));
});

const concentrationTraces = computed(() => {
  const traces = resolvedTraces.value;
  if (!traces.length) return [];
  const nSamples = traces[0].ppm.length;
  // Display-only relative composition: per-sample fraction of total ppm.
  // Neutralizes order-of-magnitude differences without touching the payload.
  const totals = normalizeComposition.value
    ? Array.from({ length: nSamples }, (_, i) => traces.reduce((sum, t) => sum + (t.ppm[i] || 0), 0))
    : null;
  return traces.map((trace) => ({
    x: Array.from({ length: nSamples }, (_, i) => i),
    y: totals
      ? trace.ppm.map((value, i) => (totals[i] > 0 ? value / totals[i] : 0))
      : trace.ppm,
    type: "scatter",
    mode: "lines+markers",
    name: normalizeComposition.value
      ? trace.name
      : `${trace.name} (≤${formatPpm(trace.maxPpm)} ppm)`,
    line: { color: trace.color },
    marker: { color: trace.color, size: 4 },
    hovertemplate: normalizeComposition.value
      ? `${trace.name}<br>sample=%{x}<br>%{y:.1%}<extra></extra>`
      : `${trace.name}<br>sample=%{x}<br>%{y:.4g} ppm<extra></extra>`,
  }));
});

const concentrationLayout = computed(() => {
  if (normalizeComposition.value) {
    return {
      height: 280,
      margin: { l: 60, r: 20, t: 20, b: 45 },
      xaxis: { title: "Sample index" },
      yaxis: { title: "Relative composition", tickformat: ".0%", rangemode: "tozero" },
      legend: { orientation: "h" },
    };
  }
  return {
    height: 280,
    margin: { l: 60, r: 20, t: 20, b: 45 },
    xaxis: { title: "Sample index" },
    yaxis: {
      title: logConcentration.value ? "Concentration (ppm, log)" : "Concentration (ppm)",
      type: logConcentration.value ? "log" : "linear",
      rangemode: "tozero",
    },
    legend: { orientation: "h" },
  };
});

const blendStats = computed(() => {
  const result = previewResult.value;
  if (!result || !result.absorbance.length) return null;
  let min = Infinity;
  let max = -Infinity;
  let sum = 0;
  let count = 0;
  for (const row of result.absorbance) {
    for (const value of row) {
      if (value < min) min = value;
      if (value > max) max = value;
      sum += value;
      count += 1;
    }
  }
  const wn = result.wavenumber;
  const fmt = (v: number) => (Number.isFinite(v) ? v.toPrecision(4) : "n/a");
  return {
    absMin: fmt(min),
    absMax: fmt(max),
    absMean: fmt(count ? sum / count : NaN),
    wnCount: wn.length,
    wnMin: wn.length ? fmt(Math.min(...wn)) : "n/a",
    wnMax: wn.length ? fmt(Math.max(...wn)) : "n/a",
    sampleCount: result.absorbance.length,
  };
});

const previewSampleCount = computed(() => previewResult.value?.absorbance.length ?? 0);
const maxPreviewSample = computed(() => Math.max(0, previewSampleCount.value - 1));

// Sample rows drawn as curves: start, then every `skip`-th sample.
const selectedSampleIndices = computed(() => {
  const total = previewSampleCount.value;
  if (!total) return [];
  const start = Math.min(Math.max(Math.floor(previewStartSample.value) || 0, 0), total - 1);
  const skip = Math.max(1, Math.floor(previewSkip.value) || 1);
  const indices: number[] = [];
  for (let i = start; i < total; i += skip) indices.push(i);
  return indices;
});

const yAxisTitle = computed(() => (showTransmittance.value ? "Transmittance" : "Absorbance"));
const toDisplayY = (absorbance: number[]) =>
  showTransmittance.value ? absorbance.map((v) => Math.pow(10, -v)) : absorbance;

const synthesisSamplePreviewTraces = computed(() => {
  if (!previewResult.value) return [];
  const matrix = previewResult.value.absorbance;
  if (!matrix.length) return [];
  const wavenumber = [...previewResult.value.wavenumber].reverse();
  return selectedSampleIndices.value.map((sampleIndex) => ({
    x: wavenumber,
    y: [...toDisplayY(matrix[sampleIndex] ?? [])].reverse(),
    type: "scatter",
    mode: "lines",
    name: `sample ${sampleIndex}`,
    hovertemplate: `sample ${sampleIndex}<br>%{x:.2f} cm^-1<br>%{y:.5f}<extra></extra>`,
  }));
});

const synthesisPreviewGraphMax = computed(() => {
  let maxValue = 0;
  const result = previewResult.value;
  if (!result) return 1;
  for (const sampleIndex of selectedSampleIndices.value) {
    const values = toDisplayY(result.absorbance[sampleIndex] ?? []);
    for (const value of values) {
      if (Number.isFinite(value) && value > maxValue) maxValue = value;
    }
  }
  return maxValue > 0 ? maxValue : 1;
});

const componentOverlayOptions = computed(() =>
  selectedComponents.value
    .map((component, index) => ({
      id: component.id,
      name: component.name,
      color: componentColor(index),
      hasSpectrum: Boolean(component.spectrum),
    }))
    .filter((option) => option.hasSpectrum),
);

const activeSynthesisReviewComponentIds = computed(() => {
  const validIds = new Set(componentOverlayOptions.value.map((option) => option.id));
  return synthesisReviewComponentIds.value.filter((id) => validIds.has(id));
});

const synthesisComponentOverlayTraces = computed(() => {
  const result = previewResult.value;
  if (!result || !result.wavenumber.length) return [];
  const visible = new Set(activeSynthesisReviewComponentIds.value);
  if (!visible.size) return [];
  const minWavenumber = Math.min(...result.wavenumber);
  const maxWavenumber = Math.max(...result.wavenumber);
  const graphMax = synthesisPreviewGraphMax.value;

  return selectedComponents.value
    .map((component, index) => ({ component, index }))
    .filter(({ component }) => visible.has(component.id) && component.spectrum)
    .flatMap(({ component, index }) => {
      const spectrum = component.spectrum as SpectrumPayload;
      const pairs = spectrum.wavenumber
        .map((wavenumber, i) => ({ wavenumber, intensity: Number(spectrum.intensity[i] ?? 0) }))
        .filter(
          ({ wavenumber, intensity }) =>
            Number.isFinite(wavenumber) &&
            Number.isFinite(intensity) &&
            wavenumber >= minWavenumber &&
            wavenumber <= maxWavenumber,
        );
      if (!pairs.length) return [];
      const maxAbs = Math.max(...pairs.map(({ intensity }) => Math.abs(intensity)), 1e-30);
      const reversed = [...pairs].reverse();
      return [{
        x: reversed.map(({ wavenumber }) => wavenumber),
        y: reversed.map(({ intensity }) => (intensity / maxAbs) * graphMax),
        type: "scatter",
        mode: "lines",
        yaxis: "y2",
        name: `${component.name} component`,
        line: { color: componentColor(index), dash: "dot", width: 1.6 },
        opacity: 0.82,
        hovertemplate: `${component.name}<br>%{x:.2f} cm^-1<br>scaled component=%{y:.5f}<extra></extra>`,
      }];
    });
});

const synthesisPreviewTraces = computed(() => [
  ...synthesisSamplePreviewTraces.value,
  ...synthesisComponentOverlayTraces.value,
]);

const synthesisPreviewLayout = computed(() => ({
  height: 320,
  margin: { l: 55, r: synthesisComponentOverlayTraces.value.length ? 64 : 20, t: 20, b: 45 },
  xaxis: { title: "Wavenumber (cm^-1)", autorange: "reversed" },
  yaxis: { title: yAxisTitle.value },
  ...(synthesisComponentOverlayTraces.value.length
    ? {
        yaxis2: {
          title: "Component spectra (scaled)",
          overlaying: "y",
          side: "right",
          showgrid: false,
          rangemode: "tozero",
        },
      }
    : {}),
  legend: { orientation: "h" },
}));

function showAllSynthesisComponents() {
  synthesisReviewComponentIds.value = componentOverlayOptions.value.map((option) => option.id);
}

function clearSynthesisComponents() {
  synthesisReviewComponentIds.value = [];
}

// ---- Contour (always shown once a preview exists) -------------------------
// Rendered as a `heatmap`, not a `contour` trace: Plotly's contour runs
// marching-squares per cell and is ~unusably slow at 1 cm^-1 (≈50×2000).
// A heatmap draws one image with identical hover/click. Columns are
// decimated for display only (screen has far fewer than 2000 px of width);
// click maps back to the FULL wavenumber grid so slices stay full-res.
const CONTOUR_MAX_COLS = 600;
const contourTraces = computed(() => {
  const result = previewResult.value;
  if (!result || !result.absorbance.length) return [];
  const nCols = result.wavenumber.length;
  const stride = Math.max(1, Math.ceil(nCols / CONTOUR_MAX_COLS));
  const colIdx: number[] = [];
  for (let c = 0; c < nCols; c += stride) colIdx.push(c);
  const x = colIdx.map((c) => result.wavenumber[c]);
  const z = result.absorbance.map((row) => colIdx.map((c) => row[c]));
  return [
    {
      type: "heatmap",
      z, // z[sample][wavenumber]
      x,
      y: Array.from({ length: result.absorbance.length }, (_, i) => i),
      colorscale: "Viridis",
      colorbar: { title: "Abs", thickness: 12 },
      zsmooth: false,
      hovertemplate: "%{x:.2f} cm^-1<br>sample %{y}<br>abs %{z:.5f}<extra></extra>",
    },
  ];
});

// Crosshair drawn as layout shapes; `crosshair` updates on hover and on click.
const contourLayout = computed(() => {
  const shapes: Record<string, unknown>[] = [];
  if (crosshair.value) {
    shapes.push(
      {
        type: "line",
        xref: "x",
        yref: "paper",
        x0: crosshair.value.x,
        x1: crosshair.value.x,
        y0: 0,
        y1: 1,
        line: { color: "#e11d48", width: 1, dash: "dash" },
      },
      {
        type: "line",
        xref: "paper",
        yref: "y",
        x0: 0,
        x1: 1,
        y0: crosshair.value.y,
        y1: crosshair.value.y,
        line: { color: "#e11d48", width: 1, dash: "dash" },
      },
    );
  }
  return {
    height: 340,
    margin: { l: 55, r: 20, t: 20, b: 45 },
    xaxis: { title: "Wavenumber (cm^-1)", autorange: "reversed" },
    yaxis: { title: "Sample index" },
    shapes,
  };
});

function findNearestIndex(values: number[], target: number): number {
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const dist = Math.abs(values[i] - target);
    if (dist < bestDist) {
      bestDist = dist;
      best = i;
    }
  }
  return best;
}

function onContourHover(event: { points: Array<{ x: number; y: number }> }) {
  const point = event?.points?.[0];
  if (!point) return;
  crosshair.value = { x: Number(point.x), y: Number(point.y) };
}

function onContourClick(event: { points: Array<{ x: number; y: number }> }) {
  const result = previewResult.value;
  const point = event?.points?.[0];
  if (!result || !point) return;
  const sampleIndex = Math.min(Math.max(Math.round(Number(point.y)), 0), result.absorbance.length - 1);
  const wavenumberIndex = findNearestIndex(result.wavenumber, Number(point.x));
  crosshair.value = { x: result.wavenumber[wavenumberIndex], y: sampleIndex };
  sliceSelection.value = { sampleIndex, wavenumberIndex };
}

// Horizontal slice: absorbance vs wavenumber at the clicked sample row.
const horizontalSliceTraces = computed(() => {
  const result = previewResult.value;
  const sel = sliceSelection.value;
  if (!result || !sel) return [];
  return [
    {
      x: [...result.wavenumber].reverse(),
      y: [...toDisplayY(result.absorbance[sel.sampleIndex] ?? [])].reverse(),
      type: "scatter",
      mode: "lines",
      line: { color: "#e11d48" },
      name: `sample ${sel.sampleIndex}`,
      hovertemplate: `%{x:.2f} cm^-1<br>%{y:.5f}<extra></extra>`,
    },
  ];
});

const horizontalSliceLayout = computed(() => ({
  height: 240,
  margin: { l: 55, r: 20, t: 28, b: 40 },
  title: { text: `Horizontal slice — sample ${sliceSelection.value?.sampleIndex ?? ""}`, font: { size: 12 } },
  xaxis: { title: "Wavenumber (cm^-1)", autorange: "reversed" },
  yaxis: { title: yAxisTitle.value },
}));

// Vertical slice: absorbance vs sample at the clicked wavenumber column.
const verticalSliceTraces = computed(() => {
  const result = previewResult.value;
  const sel = sliceSelection.value;
  if (!result || !sel) return [];
  const column = result.absorbance.map((row) => row[sel.wavenumberIndex] ?? 0);
  return [
    {
      x: Array.from({ length: column.length }, (_, i) => i),
      y: toDisplayY(column),
      type: "scatter",
      mode: "lines+markers",
      line: { color: "#2563eb" },
      marker: { size: 4 },
      name: `${result.wavenumber[sel.wavenumberIndex]?.toFixed(2)} cm^-1`,
      hovertemplate: `sample %{x}<br>%{y:.5f}<extra></extra>`,
    },
  ];
});

const verticalSliceLayout = computed(() => ({
  height: 240,
  margin: { l: 55, r: 20, t: 28, b: 40 },
  title: {
    text: `Vertical slice — ${previewResult.value?.wavenumber[sliceSelection.value?.wavenumberIndex ?? 0]?.toFixed(2) ?? ""} cm^-1`,
    font: { size: 12 },
  },
  xaxis: { title: "Sample index" },
  yaxis: { title: yAxisTitle.value },
}));

onMounted(async () => {
  await loadSources();
  await refetchTrimmedSpectra();
  if (!searchResults.value.length) {
    await searchComponents();
  }
});

onBeforeUnmount(() => {
  if (searchDebounceTimer !== null) {
    window.clearTimeout(searchDebounceTimer);
    searchDebounceTimer = null;
  }
});

watch(searchQuery, () => {
  scheduleComponentSearch();
});

// User-initiated n_samples changes already invalidate the preview via
// the InputNumber @input handler (line 105). A separate watch on
// `settings.n_samples` fires on ANY mutation — including the
// programmatic ones inside the store's applySnapshot()/resetState() —
// and would clobber a just-restored preview on the next flush, so it
// is intentionally not added back here.

async function loadSources() {
  try {
    const response = await api.get("/synthesis/sources");
    sources.value = response.data.sources || [];
  } catch (err) {
    toast.add({
      severity: "warn",
      summary: "Synthesis sources unavailable",
      detail: getErrorMessage(err, "Could not load synthesis sources."),
      life: 5000,
    });
  }
}

function scheduleComponentSearch(delayMs = 250): void {
  if (searchDebounceTimer !== null) {
    window.clearTimeout(searchDebounceTimer);
  }
  searchDebounceTimer = window.setTimeout(() => {
    searchDebounceTimer = null;
    void searchComponents();
  }, delayMs);
}

async function searchComponents() {
  const requestSeq = ++searchRequestSeq;
  const query = searchQuery.value;
  const source = settings.source;
  searching.value = true;
  try {
    const response = await api.get("/synthesis/search", {
      params: {
        source,
        query,
        limit: 1000,
      },
    });
    if (requestSeq !== searchRequestSeq || source !== settings.source || query !== searchQuery.value) {
      return;
    }
    searchResults.value = ((response.data.components || []) as ComponentSummary[]).map((component) => ({
      ...component,
      selected_xsec_option: 0,
    }));
  } catch (err) {
    if (requestSeq !== searchRequestSeq) return;
    toast.add({
      severity: "error",
      summary: "Search failed",
      detail: getErrorMessage(err, "Could not search synthesis components."),
      life: 5000,
    });
  } finally {
    if (requestSeq === searchRequestSeq) {
      searching.value = false;
    }
  }
}

function onSourceOrGridChange() {
  const hadComponents = selectedComponents.value.length > 0 || searchResults.value.length > 0;
  if (searchDebounceTimer !== null) {
    window.clearTimeout(searchDebounceTimer);
    searchDebounceTimer = null;
  }
  clearSpectrumLoadQueue();
  synthesisStore.clearForSourceOrGridChange();
  if (hadComponents) {
    toast.add({
      severity: "info",
      summary: "Selection cleared",
      detail: "Synthesis components were cleared because the source or grid settings changed.",
      life: 3500,
    });
  }
  void searchComponents();
}

function onSourceChange() {
  searchQuery.value = "";
  onSourceOrGridChange();
}

function addComponent(component: ComponentSummary) {
  selectedComponents.value.push({
    ...component,
    spectrum: null,
    loading: false,
    native_grid: null,
    concentration_max_ppm: DEFAULT_MAX_PPM,
    control_points: seedConcentrationShape(DEFAULT_POINT_COUNT),
    selected_xsec_option: (component as ComponentSummary & { selected_xsec_option?: number }).selected_xsec_option ?? 0,
  });
  previewResult.value = null;
  recipeSeed.value = null;
}

function removeComponent(componentId: string) {
  cancelQueuedSpectrumLoad(componentId);
  selectedComponents.value = selectedComponents.value.filter((component) => component.id !== componentId);
  previewResult.value = null;
  recipeSeed.value = null;
}

function cancelQueuedSpectrumLoad(componentId: string): void {
  const remaining: SpectrumLoadQueueItem[] = [];
  for (const item of spectrumLoadQueue.value) {
    if (item.component.id === componentId) {
      item.resolve();
    } else {
      remaining.push(item);
    }
  }
  spectrumLoadQueue.value = remaining;
}

function clearSpectrumLoadQueue(): void {
  for (const item of spectrumLoadQueue.value) item.resolve();
  spectrumLoadQueue.value = [];
}

function isSpectrumLoadQueued(component: SelectedComponent): boolean {
  return spectrumLoadQueue.value.some((item) => item.component.id === component.id);
}

function spectrumLoadButtonLabel(component: SelectedComponent): string {
  if (component.loading) return "Loading";
  if (isSpectrumLoadQueued(component)) return "In queue";
  return "Load spectrum";
}

async function loadSpectrum(component: SelectedComponent): Promise<void> {
  if (component.loading || isSpectrumLoadQueued(component)) return;
  if (isHitranSource(settings.source) && activeSpectrumLoadId.value && activeSpectrumLoadId.value !== component.id) {
    await enqueueSpectrumLoad(component);
    return;
  }
  await runSpectrumLoad(component);
}

function enqueueSpectrumLoad(component: SelectedComponent): Promise<void> {
  if (isSpectrumLoadQueued(component)) return Promise.resolve();
  return new Promise((resolve) => {
    spectrumLoadQueue.value.push({ component, resolve });
  });
}

function spectrumParams(component: SelectedComponent): Record<string, string | number> {
  const componentId =
    settings.source === "hitran_xsec"
      ? `${component.id}#${component.selected_xsec_option ?? 0}`
      : component.id;
  const params: Record<string, string | number> = {
    source: settings.source,
    component_id: componentId,
  };
  if (settings.source === "nist_quant_ir") {
    params.resolution_cm1 = settings.resolution_cm1;
    params.apodization = settings.apodization;
  } else if (settings.source === "hitran") {
    params.resolution_cm1 = settings.resolution_cm1;
    params.wavenumber_min = settings.wavenumber_min;
    params.wavenumber_max = settings.wavenumber_max;
    params.temperature_k = settings.temperature_k;
    params.pressure_atm = settings.pressure_atm;
  }
  return params;
}

async function pollSpectrumLoadJob(jobId: number, component: SelectedComponent): Promise<JobInfo> {
  while (true) {
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
    const response = await api.get<JobInfo>(`/jobs/${jobId}`);
    const status = response.data.status;
    component.load_progress = response.data.progress;
    component.load_message = response.data.progress_message || null;
    if (status === "completed") return response.data;
    if (status === "failed" || status === "cancelled") {
      throw new Error(response.data.error_message || response.data.progress_message || "HITRAN spectrum load failed");
    }
  }
}

async function fetchSpectrumForComponent(component: SelectedComponent): Promise<SpectrumPayload> {
  const params = spectrumParams(component);
  if (!isHitranSource(settings.source)) {
    const response = await api.get<SpectrumPayload>("/synthesis/spectrum", { params });
    return response.data;
  }

  const loadResponse = await api.post<{
    queued: boolean;
    job_id?: number | null;
    message?: string | null;
    spectrum?: SpectrumPayload | null;
  }>("/synthesis/spectrum/load", params);
  if (loadResponse.data.spectrum) return loadResponse.data.spectrum;
  if (!loadResponse.data.queued || !loadResponse.data.job_id) {
    throw new Error(loadResponse.data.message || "HITRAN spectrum load did not return a spectrum or job id.");
  }
  component.load_progress = 0;
  component.load_message = loadResponse.data.message || "HITRAN spectrum queued";
  await pollSpectrumLoadJob(loadResponse.data.job_id, component);
  const cached = await api.get<SpectrumPayload>("/synthesis/spectrum", { params });
  return cached.data;
}

async function runSpectrumLoad(component: SelectedComponent): Promise<void> {
  activeSpectrumLoadId.value = component.id;
  component.loading = true;
  try {
    component.spectrum = await fetchSpectrumForComponent(component);
    component.spectrum_storage_trimmed = false;
    component.native_grid = computeNativeGrid(component.spectrum?.wavenumber);
    previewResult.value = null;
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Spectrum load failed",
      detail: getErrorMessage(err, "Could not load the selected component spectrum."),
      life: 7000,
    });
  } finally {
    component.loading = false;
    component.load_progress = null;
    component.load_message = null;
    if (activeSpectrumLoadId.value === component.id) {
      activeSpectrumLoadId.value = null;
    }
    if (isHitranSource(settings.source)) {
      drainSpectrumLoadQueue();
    }
  }
}

function drainSpectrumLoadQueue(): void {
  if (activeSpectrumLoadId.value || spectrumLoadQueue.value.length === 0) return;
  const next = spectrumLoadQueue.value.shift();
  if (!next) return;
  void runSpectrumLoad(next.component).finally(next.resolve);
}

async function refetchTrimmedSpectra() {
  const trimmed = selectedComponents.value.filter(
    (component) => component.spectrum_storage_trimmed && component.spectrum === null,
  );
  if (!trimmed.length) return;
  for (const component of trimmed) {
    await loadSpectrum(component);
  }
}

async function previewSynthesis() {
  previewing.value = true;
  try {
    const response = await api.post("/synthesis/preview", buildRequestPayload());
    previewResult.value = response.data;
    resetPreviewView();
    syncSeedFromResult(response.data);
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Preview failed",
      detail: getErrorMessage(err, "Could not generate synthesis preview."),
      life: 7000,
    });
  } finally {
    previewing.value = false;
  }
}

async function saveSynthesis() {
  saving.value = true;
  try {
    if (synthesisBundle.value.length) {
      const bundleName = datasetName.value || `Synthetic bundle (${synthesisBundle.value.length})`;
      let experimentId: number | null = null;
      for (const [index, item] of synthesisBundle.value.entries()) {
        const response: { data: { experiment_id: number; result: SynthesisResult } } = await api.post("/synthesis/save", {
          ...item.payload,
          name: index === 0 ? bundleName : item.name,
          experiment_id: experimentId,
          project_id: projectStore.currentProjectId,
        });
        experimentId = response.data.experiment_id;
        previewResult.value = response.data.result;
      }
      toast.add({
        severity: "success",
        summary: "Synthetic bundle saved",
        detail: `Saved ${synthesisBundle.value.length} synthetic file(s) into "${bundleName}"`,
        life: 5000,
      });
      synthesisBundle.value = [];
      emit("saved");
      return;
    }

    // Pass project_id so the backend creates the new Experiment scoped to
    // the active project. Without this, the Experiment row is created with
    // project_id=NULL and dataStore.fetchExperiments filters it out of the
    // My Dataset list (which queries by project_id).
    const response = await api.post("/synthesis/save", {
      ...buildRequestPayload(),
      name: datasetName.value || defaultDatasetName(),
      project_id: projectStore.currentProjectId,
    });
    previewResult.value = response.data.result;
    toast.add({
      severity: "success",
      summary: "Synthetic dataset saved",
      detail: `Saved ${response.data.file_path}`,
      life: 5000,
    });
    emit("saved");
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Save failed",
      detail: getErrorMessage(err, "Could not save synthetic dataset."),
      life: 7000,
    });
  } finally {
    saving.value = false;
  }
}

function snapshotPayload(): SynthesisPayload {
  return JSON.parse(JSON.stringify(buildRequestPayload())) as SynthesisPayload;
}

function addCurrentToBundle() {
  if (!canPreview.value) return;
  const name = datasetName.value || defaultDatasetName();
  synthesisBundle.value.push({
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name,
    payload: snapshotPayload(),
  });
  toast.add({
    severity: "success",
    summary: "Added to bundle",
    detail: `${name} is ready to save with this My Dataset.`,
    life: 2500,
  });
}

function removeBundleItem(id: string) {
  synthesisBundle.value = synthesisBundle.value.filter((item) => item.id !== id);
}

function buildRequestPayload() {
  const settingsPayload: Record<string, string | number | null> = {
    source: settings.source,
    range_mode: settings.range_mode,
    n_samples: Number(settings.n_samples),
    pathlength_cm: Number(settings.pathlength_cm),
    temperature_k: Number(settings.temperature_k),
    pressure_atm: Number(settings.pressure_atm),
    noise_sigma_au: Number(settings.noise_sigma_au),
    resolution_cm1: Number(settings.resolution_cm1),
    apodization: settings.source === "nist_quant_ir" ? settings.apodization : "Voigt",
  };
  if (!isHitranLineByLine.value) {
    settingsPayload.snap_tolerance_cm1 = Number(settings.snap_tolerance_cm1);
  }
  if (settings.preview_wavenumber_min != null) {
    settingsPayload.preview_wavenumber_min = Number(settings.preview_wavenumber_min);
  }
  if (settings.preview_wavenumber_max != null) {
    settingsPayload.preview_wavenumber_max = Number(settings.preview_wavenumber_max);
  }
  if (!isHitranLineByLine.value && settings.preview_wavenumber_interval_cm1 != null) {
    settingsPayload.preview_wavenumber_interval_cm1 = Number(settings.preview_wavenumber_interval_cm1);
  }
  if (Number(settings.noise_sigma_au) > 0) {
    settingsPayload.seed = ensureRecipeSeed();
  }
  return {
    settings: settingsPayload,
    components: selectedComponents.value.map((component) => ({
      component_id: component.id,
      name: component.name,
      spectrum: {
        component_id: component.id,
        name: component.name,
        source: settings.source,
        wavenumber: component.spectrum!.wavenumber,
        intensity: component.spectrum!.intensity,
        units: "absorbance",
        y_quantity:
          settings.source === "nist_quant_ir"
            ? "decadic_absorption_coefficient"
            : "absorption_cross_section",
        y_units:
          settings.source === "nist_quant_ir"
            ? "ppm^-1 m^-1"
            : "cm^2 molecule^-1",
      },
      concentration_max_ppm: Number(component.concentration_max_ppm),
      // Canonical normalized form: y∈[0,1] shape + per-species ppm
      // multiplier. The backend resolves shape×multiplier centrally, so the
      // saved recipe is fully reproducible from these two pieces.
      control_points: shapeToSchemaPoints(component.control_points),
    })),
  };
}

function invalidatePreview() {
  synthesisStore.invalidatePreview();
}

// After a fresh preview: clear crosshair/slices and pick a default skip that
// keeps the curve plot readable (~8 traces) regardless of sample count.
function resetPreviewView() {
  crosshair.value = null;
  sliceSelection.value = null;
  previewStartSample.value = 0;
  const total = previewResult.value?.absorbance.length ?? 0;
  previewSkip.value = total > 8 ? Math.ceil(total / 8) : 1;
}

function updateControlPoints(component: SelectedComponent, points: ControlPoint[]) {
  component.control_points = points;
  invalidatePreview();
}

function updateMultiplier(component: SelectedComponent, value: number | null) {
  component.concentration_max_ppm = Math.max(0, Number(value) || 0);
  invalidatePreview();
}

function updatePointCount(component: SelectedComponent, value: number | null) {
  const count = Math.min(Math.max(Math.round(Number(value) || DEFAULT_POINT_COUNT), 4), 60);
  component.control_points = resampleConcentrationShape(component.control_points, count);
  invalidatePreview();
}

function formatPpm(value: number) {
  if (!Number.isFinite(value)) return "0";
  if (value >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatInteger(value: number) {
  return Math.trunc(value).toLocaleString();
}

function sortedUniqueNumbers(values: number[] | undefined | null): number[] {
  if (!values?.length) return [];
  return [...new Set(values.map(Number).filter((value) => Number.isFinite(value)))].sort((a, b) => a - b);
}

function medianNumber(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return NaN;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function medianSpacing(values: number[]): number {
  const diffs: number[] = [];
  for (let i = 1; i < values.length; i += 1) {
    const d = values[i] - values[i - 1];
    if (d > 0) diffs.push(d);
  }
  return medianNumber(diffs);
}

// Mirrors the backend lib.wavenumber_grid.median_spacing so the per-compound
// spacing shown here matches the value the server reconciles against.
function computeNativeGrid(wavenumber: number[] | undefined | null): NativeGrid | null {
  if (!wavenumber || wavenumber.length < 2) return null;
  const unique = sortedUniqueNumbers(wavenumber);
  const spacing = medianSpacing(unique);
  if (!Number.isFinite(spacing) || spacing <= 0) return null;
  return { spacing, min: unique[0], max: unique[unique.length - 1], n: wavenumber.length };
}

// True when loaded compounds' native spacings genuinely differ (not just an
// offset). A pure offset at equal spacing is fine — it just shifts the
// minority onto the median grid. Different spacings cannot be snapped and
// will be rejected at Preview, so warn ahead of time.
const spacingInconsistent = computed(() => {
  const spacings = selectedComponents.value
    .map((c) => c.native_grid?.spacing)
    .filter((s): s is number => typeof s === "number" && s > 0);
  if (spacings.length < 2) return false;
  const lo = Math.min(...spacings);
  const hi = Math.max(...spacings);
  return hi - lo > Math.max(Number(settings.snap_tolerance_cm1) || 0, 0.01 * lo);
});

// Per-component shift reported by the backend after a Preview (median-grid
// snap). Keyed by component id → max |Δ| in cm^-1.
const shiftedById = computed<Record<string, number>>(() => {
  const grid = (previewResult.value?.recipe as { grid?: unknown } | undefined)?.grid as
    | { components?: Array<{ id?: string; shifted?: boolean; max_shift_cm1?: number }> }
    | undefined;
  const out: Record<string, number> = {};
  for (const c of grid?.components ?? []) {
    if (c?.id && c.shifted) out[c.id] = Number(c.max_shift_cm1) || 0;
  }
  return out;
});

function resetCurve(component: SelectedComponent) {
  component.control_points = seedConcentrationShape(component.control_points.length || DEFAULT_POINT_COUNT);
  invalidatePreview();
}

async function copyCurve(component: SelectedComponent) {
  const payload = {
    name: component.name,
    concentration_max_ppm: component.concentration_max_ppm,
    control_points: component.control_points.map((p) => ({ x: p.x, y: p.y })),
  };
  try {
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    toast.add({ severity: "success", summary: "Curve copied", detail: component.name, life: 2000 });
  } catch {
    toast.add({ severity: "warn", summary: "Clipboard unavailable", life: 3000 });
  }
}

function saveAllCurves() {
  const payload = {
    version: CURVE_EXPORT_VERSION,
    generated_at: new Date().toISOString(),
    spline: "Catmull-Rom (uniform)",
    curves: selectedComponents.value.map((component) => ({
      component_id: component.id,
      name: component.name,
      concentration_max_ppm: component.concentration_max_ppm,
      control_points: component.control_points.map((p) => ({ x: p.x, y: p.y })),
    })),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  downloadBlob(blob, `synthesis-curves-${selectedComponents.value.length}-${Date.now()}.json`);
}

async function loadCurves(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    const curves = Array.isArray(parsed?.curves) ? parsed.curves : [];
    if (!curves.length) throw new Error("No curves in file");
    let applied = 0;
    selectedComponents.value.forEach((component, index) => {
      const match =
        curves.find((c: { component_id?: string }) => c.component_id === component.id) ??
        curves.find((c: { name?: string }) => c.name === component.name) ??
        curves[index];
      if (!match || !Array.isArray(match.control_points)) return;
      component.control_points = match.control_points.map((p: { x: number; y: number }) => ({
        x: Math.min(Math.max(Number(p.x), 0), 100),
        y: Math.min(Math.max(Number(p.y), 0), 1),
      }));
      if (Number.isFinite(Number(match.concentration_max_ppm))) {
        component.concentration_max_ppm = Math.max(0, Number(match.concentration_max_ppm));
      }
      applied += 1;
    });
    invalidatePreview();
    toast.add({
      severity: applied ? "success" : "warn",
      summary: applied ? `Loaded ${applied} curve(s)` : "No matching components",
      life: 3000,
    });
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Could not load curves",
      detail: getErrorMessage(err, "Invalid curves JSON."),
      life: 5000,
    });
  }
}

function ensureRecipeSeed() {
  if (recipeSeed.value === null) {
    recipeSeed.value = Math.floor(Math.random() * 2147483647);
  }
  return recipeSeed.value;
}

function syncSeedFromResult(result: SynthesisResult | null) {
  const settingsRecord = result?.recipe?.settings;
  if (settingsRecord && typeof settingsRecord === "object" && "seed" in settingsRecord) {
    const seed = Number((settingsRecord as Record<string, unknown>).seed);
    if (Number.isFinite(seed)) {
      recipeSeed.value = seed;
    }
  }
}

async function reopenRecipe(recipe: SavedRecipeRecord, title?: string | null): Promise<void> {
  const recipeSettings = asRecord(recipe.settings);
  const recipeComponents = Array.isArray(recipe.components) ? recipe.components : [];
  if (!recipeComponents.length) {
    toast.add({
      severity: "warn",
      summary: "Recipe has no components",
      detail: "This saved dataset does not contain enough synthesis recipe information to reopen the editor.",
      life: 5000,
    });
    return;
  }

  clearSpectrumLoadQueue();
  settings.source = validSource(recipeSettings.source);
  settings.range_mode = validRangeMode(recipeSettings.range_mode);
  settings.resolution_cm1 = finiteOr(recipeSettings.resolution_cm1, settings.resolution_cm1);
  settings.apodization =
    typeof recipeSettings.apodization === "string" && recipeSettings.apodization.trim()
      ? recipeSettings.apodization
      : "Blackman-Harris";
  settings.n_samples = Math.max(2, Math.round(finiteOr(recipeSettings.n_samples, settings.n_samples)));
  settings.pathlength_cm = Math.max(0.001, finiteOr(recipeSettings.pathlength_cm, settings.pathlength_cm));
  settings.noise_sigma_au = Math.max(0, finiteOr(recipeSettings.noise_sigma_au, settings.noise_sigma_au));
  settings.snap_tolerance_cm1 = Math.max(0, finiteOr(recipeSettings.snap_tolerance_cm1, settings.snap_tolerance_cm1));
  settings.wavenumber_min = finiteOr(recipeSettings.wavenumber_min, settings.wavenumber_min);
  settings.wavenumber_max = finiteOr(recipeSettings.wavenumber_max, settings.wavenumber_max);
  settings.preview_wavenumber_min =
    recipeSettings.preview_wavenumber_min == null ? null : finiteOrNull(recipeSettings.preview_wavenumber_min);
  settings.preview_wavenumber_max =
    recipeSettings.preview_wavenumber_max == null ? null : finiteOrNull(recipeSettings.preview_wavenumber_max);
  settings.preview_wavenumber_interval_cm1 =
    recipeSettings.preview_wavenumber_interval_cm1 == null
      ? null
      : finiteOrNull(recipeSettings.preview_wavenumber_interval_cm1);
  settings.temperature_k = Math.max(1, finiteOr(recipeSettings.temperature_k, settings.temperature_k));
  settings.pressure_atm = Math.max(0.000001, finiteOr(recipeSettings.pressure_atm, settings.pressure_atm));
  recipeSeed.value = Number.isFinite(Number(recipeSettings.seed)) ? Number(recipeSettings.seed) : null;

  selectedComponents.value = recipeComponents.map((raw, index) => {
    const component = asRecord(raw);
    const rawId = String(component.component_id || component.id || `component_${index + 1}`);
    const [baseId, optionText] = rawId.split("#");
    const selectedOption = Number.isFinite(Number(optionText)) ? Number(optionText) : 0;
    const concentrationMaxPpm = Math.max(0, finiteOr(component.concentration_max_ppm, DEFAULT_MAX_PPM));
    return {
      id: settings.source === "hitran_xsec" ? baseId : rawId,
      name: String(component.name || rawId),
      source: settings.source,
      cas: typeof component.cas === "string" ? component.cas : null,
      formula: typeof component.formula === "string" ? component.formula : null,
      variants: [],
      xsec_options: [],
      spectrum: null,
      loading: false,
      load_progress: null,
      load_message: null,
      native_grid: null,
      concentration_max_ppm: concentrationMaxPpm,
      control_points: recipeControlPointsToEditor(component.control_points, settings.n_samples, concentrationMaxPpm),
      selected_xsec_option: selectedOption,
      spectrum_storage_trimmed: false,
    };
  });
  previewResult.value = null;
  crosshair.value = null;
  sliceSelection.value = null;
  searchQuery.value = "";
  searchResults.value = [];
  datasetName.value =
    title && title.trim()
      ? `${title.trim()} copy`
      : defaultDatasetName();
  synthesisBundle.value = [];

  await loadSources();
  await searchComponents();
  toast.add({
    severity: "success",
    summary: "Synthesis recipe reopened",
    detail: "Settings, components, and concentration profiles were restored. Load spectra, then Preview.",
    life: 5000,
  });
}

defineExpose({ reopenRecipe });

function isSelected(componentId: string) {
  return selectedComponents.value.some((component) => component.id === componentId);
}

function formatXsecNumber(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "blank";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 4, useGrouping: false });
}

function formatXsecRange(values?: [number, number] | null, suffix = ""): string {
  if (!values || values.length !== 2) return "blank";
  const [low, high] = values;
  const body =
    Math.abs(low - high) < 1e-9 ? formatXsecNumber(low) : `${formatXsecNumber(low)}-${formatXsecNumber(high)}`;
  return suffix ? `${body} ${suffix}` : body;
}

function hitranXsecOptionLabel(option: HitranXsecOption, index: number): string {
  const temp = formatXsecRange(option.temperature_k, "K");
  const pressure = formatXsecRange(option.pressure_torr, "Torr");
  const resolution = option.resolution_cm1 ? `${formatXsecNumber(option.resolution_cm1)} cm^-1` : "blank res.";
  const broadener = option.broadener || "blank broadener";
  return `${index + 1}. T ${temp} · p ${pressure} · ${resolution} · ${broadener}`;
}

function hitranXsecOptionChoices(component: ComponentSummary): Array<{ label: string; value: number }> {
  const options = component.xsec_options?.length ? component.xsec_options : [{}];
  return options.map((option, index) => ({ label: hitranXsecOptionLabel(option, index), value: index }));
}

function updateXsecOption(component: ComponentSearchRow, event: Event): void {
  const target = event.target as HTMLSelectElement | null;
  component.selected_xsec_option = Math.max(0, Number(target?.value) || 0);
}

function variantLabel(component: ComponentSummary) {
  if (settings.source === "hitran") return "Voigt, line-by-line";
  if (settings.source === "hitran_xsec") {
    return hitranXsecOptionLabel(component.xsec_options?.[0] || {}, 0);
  }
  const match = component.variants.find(
    (variant) =>
      Math.abs(variant.resolution_cm1 - settings.resolution_cm1) < 1e-9 &&
      variant.apodization === settings.apodization,
  );
  return match ? `${match.apodization}, ${match.resolution_cm1} cm^-1` : "not available";
}

function openGuide() {
  router.push("/documentation");
}
</script>

<style scoped>
.synthesis-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.synthesis-toolbar,
.search-row,
.save-row,
.preview-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.preview-toolbar {
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
}

.preview-sampling {
  display: flex;
  align-items: center;
  gap: 0.4rem 0.6rem;
  flex-wrap: wrap;
}

.preview-range-mode {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 0.6rem;
}

.preview-range-mode label,
.preview-sampling label {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.component-overlay-controls {
  align-items: center;
  color: var(--text-color-secondary);
  display: flex;
  flex-wrap: wrap;
  font-size: 0.82rem;
  gap: 0.45rem 0.65rem;
  margin: 0.5rem 0 0.35rem;
}

.component-overlay-controls > span:first-child {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.component-overlay-option {
  align-items: center;
  border: 1px solid var(--surface-200);
  border-radius: 999px;
  color: var(--text-color);
  cursor: pointer;
  display: inline-flex;
  gap: 0.35rem;
  padding: 0.2rem 0.55rem;
}

.component-overlay-option :deep(.p-checkbox) {
  height: 1rem;
  width: 1rem;
}

.preview-range-mode :deep(.p-dropdown) {
  min-width: 11.5rem;
}

.preview-range-input :deep(.p-inputnumber-input) {
  width: 6.5rem;
}

.preview-sampling :deep(.p-inputnumber-input) {
  width: 4.5rem;
  text-align: center;
}

.preview-sampling__count {
  color: var(--text-color-secondary);
  font-size: 0.8rem;
}

.contour-caption {
  color: var(--text-color-secondary);
  font-size: 0.85rem;
  margin: 0.75rem 0 0.25rem;
}

.slice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.synthesis-toolbar h3 {
  margin: 0;
  font-size: 1rem;
}

.synthesis-toolbar p,
.empty-synthesis {
  margin: 0.25rem 0 0;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.synthesis-grid {
  display: grid;
  gap: 0.75rem;
}

.synthesis-grid--source {
  grid-template-columns:
    minmax(180px, 1.4fr)
    minmax(115px, 0.8fr)
    repeat(4, minmax(120px, 0.85fr));
}

.synthesis-grid--generation {
  grid-template-columns:
    minmax(110px, 0.75fr)
    minmax(150px, 1fr)
    minmax(150px, 1fr)
    minmax(245px, 1.35fr);
  margin-top: 0.75rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 0;
}

.field label {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  white-space: nowrap;
}

.field :deep(.p-dropdown),
.field :deep(.p-inputnumber),
.field :deep(.p-inputtext),
.save-name {
  width: 100%;
}

/* Notes use a left-edge accent stripe rather than a filled card —
   default = neutral, .warn = amber. Matches the Zen vocabulary used
   for Data Story / AI feature / errors on the rest of the page. */
.synthesis-note {
  align-items: center;
  background: transparent;
  border: none;
  border-left: 3px solid var(--surface-border);
  border-radius: 0;
  color: var(--text-color-secondary);
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding: 0.25rem 0 0.25rem 1rem;
}

.synthesis-note.warn {
  background: transparent;
  border-left-color: var(--yellow-500);
  color: var(--yellow-700, #7a5300);
}

.synthesis-note.error {
  background: transparent;
  border-left-color: var(--red-500);
  color: var(--red-700, #9f1239);
}

.output-size-note {
  margin-bottom: 0.75rem;
}

.synthesis-search {
  flex: 1;
  width: 100%;
}

.synthesis-search .p-inputtext {
  width: 100%;
}

.search-summary {
  color: var(--text-color-secondary);
  font-size: 0.82rem;
  margin-top: 0.5rem;
}

.compound-results {
  border: 1px solid var(--surface-200);
  border-radius: 6px;
  margin-top: 0.75rem;
  max-height: 20rem;
  overflow: auto;
}

.compound-results-table {
  border-collapse: collapse;
  font-size: 0.86rem;
  min-width: 760px;
  width: 100%;
}

.compound-results-table th,
.compound-results-table td {
  border-bottom: 1px solid var(--surface-100);
  padding: 0.45rem 0.65rem;
  text-align: left;
  vertical-align: middle;
}

.compound-results-table th {
  background: var(--surface-50);
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  font-weight: 700;
  position: sticky;
  text-transform: uppercase;
  top: 0;
  z-index: 1;
}

.compound-results-table tbody tr:hover {
  background: var(--surface-50);
}

.compound-sort {
  align-items: center;
  background: transparent;
  border: 0;
  color: inherit;
  cursor: pointer;
  display: inline-flex;
  font: inherit;
  gap: 0.25rem;
  padding: 0;
  text-transform: inherit;
}

.compound-sort span {
  display: inline-block;
  min-width: 0.75rem;
}

.compound-action-col {
  text-align: right;
  width: 5.5rem;
}

.compound-empty {
  color: var(--text-color-secondary);
  height: 5rem;
  text-align: center;
}

.xsec-native-select {
  background: var(--surface-card);
  border: 1px solid var(--surface-300);
  border-radius: 6px;
  color: var(--text-color);
  font: inherit;
  max-width: min(34rem, 100%);
  padding: 0.35rem 0.45rem;
  width: 100%;
}

.selected-components,
.curve-list {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  margin-top: 0.75rem;
}

.selected-component {
  align-items: center;
  border: 1px solid var(--surface-200);
  border-radius: 6px;
  display: grid;
  gap: 0.75rem;
  grid-template-columns: minmax(180px, 1fr) auto auto auto;
  padding: 0.6rem 0.75rem;
}

.selected-component small {
  color: var(--text-color-secondary);
  display: block;
}

.spectrum-load-progress {
  align-items: center;
  display: grid;
  gap: 0.35rem 0.5rem;
  grid-column: 1 / -1;
  grid-template-columns: minmax(160px, 1fr) auto;
}

.spectrum-load-progress small {
  grid-column: 1 / -1;
}

.curve-editor {
  border: 1px solid var(--surface-200);
  border-radius: 6px;
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(220px, 0.42fr) minmax(360px, 0.9fr);
  align-items: stretch;
  padding: 0.75rem;
}

.curve-editor__meta {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-width: 0;
}

.curve-editor__canvas {
  justify-self: end;
  min-width: 0;
  width: min(100%, 480px);
}

.curve-editor__canvas :deep(.conc-curve-editor__canvas) {
  min-height: 320px;
  max-height: min(58vh, 480px);
}

.curve-editor__hint {
  color: var(--text-color-secondary);
  font-size: 0.8rem;
  line-height: 1.35;
}

.curve-editor-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}

.curve-editor-header strong {
  align-items: center;
  display: flex;
  gap: 0.5rem;
}

.shift-asterisk {
  color: #2563eb;
  cursor: help;
  font-weight: 700;
  margin-left: 1px;
}

.curve-swatch {
  border-radius: 3px;
  display: inline-block;
  height: 0.85rem;
  width: 0.85rem;
}

.curve-multiplier,
.curve-point-count {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.6rem;
  justify-content: space-between;
}

.curve-multiplier label,
.curve-point-count label {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.curve-multiplier :deep(.p-inputnumber-input) {
  width: 8rem;
}

.curve-point-count :deep(.p-inputnumber-input) {
  text-align: center;
  width: 4rem;
}

.concentration-preview-bar {
  align-items: center;
  color: var(--text-color-secondary);
  display: flex;
  flex-wrap: wrap;
  font-size: 0.85rem;
  gap: 0.5rem;
  justify-content: space-between;
  margin: 0.75rem 0 0.25rem;
}

.concentration-preview-actions,
.curve-actions {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.curve-actions--left {
  justify-content: flex-start;
}

.hidden-file-input {
  display: none;
}

.blend-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.5rem;
  align-items: center;
  background: var(--surface-50);
  border: 1px solid var(--surface-200);
  border-radius: 6px;
  margin-top: 0.75rem;
  padding: 0.65rem 0.75rem;
  font-size: 0.85rem;
}

.blend-stat {
  display: flex;
  flex-direction: column;
}

.blend-stat__label {
  color: var(--text-color-secondary);
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
}

.blend-stats small {
  color: var(--text-color-secondary);
  font-style: italic;
}

.save-row {
  align-items: flex-end;
}

.synthesis-bundle-rows {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-top: 0.75rem;
  border-top: 1px solid var(--surface-border);
}

.synthesis-bundle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  min-width: 0;
  padding: 0.35rem 0;
  border-bottom: 1px solid var(--surface-border);
}

.synthesis-bundle-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.85rem;
}

@media (max-width: 720px) {
  .synthesis-toolbar,
  .search-row,
  .save-row,
  .preview-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .selected-component {
    grid-template-columns: 1fr;
  }

  .curve-editor {
    grid-template-columns: 1fr;
  }

  .curve-editor__canvas :deep(.conc-curve-editor__canvas) {
    min-height: 280px;
  }

  .curve-editor__canvas {
    justify-self: stretch;
    width: 100%;
  }

  .synthesis-grid--source,
  .synthesis-grid--generation {
    grid-template-columns: 1fr;
  }

  .field label {
    white-space: normal;
  }
}

@media (min-width: 721px) and (max-width: 980px) {
  .synthesis-grid--source,
  .synthesis-grid--generation {
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  }
}
</style>
