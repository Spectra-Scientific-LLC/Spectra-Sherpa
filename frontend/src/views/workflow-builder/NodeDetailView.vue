<template>
  <div class="node-detail-view">
    <!-- Header -->
    <header class="detail-header">
      <div class="header-left">
        <span class="node-icon">{{ nodeIcon }}</span>
        <div class="header-info">
          <h1>{{ nodeLabel }}</h1>
          <span class="node-type-badge">{{ nodeType }}</span>
        </div>
      </div>
      <div class="header-actions">
        <Button
          label="Run Trial"
          icon="pi pi-play"
          class="p-button-success"
          :loading="isExecuting"
          :disabled="hasValidationErrors"
          @click="handleRunTrial"
          :title="hasValidationErrors ? 'Fix validation errors before running' : 'Run trial execution with current parameters'"
        />
        <Button
          label="Cancel"
          icon="pi pi-times"
          class="p-button-text p-button-secondary"
          @click="handleCancel"
        />
        <Button
          label="Save and Exit"
          icon="pi pi-check"
          class="p-button-primary"
          @click="handleSaveAndExit"
        />
      </div>
    </header>

    <!-- Main Content -->
    <main class="detail-content">
      <!-- Input Section -->
      <section class="detail-section">
        <div class="section-header" @click="toggleSection('input')">
          <div class="section-title">
            <i :class="sections.input ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            <h2>Input</h2>
          </div>
          <span class="section-badge" v-if="inputSummary">{{ inputSummary }}</span>
        </div>
        <Transition name="collapse">
          <div v-if="sections.input" class="section-content">
            <div v-if="!hasInput" class="empty-section">
              <i class="pi pi-inbox" />
              <p>No input data available</p>
              <small>This node has not received input yet. Execute the workflow to see input data.</small>
            </div>
            <div v-else class="input-content">
              <!-- Input source info -->
              <div class="info-grid">
                <div class="info-item" v-if="inputData?.shape">
                  <label>Shape</label>
                  <span>{{ inputData.shape[0] }} x {{ inputData.shape[1] }}</span>
                </div>
                <div class="info-item" v-if="inputData?.source">
                  <label>Source</label>
                  <span>{{ inputData.source }}</span>
                </div>
                <div class="info-item" v-if="inputData?.dataType">
                  <label>Data Type</label>
                  <span>{{ inputData.dataType }}</span>
                </div>
              </div>

              <!-- Input connections -->
              <div v-if="inputConnections.length" class="connections-list">
                <h4>Connected From</h4>
                <div
                  v-for="conn in inputConnections"
                  :key="conn.nodeId"
                  class="connection-item"
                >
                  <span class="conn-icon">{{ conn.icon }}</span>
                  <span class="conn-name">{{ conn.label }}</span>
                  <span class="conn-port">{{ conn.port }}</span>
                </div>
              </div>

              <!-- Preview table -->
              <div v-if="inputPreview.length" class="preview-table">
                <h4>Input Preview ({{ inputDataSummary }})</h4>
                <DataTable
                  :value="inputPreview"
                  :scrollable="true"
                  scrollHeight="200px"
                  class="preview-datatable"
                  size="small"
                >
                  <Column
                    v-for="col in inputPreviewColumns"
                    :key="col.field"
                    :field="col.field"
                    :header="col.header"
                    :style="{ minWidth: '80px' }"
                  />
                </DataTable>
              </div>
            </div>
          </div>
        </Transition>
      </section>

      <!-- Settings Section -->
      <section class="detail-section">
        <div class="section-header" @click="toggleSection('settings')">
          <div class="section-title">
            <i :class="sections.settings ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            <h2>Settings</h2>
          </div>
          <span class="section-badge" v-if="settingsCount">{{ settingsCount }} parameters</span>
        </div>
        <Transition name="collapse">
          <div v-if="sections.settings" class="section-content">
            <!-- Validation error banner -->
            <div v-if="hasValidationErrors" class="validation-error-banner">
              <div class="error-banner-header">
                <i class="pi pi-exclamation-triangle"></i>
                <div class="error-banner-content">
                  <strong>{{ displayedValidationErrors.length }} validation error{{ displayedValidationErrors.length > 1 ? 's' : '' }}</strong>
                  <span>Please fix the following errors before running:</span>
                </div>
              </div>
              <ul class="error-list">
                <li v-for="error in displayedValidationErrors" :key="error.param_name">
                  <strong>{{ error.param_name }}:</strong> {{ error.message }}
                </li>
              </ul>
            </div>

            <div v-if="!nodeParams.length" class="empty-section">
              <i class="pi pi-cog" />
              <p>No configurable parameters</p>
              <small>This node type does not have any settings to configure.</small>
            </div>
            <div v-else class="settings-form">
              <div
                v-for="param in nodeParams"
                :key="param.name"
                class="param-field"
                :class="{ 'has-error': getParamError(param.name) }"
              >
                <label :for="param.name">
                  {{ param.label }}
                  <span v-if="param.required" class="required-mark">*</span>
                </label>
                <small v-if="param.description" class="param-description">
                  {{ param.description }}
                </small>

                <!-- Number input -->
                <InputNumber
                  v-if="param.type === 'number'"
                  v-model="localParams[param.name]"
                  :id="param.name"
                  :min="param.min"
                  :max="param.max"
                  :step="param.step || 1"
                  :minFractionDigits="param.step && param.step < 1 ? 2 : 0"
                  :maxFractionDigits="param.step && param.step < 1 ? 4 : 0"
                  :placeholder="param.required ? '' : 'Optional input'"
                  class="full-width"
                  :class="{ 'p-invalid': getParamError(param.name) }"
                />

                <!-- Boolean toggle -->
                <div v-else-if="param.type === 'boolean'" class="toggle-field">
                  <InputSwitch v-model="localParams[param.name]" :id="param.name" />
                  <span class="toggle-label">{{ localParams[param.name] ? 'Enabled' : 'Disabled' }}</span>
                </div>

                <!-- Dropdown select -->
                <Dropdown
                  v-else-if="param.type === 'select'"
                  v-model="localParams[param.name]"
                  :id="param.name"
                  :options="param.options"
                  :optionLabel="param.optionLabel || 'label'"
                  :optionValue="param.optionValue || 'value'"
                  class="full-width"
                  :class="{ 'p-invalid': getParamError(param.name) }"
                />

                <!-- Text input -->
                <InputText
                  v-else
                  v-model="localParams[param.name]"
                  :id="param.name"
                  :placeholder="param.required ? '' : 'Optional input'"
                  class="full-width"
                  :class="{ 'p-invalid': getParamError(param.name) }"
                />

                <!-- Error message -->
                <small v-if="getParamError(param.name)" class="param-error-message">
                  {{ getParamError(param.name) }}
                </small>
              </div>

              <!-- Reset to defaults button -->
              <div class="settings-actions">
                <Button
                  label="Reset to Defaults"
                  icon="pi pi-refresh"
                  class="p-button-outlined p-button-secondary"
                  @click="resetToDefaults"
                />
              </div>
            </div>
          </div>
        </Transition>
      </section>

      <!-- Output Section -->
      <section class="detail-section">
        <div class="section-header" @click="toggleSection('output')">
          <div class="section-title">
            <i :class="sections.output ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            <h2>Output</h2>
          </div>
          <span class="section-badge" v-if="outputSummary">{{ outputSummary }}</span>
        </div>
        <Transition name="collapse">
          <div v-if="sections.output" class="section-content">
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
                  @click="toggleOutputSubsection('coordinates')"
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
                    <div v-if="datasetInfo.xAxis.points" class="inspector-item">
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
                    <div v-if="datasetInfo.yAxis.nSamples" class="inspector-item">
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

              <!-- Output metadata (scientific results) -->
              <div v-if="Object.keys(outputMetadata).length" class="inspector-section metadata-section">
                <button
                  type="button"
                  class="inspector-toggle"
                  @click="toggleOutputSubsection('metadata')"
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
                        v-if="getMetaTooltip(key)"
                        class="pi pi-info-circle meta-info-icon"
                        :title="getMetaTooltip(key)"
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
                  @click="toggleOutputSubsection('processing')"
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
                        {{ typeof step === 'string' ? step : step.operation || 'unknown' }}
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
                  @click="toggleOutputSubsection('provenance')"
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
                  <template v-for="(val, key) in provenanceInfo" :key="key">
                    <div
                      v-if="!['source_type', 'operations', 'last_modified'].includes(String(key)) && typeof val !== 'object'"
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
                  @click="toggleOutputSubsection('quality')"
                >
                  <span class="inspector-toggle-title">
                    <i class="pi pi-check-circle" />
                    Quality
                  </span>
                  <i :class="outputSubsections.quality ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                </button>
                <div v-if="outputSubsections.quality" class="inspector-grid">
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
                </div>
              </div>

              <!-- Secondary Port Outputs -->
              <div v-if="portSummaries.length > 0" class="inspector-section">
                <button
                  type="button"
                  class="inspector-toggle"
                  @click="toggleOutputSubsection('ports')"
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
                      <span v-if="port.xTitle">X: {{ port.xTitle }}<template v-if="port.xUnits"> ({{ port.xUnits }})</template><template v-if="port.xPoints">, {{ port.xPoints }} pts</template></span>
                      <span v-if="port.yTitle">Y: {{ port.yTitle }}<template v-if="port.nLabels">, {{ port.nLabels }} labels</template></span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- View Full Metadata button -->
              <div v-if="hasOutput" class="full-meta-action">
                <Button
                  label="View Full Metadata (JSON)"
                  icon="pi pi-code"
                  class="p-button-sm p-button-text"
                  @click="showFullMetadata = true"
                />
              </div>

              <!-- Quick actions -->
              <div class="output-actions">
                <Button
                  label="View Data Table"
                  icon="pi pi-table"
                  class="p-button-outlined"
                  @click="openDataTable"
                />
                <Button
                  label="Quick Plot"
                  icon="pi pi-chart-line"
                  class="p-button-outlined"
                  @click="openQuickPlot"
                />
                <Button
                  label="Export CSV"
                  icon="pi pi-download"
                  class="p-button-outlined"
                  @click="exportOutput"
                />
              </div>

              <!-- Preview table -->
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

      <!-- Plots Section -->
      <section class="detail-section" v-if="hasOutput && availablePlots.length > 0">
        <div class="section-header" @click="toggleSection('plots')">
          <div class="section-title">
            <i :class="sections.plots ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            <h2>Plots</h2>
          </div>
          <span class="section-badge">{{ availablePlots.length }} visualizations</span>
        </div>
        <Transition name="collapse">
          <div v-if="sections.plots" class="section-content plots-content">
            <!-- PCA Plots -->
            <template v-if="isPCAOutput">
              <!-- Scores Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('pcaScores')">
                  <i :class="plotSections.pcaScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Scores Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.pcaScores" class="plot-container">
                    <div class="plot-controls">
                      <div class="control-group">
                        <label>X Axis</label>
                        <Dropdown v-model="pcaXAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                      <div class="control-group">
                        <label>Y Axis</label>
                        <Dropdown v-model="pcaYAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                    </div>
                    <PlotlyChart :data="pcaScoresData" :layout="pcaScoresLayout" :config="pcaScoresConfig" />
                  </div>
                </Transition>
              </div>

              <!-- Biplot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('pcaBiplot')">
                  <i :class="plotSections.pcaBiplot ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Biplot (Scores + Loadings)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.pcaBiplot" class="plot-container">
                    <div class="plot-controls">
                      <div class="control-group">
                        <label>X Axis</label>
                        <Dropdown v-model="pcaXAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                      <div class="control-group">
                        <label>Y Axis</label>
                        <Dropdown v-model="pcaYAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                    </div>
                    <PlotlyChart :data="pcaBiplotData" :layout="pcaBiplotLayout" :config="pcaScoresConfig" />
                  </div>
                </Transition>
              </div>

              <!-- Loadings Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('pcaLoadings')">
                  <i :class="plotSections.pcaLoadings ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Loadings Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.pcaLoadings" class="plot-container">
                    <PlotlyChart :data="pcaLoadingsData" :layout="pcaLoadingsLayout" :config="pcaLoadingsConfig" />
                  </div>
                </Transition>
              </div>

              <!-- Scree Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('pcaScree')">
                  <i :class="plotSections.pcaScree ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Scree Plot (Explained Variance)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.pcaScree" class="plot-container">
                    <PlotlyChart :data="pcaScreeData" :layout="pcaScreeLayout" />
                  </div>
                </Transition>
              </div>

              <!-- Diagnostics Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('pcaDiagnostics')">
                  <i :class="plotSections.pcaDiagnostics ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Diagnostics Plot (T² / SPE)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.pcaDiagnostics" class="plot-container">
                    <PlotlyChart :data="pcaDiagnosticsData" :layout="pcaDiagnosticsLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- MCR-ALS Plots -->
            <template v-if="nodeTypeKey === 'model.mcr_als' || nodeTypeKey === 'model.simplisma'">
              <!-- Concentration Profiles -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('mcrConcentrations')">
                  <i :class="plotSections.mcrConcentrations ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Concentration Profiles (C)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.mcrConcentrations" class="plot-container">
                    <PlotlyChart :data="mcrConcentrationData" :layout="mcrConcentrationLayout" />
                  </div>
                </Transition>
              </div>

              <!-- Pure Spectra -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('mcrSpectra')">
                  <i :class="plotSections.mcrSpectra ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Pure Spectra (S<sup>T</sup>)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.mcrSpectra" class="plot-container">
                    <PlotlyChart :data="mcrSpectraData" :layout="mcrSpectraLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- EFA Eigenvalue Plot -->
            <template v-if="nodeTypeKey === 'model.efa'">
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('efaEigenvalues')">
                  <i :class="plotSections.efaEigenvalues ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Eigenvalue Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.efaEigenvalues" class="plot-container">
                    <PlotlyChart :data="efaEigenvalueData" :layout="efaEigenvalueLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- PLS Plots -->
            <template v-if="nodeTypeKey === 'model.pls'">
              <!-- Scores Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plsScores')">
                  <i :class="plotSections.plsScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Scores Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plsScores" class="plot-container">
                    <div class="plot-controls">
                      <div class="control-group">
                        <label>X Axis</label>
                        <Dropdown v-model="pcaXAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                      <div class="control-group">
                        <label>Y Axis</label>
                        <Dropdown v-model="pcaYAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                    </div>
                    <PlotlyChart :data="plsScoresData" :layout="plsScoresLayout" :config="pcaScoresConfig" />
                  </div>
                </Transition>
              </div>

              <!-- Loadings Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plsLoadings')">
                  <i :class="plotSections.plsLoadings ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Loadings Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plsLoadings" class="plot-container">
                    <PlotlyChart :data="plsLoadingsData" :layout="plsLoadingsLayout" :config="pcaLoadingsConfig" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- PLS-DA Plots -->
            <template v-if="nodeTypeKey === 'classification.plsda'">
              <!-- Scores Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('classificationScores')">
                  <i :class="plotSections.classificationScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Scores Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.classificationScores" class="plot-container">
                    <div class="plot-controls">
                      <div class="control-group">
                        <label>X Axis</label>
                        <Dropdown v-model="pcaXAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                      <div class="control-group">
                        <label>Y Axis</label>
                        <Dropdown v-model="pcaYAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                    </div>
                    <PlotlyChart :data="classificationScoresData" :layout="classificationScoresLayout" :config="pcaScoresConfig" />
                  </div>
                </Transition>
              </div>

              <!-- Loadings Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plsdaLoadings')">
                  <i :class="plotSections.plsdaLoadings ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Loadings Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plsdaLoadings" class="plot-container">
                    <div class="plot-controls">
                      <Button
                        :label="'Line Plot'"
                        :class="{ 'p-button-outlined': plsdaLoadingsViewMode !== 'lines' }"
                        @click="plsdaLoadingsViewMode = 'lines'"
                        size="small"
                      />
                      <Button
                        :label="'Biplot'"
                        :class="{ 'p-button-outlined': plsdaLoadingsViewMode !== 'biplot' }"
                        @click="plsdaLoadingsViewMode = 'biplot'"
                        size="small"
                      />
                    </div>
                    <PlotlyChart :data="plsdaLoadingsData" :layout="plsdaLoadingsLayout" :config="pcaLoadingsConfig" />
                  </div>
                </Transition>
              </div>

              <!-- VIP Scores Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plsdaVip')">
                  <i :class="plotSections.plsdaVip ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>VIP Scores (Variable Importance)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plsdaVip" class="plot-container">
                    <PlotlyChart :data="plsdaVipData" :layout="plsdaVipLayout" />
                  </div>
                </Transition>
              </div>

              <!-- Confusion Matrix (Training) -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plsdaConfusionTrain')">
                  <i :class="plotSections.plsdaConfusionTrain ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Confusion Matrix (Training)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plsdaConfusionTrain" class="plot-container">
                    <PlotlyChart :data="plsdaConfusionTrainData" :layout="plsdaConfusionTrainLayout" />
                  </div>
                </Transition>
              </div>

              <!-- Confusion Matrix (Cross-Validation) -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plsdaConfusionCV')">
                  <i :class="plotSections.plsdaConfusionCV ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Confusion Matrix (Cross-Validation)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plsdaConfusionCV" class="plot-container">
                    <PlotlyChart :data="plsdaConfusionCVData" :layout="plsdaConfusionCVLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- SIMCA Plots -->
            <template v-if="nodeTypeKey === 'classification.simca'">
              <!-- Scores Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('classificationScores')">
                  <i :class="plotSections.classificationScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Scores Plot (Class Model Projections)</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.classificationScores" class="plot-container">
                    <div class="plot-controls">
                      <div class="control-group">
                        <label>X Axis</label>
                        <Dropdown v-model="pcaXAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                      <div class="control-group">
                        <label>Y Axis</label>
                        <Dropdown v-model="pcaYAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                    </div>
                    <PlotlyChart :data="classificationScoresData" :layout="classificationScoresLayout" :config="pcaScoresConfig" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- KNN Plots -->
            <template v-if="nodeTypeKey === 'classification.knn'">
              <!-- Scores Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('classificationScores')">
                  <i :class="plotSections.classificationScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Feature Space Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.classificationScores" class="plot-container">
                    <div class="plot-controls">
                      <div class="control-group">
                        <label>X Axis</label>
                        <Dropdown v-model="pcaXAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                      <div class="control-group">
                        <label>Y Axis</label>
                        <Dropdown v-model="pcaYAxis" :options="pcaAxisOptions" optionLabel="label" optionValue="value" />
                      </div>
                    </div>
                    <PlotlyChart :data="classificationScoresData" :layout="classificationScoresLayout" :config="pcaScoresConfig" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- Predicted vs Actual (Regression) — PLS/PCR/SVR only -->
            <template v-if="['model.pls', 'model.pcr', 'model.svr'].includes(nodeTypeKey) && regressionCorrelationData.length > 0">
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('regressionCorrelation')">
                  <i :class="plotSections.regressionCorrelation ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Predicted vs Actual</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.regressionCorrelation" class="plot-container">
                    <div v-if="regressionTargetOptions.length > 1" class="plot-controls">
                      <div class="control-group">
                        <label>Target</label>
                        <Dropdown v-model="regressionTargetIdx" :options="regressionTargetOptions" optionLabel="label" optionValue="value" />
                      </div>
                    </div>
                    <PlotlyChart :data="regressionCorrelationData" :layout="regressionCorrelationLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- Per-Class Accuracy (Classification) — PLS-DA/SIMCA/KNN only -->
            <template v-if="['classification.plsda', 'classification.simca', 'classification.knn'].includes(nodeTypeKey) && classificationAccuracyData.length > 0">
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('classificationAccuracy')">
                  <i :class="plotSections.classificationAccuracy ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Per-Class Accuracy</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.classificationAccuracy" class="plot-container">
                    <PlotlyChart :data="classificationAccuracyData" :layout="classificationAccuracyLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- HCA Plots -->
            <template v-if="nodeTypeKey === 'model.hca'">
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('hcaDendrogram')">
                  <i :class="plotSections.hcaDendrogram ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Dendrogram</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.hcaDendrogram" class="plot-container">
                    <PlotlyChart :data="hcaDendrogramData" :layout="hcaDendrogramLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- Peak Finding Plot (pre-computed on the backend) -->
            <template v-if="nodeTypeKey === 'analysis.peak_finding'">
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('peakFinding')">
                  <i :class="plotSections.peakFinding ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Spectra with Peaks</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.peakFinding" class="plot-container">
                    <PlotlyChart :data="peakFindingPlotData" :layout="peakFindingPlotLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- Plot / Contour Node Visualization (server-rendered Plotly) -->
            <template v-if="nodeTypeKey === 'output.plot' || nodeTypeKey === 'output.contour'">
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plotVisualization')">
                  <i :class="plotSections.plotVisualization ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Visualization</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plotVisualization" class="plot-container">
                    <PlotlyChart v-if="plotNodeData.length > 0" :data="plotNodeData" :layout="plotNodeLayout" />
                    <div v-else class="empty-plot-message">
                      <i class="pi pi-play" />
                      <span>Run the node to generate the visualization.</span>
                    </div>
                  </div>
                </Transition>
              </div>
            </template>

            <!-- Preprocessing / DATA Plots with Interactive Contour -->
            <template v-if="(isPreprocessingNode || isDataNode) && isSpectraData">
              <!-- Spectra Overview - Only for spectral data -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('spectraOverview')">
                  <i :class="plotSections.spectraOverview ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Spectra Overview</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.spectraOverview" class="plot-container">
                    <div class="plot-controls">
                      <div class="control-group">
                        <label>Display</label>
                        <Dropdown v-model="spectraDisplayMode" :options="spectraDisplayOptions" optionLabel="label" optionValue="value" />
                      </div>
                    </div>
                    <PlotlyChart
                      v-if="spectraDisplayMode === 'overlay'"
                      :data="spectraOverlayData"
                      :layout="spectraOverlayLayout"
                    />
                    <div v-else class="interactive-contour-container">
                      <PlotlyChart
                        :data="spectraContourData"
                        :layout="spectraContourLayout"
                        @click="handleContourClick"
                      />
                      <!-- Slice plots below contour -->
                      <div v-if="contourClickPoint" class="slice-plots">
                        <div class="slice-plot">
                          <h5>Spectrum at Sample {{ contourClickPoint.sampleIdx + 1 }}</h5>
                          <PlotlyChart :data="horizontalSliceData" :layout="horizontalSliceLayout" />
                        </div>
                        <div class="slice-plot">
                          <h5>Time Profile at {{ contourClickPoint.wavenumber.toFixed(1) }} {{ nodeOutput?.metadata?.x_units || '' }}</h5>
                          <PlotlyChart :data="verticalSliceData" :layout="verticalSliceLayout" />
                        </div>
                      </div>
                      <div v-else class="slice-hint">
                        <i class="pi pi-info-circle" />
                        <span>Click on the contour plot to view spectral and temporal slices</span>
                      </div>
                    </div>
                  </div>
                </Transition>
              </div>
            </template>

            <!-- Generic Data Overview - For non-spectral datasets like Iris -->
            <template v-if="isGenericDataNode">
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('dataOverview')">
                  <i :class="plotSections.dataOverview ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Data Overview</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.dataOverview" class="plot-container">
                    <div class="plot-controls">
                      <div class="control-group">
                        <label>Display</label>
                        <Dropdown v-model="genericDisplayMode" :options="genericDisplayOptions" optionLabel="label" optionValue="value" />
                      </div>
                      <!-- Feature selectors for scatter plot -->
                      <template v-if="genericDisplayMode === 'scatter'">
                        <div class="control-group">
                          <label>X Axis</label>
                          <Dropdown v-model="featureXAxis" :options="featureOptions" optionLabel="label" optionValue="value" />
                        </div>
                        <div class="control-group">
                          <label>Y Axis</label>
                          <Dropdown v-model="featureYAxis" :options="featureOptions" optionLabel="label" optionValue="value" />
                        </div>
                      </template>
                    </div>
                    <PlotlyChart
                      v-if="genericDisplayMode === 'boxplot'"
                      :data="genericBoxPlotData"
                      :layout="genericBoxPlotLayout"
                    />
                    <PlotlyChart
                      v-else
                      :data="genericScatterData"
                      :layout="genericScatterLayout"
                    />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- STATS Plots -->
            <template v-if="nodeTypeKey === 'stats.summary'">
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('statsDistribution')">
                  <i :class="plotSections.statsDistribution ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Summary Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.statsDistribution" class="plot-container">
                    <PlotlyChart :data="statsPlotData" :layout="statsPlotLayout" />
                  </div>
                </Transition>
              </div>
            </template>

            <!-- PLS Plots -->
            <template v-if="nodeTypeKey === 'model.pls'">
              <!-- Scores Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plsScores')">
                  <i :class="plotSections.plsScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Scores Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plsScores" class="plot-container">
                    <PlotlyChart :data="plsScoresData" :layout="plsScoresLayout" />
                  </div>
                </Transition>
              </div>

              <!-- Loadings Plot -->
              <div class="plot-subsection">
                <div class="plot-subsection-header" @click="togglePlot('plsLoadings')">
                  <i :class="plotSections.plsLoadings ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                  <span>Loadings Plot</span>
                </div>
                <Transition name="collapse">
                  <div v-if="plotSections.plsLoadings" class="plot-container">
                    <PlotlyChart :data="plsLoadingsData" :layout="plsLoadingsLayout" />
                  </div>
                </Transition>
              </div>
            </template>

          </div>
        </Transition>
      </section>

      <!-- Log Section -->
      <section class="detail-section">
        <div class="section-header" @click="toggleSection('log')">
          <div class="section-title">
            <i :class="sections.log ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
            <h2>Execution Log</h2>
          </div>
          <span class="section-badge" v-if="executionLogs.length">{{ executionLogs.length }} entries</span>
        </div>
        <Transition name="collapse">
          <div v-if="sections.log" class="section-content log-content">
            <div v-if="executionLogs.length === 0" class="empty-section">
              <i class="pi pi-list" />
              <p>No execution logs yet</p>
              <small>Click "Run Node" to execute and see logs here.</small>
            </div>
            <div v-else class="log-entries">
              <div
                v-for="(log, idx) in executionLogs"
                :key="idx"
                class="log-entry"
                :class="log.type"
              >
                <span class="log-time">{{ log.time }}</span>
                <span class="log-icon">
                  <i :class="getLogIcon(log.type)" />
                </span>
                <span class="log-message">{{ log.message }}</span>
                <span v-if="log.details" class="log-details">{{ log.details }}</span>
              </div>
            </div>
            <div v-if="executionLogs.length > 0" class="log-actions">
              <Button
                label="Clear Log"
                icon="pi pi-trash"
                class="p-button-sm p-button-text p-button-secondary"
                @click="clearLogs"
              />
            </div>
          </div>
        </Transition>
      </section>
    </main>

    <!-- Modals -->
    <QuickPlotModal
      v-model="showQuickPlotModal"
      :nodeOutput="nodeOutput"
      :nodeType="nodeType"
      :nodeLabel="nodeLabel"
      :nodeInput="inputData"
    />
    <DataTableModal
      v-model="showDataTableModal"
      :nodeOutput="nodeOutput"
      :nodeType="nodeType"
      :nodeLabel="nodeLabel"
    />

    <!-- Full Metadata Modal -->
    <Dialog
      v-model:visible="showFullMetadata"
      header="Full Metadata (JSON)"
      :style="{ width: '720px', maxHeight: '80vh' }"
      :modal="true"
      class="full-metadata-dialog"
    >
      <pre class="full-metadata-json">{{ fullMetadataJson }}</pre>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import InputSwitch from "primevue/inputswitch";
import Dropdown from "primevue/dropdown";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import { useToast } from "primevue/usetoast";
import QuickPlotModal from "./modals/QuickPlotModal.vue";
import DataTableModal from "./modals/DataTableModal.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore } from "@/stores/workflow";
import { createCategoryColorMap } from "@/utils/colors";
import { getYAxisLabel, getXAxisLabel, isSpectralData as checkIsSpectral } from "@/utils/plotLabels";
import { buildNodeOutput, type NodeOutput } from "@/utils/nodeOutput";
import {
  buildLabelTable,
  compactSampleLabel,
  detectLabelDelimiter,
  normalizeSampleLabel,
  splitLabelByDelimiter,
} from "@/utils/sampleLabels";
import api from "@/api/client";


const route = useRoute();
const router = useRouter();
const toast = useToast();

// Session storage key for passing data between tabs
const STORAGE_KEY = "node_detail_data";

// BroadcastChannel for cross-tab communication
const BROADCAST_CHANNEL_NAME = "workflow_node_updates";
const broadcastChannel = ref<BroadcastChannel | null>(null);

// Execution state
const isExecuting = ref(false);
let executionTimeout: ReturnType<typeof setTimeout> | null = null;

// Section collapse state
const sections = ref({
  input: false,
  settings: false,
  output: false,
  plots: false,
  log: false,
});

const outputSubsections = ref({
  coordinates: false,
  metadata: false,
  processing: false,
  provenance: false,
  quality: false,
  ports: false,
});

// Execution log entries
interface LogEntry {
  time: string;
  type: "info" | "success" | "error" | "warn";
  message: string;
  details?: string;
}
const executionLogs = ref<LogEntry[]>([]);
const previewRowLimit = 50;

const addLog = (type: LogEntry["type"], message: string, details?: string) => {
  const now = new Date();
  const time = now.toLocaleTimeString("en-US", { hour12: false });
  executionLogs.value.unshift({ time, type, message, details });
  // Keep max 50 entries
  if (executionLogs.value.length > 50) {
    executionLogs.value.pop();
  }
};

const clearLogs = () => {
  executionLogs.value = [];
};

const getLogIcon = (type: LogEntry["type"]): string => {
  switch (type) {
    case "success": return "pi pi-check-circle";
    case "error": return "pi pi-times-circle";
    case "warn": return "pi pi-exclamation-triangle";
    default: return "pi pi-info-circle";
  }
};

// Plot subsection collapse state
const plotSections = ref<Record<string, boolean>>({
  pcaScores: false,
  pcaBiplot: false,
  pcaLoadings: false,
  pcaScree: false,
  pcaDiagnostics: false,
  mcrConcentrations: false,
  mcrSpectra: false,
  spectraOverview: false,
  dataOverview: false, // For generic non-spectral data like Iris
  statsDistribution: false,
  plsScores: false,
  plsLoadings: false,
  classificationScores: false,
  plsdaLoadings: false,
  plsdaVip: false,
  plsdaConfusionTrain: false,
  plsdaConfusionCV: false,
  regressionCorrelation: false,
  classificationAccuracy: false,
  hcaDendrogram: false,
  peakFinding: false,
  plotVisualization: false,
  efaEigenvalues: false,
});

// PLS-DA loadings view mode (lines or biplot)
const plsdaLoadingsViewMode = ref<"lines" | "biplot">("lines");

// Regression correlation plot target selector
const regressionTargetIdx = ref(0);

// Modal state
const showQuickPlotModal = ref(false);
const showDataTableModal = ref(false);
const showFullMetadata = ref(false);

// Node data loaded from session storage
const nodeData = ref<any>(null);
const localParams = ref<Record<string, any>>({});
const originalParams = ref<Record<string, any>>({});

// Validation errors
const workflowStore = useWorkflowStore();
const projectStore = useProjectStore();
const validationErrors = ref<Array<{ param_name: string; message: string }>>([]);

// Filter out internal "_metadata" errors from display (these occur when library isn't loaded yet)
const displayedValidationErrors = computed(() => {
  return validationErrors.value.filter(e => e.param_name !== "_metadata");
});

const hasValidationErrors = computed(() => {
  return displayedValidationErrors.value.length > 0;
});

// Validate parameters
const validateParams = () => {
  if (!nodeType.value) {
    validationErrors.value = [];
    return;
  }

  // Skip validation if node library is still loading
  if (workflowStore.isLoadingNodeLibrary) {
    validationErrors.value = [];
    return;
  }

  // Skip validation if node library failed to load or is empty
  if (workflowStore.nodeLibraryLoadError || workflowStore.nodeLibrary.size === 0) {
    validationErrors.value = [];
    return;
  }

  validationErrors.value = workflowStore.validateNodeParams(nodeType.value, localParams.value);
};

// Get error message for a specific parameter (excluding metadata errors)
const getParamError = (paramName: string): string | null => {
  const error = validationErrors.value.find(e => e.param_name === paramName && e.param_name !== "_metadata");
  return error ? error.message : null;
};

// Watch for parameter changes and validate
watch(localParams, () => {
  validateParams();
}, { deep: true });

// Watch for node library to finish loading, then validate
watch(() => workflowStore.isLoadingNodeLibrary, (isLoading) => {
  if (!isLoading && workflowStore.nodeLibrary.size > 0) {
    // Library finished loading, validate now
    validateParams();
  }
});

// Node icon mapping
const NODE_ICONS: Record<string, string> = {
  "data.source": "📊",
  "preprocess.normalize": "📏",
  "preprocess.scale": "📏",
  "baseline.penalized_ls": "📉",
  "preprocess.smooth": "〰️",
  "model.pca": "🔀",
  "model.pls": "📈",
  "model.mcr_als": "🧩",
  "stats.summary": "📊",
  "output.plot": "📈",
  "output.contour": "🗺️",
  "output.export": "💾",
};

// Computed properties
const nodeId = computed(() => route.params.nodeId as string);
const nodeType = computed(() => nodeData.value?.type || "Unknown");
const nodeTypeKey = computed(() => nodeType.value);
const isDataNode = computed(() => nodeType.value.startsWith("data."));

// Detect if data is spectral (vs generic like Iris dataset)
const isSpectraData = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};

  // Use explicit flag if available
  if (metadata.is_spectra !== undefined) {
    return metadata.is_spectra;
  }

  // Check data_type if available
  if (metadata.data_type === "spectra") return true;
  if (metadata.data_type === "generic") return false;

  // Fallback: check if x_title contains spectral keywords
  const xTitle = (metadata.x_title || "").toLowerCase();
  const spectralKeywords = ['wavenumber', 'wavelength', 'raman', 'cm-1', 'cm⁻¹', 'nm', 'shift', 'frequency'];
  return spectralKeywords.some(kw => xTitle.includes(kw));
});

// Detect if data is time-series (kinetic / evolving)
const isTimeSeriesData = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  return !!metadata.is_time_series;
});

// Detect if this is a generic dataset (like Iris) with feature names
const isGenericDataNode = computed(() => {
  if (!isDataNode.value) return false;
  const metadata = nodeOutput.value?.metadata || {};
  const hasFeatureNames = metadata.feature_names && metadata.feature_names.length > 0;
  return !isSpectraData.value && hasFeatureNames;
});

const nodeLabel = computed(() => nodeData.value?.label || `Node ${nodeId.value}`);
const nodeIcon = computed(() => NODE_ICONS[nodeType.value] || "📦");
const nodeMetadata = computed(() => workflowStore.getNodeMetadata(nodeType.value));
const mapMetadataParams = (_nodeType: string, parameters: any[]): any[] => {
  return parameters.map((param) => {
    return {
      name: param.name,
      label: param.label,
      type: param.param_type,
      min: param.min_value,
      max: param.max_value,
      step: param.step,
      options: param.options,
      description: param.description,
      default: param.default,
      required: param.required,
      visible_when: param.visible_when || null,
    };
  });
};

/** Check if a parameter should be visible based on visible_when rules. */
const isParamVisible = (param: any): boolean => {
  if (!param.visible_when) return true;
  for (const [controlParam, allowedValues] of Object.entries(param.visible_when)) {
    const currentValue = String(localParams.value[controlParam] ?? '');
    if (!(allowedValues as string[]).includes(currentValue)) return false;
  }
  return true;
};

const nodeParams = computed(() => {
  let params: any[];
  if (nodeMetadata.value?.parameters?.length) {
    params = mapMetadataParams(nodeType.value, nodeMetadata.value.parameters);
  } else {
    params = nodeData.value?.paramDefinitions || [];
  }
  return params.filter(isParamVisible);
});
const nodeOutput = computed(() => nodeData.value?.output || null);

const hasInput = computed(() => {
  return nodeData.value?.inputConnections?.length > 0 || nodeData.value?.inputData;
});

const hasOutput = computed(() => {
  if (!nodeOutput.value) return false;
  const hasData = nodeOutput.value.data &&
    (Array.isArray(nodeOutput.value.data) ? nodeOutput.value.data.length > 0 : true);
  const hasPlots = nodeOutput.value.plots && Object.keys(nodeOutput.value.plots).length > 0;
  // Visualization nodes may have layout in metadata even when trace data was
  // stripped for sessionStorage transfer (large spectral plots).
  const hasMeta = nodeOutput.value.metadata &&
    Object.keys(nodeOutput.value.metadata).length > 0;
  return !!hasData || !!hasPlots || !!hasMeta;
});

const inputSummary = computed(() => {
  if (!hasInput.value) return "";
  const conns = nodeData.value?.inputConnections?.length || 0;
  return conns > 0 ? `${conns} connection${conns > 1 ? 's' : ''}` : "";
});

const outputSummary = computed(() => {
  if (!hasOutput.value) return "";
  const data = nodeOutput.value?.data;
  if (Array.isArray(data)) {
    const rows = data.length;
    const cols = Array.isArray(data[0]) ? data[0].length : 1;
    return `${rows} x ${cols}`;
  }
  return "Available";
});

const settingsCount = computed(() => nodeParams.value.length);

const inputConnections = computed(() => {
  return nodeData.value?.inputConnections || [];
});

const inputData = computed(() => {
  return nodeData.value?.inputData || null;
});

const outputData = computed(() => {
  if (!hasOutput.value) return null;
  const data = nodeOutput.value.data;
  const metadata = nodeOutput.value.metadata || {};

  if (!Array.isArray(data)) return { type: typeof data };

  const rows = data.length;
  const cols = Array.isArray(data[0]) ? data[0].length : 1;

  // Calculate range
  let min = Infinity, max = -Infinity;
  for (const row of data) {
    if (Array.isArray(row)) {
      for (const val of row) {
        if (typeof val === "number" && !isNaN(val)) {
          min = Math.min(min, val);
          max = Math.max(max, val);
        }
      }
    } else if (typeof row === "number") {
      min = Math.min(min, row);
      max = Math.max(max, row);
    }
  }

  return {
    rows,
    cols,
    type: metadata.type || metadata.output_type || "dataset",
    range: min !== Infinity ? [min, max] : null,
  };
});

const outputMetadata = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const filtered: Record<string, any> = {};

  // Keys shown in dedicated sections (coordinates, processing, provenance)
  const structuredKeys = [
    "data", "wavenumbers", "x_axis", "sample_labels", "labels",
    "processing_history", "provenance", "quality_summary",
    "x_title", "x_units", "y_title", "y_units",
    "data_type", "is_spectra", "spectral_technique", "data_quantity",
    "value_units", "value_units_label",
  ];

  for (const [key, value] of Object.entries(metadata)) {
    if (structuredKeys.includes(key)) continue;
    // Large arrays: summarize
    if (Array.isArray(value) && value.length > 20) {
      filtered[key] = `[${value.length} values]`;
      continue;
    }
    // Nested objects: summarize if too large, otherwise include
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      const keys = Object.keys(value);
      if (keys.length > 10) {
        filtered[key] = `{${keys.length} fields}`;
        continue;
      }
    }
    filtered[key] = value;
  }

  return filtered;
});

/** Coordinate and dataset identity info from the primary output. */
const datasetInfo = computed(() => {
  if (!hasOutput.value || !nodeOutput.value) return null;
  const primaryPort = nodeOutput.value.primary_port;
  const portValue = primaryPort && nodeOutput.value.ports?.[primaryPort]?.value;
  const metadata = nodeOutput.value.metadata || {};
  const info: Record<string, any> = {};

  // X-axis
  const xAxis = portValue?.x_axis;
  if (xAxis?.data?.length) {
    const nums = xAxis.data.filter((v: any) => typeof v === "number" && isFinite(v));
    info.xAxis = {
      title: xAxis.title || metadata.x_title || "Feature",
      units: xAxis.units || metadata.x_units || "",
      points: xAxis.data.length,
      range: nums.length ? [Math.min(...nums), Math.max(...nums)] : null,
    };
  } else if (metadata.x_title || metadata.wavenumbers?.length) {
    info.xAxis = {
      title: metadata.x_title || "Feature",
      units: metadata.x_units || "",
      points: metadata.wavenumbers?.length || metadata.n_features,
    };
  }

  // Y-axis — override title for time-series data
  const defaultSampleTitle = metadata.is_time_series ? "Scan / Time Index" : "Sample";
  const yAxis = portValue?.y_axis;
  if (yAxis) {
    info.yAxis = {
      title: yAxis.title || metadata.y_title || defaultSampleTitle,
      units: yAxis.units || metadata.y_units || "",
      labels: yAxis.labels,
      nSamples: yAxis.data?.length,
    };
  } else if (metadata.sample_labels?.length) {
    info.yAxis = {
      title: metadata.y_title || defaultSampleTitle,
      units: metadata.y_units || "",
      labels: metadata.sample_labels,
      nSamples: metadata.sample_labels.length,
    };
  }

  // Spectral identity
  if (metadata.spectral_technique) info.spectralTechnique = metadata.spectral_technique;
  if (metadata.data_quantity) info.dataQuantity = metadata.data_quantity;
  if (metadata.is_spectra) info.isSpectra = true;
  if (metadata.value_units || metadata.value_units_label) {
    info.valueUnits = metadata.value_units || metadata.value_units_label;
  }
  if (portValue?.title) info.title = portValue.title;

  // Domain context (from SherpaDataset)
  if (metadata.domain_technique) info.domainTechnique = metadata.domain_technique;
  if (metadata.domain_data_quantity) info.domainDataQuantity = metadata.domain_data_quantity;

  return Object.keys(info).length > 0 ? info : null;
});

const labelPreviewLimit = 6;

const datasetLabelTable = computed<{ headers: string[]; rows: string[][] }>(() => {
  const labels = datasetInfo.value?.yAxis?.labels;
  if (!Array.isArray(labels) || labels.length === 0) {
    return { headers: ["Label"], rows: [] };
  }

  const table = buildLabelTable(labels, {
    limit: labelPreviewLimit,
    columnHeaderPrefix: "Field",
  });
  return { headers: table.headers, rows: table.rows };
});

/** Processing history from metadata. */
const processingHistory = computed(() => {
  const hist = nodeOutput.value?.metadata?.processing_history;
  return Array.isArray(hist) && hist.length > 0 ? hist : null;
});

/** Provenance info from metadata. */
const provenanceInfo = computed(() => {
  const prov = nodeOutput.value?.metadata?.provenance;
  return prov && typeof prov === "object" ? prov : null;
});

/** Quality summary from metadata (populated by SherpaDataset serializer). */
const qualitySummary = computed(() => {
  const qs = nodeOutput.value?.metadata?.quality_summary;
  return qs && typeof qs === "object" ? qs as Record<string, unknown> : null;
});

const isRegressionNode = computed(() => ["model.pls", "model.pcr", "model.svr"].includes(nodeTypeKey.value));

/** Summaries of secondary output ports (e.g. loadings, X_loadings, target). */
const portSummaries = computed(() => {
  if (!nodeOutput.value?.ports) return [];
  const summaries: Array<{
    name: string;
    type?: string;
    shape?: number[];
    title?: string;
    xTitle?: string;
    xUnits?: string;
    xPoints?: number;
    yTitle?: string;
    nLabels?: number;
  }> = [];
  for (const [name, port] of Object.entries(nodeOutput.value.ports)) {
    if (name === nodeOutput.value.primary_port) continue;
    const raw = (port as any).value;
    summaries.push({
      name,
      type: (port as any).type,
      shape: raw?.shape,
      title: raw?.title,
      xTitle: raw?.x_axis?.title,
      xUnits: raw?.x_axis?.units,
      xPoints: raw?.x_axis?.data?.length,
      yTitle: raw?.y_axis?.title,
      nLabels: raw?.y_axis?.labels?.length,
    });
  }
  return summaries;
});

/** Full metadata JSON for the inspector modal. */
const fullMetadataJson = computed(() => {
  if (!nodeOutput.value) return "{}";
  const full: Record<string, any> = { metadata: nodeOutput.value.metadata };
  // Include port-level metadata
  if (nodeOutput.value.ports) {
    full.ports = {};
    for (const [name, port] of Object.entries(nodeOutput.value.ports)) {
      const raw = (port as any).value;
      full.ports[name] = {
        type: (port as any).type,
        shape: raw?.shape,
        title: raw?.title,
        x_axis: raw?.x_axis ? { title: raw.x_axis.title, units: raw.x_axis.units, points: raw.x_axis.data?.length } : undefined,
        y_axis: raw?.y_axis ? { title: raw.y_axis.title, labels_count: raw.y_axis.labels?.length } : undefined,
        metadata: (port as any).metadata,
      };
    }
  }
  return JSON.stringify(full, null, 2);
});

const normalizeNodeOutput = (result: any): NodeOutput => {
  const outputPorts = nodeMetadata.value?.output_ports;
  return buildNodeOutput(result, outputPorts);
};

const resolvePortPayload = (port: any): any => {
  if (!port || typeof port !== "object") return port;
  return "value" in port ? port.value : port;
};

const isPCAOutput = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  return nodeTypeKey.value === "model.pca" || metadata.type === "model.pca" || metadata.isPCA === true;
});

const primaryOutputPayload = computed(() => {
  const primaryPort = nodeOutput.value?.primary_port;
  if (!primaryPort) return null;
  return resolvePortPayload(nodeOutput.value?.ports?.[primaryPort]);
});

const pcaSampleLabels = computed<string[]>(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const candidates = [
    metadata.sample_labels,
    metadata.labels,
    primaryOutputPayload.value?.y_axis?.labels,
  ];

  for (const raw of candidates) {
    if (Array.isArray(raw) && raw.length > 0) {
      return raw.map((item) => normalizeSampleLabel(item));
    }
  }

  return [];
});

const pcaLabelCategories = computed<string[]>(() => {
  const labels = pcaSampleLabels.value;
  if (labels.length === 0) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const labelSet = new Set(labels);

  const rawCategories = Array.isArray(metadata.label_categories)
    ? metadata.label_categories.map((item: any) => normalizeSampleLabel(item))
    : [];

  let categories = rawCategories.filter((category: string) => labelSet.has(category));
  if (categories.length === 0) {
    categories = Array.from(labelSet);
  }
  return Array.from(new Set(categories));
});

const pcaUseCategorical = computed(() => {
  const labels = pcaSampleLabels.value;
  const categories = pcaLabelCategories.value;
  if (labels.length === 0 || categories.length < 2) return false;
  // Avoid one-trace-per-sample views (noisy and frequently unreadable).
  if (categories.length >= labels.length) return false;
  return categories.length <= 20;
});

const metaTooltips: Record<string, string> = {
  t2_mean: "Hotelling's T² mean across samples (distance in PCA score space).",
  t2_p95: "95th percentile of Hotelling's T²; common control limit for outliers.",
  spe_mean: "Mean Squared Prediction Error (SPE/Q residuals) across samples.",
  spe_p95: "95th percentile of SPE; common control limit for residual outliers.",
};

const getMetaTooltip = (key: string): string => metaTooltips[key] || "";

// Preview data for tables
const inputPreview = computed(() => {
  const data = nodeData.value?.inputData?.data;
  if (!data || !Array.isArray(data)) return [];
  return data.slice(0, previewRowLimit).map((row: any, i: number) => {
    const obj: any = { _index: i + 1 };
    if (Array.isArray(row)) {
      row.slice(0, 10).forEach((val: any, j: number) => {
        obj[`col_${j}`] = typeof val === "number" ? val.toFixed(4) : val;
      });
    } else {
      obj.value = typeof row === "number" ? row.toFixed(4) : row;
    }
    return obj;
  });
});

const inputDataSummary = computed(() => {
  const data = nodeData.value?.inputData?.data;
  if (!data || !Array.isArray(data)) return "";
  const totalRows = data.length;
  const totalCols = Array.isArray(data[0]) ? data[0].length : 1;
  const shownRows = Math.min(totalRows, previewRowLimit);
  const shownCols = Math.min(totalCols, 10);
  let summary = `${shownRows} of ${totalRows} rows`;
  if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
  return summary;
});

const inputPreviewColumns = computed(() => {
  if (!inputPreview.value.length) return [];
  const first = inputPreview.value[0];
  const metadata = nodeData.value?.inputData?.metadata || {};
  const featureNames = metadata.feature_names || [];
  const xTitle = metadata.x_title || "";

  return Object.keys(first).map((key) => {
    let header = key;
    if (key === "_index") {
      header = "#";
    } else if (key.startsWith("col_")) {
      const colIdx = parseInt(key.replace("col_", ""));
      if (featureNames.length > colIdx) {
        header = featureNames[colIdx];
      } else if (xTitle && xTitle !== "Feature") {
        header = `${xTitle} ${colIdx + 1}`;
      } else {
        header = `Col ${colIdx + 1}`;
      }
    }
    return { field: key, header };
  });
});

const outputPreview = computed(() => {
  const data = nodeOutput.value?.data;
  if (!data || !Array.isArray(data)) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const labelsRaw = metadata.sample_labels || metadata.labels || [];
  const labels = Array.isArray(labelsRaw)
    ? labelsRaw.map((label: any) => normalizeSampleLabel(label))
    : [];
  const labelDelimiter = detectLabelDelimiter(labels);
  const splitLabels = labelDelimiter
    ? labels.map((label: string) => splitLabelByDelimiter(label, labelDelimiter))
    : [];
  const maxLabelParts = splitLabels.length > 0
    ? Math.max(...splitLabels.map((parts: string[]) => parts.length))
    : 0;
  const useSplitLabelColumns = !!labelDelimiter && maxLabelParts > 1;

  return data.slice(0, previewRowLimit).map((row: any, i: number) => {
    const obj: any = { _index: i + 1 };
    const fullLabel = labels[i] || "";
    obj._label_full = fullLabel;

    if (labels.length > 0) {
      if (useSplitLabelColumns) {
        const parts = splitLabels[i] || [];
        for (let labelIdx = 0; labelIdx < maxLabelParts; labelIdx += 1) {
          const value = parts[labelIdx] || "";
          obj[`_label_${labelIdx}`] = compactSampleLabel(value, {
            maxLength: 42,
            headLength: 28,
            tailLength: 12,
          });
        }
      } else {
        obj._label = compactSampleLabel(fullLabel, {
          maxLength: 52,
          headLength: 34,
          tailLength: 14,
        });
      }
    }

    if (Array.isArray(row)) {
      row.slice(0, 10).forEach((val: any, j: number) => {
        obj[`col_${j}`] = typeof val === "number" ? val.toFixed(4) : val;
      });
    } else if (typeof row === "object" && row !== null) {
      // Dict rows (e.g. PeakFinding stats output)
      for (const [k, v] of Object.entries(row)) {
        obj[k] = typeof v === "number" ? Number(v).toFixed(4) : v;
      }
    } else {
      obj.value = typeof row === "number" ? row.toFixed(4) : row;
    }
    return obj;
  });
});

const outputPreviewColumns = computed(() => {
  if (!outputPreview.value.length) return [];
  const first = outputPreview.value[0] as Record<string, any>;
  const metadata = nodeOutput.value?.metadata || {};
  const pcLabels = metadata.pc_labels || [];
  const mcrLabels = metadata.labels || [];
  const featureNames = metadata.feature_names || [];
  const columnNames: string[] = Array.isArray(metadata.column_names) ? metadata.column_names : [];
  const xTitle = metadata.x_title || "";
  const isPCA = metadata.type === "model.pca" || metadata.isPCA;
  const isMCR = metadata.type === "model.mcr_als";

  return Object.keys(first)
    .filter((key) => key !== "_label_full")
    .map((key) => {
    let header = key;
    if (key === "_index") {
      header = "#";
    } else if (key === "_label") {
      header = "Label";
    } else if (key.startsWith("_label_")) {
      const labelIdx = Number.parseInt(key.replace("_label_", ""), 10);
      header = Number.isNaN(labelIdx) ? "Label" : `Field ${labelIdx + 1}`;
    } else if (key.startsWith("col_")) {
      const colIdx = parseInt(key.replace("col_", ""));
      if (columnNames.length > colIdx) {
        header = columnNames[colIdx];
      } else if (isPCA && pcLabels[colIdx]) {
        header = pcLabels[colIdx];
      } else if (isMCR && mcrLabels[colIdx]) {
        header = mcrLabels[colIdx];
      } else if (featureNames.length > colIdx) {
        header = featureNames[colIdx];
      } else if (xTitle && xTitle !== "Feature") {
        header = `${xTitle} ${colIdx + 1}`;
      } else {
        header = `Col ${colIdx + 1}`;
      }
    }
    return { field: key, header };
  });
});

const outputDataSummary = computed(() => {
  const data = nodeOutput.value?.data;
  if (!data || !Array.isArray(data)) return "";
  const totalRows = data.length;
  const totalCols = Array.isArray(data[0]) ? data[0].length : 1;
  const shownRows = Math.min(totalRows, previewRowLimit);
  const shownCols = Math.min(totalCols, 10);
  let summary = `${shownRows} of ${totalRows} rows`;
  if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
  return summary;
});

const pcaDiagnosticsPreview = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const t2 = Array.isArray(metadata.t2) ? metadata.t2 : [];
  const spe = Array.isArray(metadata.spe) ? metadata.spe : [];
  const rowCount = Math.max(t2.length, spe.length);
  if (rowCount === 0) return [];

  const rows = [];
  const limit = Math.min(rowCount, previewRowLimit);
  for (let i = 0; i < limit; i += 1) {
    rows.push({
      sample: i + 1,
      t2: typeof t2[i] === "number" ? t2[i].toFixed(4) : "",
      spe: typeof spe[i] === "number" ? spe[i].toFixed(6) : "",
    });
  }
  return rows;
});

const pcaDiagSummary = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return "";
  const metadata = nodeOutput.value?.metadata || {};
  const t2 = Array.isArray(metadata.t2) ? metadata.t2 : [];
  const spe = Array.isArray(metadata.spe) ? metadata.spe : [];
  const totalRows = Math.max(t2.length, spe.length);
  const shownRows = Math.min(totalRows, previewRowLimit);
  return `${shownRows} of ${totalRows} rows`;
});

const pcaDiagnosticsColumns = computed(() => ([
  { field: "sample", header: "Sample" },
  { field: "t2", header: "T²" },
  { field: "spe", header: "SPE (Q)" },
]));

// ============================================================================
// PLOTS SECTION - State and Computed Properties
// ============================================================================

// PCA axis selection
const pcaXAxis = ref(0);
const pcaYAxis = ref(1);

// Spectra display mode
const spectraDisplayMode = ref<"overlay" | "contour">("contour");
const spectraDisplayOptions = [
  { label: "Overlay", value: "overlay" },
  { label: "Contour (Interactive)", value: "contour" },
];

// Generic data display mode (for non-spectral datasets like Iris)
const genericDisplayMode = ref<"boxplot" | "scatter">("boxplot");
const genericDisplayOptions = [
  { label: "Box Plot (by Label)", value: "boxplot" },
  { label: "Feature Scatter", value: "scatter" },
];

// Feature selection for scatter plot
const featureXAxis = ref(0);
const featureYAxis = ref(1);

// Available features for scatter plot axis selection
const featureOptions = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const featureNames = metadata.feature_names || [];
  if (featureNames.length === 0) return [];
  return featureNames.map((name: string, i: number) => ({ label: name, value: i }));
});

// Contour click point for slicing
const contourClickPoint = ref<{ sampleIdx: number; wavenumberIdx: number; wavenumber: number } | null>(null);

// Check if node is a preprocessing type
const isPreprocessingNode = computed(() => {
  const nt = nodeType.value;
  return (
    nt.startsWith("normalize.") ||
    nt.startsWith("baseline.") ||
    nt.startsWith("smooth.") ||
    nt.startsWith("derivative.") ||
    nt.startsWith("preprocess.")
  );
});

// Available plots based on node type
const availablePlots = computed(() => {
  const plots: string[] = [];
  if (isPCAOutput.value) {
    plots.push("Scores Plot", "Biplot", "Loadings Plot", "Scree Plot", "Diagnostics Plot");
    return plots;
  }
  switch (nodeTypeKey.value) {
    case "model.mcr_als":
    case "model.simplisma":
      plots.push("Concentration Profiles", "Pure Spectra");
      break;
    case "model.efa":
      plots.push("Eigenvalue Plot");
      break;
    case "model.pls":
      plots.push("Scores Plot", "Loadings Plot", "Predicted vs Actual");
      break;
    case "model.pcr":
    case "model.svr":
      plots.push("Predicted vs Actual");
      break;
    case "classification.plsda":
      plots.push("Scores Plot (with confidence ellipses)", "Loadings Plot", "VIP Scores", "Class Accuracy");
      break;
    case "classification.simca":
      plots.push("Scores Plot", "Class Accuracy");
      break;
    case "classification.knn":
      plots.push("Scores Plot", "Class Accuracy");
      break;
    case "model.hca":
      plots.push("Dendrogram");
      break;
    case "stats.summary":
      plots.push("Summary Plot");
      break;
    case "analysis.peak_finding":
      plots.push("Spectra with Peaks");
      break;
    case "output.plot":
    case "output.contour":
      plots.push("Visualization");
      break;
    case "data.source":
    case "preprocess.normalize":
    case "preprocess.scale":
    case "preprocess.clip_range":
    case "preprocess.cosmic_ray":
    case "baseline.penalized_ls":
    case "baseline.rubberband":
    case "preprocess.smooth":
      // Show appropriate overview based on data type
      if (isGenericDataNode.value) {
        plots.push("Data Overview");
      } else if (isSpectraData.value) {
        plots.push("Spectra Overview");
      } else {
        plots.push("Data Overview"); // Default to Data Overview for unknown types
      }
      break;
  }
  if (plots.length === 0 && (isDataNode.value || isPreprocessingNode.value)) {
    if (isGenericDataNode.value) {
      plots.push("Data Overview");
    } else if (isSpectraData.value) {
      plots.push("Spectra Overview");
    } else {
      plots.push("Data Overview");
    }
  }
  return plots;
});

// Base plot layout for dark theme
const basePlotLayout = {
  autosize: true,
  paper_bgcolor: "#1e293b",
  plot_bgcolor: "#0f172a",
  font: { color: "#f8fafc", size: 12 },
  margin: { t: 40, r: 20, b: 50, l: 60 },
  xaxis: { gridcolor: "#334155", zerolinecolor: "#475569" },
  yaxis: { gridcolor: "#334155", zerolinecolor: "#475569" },
};

// ============================================================================
// Dynamic Axis Labels (using shared utilities from @/utils/plotLabels)
// ============================================================================

/**
 * Compute Y-axis label from metadata using shared utility.
 * Never uses "a.u." - falls back to ML terms ("Response").
 */
const yAxisLabel = computed(() => getYAxisLabel(nodeOutput.value?.metadata));

/**
 * Compute X-axis label from metadata using shared utility.
 * Never uses "a.u." - falls back to ML terms ("Feature").
 */
const xAxisLabel = computed(() => getXAxisLabel(nodeOutput.value?.metadata));

// Watch for changes in PCA component count and clamp axis indices
watch(
  () => nodeOutput.value?.metadata?.n_components,
  (n_components) => {
    if (isPCAOutput.value && typeof n_components === "number") {
      const maxIndex = Math.max(0, n_components - 1);
      // Clamp X axis
      if (pcaXAxis.value > maxIndex) {
        pcaXAxis.value = Math.min(pcaXAxis.value, maxIndex);
      }
      // Clamp Y axis, ensuring it's different from X axis if possible
      if (pcaYAxis.value > maxIndex) {
        pcaYAxis.value = Math.min(pcaYAxis.value, maxIndex);
      }
      // Special case: if only 1 component, both should be 0
      if (n_components === 1) {
        pcaXAxis.value = 0;
        pcaYAxis.value = 0;
      } else if (pcaXAxis.value === pcaYAxis.value && n_components > 1) {
        // If they're the same and we have >1 components, offset Y axis
        pcaYAxis.value = (pcaXAxis.value + 1) % n_components;
      }
    }
  },
  { immediate: true }
);

// ============================================================================
// PCA Plots
// ============================================================================

/**
 * Derive PC axis labels from explained_variance_ratio.
 * Falls back to metadata.pc_labels for backwards compat with old node outputs.
 */
const pcLabels = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  // Backwards compat: use pre-computed pc_labels if available
  if (metadata.pc_labels?.length) return metadata.pc_labels;
  // Derive from explained_variance_ratio
  const evr = metadata.explained_variance_ratio || [];
  if (!evr.length) return [];
  const yTitle = metadata.y_title;
  const suffix = yTitle && yTitle !== "Response" ? ` [${yTitle}]` : "";
  return evr.map((v: number, i: number) => {
    const pct = v > 1 ? v : v * 100;
    return `PC${i + 1} (${pct.toFixed(1)}%)${suffix}`;
  });
});

const pcaAxisOptions = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const labels = pcLabels.value;
  const n = labels.length || metadata.n_components || 5;
  return Array.from({ length: n }, (_, i) => ({
    label: labels[i] || `PC${i + 1}`,
    value: i,
  }));
});

const pcaScoresData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];
  const scores = nodeOutput.value?.data || [];
  if (!scores.length) return [];

  const labels = pcaSampleLabels.value.length === scores.length
    ? pcaSampleLabels.value
    : Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const axisLabels = pcLabels.value;  // Use computed pcLabels
  const labelCategories = pcaLabelCategories.value;

  // Determine if we should use categorical coloring
  const useCategorical = pcaUseCategorical.value;

  if (useCategorical) {
    // Multiple traces, one per category
    const colorMap = createCategoryColorMap(labels, labelCategories);
    const traces: any[] = [];

    // Group points by category
    const categoryGroups = new Map<string | number, { x: number[], y: number[], labels: string[] }>();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = labels[idx];
      const group = categoryGroups.get(category);
      if (group) {
        group.x.push(row[pcaXAxis.value]);
        group.y.push(row[pcaYAxis.value]);
        group.labels.push(String(labels[idx]));
      }
    });

    // Create one trace per category
    labelCategories.forEach((category: any) => {
      const group = categoryGroups.get(category);
      if (group && group.x.length > 0) {
        traces.push({
          type: "scatter",
          mode: "markers",
          x: group.x,
          y: group.y,
          text: group.labels,
          name: String(category),
          marker: {
            size: 10,
            color: colorMap.get(category),
            opacity: 0.8,
            line: { width: 1, color: "rgba(0,0,0,0.3)" },
          },
          hovertemplate: `%{text}<br>${axisLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}`}: %{x:.3f}<br>${axisLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
        });
      }
    });

    if (traces.length > 0) {
      return traces;
    }
  }
  // Fallback: Single trace with default blue color
  const x = scores.map((row: number[]) => row[pcaXAxis.value]);
  const y = scores.map((row: number[]) => row[pcaYAxis.value]);

  return [{
    type: "scatter",
    mode: "markers",
    x, y,
    text: labels,
    marker: { size: 10, color: "#3b82f6", opacity: 0.8, line: { width: 1, color: "#1e40af" } },
    hovertemplate: `%{text}<br>${axisLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}`}: %{x:.3f}<br>${axisLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
  }];
});

const pcaScoresLayout = computed(() => {
  const axisLabels = pcLabels.value;  // Use computed pcLabels
  const hasCategorical = pcaUseCategorical.value;

  const layout: Record<string, any> = {
    ...basePlotLayout,
    height: 400,
    showlegend: hasCategorical,
    xaxis: { ...basePlotLayout.xaxis, title: axisLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}` },
    yaxis: { ...basePlotLayout.yaxis, title: axisLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}` },
  };

  // Ensure legend is properly configured when categorical
  if (hasCategorical) {
    layout.legend = {
      bgcolor: "rgba(30, 41, 59, 0.8)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1,
      y: 1,
      xanchor: "right",
      yanchor: "top",
    } as any;
  }

  return layout;
});

const pcaScoresConfig = computed(() => ({
  editable: true,
  edits: { legendPosition: true },
}));

const pcaBiplotData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];

  const scores = nodeOutput.value?.data || [];
  if (!Array.isArray(scores) || scores.length === 0) return [];

  const loadingsPort = nodeOutput.value?.ports?.loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const loadings = loadingsPort?.data || metadata.loadings || [];

  // Fallback to scores-only plot when loadings are unavailable.
  if (!Array.isArray(loadings) || loadings.length === 0) {
    return pcaScoresData.value;
  }

  const maxLoadingPcIndex = loadings.length - 1;
  const pcX = Math.max(0, Math.min(pcaXAxis.value, maxLoadingPcIndex));
  const pcY = Math.max(0, Math.min(pcaYAxis.value, maxLoadingPcIndex));

  const loadingXRaw = Array.isArray(loadings[pcX]) ? loadings[pcX] : [];
  const loadingYRaw = Array.isArray(loadings[pcY]) ? loadings[pcY] : [];
  if (!loadingXRaw.length || !loadingYRaw.length) {
    return pcaScoresData.value;
  }

  const nFeatures = Math.min(loadingXRaw.length, loadingYRaw.length);
  const axisLabels = pcLabels.value;
  const pcXLabel = axisLabels[pcX] || `PC${pcX + 1}`;
  const pcYLabel = axisLabels[pcY] || `PC${pcY + 1}`;

  const sampleLabels = pcaSampleLabels.value.length === scores.length
    ? pcaSampleLabels.value
    : Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const labelCategories = pcaLabelCategories.value;
  const useCategorical = pcaUseCategorical.value;

  const sampleTraces: any[] = [];
  if (useCategorical) {
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);
    const categoryGroups = new Map<string | number, { x: number[]; y: number[]; labels: string[] }>();
    labelCategories.forEach((category: string | number) => {
      categoryGroups.set(category, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = sampleLabels[idx];
      const group = categoryGroups.get(category);
      if (group && Array.isArray(row) && row.length > Math.max(pcX, pcY)) {
        group.x.push(Number(row[pcX]));
        group.y.push(Number(row[pcY]));
        group.labels.push(String(sampleLabels[idx]));
      }
    });

    labelCategories.forEach((category: string | number) => {
      const group = categoryGroups.get(category);
      if (!group || group.x.length === 0) return;
      sampleTraces.push({
        type: "scatter",
        mode: "markers",
        x: group.x,
        y: group.y,
        text: group.labels,
        name: String(category),
        marker: {
          size: 9,
          color: colorMap.get(category),
          opacity: 0.78,
          line: { width: 1, color: "rgba(15, 23, 42, 0.55)" },
        },
        hovertemplate: `%{text}<br>${pcXLabel}: %{x:.3f}<br>${pcYLabel}: %{y:.3f}<extra></extra>`,
      });
    });
  } else {
    const pairedPoints = scores
      .map((row: number[], idx: number) => ({
        x: Number(row?.[pcX]),
        y: Number(row?.[pcY]),
        label: sampleLabels[idx],
      }))
      .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));

    sampleTraces.push({
      type: "scatter",
      mode: "markers",
      x: pairedPoints.map((point) => point.x),
      y: pairedPoints.map((point) => point.y),
      text: pairedPoints.map((point) => point.label),
      name: "Samples",
      marker: {
        size: 9,
        color: "#60a5fa",
        opacity: 0.8,
        line: { width: 1, color: "#1d4ed8" },
      },
      hovertemplate: `%{text}<br>${pcXLabel}: %{x:.3f}<br>${pcYLabel}: %{y:.3f}<extra></extra>`,
    });
  }

  // Build feature labels for loading vectors.
  const featureNames = metadata.feature_names;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;
  const featureLabels = Array.from({ length: nFeatures }, (_, idx) => {
    if (Array.isArray(featureNames) && featureNames.length === nFeatures) {
      return String(featureNames[idx]);
    }
    if (Array.isArray(wavenumbers) && wavenumbers.length === nFeatures) {
      const w = Number(wavenumbers[idx]);
      return Number.isFinite(w) ? `${w.toFixed(0)}` : String(wavenumbers[idx]);
    }
    return `F${idx + 1}`;
  });

  // Keep biplot readable on high-dimensional data:
  // draw strongest vectors and label the strongest subset.
  const vectors = Array.from({ length: nFeatures }, (_, idx) => {
    const lx = Number(loadingXRaw[idx]);
    const ly = Number(loadingYRaw[idx]);
    return {
      idx,
      lx,
      ly,
      label: featureLabels[idx],
      norm: Math.hypot(lx, ly),
    };
  }).filter((row) => Number.isFinite(row.lx) && Number.isFinite(row.ly));

  if (vectors.length === 0) {
    return sampleTraces;
  }

  vectors.sort((a, b) => b.norm - a.norm);
  const maxVectors = Math.min(80, vectors.length);
  const selectedVectors = vectors.slice(0, maxVectors);
  const labeledCount = Math.min(24, selectedVectors.length);
  const labeledFeatures = new Set(selectedVectors.slice(0, labeledCount).map((row) => row.idx));

  const scoreXValues = scores
    .map((row: number[]) => Number(row?.[pcX]))
    .filter((value: number) => Number.isFinite(value));
  const scoreYValues = scores
    .map((row: number[]) => Number(row?.[pcY]))
    .filter((value: number) => Number.isFinite(value));

  const maxScoreX = Math.max(1e-12, ...scoreXValues.map((value: number) => Math.abs(value)));
  const maxScoreY = Math.max(1e-12, ...scoreYValues.map((value: number) => Math.abs(value)));
  const maxLoadX = Math.max(1e-12, ...selectedVectors.map((row) => Math.abs(row.lx)));
  const maxLoadY = Math.max(1e-12, ...selectedVectors.map((row) => Math.abs(row.ly)));
  const loadingScale = 0.82 * Math.min(maxScoreX / maxLoadX, maxScoreY / maxLoadY);

  const vectorLineX: Array<number | null> = [];
  const vectorLineY: Array<number | null> = [];
  const vectorEndX: number[] = [];
  const vectorEndY: number[] = [];
  const vectorText: string[] = [];
  const vectorCustomData: Array<[string, number, number, number]> = [];

  selectedVectors.forEach((row) => {
    const scaledX = row.lx * loadingScale;
    const scaledY = row.ly * loadingScale;

    vectorLineX.push(0, scaledX, null);
    vectorLineY.push(0, scaledY, null);
    vectorEndX.push(scaledX);
    vectorEndY.push(scaledY);
    vectorText.push(labeledFeatures.has(row.idx) ? row.label : "");
    vectorCustomData.push([row.label, row.lx, row.ly, row.norm]);
  });

  const loadingLineTrace = {
    type: "scatter",
    mode: "lines",
    x: vectorLineX,
    y: vectorLineY,
    name: "Loadings vectors",
    line: { color: "#f59e0b", width: 1.6 },
    hoverinfo: "skip",
    showlegend: true,
  };

  const loadingMarkerTrace = {
    type: "scatter",
    mode: "markers+text",
    x: vectorEndX,
    y: vectorEndY,
    text: vectorText,
    textposition: "top center",
    textfont: { size: 10, color: "#fde68a" },
    customdata: vectorCustomData,
    marker: {
      size: 6,
      color: "#f97316",
      opacity: 0.92,
      line: { width: 1, color: "#7c2d12" },
    },
    name: "Variables",
    showlegend: false,
    hovertemplate:
      `<b>%{customdata[0]}</b><br>${pcXLabel} loading: %{customdata[1]:.3f}` +
      `<br>${pcYLabel} loading: %{customdata[2]:.3f}` +
      `<br>Vector norm: %{customdata[3]:.3f}<extra></extra>`,
  };

  return [...sampleTraces, loadingLineTrace, loadingMarkerTrace];
});

const pcaBiplotLayout = computed(() => {
  const axisLabels = pcLabels.value;
  const pcXLabel = axisLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}`;
  const pcYLabel = axisLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}`;
  const hasCategorical = pcaUseCategorical.value;

  return {
    ...basePlotLayout,
    height: 460,
    showlegend: true,
    legend: {
      bgcolor: "rgba(30, 41, 59, 0.82)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1,
      y: 1,
      xanchor: "right",
      yanchor: "top",
      orientation: hasCategorical ? "v" : "h",
    },
    xaxis: {
      ...basePlotLayout.xaxis,
      title: `${pcXLabel} (scores)`,
      zeroline: true,
      zerolinecolor: "#64748b",
      zerolinewidth: 1.2,
    },
    yaxis: {
      ...basePlotLayout.yaxis,
      title: `${pcYLabel} (scores)`,
      zeroline: true,
      zerolinecolor: "#64748b",
      zerolinewidth: 1.2,
    },
    annotations: [
      {
        xref: "paper",
        yref: "paper",
        x: 0,
        y: 1.08,
        showarrow: false,
        text: "Loading vectors are scaled to score-space for interpretation.",
        font: { size: 11, color: "#cbd5e1" },
      },
    ],
    hovermode: "closest",
  };
});

const pcaLoadingsData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];

  // Read loadings from port (new architecture) or metadata (backwards compat)
  const loadingsPort = nodeOutput.value?.ports?.loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const loadings = loadingsPort?.data || metadata.loadings || [];
  if (!loadings.length) return [];

  // Wavenumbers/features: prefer loadings port x_axis (has actual wavenumbers), then metadata
  const portWavenumbers = loadingsPayload?.x_axis?.data;
  const feature_names = metadata.feature_names;
  const wavenumbers = portWavenumbers || metadata.wavenumbers;
  const axisLabels = pcLabels.value;  // Use computed pcLabels

  // Priority: feature_names > wavenumbers > feature indices
  let x_values;
  if (feature_names && feature_names.length === loadings[0]?.length) {
    x_values = feature_names;
  } else if (wavenumbers && wavenumbers.length === loadings[0]?.length) {
    x_values = wavenumbers;
  } else {
    x_values = Array.from({ length: loadings[0]?.length || 0 }, (_, i) => i);
  }

  return loadings.map((loading: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: x_values,
    y: loading,
    name: axisLabels[i] || `PC${i + 1}`,
    line: { width: 2 },
  }));
});

const pcaLoadingsLayout = computed(() => {
  const loadingsPort = nodeOutput.value?.ports?.loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const feature_names = metadata.feature_names;
  // Prefer loadings port x_axis metadata (has actual wavenumber title/units)
  const portXTitle = loadingsPayload?.x_axis?.title;
  const portXUnits = loadingsPayload?.x_axis?.units;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;

  // Determine x-axis title and orientation from actual metadata
  let xaxis_title = "Feature Index";
  let xaxis_reversed = false;
  if (feature_names && feature_names.length > 0) {
    xaxis_title = "Feature";
  } else if (portXTitle) {
    // Use title/units from loadings port coordinate
    xaxis_title = portXUnits ? `${portXTitle} (${portXUnits})` : portXTitle;
    xaxis_reversed = portXTitle.toLowerCase().includes("wavenumber");
  } else if (wavenumbers && wavenumbers.length > 0) {
    // Use metadata x_title/x_units (could be wavenumber, wavelength, m/z, etc.)
    const xTitle = metadata.x_title || "Feature";
    const xUnits = metadata.x_units || "";
    xaxis_title = xUnits ? `${xTitle} (${xUnits})` : xTitle;
    xaxis_reversed = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  }

  return {
    ...basePlotLayout,
    height: 350,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...basePlotLayout.xaxis, title: xaxis_title, autorange: xaxis_reversed ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: "Loading" },
  };
});

const pcaLoadingsConfig = computed(() => ({
  editable: true,
  edits: { legendPosition: true },
}));

const pcaScreeData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const variance = metadata.explained_variance_ratio || [];

  // Debug: log what we're getting
  console.log('[PCA Scree] variance data:', variance, 'length:', variance.length);

  if (!variance.length) return [];

  // Detect if variance is already in percentage form (values > 1) or ratio form (0-1)
  const maxVal = Math.max(...variance);
  const isPercentage = maxVal > 1;

  // Convert to percentage if needed
  const variancePercent = isPercentage
    ? variance.map((v: number) => v)
    : variance.map((v: number) => v * 100);

  // Use simple PC labels for x-axis (not the ones with percentages)
  const xLabels = Array.from({ length: variance.length }, (_, i) => `PC${i + 1}`);

  // Bar chart for individual variance
  const bars = {
    type: "bar",
    x: xLabels,
    y: variancePercent,
    name: "Individual %",
    marker: { color: "#3b82f6" },
    hovertemplate: "%{x}: %{y:.1f}%<extra></extra>",
  };

  // Line for cumulative variance - on same y-axis for visibility
  let cumulative = 0;
  const cumulativeY = variancePercent.map((v: number) => {
    cumulative += v;
    return cumulative;
  });

  const line = {
    type: "scatter",
    mode: "lines+markers",
    x: xLabels,
    y: cumulativeY,
    name: "Cumulative %",
    line: { color: "#f97316", width: 3 },
    marker: { size: 10, color: "#f97316" },
    hovertemplate: "%{x}: %{y:.1f}% cumulative<extra></extra>",
  };

  console.log('[PCA Scree] bars y:', variancePercent, 'cumulative y:', cumulativeY);

  return [bars, line];
});

const pcaScreeLayout = computed(() => ({
  ...basePlotLayout,
  height: 350,
  showlegend: true,
  legend: {
    x: 0.5,
    xanchor: "center",
    y: 1.15,
    orientation: "h",
    bgcolor: "rgba(0,0,0,0)",
    font: { color: "#f8fafc" },
  },
  xaxis: {
    ...basePlotLayout.xaxis,
    title: { text: "Principal Component", font: { color: "#f8fafc" } },
  },
  yaxis: {
    ...basePlotLayout.yaxis,
    title: { text: "Variance (%)", font: { color: "#f8fafc" } },
    rangemode: "tozero",
    range: [0, 105],
  },
}));

const pcaDiagnosticsData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const t2 = Array.isArray(metadata.t2) ? metadata.t2 : [];
  const spe = Array.isArray(metadata.spe) ? metadata.spe : [];
  const rowCount = Math.max(t2.length, spe.length);
  if (rowCount === 0) return [];
  const sampleLabels = pcaSampleLabels.value.length === rowCount
    ? pcaSampleLabels.value
    : Array.from({ length: rowCount }, (_, i) => `Sample ${i + 1}`);
  const labelCategories = pcaLabelCategories.value;

  const x = Array.from({ length: rowCount }, (_, i) => i + 1);
  const traces = [];

  // Determine if we should use categorical coloring
  const useCategorical = pcaUseCategorical.value;

  if (useCategorical) {
    // Categorical coloring: one trace per category
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);

    // Group data by category
    const categoryGroups = new Map<string | number, { indices: number[], t2Values: number[], speValues: number[], labels: string[] }>();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { indices: [], t2Values: [], speValues: [], labels: [] });
    });

    x.forEach((idx: number, i: number) => {
      const category = sampleLabels[i];
      const group = categoryGroups.get(category);
      if (group) {
        group.indices.push(idx);
        if (t2.length > i) group.t2Values.push(t2[i]);
        if (spe.length > i) group.speValues.push(spe[i]);
        group.labels.push(String(sampleLabels[i]));
      }
    });

    // Create T² traces per category
    if (t2.length > 0) {
      labelCategories.forEach((category: any) => {
        const group = categoryGroups.get(category);
        if (group && group.t2Values.length > 0) {
          traces.push({
            type: "scatter",
            mode: "lines+markers",
            x: group.indices,
            y: group.t2Values,
            name: `T²: ${String(category)}`,
            text: group.labels,
            yaxis: "y",
            line: { color: colorMap.get(category), width: 2 },
            marker: { size: 6, color: colorMap.get(category), symbol: "circle" },
            hovertemplate: "%{text}<br>T²: %{y:.4f}<extra></extra>",
            legendgroup: String(category),
          });
        }
      });

      // Add T² control limit as separate trace
      if (typeof metadata.t2_p95 === "number") {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: [x[0], x[x.length - 1]],
          y: [metadata.t2_p95, metadata.t2_p95],
          name: "T² Limit (95%)",
          yaxis: "y",
          line: { color: "#64748b", width: 1, dash: "dash" },
          showlegend: true,
          hoverinfo: "skip",
          legendgroup: "limits",
        });
      }
    }

    // Create SPE traces per category
    if (spe.length > 0) {
      labelCategories.forEach((category: any) => {
        const group = categoryGroups.get(category);
        if (group && group.speValues.length > 0) {
          traces.push({
            type: "scatter",
            mode: "lines+markers",
            x: group.indices,
            y: group.speValues,
            name: `SPE: ${String(category)}`,
            text: group.labels,
            yaxis: "y2",
            line: { color: colorMap.get(category), width: 2 },
            marker: { size: 6, color: colorMap.get(category), symbol: "square" },
            hovertemplate: "%{text}<br>SPE: %{y:.6f}<extra></extra>",
            legendgroup: String(category),
          });
        }
      });

      // Add SPE control limit as separate trace
      if (typeof metadata.spe_p95 === "number") {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: [x[0], x[x.length - 1]],
          y: [metadata.spe_p95, metadata.spe_p95],
          name: "SPE Limit (95%)",
          yaxis: "y2",
          line: { color: "#64748b", width: 1, dash: "dash" },
          showlegend: true,
          hoverinfo: "skip",
          legendgroup: "limits",
        });
      }
    }
  } else {
    // Fallback: static colors when no categorical labels
    if (t2.length > 0) {
      traces.push({
        type: "scatter",
        mode: "lines+markers",
        x,
        y: t2,
        name: "T²",
        text: sampleLabels,
        yaxis: "y",
        line: { color: "#38bdf8", width: 2 },
        marker: { size: 6, color: "#38bdf8", symbol: "circle" },
        hovertemplate: "%{text}<br>T²: %{y:.4f}<extra></extra>",
      });

      // Add T² control limit
      if (typeof metadata.t2_p95 === "number") {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: [x[0], x[x.length - 1]],
          y: [metadata.t2_p95, metadata.t2_p95],
          name: "T² Limit (95%)",
          yaxis: "y",
          line: { color: "#38bdf8", width: 1, dash: "dash" },
          showlegend: true,
          hoverinfo: "skip",
        });
      }
    }

    if (spe.length > 0) {
      traces.push({
        type: "scatter",
        mode: "lines+markers",
        x,
        y: spe,
        name: "SPE (Q)",
        text: sampleLabels,
        yaxis: "y2",
        line: { color: "#f97316", width: 2 },
        marker: { size: 6, color: "#f97316", symbol: "square" },
        hovertemplate: "%{text}<br>SPE: %{y:.6f}<extra></extra>",
      });

      // Add SPE control limit
      if (typeof metadata.spe_p95 === "number") {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: [x[0], x[x.length - 1]],
          y: [metadata.spe_p95, metadata.spe_p95],
          name: "SPE Limit (95%)",
          yaxis: "y2",
          line: { color: "#f97316", width: 1, dash: "dash" },
          showlegend: true,
          hoverinfo: "skip",
        });
      }
    }
  }

  return traces;
});

const pcaDiagnosticsLayout = computed(() => {
  return {
    ...basePlotLayout,
    height: 350,
    margin: { t: 40, r: 80, b: 50, l: 60 },
    showlegend: true,
    legend: {
      x: 0.5,
      xanchor: "center",
      y: 1.15,
      orientation: "h",
      bgcolor: "rgba(0,0,0,0)",
      font: { color: "#f8fafc" },
    },
    xaxis: { ...basePlotLayout.xaxis, title: "Sample" },
    yaxis: { ...basePlotLayout.yaxis, title: "T²" },
    yaxis2: {
      overlaying: "y",
      side: "right",
      title: { text: "SPE (Q)", standoff: 20 },
      gridcolor: "rgba(0,0,0,0)",
      zerolinecolor: "#475569",
    },
  };
});

// ============================================================================
// MCR-ALS Plots
// ============================================================================

const mcrConcentrationData = computed(() => {
  if ((nodeTypeKey.value !== "model.mcr_als" && nodeTypeKey.value !== "model.simplisma") || !hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const labels = metadata.labels || Array.from({ length: data[0]?.length || 0 }, (_, i) => `Component ${i + 1}`);

  if (!data.length || !Array.isArray(data[0])) return [];

  const nSamples = data.length;
  const nComponents = data[0].length;
  const x = Array.from({ length: nSamples }, (_, i) => i + 1);

  return Array.from({ length: nComponents }, (_, c) => ({
    type: "scatter",
    mode: "lines",
    x,
    y: data.map((row: number[]) => row[c]),
    name: labels[c],
    line: { width: 2 },
  }));
});

const mcrConcentrationLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  return {
    ...basePlotLayout,
    height: 350,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...basePlotLayout.xaxis, title: metadata.y_title || "Sample Index" },
    yaxis: { ...basePlotLayout.yaxis, title: metadata.value_units_label || metadata.value_units || "Relative Concentration" },
  };
});

const mcrSpectraData = computed(() => {
  if ((nodeTypeKey.value !== "model.mcr_als" && nodeTypeKey.value !== "model.simplisma") || !hasOutput.value) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const St = metadata.St || [];
  if (!St.length) return [];
  const nFeatures = St[0]?.length || 0;
  // Use spectral_wavenumbers (survives serialization) with length-check fallback.
  // metadata.wavenumbers may be component indices [0,1] from C_dataset's feature
  // axis, so only use it if its length matches the spectrum length.
  const candidates = metadata.spectral_wavenumbers || metadata.wavenumbers;
  const wavenumbers = (candidates && Array.isArray(candidates) && candidates.length === nFeatures)
    ? candidates
    : Array.from({ length: nFeatures }, (_, i) => i);
  const labels = metadata.St_labels || Array.from({ length: St.length }, (_, i) => `Component ${i + 1}`);

  return St.map((spectrum: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: wavenumbers,
    y: spectrum,
    name: labels[i],
    line: { width: 2 },
  }));
});

const mcrSpectraLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  // Use spectral_x_title/x_units (survives serialization) with fallback.
  // Only use axis info if the actual wavenumber data was resolved (not index fallback).
  const St = metadata.St || [];
  const nFeatures = St[0]?.length || 0;
  const candidates = metadata.spectral_wavenumbers || metadata.wavenumbers;
  const hasRealWavenumbers = candidates && Array.isArray(candidates) && candidates.length === nFeatures;
  const xTitle = hasRealWavenumbers ? (metadata.spectral_x_title || metadata.x_title || "") : "";
  const xUnits = hasRealWavenumbers ? (metadata.spectral_x_units || metadata.x_units || "") : "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : (xTitle || "Feature Index");
  const yLabel = yAxisLabel.value || "Response";
  // Reverse x-axis for wavenumber data (cm⁻¹), not for wavelength (nm)
  const shouldReverse = hasRealWavenumbers && (xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber"));

  return {
    ...basePlotLayout,
    height: 350,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: {
      ...basePlotLayout.xaxis,
      title: xLabel,
      autorange: shouldReverse ? "reversed" : true,
    },
    yaxis: { ...basePlotLayout.yaxis, title: yLabel },
  };
});

// ============================================================================
// Plot / Contour Node Visualization (server-rendered Plotly)
// ============================================================================

const plotNodeData = computed(() => {
  if (!['output.plot', 'output.contour'].includes(nodeTypeKey.value) || !hasOutput.value) return [];
  // The visualization port stores {plot_type, data, layout}.
  // After buildNodeOutput, data = plotly traces, metadata = full vis object.
  const viz = nodeOutput.value?.ports?.visualization?.value || nodeOutput.value?.metadata || {};
  return viz.data || nodeOutput.value?.data || [];
});

const plotNodeLayout = computed(() => {
  if (!['output.plot', 'output.contour'].includes(nodeTypeKey.value) || !hasOutput.value) return basePlotLayout;
  const viz = nodeOutput.value?.ports?.visualization?.value || nodeOutput.value?.metadata || {};
  return {
    ...basePlotLayout,
    ...(viz.layout || {}),
    height: 450,
    paper_bgcolor: basePlotLayout.paper_bgcolor,
    plot_bgcolor: basePlotLayout.plot_bgcolor,
    font: basePlotLayout.font,
  };
});

// ============================================================================
// PLS Plots
// ============================================================================

const plsScoresData = computed(() => {
  if (nodeTypeKey.value !== "model.pls" || !hasOutput.value) return [];
  const scores = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  if (!scores.length) return [];

  const labels = metadata.sample_labels || Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const lvLabels = metadata.pc_labels || [];
  const labelCategories = metadata.label_categories;

  // Determine if we should use categorical coloring
  const useCategorical = labelCategories && labelCategories.length > 0 && labelCategories.length < 50;

  if (useCategorical) {
    const colorMap = createCategoryColorMap(labels, labelCategories);
    const traces: any[] = [];
    const categoryGroups = new Map<string | number, { x: number[], y: number[], labels: string[] }>();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = labels[idx];
      const group = categoryGroups.get(category);
      if (group) {
        group.x.push(row[pcaXAxis.value]);
        group.y.push(row[pcaYAxis.value]);
        group.labels.push(String(labels[idx]));
      }
    });

    labelCategories.forEach((category: any) => {
      const group = categoryGroups.get(category);
      if (group && group.x.length > 0) {
        traces.push({
          type: "scatter",
          mode: "markers",
          x: group.x,
          y: group.y,
          text: group.labels,
          name: String(category),
          marker: {
            size: 10,
            color: colorMap.get(category),
            opacity: 0.8,
            line: { width: 1, color: "rgba(0,0,0,0.3)" },
          },
          hovertemplate: `%{text}<br>${lvLabels[pcaXAxis.value] || `LV${pcaXAxis.value + 1}`}: %{x:.3f}<br>${lvLabels[pcaYAxis.value] || `LV${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
        });
      }
    });
    return traces;
  } else {
    const x = scores.map((row: number[]) => row[pcaXAxis.value]);
    const y = scores.map((row: number[]) => row[pcaYAxis.value]);
    return [{
      type: "scatter",
      mode: "markers",
      x, y,
      text: labels,
      marker: { size: 10, color: "#3b82f6", opacity: 0.8, line: { width: 1, color: "#1e40af" } },
      hovertemplate: `%{text}<br>${lvLabels[pcaXAxis.value] || `LV${pcaXAxis.value + 1}`}: %{x:.3f}<br>${lvLabels[pcaYAxis.value] || `LV${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
    }];
  }
});

const plsScoresLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const lvLabels = metadata.pc_labels || [];
  const hasCategorical = metadata.label_categories && metadata.label_categories.length > 0 && metadata.label_categories.length < 50;

  const layout: Record<string, any> = {
    ...basePlotLayout,
    height: 400,
    showlegend: hasCategorical,
    xaxis: { ...basePlotLayout.xaxis, title: lvLabels[pcaXAxis.value] || `LV${pcaXAxis.value + 1}` },
    yaxis: { ...basePlotLayout.yaxis, title: lvLabels[pcaYAxis.value] || `LV${pcaYAxis.value + 1}` },
  };

  if (hasCategorical) {
    layout.legend = {
      bgcolor: "rgba(30, 41, 59, 0.8)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1,
      y: 1,
      xanchor: "right",
      yanchor: "top",
    } as any;
  }

  return layout;
});

const plsLoadingsData = computed(() => {
  if (nodeTypeKey.value !== "model.pls" || !hasOutput.value) return [];

  // Read loadings from port (new architecture) or metadata (backwards compat)
  const loadingsPort = nodeOutput.value?.ports?.X_loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const loadings = loadingsPort?.data || metadata.X_loadings || [];
  if (!loadings.length) return [];

  // Wavenumbers/features: prefer loadings port x_axis, then metadata
  const portWavenumbers = loadingsPayload?.x_axis?.data;
  const feature_names = metadata.feature_names;
  const wavenumbers = portWavenumbers || metadata.wavenumbers;
  const lvLabels = metadata.pc_labels || [];

  // Priority: feature_names > wavenumbers > feature indices
  let x_values;
  if (feature_names && feature_names.length === loadings[0]?.length) {
    x_values = feature_names;
  } else if (wavenumbers && wavenumbers.length === loadings[0]?.length) {
    x_values = wavenumbers;
  } else {
    x_values = Array.from({ length: loadings[0]?.length || 0 }, (_, i) => i);
  }

  return loadings.map((loading: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: x_values,
    y: loading,
    name: lvLabels[i] || `LV${i + 1}`,
    line: { width: 2 },
  }));
});

const plsLoadingsLayout = computed(() => {
  const loadingsPort = nodeOutput.value?.ports?.X_loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const feature_names = metadata.feature_names;
  const portXTitle = loadingsPayload?.x_axis?.title;
  const portXUnits = loadingsPayload?.x_axis?.units;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;

  // Determine x-axis title and orientation from actual metadata
  let xaxis_title = "Feature Index";
  let xaxis_reversed = false;
  if (feature_names && feature_names.length > 0) {
    xaxis_title = "Feature";
  } else if (portXTitle) {
    xaxis_title = portXUnits ? `${portXTitle} (${portXUnits})` : portXTitle;
    xaxis_reversed = portXTitle.toLowerCase().includes("wavenumber");
  } else if (wavenumbers && wavenumbers.length > 0) {
    const xTitle = metadata.x_title || "Feature";
    const xUnits = metadata.x_units || "";
    xaxis_title = xUnits ? `${xTitle} (${xUnits})` : xTitle;
    xaxis_reversed = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  }

  return {
    ...basePlotLayout,
    height: 350,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...basePlotLayout.xaxis, title: xaxis_title, autorange: xaxis_reversed ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: "Loading" },
  };
});

// ============================================================================
// Classification Plots (PLS-DA, SIMCA, KNN)
// ============================================================================

const classificationScoresData = computed(() => {
  const nodeType = nodeTypeKey.value;
  if (!["classification.plsda", "classification.simca", "classification.knn"].includes(nodeType) || !hasOutput.value) return [];

  // For PLS-DA, use pre-built scores plot if available
  if (nodeType === "classification.plsda") {
    const plots = nodeOutput.value?.plots;
    if (plots?.scores?.data) {
      return plots.scores.data;
    }
  }

  // Fallback: build scores plot from raw data
  const scores = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  if (!scores.length) return [];

  const labels = metadata.sample_labels || Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const pcLabels = metadata.pc_labels || [];
  const labelCategories = metadata.label_categories;

  const useCategorical = labelCategories && labelCategories.length > 0 && labelCategories.length < 50;

  if (useCategorical) {
    const colorMap = createCategoryColorMap(labels, labelCategories);
    const traces: any[] = [];
    const categoryGroups = new Map<string | number, { x: number[], y: number[], labels: string[] }>();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = labels[idx];
      const group = categoryGroups.get(category);
      if (group) {
        group.x.push(row[pcaXAxis.value]);
        group.y.push(row[pcaYAxis.value]);
        group.labels.push(String(labels[idx]));
      }
    });

    labelCategories.forEach((category: any) => {
      const group = categoryGroups.get(category);
      if (group && group.x.length > 0) {
        traces.push({
          type: "scatter",
          mode: "markers",
          x: group.x,
          y: group.y,
          text: group.labels,
          name: String(category),
          marker: {
            size: 10,
            color: colorMap.get(category),
            opacity: 0.8,
            line: { width: 1, color: "rgba(0,0,0,0.3)" },
          },
          hovertemplate: `%{text}<br>${pcLabels[pcaXAxis.value] || `Dimension ${pcaXAxis.value + 1}`}: %{x:.3f}<br>${pcLabels[pcaYAxis.value] || `Dimension ${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
        });
      }
    });
    return traces;
  } else {
    const x = scores.map((row: number[]) => row[pcaXAxis.value]);
    const y = scores.map((row: number[]) => row[pcaYAxis.value]);
    return [{
      type: "scatter",
      mode: "markers",
      x, y,
      text: labels,
      marker: { size: 10, color: "#3b82f6", opacity: 0.8, line: { width: 1, color: "#1e40af" } },
      hovertemplate: `%{text}<br>${pcLabels[pcaXAxis.value] || `Dimension ${pcaXAxis.value + 1}`}: %{x:.3f}<br>${pcLabels[pcaYAxis.value] || `Dimension ${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
    }];
  }
});

const classificationScoresLayout = computed(() => {
  // For PLS-DA, use pre-built layout if available
  if (nodeTypeKey.value === "classification.plsda") {
    const plots = nodeOutput.value?.plots;
    if (plots?.scores?.layout) {
      return {
        ...basePlotLayout,
        ...plots.scores.layout,
        height: 400,
      };
    }
  }

  // Fallback layout
  const metadata = nodeOutput.value?.metadata || {};
  const pcLabels = metadata.pc_labels || [];
  const hasCategorical = metadata.label_categories && metadata.label_categories.length > 0 && metadata.label_categories.length < 50;

  const layout: Record<string, any> = {
    ...basePlotLayout,
    height: 400,
    showlegend: hasCategorical,
    xaxis: { ...basePlotLayout.xaxis, title: pcLabels[pcaXAxis.value] || `Dimension ${pcaXAxis.value + 1}` },
    yaxis: { ...basePlotLayout.yaxis, title: pcLabels[pcaYAxis.value] || `Dimension ${pcaYAxis.value + 1}` },
  };

  if (hasCategorical) {
    layout.legend = {
      bgcolor: "rgba(30, 41, 59, 0.8)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1,
      y: 1,
      xanchor: "right",
      yanchor: "top",
    } as any;
  }

  return layout;
});

// ============================================================================
// HCA Plots
// ============================================================================

const hcaDendrogramData = computed(() => {
  if (nodeTypeKey.value !== "model.hca" || !hasOutput.value) return [];
  const plots = nodeOutput.value?.plots;
  if (plots?.dendrogram?.data) {
    return plots.dendrogram.data;
  }
  return [];
});

const hcaDendrogramLayout = computed(() => {
  // Early return for non-HCA nodes (consistent with hcaDendrogramData)
  if (nodeTypeKey.value !== "model.hca" || !hasOutput.value) {
    return { ...basePlotLayout, height: 500, showlegend: false };
  }

  const plots = nodeOutput.value?.plots;
  const dendrogramLayout = plots?.dendrogram?.layout;
  if (dendrogramLayout) {
    // Let backend layout (including height) take precedence
    return {
      ...basePlotLayout,
      height: 500,           // Default height (will be overwritten by backend if provided)
      showlegend: false,
      ...dendrogramLayout,   // Backend values override defaults
    };
  }
  // Fallback: axis titles match backend defaults (Distance on X, Sample Index on Y for rotated dendrogram)
  return {
    ...basePlotLayout,
    height: 500,
    showlegend: false,
    xaxis: { ...basePlotLayout.xaxis, title: "Distance" },
    yaxis: { ...basePlotLayout.yaxis, title: "Sample Index" },
  };
});

// ============================================================================
// Peak Finding Plot (pre-computed on the backend)
// ============================================================================
const peakFindingPlotData = computed(() => {
  if (nodeTypeKey.value !== "analysis.peak_finding" || !hasOutput.value) return [];
  const plots = nodeOutput.value?.plots;
  if (plots?.peak_finding?.data) {
    return plots.peak_finding.data;
  }
  return [];
});

const peakFindingPlotLayout = computed(() => {
  if (nodeTypeKey.value !== "analysis.peak_finding" || !hasOutput.value) {
    return { ...basePlotLayout, height: 500 };
  }
  const plots = nodeOutput.value?.plots;
  const backendLayout = plots?.peak_finding?.layout;
  if (backendLayout) {
    return { ...basePlotLayout, height: 500, ...backendLayout };
  }
  return { ...basePlotLayout, height: 500 };
});

const plsdaLoadingsData = computed(() => {
  if (nodeTypeKey.value !== "classification.plsda" || !hasOutput.value) return [];

  // Use pre-built plots from backend (preferred)
  const plots = nodeOutput.value?.plots;

  if (plsdaLoadingsViewMode.value === "lines") {
    // Try loadings_lines first, fall back to loadings
    if (plots?.loadings_lines?.data) {
      return plots.loadings_lines.data;
    } else if (plots?.loadings?.data) {
      return plots.loadings.data;
    }
  } else if (plsdaLoadingsViewMode.value === "biplot") {
    // Try loadings_biplot first, fall back to old biplot in loadings
    if (plots?.loadings_biplot?.data) {
      return plots.loadings_biplot.data;
    }
  }

  // Fallback: dummy invisible trace needed for Plotly to render annotations
  return [{
    x: [0],
    y: [0],
    type: "scatter",
    mode: "markers",
    marker: { size: 0.1, opacity: 0 },
    showlegend: false,
    hoverinfo: "skip",
  }];
});

const plsdaLoadingsLayout = computed(() => {
  // Use pre-built layout if available
  const plots = nodeOutput.value?.plots;

  if (plsdaLoadingsViewMode.value === "lines") {
    if (plots?.loadings_lines?.layout) {
      return {
        ...basePlotLayout,
        ...plots.loadings_lines.layout,
        height: 350,
      };
    } else if (plots?.loadings?.layout) {
      return {
        ...basePlotLayout,
        ...plots.loadings.layout,
        height: 350,
      };
    }
  } else if (plsdaLoadingsViewMode.value === "biplot") {
    if (plots?.loadings_biplot?.layout) {
      return {
        ...basePlotLayout,
        ...plots.loadings_biplot.layout,
        height: 350,
      };
    }
  }

  // Fallback layout with arrow annotations
  const loadingsPort = nodeOutput.value?.ports?.loadings || nodeOutput.value?.ports?.X_loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const loadings = loadingsPort?.data || metadata.loadings || [];
  const feature_names = metadata.feature_names;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;

  if (!loadings || loadings.length === 0 || loadings[0]?.length < 2) {
    return {
      ...basePlotLayout,
      height: 350,
      showlegend: false,
      xaxis: { ...basePlotLayout.xaxis, title: "Loading on LV1" },
      yaxis: { ...basePlotLayout.yaxis, title: "Loading on LV2" },
    };
  }

  const n_features = loadings.length;

  // Create labels for features
  let labels;
  if (feature_names && feature_names.length === n_features) {
    labels = feature_names;
  } else if (wavenumbers && wavenumbers.length === n_features) {
    if (wavenumbers.length <= 50) {
      labels = wavenumbers.map((w: number) => w.toFixed(0));
    } else {
      const step = Math.floor(wavenumbers.length / 20);
      labels = wavenumbers.map((w: number, i: number) => i % step === 0 ? w.toFixed(0) : "");
    }
  } else {
    labels = Array.from({ length: n_features }, (_, i) => `F${i}`);
  }

  // Create arrow annotations (quiver plot style)
  const annotations: any[] = [];
  for (let i = 0; i < loadings.length; i++) {
    const lv1 = loadings[i][0];
    const lv2 = loadings[i][1];

    // Arrow from origin to loading position
    annotations.push({
      x: lv1,
      y: lv2,
      ax: 0,
      ay: 0,
      xref: "x",
      yref: "y",
      axref: "x",
      ayref: "y",
      showarrow: true,
      arrowhead: 2,
      arrowsize: 1,
      arrowwidth: 2,
      arrowcolor: "steelblue",
    });

    // Text label at 1.15x arrow length
    annotations.push({
      x: lv1 * 1.15,
      y: lv2 * 1.15,
      text: labels[i],
      xref: "x",
      yref: "y",
      showarrow: false,
      font: { size: 10, color: "black" },
      xanchor: "center",
      yanchor: "middle",
    });
  }

  return {
    ...basePlotLayout,
    height: 350,
    showlegend: false,
    xaxis: {
      ...basePlotLayout.xaxis,
      title: "Loading on LV1",
      zeroline: true,
      zerolinecolor: "gray",
      zerolinewidth: 1,
    },
    yaxis: {
      ...basePlotLayout.yaxis,
      title: "Loading on LV2",
      zeroline: true,
      zerolinecolor: "gray",
      zerolinewidth: 1,
    },
    annotations,
    hovermode: "closest",
  };
});

const plsdaVipData = computed(() => {
  if (nodeTypeKey.value !== "classification.plsda" || !hasOutput.value) return [];

  // Use pre-built VIP plot
  const plots = nodeOutput.value?.plots;
  if (plots?.vip?.data) {
    return plots.vip.data;
  }

  // Fallback: build from metadata
  const loadingsPort = nodeOutput.value?.ports?.loadings || nodeOutput.value?.ports?.X_loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const vip_scores = metadata.vip_scores;
  const feature_names = metadata.feature_names;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;

  if (!vip_scores || vip_scores.length === 0) return [];

  // Show top N VIP scores
  const top_n = Math.min(50, vip_scores.length);
  const indices = Array.from(vip_scores.keys()) as number[];
  indices.sort((a, b) => vip_scores[b] - vip_scores[a]);
  const top_indices = indices.slice(0, top_n);

  // Priority: feature_names > wavenumbers > feature indices
  let x_values;
  if (feature_names && feature_names.length === vip_scores.length) {
    x_values = top_indices.map((i: number) => feature_names[i]);
  } else if (wavenumbers && wavenumbers.length === vip_scores.length) {
    x_values = top_indices.map((i: number) => wavenumbers[i]);
  } else {
    x_values = top_indices;
  }

  const y_values = top_indices.map((i: number) => vip_scores[i]);

  return [{
    x: x_values,
    y: y_values,
    type: "bar",
    name: "VIP Scores",
    marker: {
      color: y_values,
      colorscale: "Viridis",
      showscale: true,
      colorbar: { title: "VIP" },
    },
  }];
});

const plsdaVipLayout = computed(() => {
  // Use pre-built layout if available
  const plots = nodeOutput.value?.plots;
  if (plots?.vip?.layout) {
    return {
      ...basePlotLayout,
      ...plots.vip.layout,
      height: 350,
    };
  }

  // Fallback layout
  const metadata = nodeOutput.value?.metadata || {};
  const vip_scores = metadata.vip_scores || [];
  const feature_names = metadata.feature_names;
  const wavenumbers = metadata.wavenumbers;

  // Determine x-axis title from actual metadata
  let xaxis_title = "Feature Index";
  let xaxis_reversed = false;
  if (feature_names && feature_names.length > 0) {
    xaxis_title = "Feature";
  } else if (wavenumbers && wavenumbers.length > 0) {
    const xTitle = metadata.x_title || "Feature";
    const xUnits = metadata.x_units || "";
    xaxis_title = xUnits ? `${xTitle} (${xUnits})` : xTitle;
    xaxis_reversed = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  }

  // Calculate number of bars for threshold line
  const top_n = Math.min(50, vip_scores.length);

  return {
    ...basePlotLayout,
    height: 350,
    xaxis: { ...basePlotLayout.xaxis, title: xaxis_title, autorange: xaxis_reversed ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: "VIP Score" },
    shapes: top_n > 0 ? [{
      type: "line",
      x0: 0,
      x1: top_n - 1,
      y0: 1,
      y1: 1,
      line: { color: "red", width: 2, dash: "dash" },
    }] : [],
  };
});

// Confusion Matrix (Training) for PLS-DA
const plsdaConfusionTrainData = computed(() => {
  if (nodeTypeKey.value !== "classification.plsda" || !hasOutput.value) return [];

  const plots = nodeOutput.value?.plots;
  if (plots?.confusion_matrix_train?.data) {
    return plots.confusion_matrix_train.data;
  }

  return [];
});

const plsdaConfusionTrainLayout = computed(() => {
  const plots = nodeOutput.value?.plots;
  if (plots?.confusion_matrix_train?.layout) {
    return {
      ...basePlotLayout,
      ...plots.confusion_matrix_train.layout,
      height: 400,
    };
  }

  return {
    ...basePlotLayout,
    height: 400,
    title: "Confusion Matrix (Training)",
    xaxis: { ...basePlotLayout.xaxis, title: "Predicted Class" },
    yaxis: { ...basePlotLayout.yaxis, title: "True Class", autorange: "reversed" },
  };
});

// Confusion Matrix (Cross-Validation) for PLS-DA
const plsdaConfusionCVData = computed(() => {
  if (nodeTypeKey.value !== "classification.plsda" || !hasOutput.value) return [];

  const plots = nodeOutput.value?.plots;
  if (plots?.confusion_matrix_cv?.data) {
    return plots.confusion_matrix_cv.data;
  }

  return [];
});

const plsdaConfusionCVLayout = computed(() => {
  const plots = nodeOutput.value?.plots;
  if (plots?.confusion_matrix_cv?.layout) {
    return {
      ...basePlotLayout,
      ...plots.confusion_matrix_cv.layout,
      height: 400,
    };
  }

  return {
    ...basePlotLayout,
    height: 400,
    title: "Confusion Matrix (Cross-Validation)",
    xaxis: { ...basePlotLayout.xaxis, title: "Predicted Class" },
    yaxis: { ...basePlotLayout.yaxis, title: "True Class", autorange: "reversed" },
  };
});

// ============================================================================
// Preprocessing / DATA Spectra Plots
// ============================================================================

const spectraOverlayData = computed(() => {
  if (!hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const nFeatures = data[0]?.length || 0;
  const wn = metadata.wavenumbers;
  const wavenumbers = (Array.isArray(wn) && wn.length === nFeatures) ? wn : Array.from({ length: nFeatures }, (_, i) => i);
  const labelsRaw = metadata.labels || metadata.sample_labels || [];
  const labels = Array.isArray(labelsRaw) ? labelsRaw.map((label: any) => normalizeSampleLabel(label)) : [];

  if (!Array.isArray(data[0])) return [];

  const maxTraces = Math.min(data.length, 50);
  return data.slice(0, maxTraces).map((spectrum: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: wavenumbers,
    y: spectrum,
    name: labels[i] || `Spectrum ${i + 1}`,
    line: { width: 1.5 },
    opacity: 0.8,
  }));
});

const spectraOverlayLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const shouldReverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");

  return {
    ...basePlotLayout,
    height: 400,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)", font: { size: 10 } },
    xaxis: { ...basePlotLayout.xaxis, title: xLabel, autorange: shouldReverse ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: yAxisLabel.value || "Response" },
  };
});

const spectraContourData = computed(() => {
  if (!hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};

  if (!Array.isArray(data[0])) return [];

  const nFeatures = data[0].length;
  const wn = metadata.wavenumbers;
  const xValues = (Array.isArray(wn) && wn.length === nFeatures) ? wn : Array.from({ length: nFeatures }, (_, i) => i);
  const sampleIndices = Array.from({ length: data.length }, (_, i) => i + 1);
  const xTitle = metadata.x_title || "Feature";

  return [{
    type: "heatmap",
    z: data,
    x: xValues,
    y: sampleIndices,
    colorscale: "Viridis",
    hovertemplate: `${xTitle}: %{x:.1f}<br>Sample: %{y}<br>Value: %{z:.4f}<extra></extra>`,
  }];
});

const spectraContourLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const shouldReverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  const yLabel = metadata.is_time_series ? "Scan / Time Index" : "Sample Index";

  return {
    ...basePlotLayout,
    height: 400,
    xaxis: { ...basePlotLayout.xaxis, title: xLabel, autorange: shouldReverse ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: yLabel },
  };
});

// ============================================================================
// Generic Data Plots (for non-spectral datasets like Iris)
// ============================================================================

// Box plot data: one box per feature with points colored by class
const genericBoxPlotData = computed(() => {
  if (!hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const featureNames = metadata.feature_names || [];
  const targetPort = nodeOutput.value?.ports?.target;
  const target = targetPort?.data || metadata.target || [];
  const targetNames = metadata.target_names || [];

  if (!Array.isArray(data) || data.length === 0 || !Array.isArray(data[0])) return [];

  const numFeatures = data[0].length;
  const traces: any[] = [];
  const colors = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316"];

  // Create one box per feature (showing all data)
  for (let f = 0; f < numFeatures; f++) {
    const featureData = data.map((row: number[]) => row[f]);
    const featureName = featureNames[f] || `Feature ${f + 1}`;
    traces.push({
      type: "box",
      y: featureData,
      name: featureName,
      marker: { color: "#64748b" }, // Neutral gray for boxes
      boxpoints: false, // Don't show points on box - we'll add colored scatter
      showlegend: false,
    });
  }

  // If we have labels, add colored scatter points on top
  if (target.length > 0 && targetNames.length > 0) {
    targetNames.forEach((className: string, classIdx: number) => {
      const classIndices = target
        .map((t: number | string, i: number) => (t === classIdx || t === className) ? i : -1)
        .filter((i: number) => i >= 0);

      // Collect all points for this class across all features
      const xValues: string[] = [];
      const yValues: number[] = [];

      featureNames.forEach((featureName: string, featureIdx: number) => {
        classIndices.forEach((rowIdx: number) => {
          // Add jitter to x position for visibility
          xValues.push(featureName);
          yValues.push(data[rowIdx][featureIdx]);
        });
      });

      traces.push({
        type: "scatter",
        mode: "markers",
        x: xValues,
        y: yValues,
        name: className,
        marker: {
          color: colors[classIdx % colors.length],
          size: 6,
          opacity: 0.7,
        },
        legendgroup: className,
        showlegend: true,
        hovertemplate: `${className}<br>%{x}: %{y:.3f}<extra></extra>`,
      });
    });
  }

  return traces;
});

const genericBoxPlotLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const targetPort = nodeOutput.value?.ports?.target;
  const hasTarget = (targetPort?.data?.length || metadata.target?.length || 0) > 0;

  return {
    ...basePlotLayout,
    height: 400,
    showlegend: hasTarget,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)", font: { size: 10 } },
    xaxis: { ...basePlotLayout.xaxis, title: "Feature" },
    yaxis: { ...basePlotLayout.yaxis, title: "Value" },
  };
});

// Feature scatter plot: X vs Y with label coloring
const genericScatterData = computed(() => {
  if (!hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const featureNames = metadata.feature_names || [];
  const targetPort = nodeOutput.value?.ports?.target;
  const target = targetPort?.data || metadata.target || [];
  const targetNames = metadata.target_names || [];

  if (!Array.isArray(data) || data.length === 0 || !Array.isArray(data[0])) return [];

  const xIdx = featureXAxis.value;
  const yIdx = featureYAxis.value;
  const xName = featureNames[xIdx] || `Feature ${xIdx + 1}`;
  const yName = featureNames[yIdx] || `Feature ${yIdx + 1}`;

  const colors = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316"];

  // If we have labels, create one trace per class
  if (target.length > 0 && targetNames.length > 0) {
    return targetNames.map((className: string, classIdx: number) => {
      const classIndices = target
        .map((t: number | string, i: number) => (t === classIdx || t === className) ? i : -1)
        .filter((i: number) => i >= 0);

      return {
        type: "scatter",
        mode: "markers",
        x: classIndices.map((i: number) => data[i][xIdx]),
        y: classIndices.map((i: number) => data[i][yIdx]),
        name: className,
        marker: {
          color: colors[classIdx % colors.length],
          size: 8,
          opacity: 0.8,
        },
        hovertemplate: `${xName}: %{x:.3f}<br>${yName}: %{y:.3f}<br>${className}<extra></extra>`,
      };
    });
  } else {
    // No labels: single trace
    return [{
      type: "scatter",
      mode: "markers",
      x: data.map((row: number[]) => row[xIdx]),
      y: data.map((row: number[]) => row[yIdx]),
      name: "Samples",
      marker: {
        color: "#3b82f6",
        size: 8,
        opacity: 0.8,
      },
      hovertemplate: `${xName}: %{x:.3f}<br>${yName}: %{y:.3f}<extra></extra>`,
    }];
  }
});

const genericScatterLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const targetPort = nodeOutput.value?.ports?.target;
  const featureNames = metadata.feature_names || [];
  const xName = featureNames[featureXAxis.value] || `Feature ${featureXAxis.value + 1}`;
  const yName = featureNames[featureYAxis.value] || `Feature ${featureYAxis.value + 1}`;
  const hasTarget = (targetPort?.data?.length || metadata.target?.length || 0) > 0;

  return {
    ...basePlotLayout,
    height: 400,
    showlegend: hasTarget,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)", font: { size: 10 } },
    xaxis: { ...basePlotLayout.xaxis, title: xName },
    yaxis: { ...basePlotLayout.yaxis, title: yName },
  };
});

// Handle contour click for interactive slicing
const handleContourClick = (event: any) => {
  if (!event.points || !event.points.length) return;
  const point = event.points[0];
  const metadata = nodeOutput.value?.metadata || {};
  const wavenumbers = metadata.wavenumbers || [];

  // Find closest indices
  const clickedX = point.x;
  const clickedY = point.y;

  // Find wavenumber index
  let wavenumberIdx = 0;
  if (wavenumbers.length) {
    let minDiff = Infinity;
    wavenumbers.forEach((wn: number, i: number) => {
      const diff = Math.abs(wn - clickedX);
      if (diff < minDiff) {
        minDiff = diff;
        wavenumberIdx = i;
      }
    });
  } else {
    wavenumberIdx = Math.round(clickedX);
  }

  const sampleIdx = Math.round(clickedY) - 1; // Convert to 0-indexed

  contourClickPoint.value = {
    sampleIdx: Math.max(0, sampleIdx),
    wavenumberIdx,
    wavenumber: wavenumbers[wavenumberIdx] || wavenumberIdx,
  };
};

// Horizontal slice (spectrum at selected sample)
const horizontalSliceData = computed(() => {
  if (!contourClickPoint.value || !hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const nFeatures = data[0]?.length || 0;
  const wn = metadata.wavenumbers;
  const xValues = (Array.isArray(wn) && wn.length === nFeatures) ? wn : Array.from({ length: nFeatures }, (_, i) => i);
  const xTitle = metadata.x_title || "Feature";

  const spectrum = data[contourClickPoint.value.sampleIdx];
  if (!spectrum) return [];

  return [{
    type: "scatter",
    mode: "lines",
    x: xValues,
    y: spectrum,
    line: { color: "#3b82f6", width: 2 },
    hovertemplate: `${xTitle}: %{x:.1f}<br>Value: %{y:.4f}<extra></extra>`,
  }, {
    // Marker at clicked point
    type: "scatter",
    mode: "markers",
    x: [contourClickPoint.value.wavenumber],
    y: [spectrum[contourClickPoint.value.wavenumberIdx]],
    marker: { size: 12, color: "#f97316", symbol: "circle" },
    showlegend: false,
    hoverinfo: "skip",
  }];
});

const horizontalSliceLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const shouldReverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");

  return {
    ...basePlotLayout,
    height: 250,
    showlegend: false,
    xaxis: { ...basePlotLayout.xaxis, title: xLabel, autorange: shouldReverse ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: yAxisLabel.value || "Response" },
  };
});

// Vertical slice (time profile at selected wavenumber)
const verticalSliceData = computed(() => {
  if (!contourClickPoint.value || !hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];

  const profile = data.map((row: number[]) => row[contourClickPoint.value!.wavenumberIdx]);
  const x = Array.from({ length: data.length }, (_, i) => i + 1);

  return [{
    type: "scatter",
    mode: "lines",
    x,
    y: profile,
    line: { color: "#10b981", width: 2 },
    hovertemplate: "Sample %{x}: %{y:.4f}<extra></extra>",
  }, {
    // Marker at clicked point
    type: "scatter",
    mode: "markers",
    x: [contourClickPoint.value.sampleIdx + 1],
    y: [profile[contourClickPoint.value.sampleIdx]],
    marker: { size: 12, color: "#f97316", symbol: "circle" },
    showlegend: false,
    hoverinfo: "skip",
  }];
});

const verticalSliceLayout = computed(() => ({
  ...basePlotLayout,
  height: 250,
  showlegend: false,
  xaxis: { ...basePlotLayout.xaxis, title: "Sample Index" },
  yaxis: { ...basePlotLayout.yaxis, title: yAxisLabel.value || "Response" },
}));

// ============================================================================
// STATS Plots (adaptive: PeakFinding → bar chart, otherwise → histogram)
// ============================================================================

const statsPlotData = computed(() => {
  if (nodeTypeKey.value !== "stats.summary" || !hasOutput.value) return [];
  const portValue = nodeOutput.value?.ports?.statistics?.value as Record<string, unknown> | undefined;
  const metadata = nodeOutput.value?.metadata || {};
  const inputType = (portValue?.input_type as string) || (metadata.type as string) || "";

  // PeakFinding: two-axis plot
  //   - Vertical axis: median height with IQR error bars (intensity variation)
  //   - Horizontal axis: position with std error bars (positional scatter)
  if (inputType === "PeakFinding") {
    const horiz = (portValue?.horizontal || []) as Array<Record<string, number | string>>;
    const vert = (portValue?.vertical || []) as Array<Record<string, number | string>>;
    if (!horiz.length) return [];

    const positions = horiz.map((h) => Number(h.median_pos));
    const heights = vert.map((v) => Number(v.median_height));
    const q1 = vert.map((v) => Number(v.q1_height));
    const q3 = vert.map((v) => Number(v.q3_height));
    const posStd = horiz.map((h) => Number(h.std_pos));
    const labels = horiz.map((h, i) => {
      const v = vert[i];
      return `<b>${h.label}</b><br>` +
        `Position: ${Number(h.median_pos).toFixed(1)} ± ${Number(h.std_pos).toFixed(1)}<br>` +
        `Range: ${Number(h.min_pos).toFixed(1)}–${Number(h.max_pos).toFixed(1)}<br>` +
        `Height: ${Number(v.median_height).toFixed(4)}<br>` +
        `IQR: ${Number(v.q1_height).toFixed(4)}–${Number(v.q3_height).toFixed(4)}`;
    });

    return [{
      type: "scatter",
      mode: "markers",
      x: positions,
      y: heights,
      text: labels,
      hovertemplate: "%{text}<extra></extra>",
      marker: { color: "#3b82f6", size: 10 },
      name: "Median Height",
      error_y: {
        type: "data",
        symmetric: false,
        array: q3.map((q, i) => q - heights[i]),       // upper = q3 - median
        arrayminus: heights.map((h, i) => h - q1[i]),   // lower = median - q1
        color: "#60a5fa",
        thickness: 2,
        width: 6,
      },
      error_x: {
        type: "data",
        array: posStd,
        arrayminus: posStd,
        color: "#94a3b8",
        thickness: 1.5,
        width: 4,
      },
    }];
  }

  // Default: histogram of flattened numeric data
  const data = nodeOutput.value?.data || [];
  const values: number[] = [];
  for (const row of data) {
    if (Array.isArray(row)) {
      for (const val of row) {
        if (typeof val === "number" && !isNaN(val)) values.push(val);
      }
    } else if (typeof row === "number") {
      values.push(row);
    } else if (typeof row === "object" && row !== null) {
      for (const val of Object.values(row)) {
        if (typeof val === "number" && !isNaN(val)) values.push(val);
      }
    }
  }
  return [{
    type: "histogram",
    x: values,
    nbinsx: 50,
    marker: { color: "#3b82f6" },
    hovertemplate: "Range: %{x}<br>Count: %{y}<extra></extra>",
  }];
});

const statsPlotLayout = computed(() => {
  const portValue = nodeOutput.value?.ports?.statistics?.value as Record<string, unknown> | undefined;
  const metadata = nodeOutput.value?.metadata || {};
  const inputType = (portValue?.input_type as string) || (metadata.type as string) || "";

  if (inputType === "PeakFinding") {
    const summary = (portValue?.summary || {}) as Record<string, unknown>;
    const xLabel = (summary.x_label as string) || "Position";
    return {
      ...basePlotLayout,
      height: 450,
      title: { text: "Peak Consensus: Position ± σ (horizontal) · Height ± IQR (vertical)", font: { size: 13, color: "#94a3b8" } },
      xaxis: { ...basePlotLayout.xaxis, title: xLabel },
      yaxis: { ...basePlotLayout.yaxis, title: "Peak Height (absorbance)" },
      showlegend: false,
    };
  }
  return {
    ...basePlotLayout,
    height: 350,
    xaxis: { ...basePlotLayout.xaxis, title: "Value" },
    yaxis: { ...basePlotLayout.yaxis, title: "Count" },
    bargap: 0.05,
  };
});



// ============================================================================
// EFA Eigenvalue Plot
// ============================================================================

const efaEigenvalueData = computed(() => {
  if (nodeTypeKey.value !== "model.efa" || !hasOutput.value) return [];
  // EFA primary output is forward eigenvalues as a SherpaDataset
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  if (!data.length || !Array.isArray(data[0])) return [];

  const nSamples = data.length;
  const nComponents = data[0].length;
  const x = Array.from({ length: nSamples }, (_, i) => i + 1);

  // Forward eigenvalues from primary output
  const traces: Record<string, unknown>[] = [];
  for (let c = 0; c < nComponents; c++) {
    traces.push({
      type: "scatter",
      mode: "lines",
      x,
      y: data.map((row: number[]) => row[c]),
      name: `Forward EV ${c + 1}`,
      line: { width: 2 },
    });
  }

  // Backward eigenvalues from ports if available
  const bwPort = nodeOutput.value?.ports?.backward_eigenvalues;
  const bwData = bwPort?.data || bwPort?.value?.data;
  if (bwData && Array.isArray(bwData) && bwData.length > 0) {
    const bwComponents = bwData[0]?.length || 0;
    for (let c = 0; c < bwComponents; c++) {
      traces.push({
        type: "scatter",
        mode: "lines",
        x,
        y: bwData.map((row: number[]) => row[c]),
        name: `Backward EV ${c + 1}`,
        line: { width: 2, dash: "dash" },
      });
    }
  }

  return traces;
});

const efaEigenvalueLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  return {
    ...basePlotLayout,
    height: 450,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...basePlotLayout.xaxis, title: metadata.x_title || "Sample Index" },
    yaxis: { ...basePlotLayout.yaxis, title: "Eigenvalue (log scale)", type: "log" },
  };
});

// ============================================================================
// Regression: Predicted vs Actual correlation plot
// ============================================================================

const regressionTargetNames = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const yLoadings = resolvePortPayload(nodeOutput.value?.ports?.Y_loadings);
  const targetPort = resolvePortPayload(nodeOutput.value?.ports?.target);
  const candidates = [
    metadata.target_names,
    yLoadings?.y_axis?.labels,
    targetPort?.y_axis?.labels,
    targetPort?.metadata?.target_names,
  ];

  for (const raw of candidates) {
    if (Array.isArray(raw) && raw.length > 0) {
      return raw.map((name: unknown) => normalizeSampleLabel(name));
    }
  }

  return [];
});

const regressionTargetOptions = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const yTrue = metadata.y_true;
  if (!Array.isArray(yTrue) || yTrue.length === 0) return [];
  const nTargets = Array.isArray(yTrue[0]) ? yTrue[0].length : 1;
  const names = regressionTargetNames.value;
  return Array.from({ length: nTargets }, (_, i) => ({
    label: names[i] || `Target ${i + 1}`,
    value: i,
  }));
});

watch(
  regressionTargetOptions,
  (options) => {
    if (options.length === 0) {
      regressionTargetIdx.value = 0;
      return;
    }
    if (!options.some((option) => option.value === regressionTargetIdx.value)) {
      regressionTargetIdx.value = options[0].value;
    }
  },
  { immediate: true },
);

const selectedRegressionR2 = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const r2List = metadata.r2_per_target;
  if (!Array.isArray(r2List)) return null;
  const value = r2List[regressionTargetIdx.value];
  return typeof value === "number" ? value : null;
});

const selectedRegressionRmse = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const rmseList = metadata.rmse_per_target;
  if (!Array.isArray(rmseList)) return null;
  const value = rmseList[regressionTargetIdx.value];
  return typeof value === "number" ? value : null;
});

const regressionCorrelationData = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const yTrue = metadata.y_true;
  const yPred = metadata.y_pred;
  if (!Array.isArray(yTrue) || !Array.isArray(yPred) || yTrue.length === 0) return [];

  try {
    const idx = regressionTargetIdx.value;
    const trueVals = yTrue.map((row: number[]) => (Array.isArray(row) ? row[idx] : row));
    const predVals = yPred.map((row: number[]) => (Array.isArray(row) ? row[idx] : row));

    const allVals = [...trueVals, ...predVals];
    const minVal = Math.min(...allVals);
    const maxVal = Math.max(...allVals);
    const pad = (maxVal - minVal) * 0.05 || 0.1;

  return [
    {
      type: "scatter",
      mode: "markers",
      x: trueVals,
      y: predVals,
      marker: { color: "#3b82f6", size: 7, opacity: 0.7 },
      name: "Samples",
      hovertemplate: "Actual: %{x:.3f}<br>Predicted: %{y:.3f}<extra></extra>",
    },
    {
      type: "scatter",
      mode: "lines",
      x: [minVal - pad, maxVal + pad],
      y: [minVal - pad, maxVal + pad],
      line: { color: "#94a3b8", dash: "dash", width: 1.5 },
      name: "1:1 Line",
      showlegend: false,
      hoverinfo: "skip",
    },
  ];
  } catch (e) {
    console.error("[Regression Plot] ERROR in computed:", e);
    return [];
  }
});

const regressionCorrelationLayout = computed(() => {
  const targetName = regressionTargetOptions.value.find((option) => option.value === regressionTargetIdx.value)?.label || "";
  const r2 = selectedRegressionR2.value;
  const rmse = selectedRegressionRmse.value;

  let title = "Predicted vs Actual";
  if (targetName) title += ` — ${targetName}`;
  const metrics: string[] = [];
  if (r2 != null) metrics.push(`R² = ${r2.toFixed(4)}`);
  if (rmse != null) metrics.push(`RMSE = ${rmse.toFixed(4)}`);
  if (metrics.length) title += `<br><span style="font-size:11px;color:#94a3b8">${metrics.join("  |  ")}</span>`;

  return {
    ...basePlotLayout,
    height: 400,
    title: { text: title, font: { size: 14, color: "#f8fafc" } },
    xaxis: { ...basePlotLayout.xaxis, title: "Actual" },
    yaxis: { ...basePlotLayout.yaxis, title: "Predicted", scaleanchor: "x", scaleratio: 1 },
    showlegend: false,
  };
});

// ============================================================================
// Classification: Per-class accuracy bar chart
// ============================================================================

const classificationAccuracyData = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const yTrue = metadata.y_true;
  const yPred = metadata.y_pred;
  const categories = metadata.label_categories;
  if (!Array.isArray(yTrue) || !Array.isArray(yPred) || !Array.isArray(categories)) return [];

  // Compute per-class accuracy
  const classCorrect: Record<string, number> = {};
  const classTotal: Record<string, number> = {};
  for (const c of categories) {
    classCorrect[c] = 0;
    classTotal[c] = 0;
  }
  for (let i = 0; i < yTrue.length; i++) {
    const t = String(yTrue[i]);
    const p = String(yPred[i]);
    if (classTotal[t] !== undefined) {
      classTotal[t]++;
      if (t === p) classCorrect[t]++;
    }
  }

  const accuracies = categories.map((c: string) =>
    classTotal[c] > 0 ? classCorrect[c] / classTotal[c] : 0
  );
  const overall = yTrue.length > 0
    ? yTrue.filter((t: string, i: number) => String(t) === String(yPred[i])).length / yTrue.length
    : 0;

  return [
    {
      type: "bar",
      x: categories,
      y: accuracies.map((a: number) => a * 100),
      marker: { color: "#3b82f6" },
      name: "Per-class",
      hovertemplate: "%{x}: %{y:.1f}%<extra></extra>",
    },
    {
      type: "scatter",
      mode: "lines",
      x: [categories[0], categories[categories.length - 1]],
      y: [overall * 100, overall * 100],
      line: { color: "#f59e0b", dash: "dash", width: 2 },
      name: `Overall (${(overall * 100).toFixed(1)}%)`,
    },
  ];
});

const classificationAccuracyLayout = computed(() => {
  return {
    ...basePlotLayout,
    height: 350,
    title: { text: "Per-Class Accuracy", font: { size: 14, color: "#f8fafc" } },
    xaxis: { ...basePlotLayout.xaxis, title: "Class" },
    yaxis: { ...basePlotLayout.yaxis, title: "Accuracy (%)", range: [0, 105] },
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
  };
});

// ============================================================================
// End of Plots Section
// ============================================================================

// Methods
const toggleSection = (section: "input" | "settings" | "output" | "plots" | "log") => {
  sections.value[section] = !sections.value[section];
};

const toggleOutputSubsection = (
  section: "coordinates" | "metadata" | "processing" | "provenance" | "quality" | "ports",
) => {
  outputSubsections.value[section] = !outputSubsections.value[section];
};

const togglePlot = (plot: string) => {
  plotSections.value[plot] = !plotSections.value[plot];
};

const resetToDefaults = () => {
  for (const param of nodeParams.value) {
    if (param.default !== undefined) {
      localParams.value[param.name] = param.default;
    }
  }
  toast.add({
    severity: "info",
    summary: "Reset",
    detail: "Parameters reset to defaults",
    life: 2000,
  });
};

const formatMetaValue = (value: any): string => {
  if (value === null || value === undefined) return "\u2014";
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const preview = value.slice(0, 5).map((v: any) =>
      typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(4)) : String(v)
    );
    return `[${preview.join(", ")}${value.length > 5 ? `, \u2026 (${value.length})` : ""}]`;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length === 0) return "{}";
    const preview = keys.slice(0, 4).map((k) => {
      const v = value[k];
      const short = typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2))
        : typeof v === "string" ? (v.length > 20 ? v.slice(0, 20) + "\u2026" : v)
        : String(v);
      return `${k}: ${short}`;
    });
    return `{${preview.join(", ")}${keys.length > 4 ? ", \u2026" : ""}}`;
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  return String(value);
};

const openDataTable = () => {
  showDataTableModal.value = true;
};

const openQuickPlot = () => {
  showQuickPlotModal.value = true;
};

const exportOutput = () => {
  const data = nodeOutput.value?.data;
  if (!data || !Array.isArray(data)) return;

  let csv = "";
  if (Array.isArray(data[0])) {
    csv = data.map((row: any[]) => row.join(",")).join("\n");
  } else {
    csv = data.join("\n");
  }

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${nodeLabel.value.replace(/\s+/g, "_")}_output.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
};

const handleCancel = () => {
  // Close without saving
  window.close();
};

// Broadcast params update to main tab
const broadcastParamsUpdate = () => {
  const updateMessage = {
    type: "node_params_updated",
    nodeId: nodeData.value?.id,
    nodeType: nodeData.value?.type,
    params: { ...localParams.value },
    timestamp: Date.now(),
  };

  // Try BroadcastChannel first (more reliable)
  if (broadcastChannel.value) {
    broadcastChannel.value.postMessage(updateMessage);
  }

  // Also update sessionStorage and dispatch event as fallback
  const updatedData = {
    ...nodeData.value,
    params: { ...localParams.value },
    _saved: true,
    _savedAt: Date.now(),
  };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(updatedData));
  window.dispatchEvent(new StorageEvent("storage", {
    key: STORAGE_KEY,
    newValue: JSON.stringify(updatedData),
  }));
};

const handleSaveAndExit = () => {
  // Broadcast params update to main tab
  broadcastParamsUpdate();

  toast.add({
    severity: "success",
    summary: "Saved",
    detail: "Settings saved successfully",
    life: 1500,
  });

  // Close after brief delay
  setTimeout(() => {
    window.close();
  }, 500);
};

/**
 * Run a trial execution of this node with current local parameters.
 *
 * This calls the backend trial API directly, bypassing the main workflow.
 * The trial runs in a fresh execution context (no caching) and does NOT
 * persist any changes to the workflow.
 *
 * Flow:
 * - Run Trial: Execute with trial params, see results locally
 * - Cancel: Discard trial, close window (no changes saved)
 * - Save and Exit: Persist params to workflow, then close
 *
 * IMPORTANT: Since Pinia stores don't sync across browser tabs, this function
 * reads the workflow nodes/edges from sessionStorage (passed by WorkflowInspector).
 */
const handleRunTrial = async () => {
  if (!nodeData.value) return;

  isExecuting.value = true;
  addLog("info", "Trial started", `Running ${nodeType.value} with trial settings`);

  toast.add({
    severity: "info",
    summary: "Running Trial",
    detail: "Executing with current settings...",
    life: 2000,
  });

  try {
    // Read workflow nodes/edges from nodeData (loaded from sessionStorage)
    // These are passed by WorkflowInspector since Pinia stores don't sync across tabs
    const workflowNodes = nodeData.value.workflowNodes || [];
    const workflowEdges = nodeData.value.workflowEdges || [];

    if (workflowNodes.length === 0) {
      throw new Error("No workflow nodes found. Please reopen from the workflow inspector.");
    }

    // Build nodes list for trial API (using backend format)
    // IMPORTANT: Map ALL node parameters from frontend names to backend names
    const trialNodes = workflowNodes.map((node: any) => ({
      node_id: String(node.id),
      node_type: node.type,
      parameters: { ...(node.params || {}) },
    }));

    // Build edges list for trial API
    const trialEdges = workflowEdges.map((edge: any) => ({
      from_node_id: String(edge.from),
      to_node_id: String(edge.to),
      from_output: edge.fromPort || "default",
      to_input: edge.toPort || "default",
    }));

    // Build initial data for DATA nodes (needed for upstream dependencies)
    const initialData: Record<string, any> = {};
    // If this node's input came from a DATA node, include its config
    if (nodeData.value.inputData?.experiment_id) {
      // Find DATA node ID from input connections
      const inputConnections = nodeData.value.inputConnections || [];
      for (const conn of inputConnections) {
        if (conn.nodeType === "data.source") {
          initialData[String(conn.nodeId)] = {
            experiment_id: nodeData.value.inputData.experiment_id,
            source: nodeData.value.inputData.source || "experiment",
          };
        }
      }
    }

    // Map trial params from frontend names to backend names
    // E.g., "components" -> "n_components" for PCA
    const mappedTrialParams = { ...localParams.value };

    // Build trial execution request payload
    const trialPayload = {
      target_node_id: String(nodeData.value.id),
      trial_params: mappedTrialParams,
      nodes: trialNodes,
      edges: trialEdges,
      initial_data: Object.keys(initialData).length > 0 ? initialData : null,
    };

    const targetNodeInList = trialNodes.find((n: any) => n.node_id === String(nodeData.value.id));

    console.log("[NodeDetailView] Trial execution details:", {
      targetNodeId: trialPayload.target_node_id,
      targetNodeIdType: typeof trialPayload.target_node_id,
      nodeType: nodeData.value.type,
      nodeCount: trialNodes.length,
      edgeCount: trialEdges.length,
      localParams: localParams.value,
      mappedTrialParams: mappedTrialParams,
      targetNodeInList: targetNodeInList,
      allNodeIds: trialNodes.map((n: any) => ({ id: n.node_id, type: typeof n.node_id, params: n.parameters })),
    });

    // Log meaningful parameter changes
    const changes: string[] = [];
    for (const [key, value] of Object.entries(mappedTrialParams)) {
      const oldValue = nodeData.value.params?.[key];
      if (oldValue !== undefined && oldValue !== value) {
        changes.push(`${key}: ${oldValue} → ${value}`);
      }
    }
    if (changes.length > 0) {
      addLog("info", "Parameter changes", changes.join(", "));
    }

    // Execute trial via direct API call
    const response = await api.post("/workflows/trial/execute", trialPayload);

    isExecuting.value = false;

    if (response.data.status === "error" || response.data.error) {
      addLog("error", "Trial failed", response.data.error || "Unknown error");
      toast.add({
        severity: "error",
        summary: "Trial Failed",
        detail: response.data.error || "Execution failed",
        life: 5000,
      });
      return;
    }

    // Update local output with trial result
    if (response.data.result) {
      // The result from trial API has the data and metadata directly
      const output = normalizeNodeOutput(response.data.result);

      console.log("[NodeDetailView] Trial completed, updating output:", {
        hasData: !!output.data,
        dataLength: Array.isArray(output.data) ? output.data.length : "N/A",
        metadataKeys: output.metadata ? Object.keys(output.metadata) : [],
      });

      // Update node data with new output (triggers reactive updates for plots)
      nodeData.value = {
        ...nodeData.value,
        output: output,
      };

      // Build output summary for log
      let outputSummary = "Trial completed";
      if (output.data && Array.isArray(output.data)) {
        const rows = output.data.length;
        const cols = Array.isArray(output.data[0]) ? output.data[0].length : 1;
        outputSummary = `Output: ${rows} × ${cols} matrix`;
      }

      addLog("success", "Trial completed", outputSummary);
      toast.add({
        severity: "success",
        summary: "Trial Complete",
        detail: outputSummary,
        life: 3000,
      });
    } else {
      addLog("warn", "Trial completed", "No output data returned");
      toast.add({
        severity: "warn",
        summary: "Trial Complete",
        detail: "Execution completed but no output data was returned",
        life: 3000,
      });
    }
  } catch (error: any) {
    isExecuting.value = false;
    const message = error?.response?.data?.detail || error?.message || String(error);
    addLog("error", "Trial failed", message);
    toast.add({
      severity: "error",
      summary: "Trial Failed",
      detail: message,
      life: 5000,
    });
  }
};

// Handle execution result from main tab
const handleBroadcastMessage = (event: MessageEvent) => {
  const { type, nodeId, output, error } = event.data;

  console.log('[NodeDetailView] Received broadcast:', { type, nodeId, localNodeId: nodeData.value?.id, hasOutput: !!output });

  // Use loose equality (==) to handle string/number type mismatches
  // e.g., nodeId might be "1" (string) while nodeData.value.id is 1 (number)
  if (String(nodeId) !== String(nodeData.value?.id)) {
    console.log('[NodeDetailView] Node ID mismatch, ignoring message');
    return;
  }

  if (type === "node_execution_result") {
    // Clear the timeout since we got a response
    if (executionTimeout) {
      clearTimeout(executionTimeout);
      executionTimeout = null;
    }

    isExecuting.value = false;

    if (error) {
      addLog("error", "Execution failed", error);
      toast.add({
        severity: "error",
        summary: "Execution Failed",
        detail: error,
        life: 5000,
      });
    } else if (output) {
      // Update node data with new output
      console.log('[NodeDetailView] Updating output:', {
        hasData: !!output.data,
        dataLength: Array.isArray(output.data) ? output.data.length : 'N/A',
        metadataKeys: output.metadata ? Object.keys(output.metadata) : [],
      });

      nodeData.value = {
        ...nodeData.value,
        output: output,
      };

      console.log('[NodeDetailView] nodeData.value.output updated, hasOutput:', hasOutput.value);

      // Build output summary for log
      let outputSummary = "Output updated";
      if (output.data && Array.isArray(output.data)) {
        const rows = output.data.length;
        const cols = Array.isArray(output.data[0]) ? output.data[0].length : 1;
        outputSummary = `Output: ${rows} x ${cols} matrix`;
      }

      addLog("success", "Execution complete", outputSummary);
      toast.add({
        severity: "success",
        summary: "Execution Complete",
        detail: "Node executed successfully. Output updated.",
        life: 3000,
      });
    } else {
      addLog("info", "Execution complete", "No output data received");
      toast.add({
        severity: "info",
        summary: "Execution Complete",
        detail: "Node executed but no output data received.",
        life: 3000,
      });
    }
  }
};

// Lifecycle
onMounted(() => {
  // Set up BroadcastChannel for cross-tab communication
  try {
    broadcastChannel.value = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
    broadcastChannel.value.onmessage = handleBroadcastMessage;
    console.log('[NodeDetailView] BroadcastChannel initialized');
  } catch (e) {
    console.warn('[NodeDetailView] BroadcastChannel not supported:', e);
  }

  // Load node data from session storage
  const storedData = sessionStorage.getItem(STORAGE_KEY);
  if (storedData) {
    try {
      nodeData.value = JSON.parse(storedData);

      // Build params with defaults from paramDefinitions, then override with stored values
      const defaults: Record<string, any> = {};
      const paramDefs = nodeParams.value || [];
      for (const param of paramDefs) {
        if (param.default !== undefined) {
          defaults[param.name] = param.default;
        }
      }

      // Merge: defaults first, then stored params override
      localParams.value = { ...defaults, ...nodeData.value.params };
      originalParams.value = { ...localParams.value };

      console.log('[NodeDetailView] Loaded params:', {
        defaults,
        stored: nodeData.value.params,
        merged: localParams.value,
      });
    } catch (e) {
      console.error("Failed to parse node data from session storage:", e);
      toast.add({
        severity: "error",
        summary: "Error",
        detail: "Failed to load node data",
        life: 3000,
      });
    }
  } else {
    toast.add({
      severity: "warn",
      summary: "No Data",
      detail: "No node data found. Please open from the workflow inspector.",
      life: 5000,
    });
  }
});

// Clean up on unmount
onUnmounted(() => {
  if (broadcastChannel.value) {
    broadcastChannel.value.close();
    broadcastChannel.value = null;
    console.log('[NodeDetailView] BroadcastChannel closed');
  }
});
</script>

<style scoped>
.node-detail-view {
  min-height: 100vh;
  background: #0f172a;
  color: #f8fafc;
}

/* Header */
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 32px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.node-icon {
  font-size: 2.5rem;
}

.header-info h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.node-type-badge {
  display: inline-block;
  margin-top: 4px;
  padding: 2px 10px;
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: uppercase;
}

.header-actions {
  display: flex;
  gap: 12px;
}

/* Main Content */
.detail-content {
  max-width: 1000px;
  margin: 0 auto;
  padding: 32px;
}

/* Sections */
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

.section-header:hover {
  background: rgba(51, 65, 85, 0.5);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-title i {
  font-size: 0.85rem;
  color: #64748b;
}

.section-title h2 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}

.section-badge {
  padding: 4px 10px;
  background: #334155;
  border-radius: 12px;
  font-size: 0.75rem;
  color: #94a3b8;
}

.section-content {
  padding: 20px;
  border-top: 1px solid #334155;
}

/* Collapse animation */
.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.collapse-enter-from,
.collapse-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

/* Empty sections */
.empty-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
}

.empty-section i {
  font-size: 2.5rem;
  margin-bottom: 16px;
  color: #475569;
}

.empty-section p {
  margin: 0 0 8px;
  font-size: 1rem;
}

.empty-section small {
  color: #475569;
  font-size: 0.85rem;
}

/* Info grid */
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-item label {
  font-size: 0.75rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.info-item span {
  font-size: 1rem;
  font-weight: 500;
}

/* Connections */
.connections-list {
  margin-bottom: 20px;
}

.connections-list h4 {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: #94a3b8;
  font-weight: 500;
}

.connection-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #0f172a;
  border-radius: 8px;
  margin-bottom: 8px;
}

.conn-icon {
  font-size: 1.2rem;
}

.conn-name {
  flex: 1;
  font-weight: 500;
}

.conn-port {
  font-size: 0.8rem;
  color: #64748b;
  padding: 2px 8px;
  background: #334155;
  border-radius: 4px;
}

/* Settings form */
.settings-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.param-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.param-field > label {
  font-size: 0.9rem;
  font-weight: 500;
}

.required-mark {
  color: #f87171;
  margin-left: 2px;
}

.param-description {
  font-size: 0.8rem;
  color: #64748b;
  margin-bottom: 4px;
}

/* Validation error styling */
.validation-error-banner {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 20px;
}

.error-banner-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.error-banner-header i {
  color: #ef4444;
  font-size: 1.2rem;
  margin-top: 2px;
  flex-shrink: 0;
}

.error-banner-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.error-banner-content strong {
  color: #ef4444;
  font-size: 0.95rem;
}

.error-banner-content span {
  color: #f87171;
  font-size: 0.85rem;
}

.error-list {
  list-style: none;
  padding: 0;
  margin: 12px 0 0 36px;
}

.error-list li {
  font-size: 0.85rem;
  color: #f87171;
  margin: 6px 0;
  line-height: 1.4;
}

.error-list li strong {
  color: #ef4444;
  font-weight: 600;
}

.param-field.has-error > label {
  color: #ef4444;
}

.param-error-message {
  display: block;
  color: #ef4444;
  font-size: 0.75rem;
  font-weight: 500;
  margin-top: 4px;
  padding: 6px 8px;
  background: rgba(239, 68, 68, 0.1);
  border-left: 2px solid #ef4444;
  border-radius: 2px;
}

.p-invalid {
  border-color: #ef4444 !important;
}

.toggle-field {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toggle-label {
  font-size: 0.9rem;
  color: #94a3b8;
}

.full-width {
  width: 100%;
}

.settings-actions {
  display: flex;
  justify-content: flex-start;
  padding-top: 12px;
  border-top: 1px solid #334155;
  margin-top: 8px;
}

/* Metadata section */
.metadata-section {
  margin-bottom: 20px;
}

.metadata-section h4 {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: #94a3b8;
  font-weight: 500;
}

.metadata-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
}

.metadata-item {
  font-size: 0.85rem;
}

.meta-key {
  color: #64748b;
  margin-right: 4px;
}

.meta-info-icon {
  margin-left: 6px;
  color: #94a3b8;
  font-size: 0.85rem;
}

.meta-info-icon:hover {
  color: #e2e8f0;
}

.meta-value {
  font-family: "JetBrains Mono", monospace;
  color: #f8fafc;
}

/* Output actions */
.output-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

/* Preview table */
.preview-table {
  margin-top: 20px;
}

.preview-table h4 {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: #94a3b8;
  font-weight: 500;
}

.preview-datatable {
  font-size: 0.8rem;
}

.preview-datatable :deep(.p-datatable-wrapper) {
  background: #0f172a;
  border-radius: 8px;
}

.preview-datatable :deep(.p-datatable-thead > tr > th) {
  background: #1e293b;
  color: #f8fafc;
  border-color: #334155;
  padding: 8px 10px;
  font-weight: 600;
}

.preview-datatable :deep(.p-datatable-tbody > tr) {
  background: #0f172a;
  color: #f8fafc;
}

.preview-datatable :deep(.p-datatable-tbody > tr:nth-child(even)) {
  background: rgba(30, 41, 59, 0.5);
}

.preview-datatable :deep(.p-datatable-tbody > tr > td) {
  border-color: #334155;
  padding: 6px 10px;
  font-family: "JetBrains Mono", monospace;
}

/* PrimeVue dark theme overrides */
:deep(.p-inputtext),
:deep(.p-inputnumber-input),
:deep(.p-dropdown) {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}

:deep(.p-inputtext:focus),
:deep(.p-inputnumber-input:focus),
:deep(.p-dropdown:focus),
:deep(.p-dropdown.p-focus) {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

:deep(.p-dropdown-panel) {
  background: #1e293b;
  border-color: #334155;
}

:deep(.p-dropdown-item) {
  color: #f8fafc;
}

:deep(.p-dropdown-item:hover) {
  background: #334155;
}

:deep(.p-inputswitch.p-inputswitch-checked .p-inputswitch-slider) {
  background: #3b82f6;
}

/* Plots Section */
.plots-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.plot-subsection {
  background: #0f172a;
  border-radius: 8px;
  border: 1px solid #334155;
  overflow: hidden;
}

.plot-subsection-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
  font-weight: 500;
  font-size: 0.95rem;
  transition: background 0.15s;
}

.plot-subsection-header:hover {
  background: rgba(51, 65, 85, 0.5);
}

.plot-subsection-header i {
  font-size: 0.8rem;
  color: #64748b;
}

.plot-container {
  padding: 16px;
  border-top: 1px solid #334155;
}

.plot-controls {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.plot-controls .control-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.plot-controls .control-group label {
  font-size: 0.85rem;
  color: #94a3b8;
  white-space: nowrap;
}

.plot-controls :deep(.p-dropdown) {
  min-width: 140px;
}

.detail-target-dropdown {
  width: 100%;
}

/* Interactive Contour */
.interactive-contour-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.slice-plots {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.slice-plot {
  background: #1e293b;
  border-radius: 8px;
  padding: 12px;
  border: 1px solid #334155;
}

.slice-plot h5 {
  margin: 0 0 8px;
  font-size: 0.85rem;
  font-weight: 500;
  color: #94a3b8;
}

.slice-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px;
  background: rgba(51, 65, 85, 0.3);
  border-radius: 8px;
  color: #64748b;
  font-size: 0.9rem;
}

.slice-hint i {
  font-size: 1.1rem;
  color: #3b82f6;
}

@media (max-width: 900px) {
  .slice-plots {
    grid-template-columns: 1fr;
  }
}

/* Log Section */
.log-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.log-entries {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.log-entry {
  display: grid;
  grid-template-columns: 70px 24px 1fr;
  align-items: start;
  gap: 10px;
  padding: 10px 14px;
  background: #0f172a;
  border-radius: 8px;
  border-left: 3px solid #334155;
  font-size: 0.85rem;
}

.log-entry.success {
  border-left-color: #22c55e;
  background: rgba(34, 197, 94, 0.05);
}

.log-entry.error {
  border-left-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
}

.log-entry.warn {
  border-left-color: #f59e0b;
  background: rgba(245, 158, 11, 0.05);
}

.log-entry.info {
  border-left-color: #3b82f6;
  background: rgba(59, 130, 246, 0.05);
}

.log-time {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.75rem;
  color: #64748b;
}

.log-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.log-entry.success .log-icon i {
  color: #22c55e;
}

.log-entry.error .log-icon i {
  color: #ef4444;
}

.log-entry.warn .log-icon i {
  color: #f59e0b;
}

.log-entry.info .log-icon i {
  color: #3b82f6;
}

.log-message {
  font-weight: 500;
  color: #f8fafc;
}

.log-details {
  grid-column: 3;
  font-size: 0.8rem;
  color: #94a3b8;
  margin-top: 2px;
}

.log-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
  border-top: 1px solid #334155;
}

/* Dataset Inspector sections */
.inspector-section {
  margin-bottom: 20px;
  padding: 14px;
  background: #0f172a;
  border-radius: 8px;
  border: 1px solid #334155;
}

.inspector-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 12px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #94a3b8;
  font-size: 0.85rem;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
}

.inspector-toggle-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.inspector-toggle i {
  font-size: 0.85rem;
}

.inspector-toggle-title i {
  color: #3b82f6;
}

.inspector-toggle > i:last-child {
  color: #64748b;
}

.inspector-toggle:hover {
  color: #cbd5e1;
}

.inspector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px 20px;
}

.inspector-grid .wide {
  grid-column: 1 / -1;
}

.inspector-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.insp-label {
  font-size: 0.7rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.insp-value {
  font-size: 0.85rem;
  color: #f8fafc;
  font-weight: 500;
}

.insp-value.mono {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.8rem;
}

.insp-label-table-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.insp-label-table {
  width: 100%;
  border-collapse: collapse;
  border: 1px solid #334155;
  font-family: "JetBrains Mono", monospace;
  font-size: 0.78rem;
}

.insp-label-table th,
.insp-label-table td {
  border: 1px solid #334155;
  padding: 4px 6px;
  text-align: left;
  vertical-align: top;
}

.insp-label-table th {
  background: #1e293b;
  color: #cbd5e1;
  font-weight: 600;
}

.label-row-index {
  width: 44px;
  color: #94a3b8;
}

.insp-label-table .label-cell {
  max-width: 340px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.insp-units {
  color: #94a3b8;
  font-weight: 400;
}

.insp-badge {
  display: inline-block;
  padding: 1px 8px;
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  border-radius: 4px;
  font-size: 0.8rem;
}

.insp-more {
  color: #64748b;
  font-size: 0.75rem;
}

/* Processing Timeline */
.processing-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.timeline-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.step-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #334155;
  color: #94a3b8;
  font-size: 0.7rem;
  font-weight: 600;
  flex-shrink: 0;
}

.step-content {
  flex: 1;
  min-width: 0;
}

.step-operation {
  font-size: 0.85rem;
  font-weight: 500;
  color: #f8fafc;
}

.step-params {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.param-chip {
  padding: 1px 8px;
  background: #334155;
  border-radius: 4px;
  font-size: 0.7rem;
  color: #94a3b8;
  font-family: "JetBrains Mono", monospace;
}

.step-shapes {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.shape-badge {
  font-size: 0.7rem;
  color: #64748b;
  font-family: "JetBrains Mono", monospace;
}

/* Port Summaries */
.port-summaries {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.port-summary-card {
  padding: 10px 14px;
  background: #1e293b;
  border-radius: 8px;
  border: 1px solid #334155;
}

.port-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.port-name {
  font-weight: 600;
  font-size: 0.85rem;
  color: #f8fafc;
}

.port-type-badge {
  padding: 1px 8px;
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
  border-radius: 4px;
  font-size: 0.7rem;
}

.port-details {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  font-size: 0.8rem;
  color: #94a3b8;
  font-family: "JetBrains Mono", monospace;
}

/* Full metadata action */
.full-meta-action {
  margin-bottom: 16px;
}

/* Full Metadata Dialog */
.full-metadata-json {
  background: #0f172a;
  color: #e2e8f0;
  padding: 16px;
  border-radius: 8px;
  font-family: "JetBrains Mono", monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

/* Responsive */
@media (max-width: 768px) {
  .detail-header {
    flex-direction: column;
    gap: 16px;
    padding: 16px;
  }

  .header-actions {
    width: 100%;
    justify-content: stretch;
  }

  .header-actions .p-button {
    flex: 1;
  }

  .detail-content {
    padding: 16px;
  }

  .output-actions {
    flex-direction: column;
  }
}
</style>
