<template>
  <section class="detail-section">
    <div class="section-header" @click="$emit('toggle')">
      <div class="section-title">
        <i :class="expanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
        <h2>Output</h2>
      </div>
      <span class="section-badge" v-if="outputSummary">{{ outputSummary }}</span>
    </div>
    <Transition name="collapse">
      <div v-if="expanded" class="section-content">
        <div v-if="!hasOutput" class="empty-section">
          <i class="pi pi-box" />
          <p>No output data available</p>
          <small>Execute this node to generate output data.</small>
        </div>
        <div v-else class="output-content">
          <!-- Output stats -->
          <div class="info-grid">
            <div class="info-item" v-if="outputData?.rows !== undefined">
              <label>Rows</label>
              <span>{{ outputData.rows }}</span>
            </div>
            <div class="info-item" v-if="outputData?.cols !== undefined">
              <label>Columns</label>
              <span>{{ outputData.cols }}</span>
            </div>
            <div class="info-item" v-if="outputData?.type">
              <label>Output Type</label>
              <span>{{ outputData.type }}</span>
            </div>
            <div class="info-item" v-if="outputData?.range">
              <label>Value Range</label>
              <span>{{ outputData.range[0].toFixed(3) }} - {{ outputData.range[1].toFixed(3) }}</span>
            </div>
          </div>

          <!-- Dataset Inspector: Coordinates -->
          <div v-if="datasetInfo" class="inspector-section">
            <button
              type="button"
              class="inspector-toggle"
              @click="$emit('toggleSub', 'coordinates')"
            >
              <span class="inspector-toggle-title">
                <i class="pi pi-compass" />
                Dataset Coordinates
              </span>
              <i :class="outputSubsections.coordinates ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            </button>
            <div v-if="outputSubsections.coordinates" class="inspector-grid">
              <div v-if="datasetInfo.title" class="inspector-item">
                <span class="insp-label">Title</span>
                <span class="insp-value">{{ datasetInfo.title }}</span>
              </div>
              <div v-if="datasetInfo.isSpectra" class="inspector-item">
                <span class="insp-label">Data Type</span>
                <span class="insp-value insp-badge">Spectral</span>
              </div>
              <div v-if="datasetInfo.dataRoleLabel" class="inspector-item">
                <span class="insp-label">
                  Data Role
                  <i
                    class="pi pi-info-circle meta-info-icon"
                    title="X_spectra has an ordered spectral axis. X_features is an unordered multivariate feature table; spectral preprocessing such as peak finding and baseline correction is blocked for it."
                  ></i>
                </span>
                <span class="insp-value insp-badge">{{ datasetInfo.dataRoleLabel }}</span>
              </div>
              <div v-if="datasetInfo.target" class="inspector-item">
                <span class="insp-label">
                  Target
                  <i
                    class="pi pi-info-circle meta-info-icon"
                    title="Target values or class labels are attached to this matrix and can be used by supervised chemometric nodes."
                  ></i>
                </span>
                <span class="insp-value">
                  {{ datasetInfo.target.type }}
                  <span v-if="datasetInfo.target.names?.length" class="insp-units">
                    ({{ datasetInfo.target.names.length }} field{{ datasetInfo.target.names.length === 1 ? '' : 's' }})
                  </span>
                </span>
              </div>
              <div v-if="datasetInfo.spectralTechnique" class="inspector-item">
                <span class="insp-label">Technique</span>
                <span class="insp-value">{{ datasetInfo.spectralTechnique }}</span>
              </div>
              <div v-if="datasetInfo.dataQuantity" class="inspector-item">
                <span class="insp-label">Quantity</span>
                <span class="insp-value">{{ datasetInfo.dataQuantity }}</span>
              </div>
              <div v-if="datasetInfo.valueUnits" class="inspector-item">
                <span class="insp-label">Units</span>
                <span class="insp-value">{{ datasetInfo.valueUnits }}</span>
              </div>
              <template v-if="datasetInfo.xAxis">
                <div class="inspector-item">
                  <span class="insp-label">X-Axis</span>
                  <span class="insp-value">
                    {{ datasetInfo.xAxis.title }}
                    <span v-if="datasetInfo.xAxis.units" class="insp-units">({{ datasetInfo.xAxis.units }})</span>
                  </span>
                </div>
                <div v-if="datasetInfo.xAxis.points !== undefined && datasetInfo.xAxis.points !== null" class="inspector-item">
                  <span class="insp-label">X Points</span>
                  <span class="insp-value">{{ datasetInfo.xAxis.points }}</span>
                </div>
                <div v-if="datasetInfo.xAxis.range" class="inspector-item">
                  <span class="insp-label">X Range</span>
                  <span class="insp-value mono">
                    {{ datasetInfo.xAxis.range[0].toFixed(1) }} &ndash; {{ datasetInfo.xAxis.range[1].toFixed(1) }}
                  </span>
                </div>
              </template>
              <template v-if="datasetInfo.yAxis">
                <div class="inspector-item">
                  <span class="insp-label">Y-Axis</span>
                  <span class="insp-value">
                    {{ datasetInfo.yAxis.title }}
                    <span v-if="datasetInfo.yAxis.units" class="insp-units">({{ datasetInfo.yAxis.units }})</span>
                  </span>
                </div>
                <div v-if="datasetInfo.yAxis.nSamples !== undefined && datasetInfo.yAxis.nSamples !== null" class="inspector-item">
                  <span class="insp-label">Samples</span>
                  <span class="insp-value">{{ datasetInfo.yAxis.nSamples }}</span>
                </div>
                <div v-if="datasetInfo.yAxis.labels?.length" class="inspector-item wide">
                  <span class="insp-label">Labels</span>
                  <div class="insp-label-table-wrap">
                    <table class="insp-label-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th
                            v-for="(header, idx) in datasetLabelTable.headers"
                            :key="`label-header-${idx}`"
                          >
                            {{ header }}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr
                          v-for="(row, rowIdx) in datasetLabelTable.rows"
                          :key="`label-row-${rowIdx}`"
                        >
                          <td class="label-row-index">{{ rowIdx + 1 }}</td>
                          <td
                            v-for="(cell, cellIdx) in row"
                            :key="`label-cell-${rowIdx}-${cellIdx}`"
                            class="label-cell"
                            :title="cell"
                          >
                            {{ cell }}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                    <span v-if="datasetInfo.yAxis.labels.length > labelPreviewLimit" class="insp-more">
                      (+{{ datasetInfo.yAxis.labels.length - labelPreviewLimit }} more)
                    </span>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- Metadata -->
          <div v-if="Object.keys(outputMetadata).length" class="inspector-section metadata-section">
            <button
              type="button"
              class="inspector-toggle"
              @click="$emit('toggleSub', 'metadata')"
            >
              <span class="inspector-toggle-title">
                <i class="pi pi-database" />
                Metadata
              </span>
              <i :class="outputSubsections.metadata ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            </button>
            <div v-if="outputSubsections.metadata" class="metadata-grid">
              <div
                v-for="(value, key) in outputMetadata"
                :key="key"
                class="metadata-item"
              >
                <span class="meta-key">
                  {{ key }}:
                  <i
                    v-if="getMetaTooltip(String(key))"
                    class="pi pi-info-circle meta-info-icon"
                    :title="getMetaTooltip(String(key)) ?? undefined"
                  ></i>
                </span>
                <span class="meta-value">{{ formatMetaValue(value) }}</span>
              </div>
            </div>
          </div>

          <!-- Processing History -->
          <div v-if="processingHistory" class="inspector-section">
            <button
              type="button"
              class="inspector-toggle"
              @click="$emit('toggleSub', 'processing')"
            >
              <span class="inspector-toggle-title">
                <i class="pi pi-history" />
                Processing History
              </span>
              <i :class="outputSubsections.processing ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            </button>
            <div v-if="outputSubsections.processing" class="processing-timeline">
              <div
                v-for="(step, index) in processingHistory"
                :key="index"
                class="timeline-item"
              >
                <span class="step-number">{{ index + 1 }}</span>
                <div class="step-content">
                  <span class="step-operation">
                    {{ typeof step === 'string' ? step : (step.op_id || step.operation || 'Unknown') }}
                  </span>
                  <div
                    v-if="typeof step === 'object' && step.parameters && Object.keys(step.parameters).length > 0"
                    class="step-params"
                  >
                    <span
                      v-for="(pVal, pKey) in step.parameters"
                      :key="pKey"
                      class="param-chip"
                      v-show="pVal !== null"
                    >
                      {{ pKey }}: {{ pVal }}
                    </span>
                  </div>
                  <div
                    v-if="typeof step === 'object' && (step.input_shape || step.output_shape)"
                    class="step-shapes"
                  >
                    <span v-if="step.input_shape" class="shape-badge">In: {{ step.input_shape?.join('\u00d7') }}</span>
                    <span v-if="step.output_shape" class="shape-badge">Out: {{ step.output_shape?.join('\u00d7') }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Provenance -->
          <div v-if="provenanceInfo" class="inspector-section">
            <button
              type="button"
              class="inspector-toggle"
              @click="$emit('toggleSub', 'provenance')"
            >
              <span class="inspector-toggle-title">
                <i class="pi pi-sitemap" />
                Provenance
              </span>
              <i :class="outputSubsections.provenance ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            </button>
            <div v-if="outputSubsections.provenance" class="inspector-grid">
              <div v-if="provenanceInfo.source_type" class="inspector-item">
                <span class="insp-label">Source</span>
                <span class="insp-value">{{ provenanceInfo.source_type }}</span>
              </div>
              <div v-if="provenanceInfo.operations?.length" class="inspector-item wide">
                <span class="insp-label">Operations</span>
                <span class="insp-value mono">
                  {{ provenanceInfo.operations.join(' \u2192 ') }}
                </span>
              </div>
              <div v-if="provenanceInfo.last_modified" class="inspector-item">
                <span class="insp-label">Modified</span>
                <span class="insp-value">{{ provenanceInfo.last_modified }}</span>
              </div>
              <template v-for="(val, key) in provenanceInfo.extras" :key="key">
                <div
                  v-if="typeof val !== 'object'"
                  class="inspector-item"
                >
                  <span class="insp-label">{{ key }}</span>
                  <span class="insp-value">{{ val }}</span>
                </div>
              </template>
            </div>
          </div>

          <!-- Quality Summary -->
          <div v-if="qualitySummary" class="inspector-section">
            <button
              type="button"
              class="inspector-toggle"
              @click="$emit('toggleSub', 'quality')"
            >
              <span class="inspector-toggle-title">
                <i class="pi pi-check-circle" />
                Quality
              </span>
              <i :class="outputSubsections.quality ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            </button>
            <div v-if="outputSubsections.quality" class="inspector-grid">
              <!-- Regression-specific controls -->
              <div
                v-if="isRegressionNode && regressionTargetOptions.length > 1"
                class="inspector-item wide"
              >
                <span class="insp-label">Target Metric</span>
                <Dropdown
                  v-model="regressionTargetIdx"
                  :options="regressionTargetOptions"
                  optionLabel="label"
                  optionValue="value"
                  class="detail-target-dropdown"
                />
              </div>
              <div v-if="qualitySummary.latest_model_type" class="inspector-item">
                <span class="insp-label">Model</span>
                <span class="insp-value">{{ qualitySummary.latest_model_type }}</span>
              </div>
              <div v-if="qualitySummary.latest_r2 != null" class="inspector-item">
                <span class="insp-label">R&sup2;</span>
                <span class="insp-value">{{ Number(qualitySummary.latest_r2).toFixed(4) }}</span>
              </div>
              <div v-if="qualitySummary.latest_rmse != null" class="inspector-item">
                <span class="insp-label">RMSE</span>
                <span class="insp-value">{{ Number(qualitySummary.latest_rmse).toFixed(4) }}</span>
              </div>
              <div v-if="selectedRegressionR2 != null" class="inspector-item">
                <span class="insp-label">Selected R&sup2;</span>
                <span class="insp-value">{{ Number(selectedRegressionR2).toFixed(4) }}</span>
              </div>
              <div v-if="selectedRegressionRmse != null" class="inspector-item">
                <span class="insp-label">Selected RMSE</span>
                <span class="insp-value">{{ Number(selectedRegressionRmse).toFixed(4) }}</span>
              </div>
              <div v-if="qualitySummary.n_evaluations" class="inspector-item">
                <span class="insp-label">Evaluations</span>
                <span class="insp-value">{{ qualitySummary.n_evaluations }}</span>
              </div>
              <!-- Generic quality_summary rendering for non-regression nodes -->
              <template v-for="(val, key) in qualitySummary.extras" :key="String(key)">
                <div
                  v-if="val != null"
                  class="inspector-item"
                  :class="{ wide: Array.isArray(val) }"
                >
                  <span class="insp-label">{{ formatQualityLabel(String(key)) }}</span>
                  <span class="insp-value">{{ formatQualityValue(val) }}</span>
                </div>
              </template>
            </div>
          </div>

          <!-- Model Artifact (training nodes only) -->
          <div v-if="modelId" class="inspector-section">
            <button
              type="button"
              class="inspector-toggle"
              @click="$emit('toggleSub', 'modelArtifact')"
            >
              <span class="inspector-toggle-title">
                <i class="pi pi-bookmark" />
                Saved Model Artifact
              </span>
              <i :class="outputSubsections.modelArtifact ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            </button>
            <div v-if="outputSubsections.modelArtifact" class="model-artifact">
              <div v-if="artifactLoading" class="model-artifact__status">
                <i class="pi pi-spin pi-spinner" /> Loading artifact metadata…
              </div>
              <div v-else-if="artifactError" class="model-artifact__status model-artifact__status--error">
                <i class="pi pi-exclamation-triangle" /> {{ artifactError }}
                <span class="model-artifact__uid">{{ modelId }}</span>
              </div>
              <template v-else-if="artifact">
                <div class="inspector-grid model-artifact__grid">
                  <div class="inspector-item">
                    <span class="insp-label">Name</span>
                    <span class="insp-value">{{ artifact.display_name || artifact.name }}</span>
                  </div>
                  <div class="inspector-item">
                    <span class="insp-label">Type</span>
                    <span class="insp-value">{{ artifact.model_type }}</span>
                  </div>
                  <div v-if="artifact.source_run_id != null" class="inspector-item">
                    <span class="insp-label">Source Run</span>
                    <button
                      type="button"
                      class="insp-value artifact-link"
                      @click="openSourceRun"
                    >
                      #{{ artifact.source_run_id }}
                    </button>
                  </div>
                  <div v-if="artifact.training_dataset_id != null" class="inspector-item">
                    <span class="insp-label">Training Dataset</span>
                    <button
                      type="button"
                      class="insp-value artifact-link"
                      @click="openTrainingDataset"
                    >
                      Dataset #{{ artifact.training_dataset_id }}
                    </button>
                  </div>
                  <div v-if="artifact.n_components != null" class="inspector-item">
                    <span class="insp-label">Components</span>
                    <span class="insp-value">{{ artifact.n_components }}</span>
                  </div>
                  <div class="inspector-item">
                    <span class="insp-label">Features</span>
                    <span class="insp-value">{{ artifact.n_features }}</span>
                  </div>
                  <div v-if="artifactHeadlineMetric" class="inspector-item">
                    <span class="insp-label">{{ artifactHeadlineMetric.label }}</span>
                    <span class="insp-value mono">{{ artifactHeadlineMetric.value }}</span>
                  </div>
                  <div class="inspector-item">
                    <span class="insp-label">Artifact UID</span>
                    <span class="insp-value mono" :title="artifact.artifact_uid">
                      {{ artifact.artifact_uid.slice(0, 8) }}…
                    </span>
                  </div>
                </div>
                <div class="model-artifact__actions">
                  <Button
                    label="Open in Runs › Artifacts"
                    icon="pi pi-external-link"
                    iconPos="right"
                    class="p-button-text p-button-sm"
                    @click="openArtifactInRuns"
                  />
                </div>
              </template>
            </div>
          </div>

          <!-- Secondary Port Outputs -->
          <div v-if="portSummaries.length > 0" class="inspector-section">
            <button
              type="button"
              class="inspector-toggle"
              @click="$emit('toggleSub', 'ports')"
            >
              <span class="inspector-toggle-title">
                <i class="pi pi-share-alt" />
                Output Ports
              </span>
              <i :class="outputSubsections.ports ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            </button>
            <div v-if="outputSubsections.ports" class="port-summaries">
              <div v-for="port in portSummaries" :key="port.name" class="port-summary-card">
                <div class="port-header">
                  <span class="port-name">{{ port.name }}</span>
                  <span v-if="port.type" class="port-type-badge">{{ port.type }}</span>
                </div>
                <div class="port-details">
                  <span v-if="port.shape">Shape: {{ port.shape.join('\u00d7') }}</span>
                  <span v-if="port.title">{{ port.title }}</span>
                  <span v-if="port.xTitle">X: {{ port.xTitle }}<template v-if="port.xUnits"> ({{ port.xUnits }})</template><template v-if="port.xPoints !== undefined && port.xPoints !== null">, {{ port.xPoints }} pts</template></span>
                  <span v-if="port.yTitle">Y: {{ port.yTitle }}<template v-if="port.yCount !== undefined && port.yCount !== null">, {{ formatAxisCount(port.yCount, port.yCountLabel || 'entries') }}</template></span>
                </div>
              </div>
            </div>
          </div>

          <div v-if="hasOutput" class="full-meta-action">
            <Button
              label="View Full Metadata (JSON)"
              icon="pi pi-code"
              class="p-button-sm p-button-text"
              @click="$emit('showFullMetadata')"
            />
          </div>

          <div class="output-actions">
            <Button
              label="View Data Table"
              icon="pi pi-table"
              class="p-button-outlined"
              @click="$emit('openDataTable')"
            />
            <Button
              v-if="nodeType !== 'output.data_table'"
              label="Quick Plot"
              icon="pi pi-chart-line"
              class="p-button-outlined"
              @click="$emit('openQuickPlot')"
            />
            <Button
              label="Export CSV"
              icon="pi pi-download"
              class="p-button-outlined"
              @click="$emit('exportOutput')"
            />
          </div>

          <div v-if="outputPreview.length" class="preview-table">
            <h4>Output Preview ({{ outputDataSummary }})</h4>
            <DataTable
              :value="outputPreview"
              :scrollable="true"
              scrollHeight="200px"
              class="preview-datatable"
              size="small"
            >
              <Column
                v-for="col in outputPreviewColumns"
                :key="col.field"
                :field="col.field"
                :header="col.header"
                :style="{ minWidth: '80px' }"
              />
            </DataTable>
          </div>

          <div v-if="peakIdSummary" class="analysis-summary">
            <h4>Summary</h4>
            <p>{{ peakIdSummary }}</p>
          </div>

          <div v-if="pcaDiagnosticsPreview.length" class="preview-table">
            <h4>PCA Diagnostics ({{ pcaDiagSummary }})</h4>
            <DataTable
              :value="pcaDiagnosticsPreview"
              :scrollable="true"
              scrollHeight="200px"
              class="preview-datatable"
              size="small"
            >
              <Column
                v-for="col in pcaDiagnosticsColumns"
                :key="col.field"
                :field="col.field"
                :header="col.header"
                :style="{ minWidth: '120px' }"
              />
            </DataTable>
          </div>
        </div>
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import { useRouter } from "vue-router";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Dropdown from "primevue/dropdown";
import api from "@/api/client";
import { collectCanonicalClassificationMetrics } from "@/utils/classificationMetrics";
import { getErrorMessage } from "@/utils/errors";
import type { OutputSubsection } from "../composables/useNodeSections";
import { NODE_DETAIL_STATE_KEY } from "../state/useNodeDetailState";



defineProps<{
  expanded: boolean;
  nodeType?: string;
}>();

defineEmits<{
  (e: "toggle"): void;
  (e: "toggleSub", sub: OutputSubsection): void;
  (e: "showFullMetadata"): void;
  (e: "openDataTable"): void;
  (e: "openQuickPlot"): void;
  (e: "exportOutput"): void;
}>();

// Canonical state — the shell provides this via provide/inject.
const state = inject(NODE_DETAIL_STATE_KEY);
if (!state) {
  throw new Error("OutputPanel must be rendered inside NodeDetailView (missing NODE_DETAIL_STATE_KEY)");
}
const { output, writable } = state;

// Re-expose under the names the template uses. Refs auto-unwrap in template.
const outputSummary = output.summary;
const hasOutput = output.hasOutput;
const outputData = output.data;
const outputMetadata = output.metadata;
const outputSubsections = output.subsections;
const datasetInfo = output.datasetInfo;
const datasetLabelTable = output.datasetLabelTable;
const labelPreviewLimit = output.labelPreviewLimit;
const processingHistory = output.processingHistory;
const provenanceInfo = output.provenance;
const qualitySummary = output.quality;
const isRegressionNode = output.isRegressionNode;
const regressionTargetOptions = output.regressionTargetOptions;
const selectedRegressionR2 = output.selectedRegressionR2;
const selectedRegressionRmse = output.selectedRegressionRmse;
const portSummaries = output.portSummaries;
const modelId = output.modelId;
const { getMetaTooltip, formatMetaValue } = output;

function formatAxisCount(count: number, label: string): string {
  const singular = label.endsWith("ies")
    ? `${label.slice(0, -3)}y`
    : label.endsWith("s")
      ? label.slice(0, -1)
      : label;
  return `${count} ${count === 1 ? singular : label}`;
}

// ── Model Artifact lookup ─────────────────────────────────────────────
// When the executor's `_process_model_artifact()` lift fires for this
// node it leaves a `model_id` UID on the output. We resolve it back to
// a `ModelSummary` so the panel can show the saved-artifact's name,
// headline metric, and a link to /runs › Artifacts.

interface ArtifactSummary {
  artifact_uid: string;
  name: string;
  display_name?: string | null;
  model_type: string;
  n_features: number;
  n_components: number | null;
  node_id?: string | null;
  workflow_id?: number | null;
  source_run_id?: number | null;
  training_dataset_id?: number | null;
  metrics?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
}

const router = useRouter();
const artifact = ref<ArtifactSummary | null>(null);
const artifactLoading = ref(false);
const artifactError = ref<string | null>(null);

const HEADLINE_METRIC_KEYS: Array<{ key: string; label: string }> = [
  { key: "cv_balanced_accuracy", label: "CV Balanced Acc" },
  { key: "cv_accuracy", label: "CV Accuracy" },
  { key: "cv_f1_macro", label: "CV F1 (macro)" },
  { key: "test_accuracy", label: "Test Accuracy" },
  { key: "test_balanced_accuracy", label: "Test Balanced Acc" },
  { key: "test_f1_macro", label: "Test F1 (macro)" },
  { key: "f1_macro", label: "F1 (macro)" },
  { key: "cv_sensitivity_macro", label: "CV Sensitivity" },
  { key: "cv_specificity_macro", label: "CV Specificity" },
  { key: "balanced_accuracy", label: "Balanced Acc" },
  { key: "accuracy_test", label: "Test Accuracy" },
  { key: "accuracy", label: "Accuracy" },
  { key: "r2_cv", label: "R² (CV)" },
  { key: "r2_test", label: "R² (Test)" },
  { key: "r2", label: "R²" },
  { key: "rmsecv", label: "RMSECV" },
  { key: "rmse_test", label: "Test RMSE" },
  { key: "rmse", label: "RMSE" },
  { key: "mae", label: "MAE" },
];

const artifactHeadlineMetric = computed<{ label: string; value: string } | null>(() => {
  const metrics = artifact.value?.metrics;
  if (!metrics) return null;
  const flattenedMetrics: Record<string, unknown> = { ...metrics };
  collectCanonicalClassificationMetrics(metrics, flattenedMetrics);
  for (const { key, label } of HEADLINE_METRIC_KEYS) {
    const value = flattenedMetrics[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      const formatted = Math.abs(value) >= 10
        ? value.toFixed(2)
        : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
      return { label, value: formatted };
    }
  }
  return null;
});

const openArtifactInRuns = () => {
  if (!modelId.value) return;
  // /runs route mounts ModelsContent; the page reads `?artifact=<uid>` to
  // jump to the Artifacts tab and pre-select the matching row.
  router.push({ path: "/runs", query: { artifact: modelId.value } });
};

const openSourceRun = () => {
  const runId = artifact.value?.source_run_id;
  if (runId == null) return;
  router.push({ path: "/runs", query: { run: String(runId) } });
};

const openTrainingDataset = () => {
  const experimentId = artifact.value?.training_dataset_id;
  if (experimentId == null) return;
  router.push({ path: "/data", query: { experiment: String(experimentId) } });
};

watch(
  modelId,
  async (uid) => {
    if (!uid) {
      artifact.value = null;
      artifactError.value = null;
      artifactLoading.value = false;
      return;
    }
    artifactLoading.value = true;
    artifactError.value = null;
    try {
      const { data } = await api.get<ArtifactSummary>(`/models/${uid}`);
      artifact.value = data;
    } catch (error: unknown) {
      artifact.value = null;
      artifactError.value = getErrorMessage(error, "Artifact metadata unavailable");
    } finally {
      artifactLoading.value = false;
    }
  },
  { immediate: true },
);

const QUALITY_LABEL_MAP: Record<string, string> = {
  explained_variance_ratio: "Explained Variance (per PC)",
  total_variance_explained: "Total Variance Explained",
  n_components: "Components",
  t2_mean: "T² Mean",
  t2_limit_95: "T² 95% Limit (F-dist)",
  spe_mean: "SPE Mean",
  spe_limit_95: "SPE 95% Limit (χ²)",
  r2: "R²",
  r2_cv: "R² (CV)",
  r2_test: "R² (Test)",
  rmse: "RMSE",
  rmsecv: "RMSECV",
  rmse_test: "Test RMSE",
  mae: "MAE",
  bias: "Bias",
  sep: "SEP",
  rer: "RER",
  q2: "Q²",
  cv_method: "CV Method",
  accuracy: "Accuracy",
  train_accuracy: "Train Accuracy",
  cv_accuracy: "CV Accuracy",
  test_accuracy: "Test Accuracy",
  train_balanced_accuracy: "Train Balanced Accuracy",
  cv_balanced_accuracy: "CV Balanced Accuracy",
  test_balanced_accuracy: "Test Balanced Accuracy",
  train_f1_macro: "Train F1 (macro)",
  cv_f1_macro: "CV F1 (macro)",
  test_f1_macro: "Test F1 (macro)",
  train_precision_macro: "Train Precision",
  cv_precision_macro: "CV Precision",
  test_precision_macro: "Test Precision",
  train_recall_macro: "Train Recall",
  cv_recall_macro: "CV Recall",
  test_recall_macro: "Test Recall",
  train_sensitivity_macro: "Train Sensitivity",
  cv_sensitivity_macro: "CV Sensitivity",
  test_sensitivity_macro: "Test Sensitivity",
  train_specificity_macro: "Train Specificity",
  cv_specificity_macro: "CV Specificity",
  test_specificity_macro: "Test Specificity",
  balanced_accuracy: "Balanced Accuracy",
  f1: "F1 Score",
  f1_macro: "F1 (macro)",
  n_classes: "Classes",
  n_neighbors: "Neighbors (k)",
  confidence_level: "Confidence Level",
  n_clusters: "Clusters",
  silhouette_score: "Silhouette Score",
  inertia: "Inertia",
  linkage: "Linkage",
  metric: "Distance Metric",
  n_peaks: "Peaks Found",
  n_consensus_peaks: "Consensus Peaks",
  kernel: "Kernel",
  method: "Method",
  algorithm: "Algorithm",
  reconstruction_err: "Reconstruction Error",
  n_iter: "Iterations",
  lof_percent: "LOF (%)",
  residual_rms: "Residual RMS",
};

const formatQualityLabel = (key: string): string =>
  QUALITY_LABEL_MAP[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const formatQualityValue = (val: unknown): string => {
  if (val == null) return "\u2014";
  if (typeof val === "number") {
    if (Number.isInteger(val)) return String(val);
    return val < 0.01 ? val.toExponential(3) : val.toFixed(4);
  }
  if (Array.isArray(val)) {
    const preview = val.slice(0, 6).map((v: unknown) =>
      typeof v === "number" ? (v < 0.01 ? v.toExponential(2) : v.toFixed(3)) : String(v)
    );
    const suffix = val.length > 6 ? `, \u2026 (${val.length})` : "";
    return `[${preview.join(", ")}${suffix}]`;
  }
  return String(val);
};

// Preview and pcaDiagnostics are bundled tables in the new slice; re-expose
// the individual fields the template reads (rows / columns / summary).
const outputPreview = computed(() => output.preview.value.rows);
const outputPreviewColumns = computed(() => output.preview.value.columns);
const outputDataSummary = computed(() => output.preview.value.summary);
const peakIdSummary = computed(() => {
  if (state.plots.value.nodeTypeKey !== "analysis.peak_id") return "";
  const summary = outputMetadata.value?.summary;
  return typeof summary === "string" ? summary.trim() : "";
});
const pcaDiagnosticsPreview = computed(() => output.pcaDiagnostics.value.rows);
const pcaDiagnosticsColumns = computed(() => output.pcaDiagnostics.value.columns);
const pcaDiagSummary = computed(() => output.pcaDiagnostics.value.summary);

// Writable ref shared with shell: mutating .value here propagates back.
const regressionTargetIdx = writable.regressionTargetIdx;
</script>

<style scoped>
/* Section chrome — duplicated pending style consolidation in plan step 6 */
.detail-section {
  background: #1e293b;
  border-radius: 12px;
  margin-bottom: 24px;
  overflow: hidden;
  border: 1px solid #334155;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  cursor: pointer;
  transition: background 0.15s;
}
.section-header:hover { background: rgba(51, 65, 85, 0.5); }
.section-title { display: flex; align-items: center; gap: 12px; }
.section-title i { font-size: 0.85rem; color: #64748b; }
.section-title h2 { margin: 0; font-size: 1.1rem; font-weight: 600; }
.section-badge {
  padding: 4px 10px;
  background: #334155;
  border-radius: 12px;
  font-size: 0.75rem;
  color: #94a3b8;
}
.section-content { padding: 20px; border-top: 1px solid #334155; }
.collapse-enter-active,
.collapse-leave-active { transition: all 0.2s ease; overflow: hidden; }
.collapse-enter-from,
.collapse-leave-to { opacity: 0; max-height: 0; padding-top: 0; padding-bottom: 0; }
.empty-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
}
.empty-section i { font-size: 2.5rem; margin-bottom: 16px; color: #475569; }
.empty-section p { margin: 0 0 8px; font-size: 1rem; }
.empty-section small { color: #475569; font-size: 0.85rem; }

.output-content { display: flex; flex-direction: column; gap: 18px; }
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 14px;
  background: #0f172a;
  border-radius: 8px;
}
.info-item label {
  font-size: 0.75rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.info-item span { font-size: 0.95rem; color: #f8fafc; font-weight: 500; }

/* Inspector sections (coordinates / metadata / processing / provenance / quality / ports) */
.inspector-section {
  padding: 12px 14px;
  background: #0f172a;
  border-radius: 8px;
  border: 1px solid #1e293b;
  overflow: hidden;
  min-width: 0;
}
.inspector-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 4px 0;
  background: none;
  border: none;
  color: #e2e8f0;
  cursor: pointer;
  font-size: 0.9rem;
}
.inspector-toggle:hover { color: #f8fafc; }
.inspector-toggle-title { display: flex; align-items: center; gap: 8px; font-weight: 500; }
.inspector-toggle-title i { color: #64748b; }
.inspector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-top: 10px;
}
.inspector-item { display: flex; flex-direction: column; gap: 3px; }
.inspector-item.wide { grid-column: 1 / -1; }
.insp-label {
  font-size: 0.7rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.insp-value { font-size: 0.9rem; color: #f8fafc; }
.insp-value.mono { font-family: "JetBrains Mono", monospace; font-size: 0.85rem; }
.insp-units { color: #64748b; font-size: 0.85rem; margin-left: 4px; }
.artifact-link {
  align-self: flex-start;
  padding: 0;
  border: 0;
  background: transparent;
  color: #93c5fd;
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.artifact-link:hover {
  color: #bfdbfe;
  text-decoration: underline;
}
.insp-badge {
  display: inline-block;
  padding: 2px 8px;
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
  border-radius: 10px;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.insp-label-table-wrap { overflow-x: auto; max-width: 100%; }
.insp-label-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  margin-top: 6px;
}
.insp-label-table th {
  text-align: left;
  padding: 4px 8px;
  color: #64748b;
  font-weight: 500;
  border-bottom: 1px solid #1e293b;
}
.insp-label-table td { padding: 4px 8px; color: #cbd5e1; }
.insp-label-table .label-row-index { color: #64748b; font-variant-numeric: tabular-nums; }
.insp-label-table .label-cell { font-family: "JetBrains Mono", monospace; font-size: 0.75rem; }
.insp-more { display: block; margin-top: 6px; color: #64748b; font-size: 0.8rem; }

/* Saved Model Artifact section (training nodes only). Mirrors the
   inspector-section visual but reserves a primary-accent leading stripe
   so the artifact reference reads as "this is the persistent output of
   this node," distinct from the transient quality summary above it. */
.model-artifact {
  margin-top: 10px;
  border-left: 2px solid #3b82f6;
  padding-left: 10px;
}
.model-artifact__grid {
  margin-top: 0;
}
.model-artifact__status {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 0.85rem;
  padding: 4px 0;
}
.model-artifact__status--error {
  color: #f87171;
}
.model-artifact__uid {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.75rem;
  color: #64748b;
  margin-left: auto;
}
.model-artifact__actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}

.metadata-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
  max-width: 100%;
  overflow: hidden;
}
.metadata-item {
  display: grid;
  grid-template-columns: 120px 1fr;
  align-items: start;
  gap: 8px;
  padding: 6px 10px;
  background: #020617;
  border-radius: 6px;
  min-width: 0;
  overflow: hidden;
}
.meta-key {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  min-width: 0;
  word-break: break-word;
}
.meta-info-icon { color: #475569; font-size: 0.75rem; cursor: help; flex-shrink: 0; }
.meta-value {
  font-size: 0.85rem;
  color: #f8fafc;
  word-break: break-word;
  overflow-wrap: break-word;
  min-width: 0;
}

/* Processing timeline */
.processing-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}
.timeline-item {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 10px;
  padding: 8px 10px;
  background: #020617;
  border-radius: 6px;
}
.step-number {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1e293b;
  color: #94a3b8;
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: 600;
}
.step-content { display: flex; flex-direction: column; gap: 6px; }
.step-operation { color: #f8fafc; font-size: 0.9rem; font-weight: 500; }
.step-params {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.param-chip {
  padding: 2px 6px;
  background: #1e293b;
  color: #cbd5e1;
  border-radius: 4px;
  font-size: 0.75rem;
  font-family: "JetBrains Mono", monospace;
}
.step-shapes { display: flex; gap: 6px; }
.shape-badge {
  padding: 2px 6px;
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
  border-radius: 4px;
  font-size: 0.75rem;
  font-family: "JetBrains Mono", monospace;
}

/* Port summaries */
.port-summaries {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}
.port-summary-card {
  padding: 10px 12px;
  background: #020617;
  border-radius: 6px;
  border: 1px solid #1e293b;
}
.port-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.port-name { color: #f8fafc; font-weight: 500; font-size: 0.9rem; }
.port-type-badge {
  padding: 2px 6px;
  background: rgba(168, 85, 247, 0.15);
  color: #a855f7;
  border-radius: 4px;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.port-details {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: #94a3b8;
  font-size: 0.8rem;
}

.full-meta-action { display: flex; justify-content: flex-start; }
.output-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.preview-datatable :deep(.p-datatable-wrapper) {
  background: #0f172a;
  border-radius: 6px;
  overflow: hidden;
}
.preview-datatable :deep(.p-datatable-thead > tr > th) {
  background: #1e293b;
  color: #94a3b8;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid #334155;
}
.preview-datatable :deep(.p-datatable-tbody > tr) {
  background: #0f172a;
  color: #cbd5e1;
}
.preview-datatable :deep(.p-datatable-tbody > tr:nth-child(even)) {
  background: #111e33;
}
.preview-datatable :deep(.p-datatable-tbody > tr > td) {
  border-bottom: 1px solid #1e293b;
  font-size: 0.85rem;
}
.preview-table h4 {
  margin: 0 0 10px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.analysis-summary {
  padding: 12px 14px;
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 8px;
}
.analysis-summary h4 {
  margin: 0 0 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.analysis-summary p {
  margin: 0;
  color: #cbd5e1;
  font-size: 0.9rem;
  line-height: 1.5;
}
.detail-target-dropdown { width: 100%; }
</style>
