<template>
  <div class="workflow-inspector" :class="{ collapsed: !isOpen, hidden: !isOpen }">
    <!-- Empty state when closed -->
    <div v-if="!isOpen" class="empty-state">
      <i class="pi pi-arrow-left" />
      <span>Select a node</span>
    </div>

    <!-- Node inspector content (vertical sidebar layout) -->
    <template v-else>
      <!-- Node header with close button -->
      <div class="inspector-header">
        <div class="node-info">
          <span class="node-icon">{{ NODE_ICONS[selectedNodeType] || '📦' }}</span>
          <div class="node-details">
            <h3>{{ selectedNode ? getNodeLabel(selectedNode.type) : 'Inspector' }}</h3>
            <span v-if="selectedNode" class="node-id">ID: {{ selectedNode.id }}</span>
          </div>
        </div>
        <div class="header-actions">
          <Button
            icon="pi pi-sliders-h"
            class="p-button-text p-button-secondary p-button-sm trial-launch-btn"
            @click="openToRunTrials"
            title="Open to Run Trials"
            aria-label="Open to Run Trials"
          />
          <Button
            icon="pi pi-times"
            class="p-button-text p-button-secondary p-button-sm"
            @click="closeInspector"
            title="Close inspector"
          />
        </div>
      </div>

      <!-- Action buttons -->
      <div v-if="selectedNode" class="inspector-actions">
        <Button
          label="Run Node"
          icon="pi pi-play"
          class="p-button-sm p-button-success"
          @click="executeNode"
        />
        <Button
          label="Delete"
          icon="pi pi-trash"
          class="p-button-sm p-button-danger p-button-outlined"
          @click="deleteNode"
        />
        <Button
          v-if="isPreprocessingNode && inputConnections.length > 0"
          label="Preview"
          icon="pi pi-eye"
          class="p-button-sm p-button-outlined p-button-secondary"
          @click="runPreview"
          :disabled="hasValidationErrors"
          title="Preview before/after effect of this preprocessing"
        />
      </div>

      <!-- Node Execution Error Display -->
      <div v-if="selectedNode?.executionState?.status === 'error'" class="execution-error-banner">
        <div class="error-header">
          <i class="pi pi-times-circle"></i>
          <div class="error-content">
            <strong>Execution Failed</strong>
            <p>{{ selectedNode.executionState.error_message || 'An unknown error occurred' }}</p>
          </div>
        </div>
        <div v-if="selectedNode.executionState.error_details" class="error-details-section">
          <button
            class="show-details-btn"
            @click="showErrorDetails = !showErrorDetails"
          >
            <i :class="showErrorDetails ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"></i>
            {{ showErrorDetails ? 'Hide' : 'Show' }} Details
          </button>
          <div v-if="showErrorDetails" class="error-details-content">
            <pre>{{ selectedNode.executionState.error_details }}</pre>
          </div>
        </div>
      </div>

      <!-- Parameters section (vertical) -->
      <div v-if="selectedNode" class="inspector-params">
        <span class="section-label">Parameters</span>

        <!-- Validation error summary -->
        <div v-if="hasValidationErrors" class="validation-summary">
          <i class="pi pi-exclamation-triangle"></i>
          <div class="validation-message">
            <strong>{{ validationErrors.length }} validation error{{ validationErrors.length > 1 ? 's' : '' }}</strong>
            <span>Please fix the following errors:</span>
            <ul class="validation-error-list">
              <li v-for="error in validationErrors" :key="error.param_name">
                <strong>{{ error.param_name }}:</strong> {{ error.message }}
              </li>
            </ul>
          </div>
        </div>

        <div class="parameters-form">
          <!-- DATA node -->
          <template v-if="selectedNodeType === 'data.source'">
            <!-- Source type selector -->
            <div class="field">
              <label>Source</label>
              <Dropdown
                v-model="localParams.source"
                :options="dataSourceOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Select source type"
                appendTo="body"
                @change="onSourceChange"
              />
            </div>

            <!-- File path input (for 'file' source) -->
            <div v-if="localParams.source === 'file'" class="field">
              <label>File Path</label>
              <InputText
                v-model="localParams.file_path"
                placeholder="/path/to/als2004dataset.MAT"
                @blur="emitParams"
              />
              <small class="param-hint">
                Supports: .MAT, .CSV, .JDX, .SPA, .SPC (saved on blur or Run)
              </small>
            </div>

            <!-- Experiment/Library TreeSelect (for 'experiment' or 'library' source) -->
            <div v-if="localParams.source === 'experiment' || localParams.source === 'library'" class="field dataset-field">
              <label>Dataset</label>
              <TreeSelect
                v-model="selectedDatasetKey"
                :options="datasetTreeNodes"
                placeholder="Select a dataset..."
                selectionMode="single"
                class="dataset-tree-select"
                @update:model-value="onDatasetSelect"
              />
            </div>

            <!-- SpectroChemPy example selector -->
            <div v-if="localParams.source === 'spectrochempy'" class="field">
              <label>Example Dataset</label>
              <Dropdown
                v-model="localParams.example_dataset"
                :options="scpExampleOptions"
                placeholder="Select example"
                appendTo="body"
                @change="emitParams"
              />
            </div>

            <!-- SpectroChemPy example file (dropdown populated from API) -->
            <div v-if="localParams.source === 'spectrochempy'" class="field">
              <label>Example File (Optional)</label>
              <Dropdown
                v-model="localParams.example_file"
                :options="scpFileOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Select a single file or leave empty for default"
                :loading="isLoadingScpFiles"
                :disabled="!localParams.example_dataset"
                showClear
                appendTo="body"
                @change="emitParams"
              />
              <small class="param-hint">
                Select a single file from {{ localParams.example_dataset || 'dataset' }} ({{ scpFileOptions.length }} files available).
                Leave empty for default. <strong>For loading multiple files, use the Load Group node instead.</strong>
              </small>
            </div>

            <!-- Sklearn dataset selector -->
            <div v-if="localParams.source === 'sklearn'" class="field">
              <label>Sklearn Dataset</label>
              <Dropdown
                v-model="localParams.sklearn_dataset"
                :options="sklearnDatasetOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Select dataset"
                appendTo="body"
                @change="emitParams"
              />
              <small class="param-hint">
                Load standard machine learning datasets for testing PCA, classification, etc.
              </small>
            </div>

            <!-- Eigenvector Research dataset selector -->
            <div v-if="localParams.source === 'eigenvector'" class="field">
              <label>Eigenvector Dataset</label>
              <Dropdown
                v-model="localParams.eigenvector_dataset"
                :options="eigenvectorDatasetOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Select dataset"
                appendTo="body"
                @change="emitParams"
              />
              <small class="param-hint">
                Bundled NIR reference datasets from
                <a href="https://eigenvector.com/resources/data-sets/" target="_blank">Eigenvector Research</a>.
                Properties output on the Target port.
              </small>
            </div>

            <!-- Selected dataset info -->
            <div v-if="localParams.dataset_ref" class="field dataset-info">
              <span class="dataset-badge" :class="localParams.dataset_ref.source">
                {{ localParams.dataset_ref.source }}
              </span>
              <span class="dataset-path">{{ localParams.dataset_ref.file_path?.split('/').pop() }}</span>
            </div>

            <!-- File path display for direct file -->
            <div v-if="localParams.source === 'file' && localParams.file_path" class="field dataset-info">
              <span class="dataset-badge file">file</span>
              <span class="dataset-path">{{ localParams.file_path.split('/').pop() }}</span>
            </div>

            <!-- Axis configuration section -->
            <div class="field-group">
              <h4 class="field-group-title">Axis Configuration</h4>

              <!-- Transpose on load -->
              <div class="field checkbox-row">
                <Checkbox
                  v-model="localParams.transpose_on_load"
                  :binary="true"
                  inputId="transpose_on_load"
                  @change="emitParams"
                />
                <label for="transpose_on_load">Transpose on Load</label>
              </div>
              <small class="param-hint">
                Enable if your data is (wavenumbers × samples) instead of (samples × wavenumbers)
              </small>

              <!-- Sample axis title -->
              <div class="field">
                <label>Sample Axis Title</label>
                <InputText
                  v-model="localParams.sample_axis_title"
                  placeholder="e.g., Time, Frame, Temperature"
                  @blur="emitParams"
                />
                <small class="param-hint">
                  Title for y-axis (rows): Time, Frame #, Temperature, etc.
                </small>
              </div>

              <!-- Spectral axis title -->
              <div class="field">
                <label>Spectral Axis Title</label>
                <InputText
                  v-model="localParams.spectral_axis_title"
                  placeholder="e.g., Wavenumber, Wavelength"
                  @blur="emitParams"
                />
                <small class="param-hint">
                  Title for x-axis (columns): Wavenumber, Wavelength, Raman Shift, etc.
                </small>
              </div>
            </div>
          </template>

          <!-- MY_DATASET node -->
          <template v-else-if="selectedNodeType === 'data.my_dataset'">
            <div class="field">
              <label>Dataset</label>
              <Dropdown
                v-model="localParams.dataset_id"
                :options="myDatasetExperimentOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Select a dataset..."
                appendTo="body"
                @change="emitParams"
              />
              <small class="param-hint">
                All files in the selected dataset are loaded together.
              </small>
            </div>
          </template>

          <!-- NORMALIZE node -->
          <template v-else-if="selectedNodeType === 'preprocess.normalize'">
            <div class="field">
              <label>Method</label>
              <Dropdown
                v-model="localParams.method"
                :options="normalizeMethodOptions"
                placeholder="Select method"
                @change="emitParams"
              />
            </div>
          </template>

          <!-- SCALE node: uses metadata-driven rendering (generic) -->

          <!-- BASELINE node: uses metadata-driven rendering (generic) -->

          <!-- SMOOTH node -->
          <template v-else-if="selectedNodeType === 'preprocess.smooth'">
            <div class="field" :class="{ 'field-error': getParamError('size') }">
              <label class="param-label-with-info">
                Window Size: {{ localParams.size }}
                <i
                  class="pi pi-info-circle param-info-icon"
                  v-tooltip.right="{
                    value: 'Savitzky-Golay filter window size. Larger values produce smoother spectra but may remove fine features. Must be odd number. Typical range: 5-21.',
                    showDelay: 300,
                    hideDelay: 100,
                    class: 'scientific-tooltip'
                  }"
                ></i>
              </label>
              <Slider
                v-model="localParams.size"
                :min="3"
                :max="21"
                :step="2"
                @change="emitParams"
              />
              <small v-if="getParamError('size')" class="param-error">
                {{ getParamError('size') }}
              </small>
            </div>
            <div class="field" :class="{ 'field-error': getParamError('order') }">
              <label class="param-label-with-info">
                Polynomial Order: {{ localParams.order }}
                <i
                  class="pi pi-info-circle param-info-icon"
                  v-tooltip.right="{
                    value: 'Polynomial degree used to fit data within window. Higher order fits data more closely but may amplify noise. Typically 2-4 for spectral data.',
                    showDelay: 300,
                    hideDelay: 100,
                    class: 'scientific-tooltip'
                  }"
                ></i>
              </label>
              <Slider
                v-model="localParams.order"
                :min="1"
                :max="6"
                :step="1"
                @change="emitParams"
              />
              <small v-if="getParamError('order')" class="param-error">
                {{ getParamError('order') }}
              </small>
            </div>
          </template>

          <!-- PCA, PLS, and MCR nodes now use metadata-driven rendering (removed hardcoded templates) -->

          <!-- PLOT node -->
          <template v-else-if="selectedNodeType === 'output.plot'">
            <div class="field">
              <label>X-Axis</label>
              <Dropdown
                v-model="localParams.x_axis"
                :options="axisOptions"
                optionLabel="label"
                optionValue="value"
                @change="emitParams"
              />
            </div>
            <div class="field">
              <label>Y-Axis</label>
              <Dropdown
                v-model="localParams.y_axis"
                :options="axisOptions"
                optionLabel="label"
                optionValue="value"
                @change="emitParams"
              />
            </div>
          </template>

          <!-- EXPORT node -->
          <template v-else-if="selectedNodeType === 'output.export'">
            <div class="field">
              <label>Filename</label>
              <InputText
                v-model="localParams.filename"
                placeholder="output.csv"
                @update:model-value="emitParams"
              />
            </div>
          </template>

          <!-- STATS node -->
          <template v-else-if="selectedNodeType === 'stats.summary'">
            <div class="field">
              <label>Max Samples: {{ localParams.max_samples || 50 }}</label>
              <Slider
                v-model="localParams.max_samples"
                :min="10"
                :max="500"
                :step="10"
                @change="emitParams"
              />
              <small class="param-hint">
                Number of sample rows to return in statistics
              </small>
            </div>
          </template>

          <!-- CONTOUR_PLOT node -->
          <template v-else-if="selectedNodeType === 'output.contour'">
            <div class="field">
              <label>Color Scale</label>
              <Dropdown
                v-model="localParams.colorscale"
                :options="colorscaleOptions"
                placeholder="Select colorscale"
                @change="emitParams"
              />
            </div>
            <div class="field">
              <label>Plot Type</label>
              <Dropdown
                v-model="localParams.plot_type"
                :options="contourPlotTypeOptions"
                placeholder="Select type"
                @change="emitParams"
              />
            </div>
            <div class="field checkbox-row">
              <Checkbox
                v-model="localParams.reverse_x"
                :binary="true"
                inputId="reverse_x"
                @change="emitParams"
              />
              <label for="reverse_x">Reverse X-axis (IR standard)</label>
            </div>
            <div class="field checkbox-row">
              <Checkbox
                v-model="localParams.transpose"
                :binary="true"
                inputId="transpose"
                @change="emitParams"
              />
              <label for="transpose">Transpose Data</label>
            </div>
          </template>

          <!-- EFA now uses metadata-driven rendering (removed hardcoded template) -->

          <!-- Metadata-driven parameter rendering (generic nodes) -->
          <template v-else-if="nodeMetadata && nodeMetadata.parameters.length > 0">
            <!-- Basic Parameters -->
            <div v-if="basicParams.length > 0" class="params-section">
              <div
                v-for="param in basicParams"
                :key="param.name"
                class="field"
                :class="{ 'field-error': getParamError(param.name) }"
              >
                <label>
                  {{ param.label }}
                  <span v-if="param.required" class="required-indicator">*</span>
                </label>

                <!-- Number input -->
                <template v-if="param.param_type === 'number'">
                  <InputNumber
                    v-model="localParams[param.name]"
                    :min="param.min_value"
                    :max="param.max_value"
                    :step="param.step"
                    :placeholder="param.default?.toString()"
                    @update:model-value="emitParams"
                  />
                </template>

                <!-- Boolean checkbox -->
                <template v-else-if="param.param_type === 'boolean'">
                  <Checkbox
                    v-model="localParams[param.name]"
                    :binary="true"
                    @change="emitParams"
                  />
                </template>

                <!-- Select dropdown -->
                <template v-else-if="param.param_type === 'select' && param.options">
                  <Dropdown
                    v-model="localParams[param.name]"
                    :options="normalizeOptions(param.options)"
                    optionLabel="label"
                    optionValue="value"
                    :placeholder="`Select ${param.label.toLowerCase()}`"
                    @change="emitParams"
                  />
                </template>

                <!-- Text input -->
                <template v-else>
                  <InputText
                    v-model="localParams[param.name]"
                    :placeholder="param.default?.toString() || param.description"
                    @update:model-value="emitParams"
                  />
                </template>

                <!-- Parameter description -->
                <small v-if="param.description && !getParamError(param.name)" class="param-hint">
                  {{ param.description }}
                </small>

                <!-- Validation error -->
                <small v-if="getParamError(param.name)" class="param-error">
                  {{ getParamError(param.name) }}
                </small>
              </div>
            </div>

            <!-- Advanced Parameters Accordion -->
            <Accordion v-if="hasAdvancedParams" class="advanced-params-accordion">
              <AccordionTab>
                <template #header>
                  <span class="advanced-header">
                    <i class="pi pi-cog"></i>
                    Advanced Settings
                    <span class="param-count">({{ advancedParams.length }})</span>
                  </span>
                </template>

                <div class="params-section">
                  <div
                    v-for="param in advancedParams"
                    :key="param.name"
                    class="field"
                    :class="{ 'field-error': getParamError(param.name) }"
                  >
                    <label>
                      {{ param.label }}
                      <span v-if="param.required" class="required-indicator">*</span>
                    </label>

                    <!-- Number input -->
                    <template v-if="param.param_type === 'number'">
                      <InputNumber
                        v-model="localParams[param.name]"
                        :min="param.min_value"
                        :max="param.max_value"
                        :step="param.step"
                        :placeholder="param.default?.toString()"
                        @update:model-value="emitParams"
                      />
                    </template>

                    <!-- Boolean checkbox -->
                    <template v-else-if="param.param_type === 'boolean'">
                      <Checkbox
                        v-model="localParams[param.name]"
                        :binary="true"
                        @change="emitParams"
                      />
                    </template>

                    <!-- Select dropdown -->
                    <template v-else-if="param.param_type === 'select' && param.options">
                      <Dropdown
                        v-model="localParams[param.name]"
                        :options="normalizeOptions(param.options)"
                        optionLabel="label"
                        optionValue="value"
                        :placeholder="`Select ${param.label.toLowerCase()}`"
                        @change="emitParams"
                      />
                    </template>

                    <!-- Text input -->
                    <template v-else>
                      <InputText
                        v-model="localParams[param.name]"
                        :placeholder="param.default?.toString() || param.description"
                        @update:model-value="emitParams"
                      />
                    </template>

                    <!-- Parameter description -->
                    <small v-if="param.description && !getParamError(param.name)" class="param-hint">
                      {{ param.description }}
                    </small>

                    <!-- Validation error -->
                    <small v-if="getParamError(param.name)" class="param-error">
                      {{ getParamError(param.name) }}
                    </small>
                  </div>
                </div>
              </AccordionTab>
            </Accordion>

            <!-- No parameters message -->
            <div v-if="basicParams.length === 0 && advancedParams.length === 0" class="no-params">
              No parameters configured for this node
            </div>
          </template>

          <!-- Legacy fallback for nodes without metadata -->
          <template v-else>
            <div class="generic-params">
              <div v-for="(value, key) in localParams" :key="key" class="field">
                <label>{{ formatParamLabel(key) }}</label>
                <template v-if="typeof value === 'boolean'">
                  <Checkbox
                    v-model="localParams[key]"
                    :binary="true"
                    @change="emitParams"
                  />
                </template>
                <template v-else-if="typeof value === 'number'">
                  <InputNumber
                    v-model="localParams[key]"
                    @update:model-value="emitParams"
                  />
                </template>
                <template v-else>
                  <InputText
                    v-model="localParams[key]"
                    @update:model-value="emitParams"
                  />
                </template>
              </div>
              <span v-if="Object.keys(localParams).length === 0" class="no-params">
                No parameters configured
              </span>
            </div>
          </template>
        </div>
      </div>

      <!-- Output Preview section (vertical) -->
      <div v-if="selectedNode" class="inspector-output">
        <span class="section-label">Output</span>
        <div v-if="!nodeOutput" class="no-output">
          <p>Execute workflow to see results</p>
        </div>
        <div v-else class="output-content">
          <!-- Data shape summary - always show for any output -->
          <div class="data-shape-summary">
            <span class="shape-stat">
              <strong>{{ nodeOutput.data?.length || 0 }}</strong> rows
            </span>
            <span v-if="Array.isArray(nodeOutput.data?.[0])" class="shape-stat">
              <strong>{{ nodeOutput.data[0].length }}</strong> cols
            </span>
          </div>

          <div v-if="diagnosticEntries.length > 0" class="diagnostics-card">
            <span class="diagnostics-title">Diagnostics</span>
            <div class="diagnostics-grid">
              <div v-for="entry in diagnosticEntries" :key="entry.key" class="diagnostics-item">
                <span class="diagnostics-key">{{ entry.key }}</span>
                <span class="diagnostics-value">{{ formatDiagnosticValue(entry.value) }}</span>
              </div>
            </div>
          </div>

          <!-- Universal Quick Plot and View Data buttons -->
          <div class="output-actions">
            <Button
              icon="pi pi-chart-line"
              label="Quick Plot"
              class="p-button-sm p-button-outlined"
              @click="showQuickPlotModal = true"
              :disabled="!nodeOutput.data || nodeOutput.data.length === 0"
            />
            <Button
              icon="pi pi-table"
              label="View Data"
              class="p-button-sm p-button-outlined"
              @click="showDataTableModal = true"
              :disabled="!nodeOutput.data || nodeOutput.data.length === 0"
            />
          </div>

          <!-- Statistics output (compact inline) -->
          <template v-if="selectedNodeType === 'stats.summary' && Array.isArray(nodeOutput.data)">
            <!-- PeakFinding stats -->
            <template v-if="isPeakFindingStats">
              <div class="stats-table" style="max-height: 200px; overflow-y: auto;">
                <div
                  v-for="(stat, index) in outputStatsRows"
                  :key="index"
                  class="stat-row"
                >
                  <span class="stat-sample">Peak {{ stat.peak }}</span>
                  <span class="stat-value">pos: {{ typeof stat.position === 'number' ? stat.position.toFixed(1) : '—' }}</span>
                  <span class="stat-value">σ: {{ typeof stat.pos_std === 'number' ? stat.pos_std.toFixed(2) : '—' }}</span>
                  <span class="stat-value">h: {{ typeof stat.height === 'number' ? stat.height.toFixed(4) : '—' }}</span>
                  <span class="stat-value">{{ stat.detected || '—' }}</span>
                </div>
              </div>
              <div v-if="outputMetadata.summary" class="stats-summary">
                <span class="summary-label">Peaks:</span>
                <span>{{ outputMetadata.summary?.n_peaks ?? 0 }} consensus peaks from {{ outputMetadata.summary?.n_samples ?? 0 }} spectra</span>
              </div>
            </template>
            <!-- Standard spectral/array stats -->
            <template v-else>
              <div class="stats-table" style="max-height: 200px; overflow-y: auto;">
                <div
                  v-for="(stat, index) in outputStatsRows"
                  :key="index"
                  class="stat-row"
                >
                  <span class="stat-sample">{{ stat.wavelength != null ? `λ ${stat.wavelength}` : `#${index + 1}` }}</span>
                  <span class="stat-value">μ: {{ typeof stat.mean === 'number' ? stat.mean.toFixed(4) : '—' }}</span>
                  <span class="stat-value">σ: {{ typeof stat.std === 'number' ? stat.std.toFixed(4) : '—' }}</span>
                </div>
              </div>
              <div v-if="outputMetadata.summary" class="stats-summary">
                <span class="summary-label">Overall:</span>
                <span>{{ outputMetadata.summary.n_samples ?? 0 }} samples × {{ outputMetadata.summary.n_features ?? 0 }} features</span>
              </div>
            </template>
          </template>
        </div>
      </div>

      <!-- Metadata Editor Section (hierarchical, collapsible) -->
      <div v-if="selectedNode && isDataSourceNode" class="inspector-metadata">
        <span class="section-label">Metadata (SpectraMeta)</span>

        <Accordion :multiple="true" :activeIndex="[0]" class="metadata-accordion">
          <!-- Species Section -->
          <AccordionTab header="Species">
            <div class="metadata-group">
              <div v-for="(species, idx) in localMetadata.species" :key="idx" class="species-entry">
                <div class="species-header">
                  <span class="species-index">#{{ idx + 1 }}</span>
                  <Button
                    icon="pi pi-times"
                    class="p-button-text p-button-sm p-button-danger"
                    @click="removeSpecies(idx)"
                    title="Remove species"
                  />
                </div>
                <div class="meta-field">
                  <label>Name</label>
                  <InputText
                    v-model="species.name"
                    placeholder="e.g., Carbon Dioxide"
                    @update:model-value="emitMetadata"
                  />
                </div>
                <div class="meta-field">
                  <label>CAS Number</label>
                  <InputText
                    v-model="species.cas_number"
                    placeholder="e.g., 124-38-9"
                    @update:model-value="emitMetadata"
                  />
                </div>
                <div class="meta-field">
                  <label>Molecular Formula</label>
                  <InputText
                    v-model="species.molecular_formula"
                    placeholder="e.g., CO2"
                    @update:model-value="emitMetadata"
                  />
                </div>
                <div class="meta-field">
                  <label>Physical State</label>
                  <Dropdown
                    v-model="species.state"
                    :options="physicalStateOptions"
                    placeholder="Select state"
                    @change="emitMetadata"
                  />
                </div>
              </div>
              <Button
                icon="pi pi-plus"
                label="Add Species"
                class="p-button-sm p-button-outlined add-species-btn"
                @click="addSpecies"
              />
            </div>
          </AccordionTab>

          <!-- Conditions Section -->
          <AccordionTab header="Conditions">
            <div class="metadata-group">
              <div class="meta-field">
                <label>Temperature (°C)</label>
                <InputNumber
                  v-model="localMetadata.conditions.temperature_c"
                  placeholder="25"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Pressure (atm)</label>
                <InputNumber
                  v-model="localMetadata.conditions.pressure_atm"
                  :minFractionDigits="1"
                  :maxFractionDigits="3"
                  placeholder="1.0"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Purge Gas</label>
                <Dropdown
                  v-model="localMetadata.conditions.purge_gas"
                  :options="purgeGasOptions"
                  placeholder="Select gas"
                  @change="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Humidity (%RH)</label>
                <InputNumber
                  v-model="localMetadata.conditions.ambient_humidity_percent"
                  :min="0"
                  :max="100"
                  placeholder="50"
                  @update:model-value="emitMetadata"
                />
              </div>
            </div>
          </AccordionTab>

          <!-- Instrument Section -->
          <AccordionTab header="Instrument">
            <div class="metadata-group">
              <div class="meta-field">
                <label>Manufacturer</label>
                <Dropdown
                  v-model="localMetadata.instrument.manufacturer"
                  :options="instrumentManufacturers"
                  placeholder="Select manufacturer"
                  editable
                  @change="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Model</label>
                <InputText
                  v-model="localMetadata.instrument.model"
                  placeholder="e.g., Vertex 70"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Detector Type</label>
                <Dropdown
                  v-model="localMetadata.instrument.detector_type"
                  :options="detectorTypeOptions"
                  placeholder="Select detector"
                  @change="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Source Type</label>
                <InputText
                  v-model="localMetadata.instrument.source_type"
                  placeholder="e.g., Globar, QCL"
                  @update:model-value="emitMetadata"
                />
              </div>
            </div>
          </AccordionTab>

          <!-- Acquisition Section -->
          <AccordionTab header="Acquisition">
            <div class="metadata-group">
              <div class="meta-field">
                <label>Resolution (cm⁻¹)</label>
                <InputNumber
                  v-model="localMetadata.acquisition.resolution_cm"
                  :minFractionDigits="0"
                  :maxFractionDigits="2"
                  placeholder="4"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Number of Scans</label>
                <InputNumber
                  v-model="localMetadata.acquisition.n_scans"
                  :min="1"
                  placeholder="32"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Wavenumber Min (cm⁻¹)</label>
                <InputNumber
                  v-model="localMetadata.acquisition.wavenumber_min"
                  placeholder="400"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Wavenumber Max (cm⁻¹)</label>
                <InputNumber
                  v-model="localMetadata.acquisition.wavenumber_max"
                  placeholder="4000"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Apodization</label>
                <Dropdown
                  v-model="localMetadata.acquisition.apodization"
                  :options="apodizationOptions"
                  placeholder="Select"
                  @change="emitMetadata"
                />
              </div>
            </div>
          </AccordionTab>

          <!-- Sample Cell Section -->
          <AccordionTab header="Sample Cell">
            <div class="metadata-group">
              <div class="meta-field">
                <label>Cell Type</label>
                <Dropdown
                  v-model="localMetadata.cell.cell_type"
                  :options="cellTypeOptions"
                  placeholder="Select type"
                  @change="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Pathlength (mm)</label>
                <InputNumber
                  v-model="localMetadata.cell.pathlength_mm"
                  :minFractionDigits="1"
                  :maxFractionDigits="3"
                  placeholder="10.0"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Window Material</label>
                <Dropdown
                  v-model="localMetadata.cell.window_material"
                  :options="windowMaterialOptions"
                  placeholder="Select material"
                  @change="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Cell Volume (mL)</label>
                <InputNumber
                  v-model="localMetadata.cell.cell_volume_ml"
                  :minFractionDigits="1"
                  :maxFractionDigits="2"
                  placeholder="100"
                  @update:model-value="emitMetadata"
                />
              </div>
            </div>
          </AccordionTab>

          <!-- Audit/GxP Section -->
          <AccordionTab header="Audit (GxP)">
            <div class="metadata-group">
              <div class="meta-field">
                <label>Operator</label>
                <InputText
                  v-model="localMetadata.audit.operator"
                  placeholder="Name"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Operator ID</label>
                <InputText
                  v-model="localMetadata.audit.operator_id"
                  placeholder="Employee ID"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Lab ID</label>
                <InputText
                  v-model="localMetadata.audit.lab_id"
                  placeholder="Lab identifier"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Project ID</label>
                <InputText
                  v-model="localMetadata.audit.project_id"
                  placeholder="Project code"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>SOP ID</label>
                <InputText
                  v-model="localMetadata.audit.sop_id"
                  placeholder="SOP-xxx"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Sample ID</label>
                <InputText
                  v-model="localMetadata.audit.sample_id"
                  placeholder="Sample barcode"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label>Batch ID</label>
                <InputText
                  v-model="localMetadata.audit.batch_id"
                  placeholder="Lot number"
                  @update:model-value="emitMetadata"
                />
              </div>
            </div>
          </AccordionTab>
        </Accordion>
      </div>

      <!-- Read-only Metadata View (for non-data-source nodes) -->
      <div v-else-if="selectedNode && spectraMetadata" class="inspector-metadata readonly">
        <span class="section-label">Metadata (read-only)</span>
        <div class="metadata-preview">
          <div v-if="spectraSpeciesNames.length" class="meta-preview-item">
            <span class="meta-key">Species:</span>
            <span class="meta-value">
              {{ spectraSpeciesNames.join(', ') }}
            </span>
          </div>
          <div v-if="outputMetadata.provenance?.source_type || spectraMetadata.provenance?.source_type" class="meta-preview-item">
            <span class="meta-key">Source:</span>
            <span class="meta-value">{{ outputMetadata.provenance?.source_type || spectraMetadata.provenance?.source_type }}</span>
          </div>
          <div v-if="processingOperations.length" class="meta-preview-item">
            <span class="meta-key">Processing:</span>
            <span class="meta-value processing-history">
              {{ processingOperations.slice(-3).join(' → ') }}
              <span v-if="processingOperations.length > 3" class="more-ops">
                (+{{ processingOperations.length - 3 }} more)
              </span>
            </span>
          </div>
          <div v-if="outputMetadata.processing_history?.length" class="meta-preview-item">
            <span class="meta-key">Steps:</span>
            <span class="meta-value">{{ outputMetadata.processing_history.length }} operations applied</span>
          </div>
          <div v-if="spectraMetadata.conditions?.temperature_c" class="meta-preview-item">
            <span class="meta-key">Temp:</span>
            <span class="meta-value">{{ spectraMetadata.conditions.temperature_c }}°C</span>
          </div>
          <div v-if="spectraMetadata.acquisition?.resolution_cm" class="meta-preview-item">
            <span class="meta-key">Resolution:</span>
            <span class="meta-value">{{ spectraMetadata.acquisition.resolution_cm }} cm⁻¹</span>
          </div>
          <Button
            icon="pi pi-external-link"
            label="View Full Metadata"
            class="p-button-sm p-button-text"
            @click="showMetadataModal = true"
          />
        </div>
      </div>
    </template>
  </div>

  <!-- Quick Plot Modal (Universal Plotly-based) -->
  <QuickPlotModal
    v-model="showQuickPlotModal"
    :node-output="nodeOutput"
    :node-type="selectedNode?.type || ''"
    :node-label="selectedNode ? getNodeLabel(selectedNode.type) : 'Node'"
    :node-input="inputConnections.length > 0 ? inputConnections[0].data : undefined"
  />

  <!-- Data Table Modal (Raw data viewer) -->
  <DataTableModal
    v-model="showDataTableModal"
    :node-output="nodeOutput"
    :node-type="selectedNode?.type || ''"
    :node-label="selectedNode ? getNodeLabel(selectedNode.type) : 'Node'"
  />

  <!-- Preview Modal (Before/After Comparison) -->
  <Dialog
    v-model:visible="showPreviewModal"
    header="Preview: Before vs After"
    :style="{ width: '900px' }"
    :modal="true"
    class="preview-dialog"
  >
    <div v-if="previewData" class="preview-container">
      <div class="preview-pane">
        <h4>Original Data</h4>
        <div class="preview-content">
          <div v-if="previewData.original?.data?.length > 0" class="data-summary">
            <div class="summary-item">
              <span class="summary-label">Spectra:</span>
              <span class="summary-value">{{ previewData.original.data.length }}</span>
            </div>
            <div v-if="previewData.original.data[0]?.wavenumber" class="summary-item">
              <span class="summary-label">Points:</span>
              <span class="summary-value">{{ previewData.original.data[0].wavenumber.length }}</span>
            </div>
            <div v-if="previewData.original.data[0]?.wavenumber" class="summary-item">
              <span class="summary-label">Range:</span>
              <span class="summary-value">
                {{ Math.min(...previewData.original.data[0].wavenumber).toFixed(1) }} -
                {{ Math.max(...previewData.original.data[0].wavenumber).toFixed(1) }} cm⁻¹
              </span>
            </div>
          </div>
          <pre v-if="previewData.original">{{ JSON.stringify(previewData.original, null, 2).substring(0, 800) }}...</pre>
        </div>
      </div>
      <div class="preview-divider"></div>
      <div class="preview-pane">
        <h4>Processed Data</h4>
        <div class="preview-content">
          <div v-if="!previewData.processed" class="loading-preview">
            <i class="pi pi-spin pi-spinner"></i>
            <span>Processing...</span>
          </div>
          <template v-else>
            <div v-if="previewData.processed?.data?.length > 0" class="data-summary">
              <div class="summary-item">
                <span class="summary-label">Spectra:</span>
                <span class="summary-value">{{ previewData.processed.data.length }}</span>
              </div>
              <div v-if="previewData.processed.data[0]?.wavenumber" class="summary-item">
                <span class="summary-label">Points:</span>
                <span class="summary-value">{{ previewData.processed.data[0].wavenumber.length }}</span>
              </div>
              <div v-if="previewData.processed.data[0]?.wavenumber" class="summary-item">
                <span class="summary-label">Range:</span>
                <span class="summary-value">
                  {{ Math.min(...previewData.processed.data[0].wavenumber).toFixed(1) }} -
                  {{ Math.max(...previewData.processed.data[0].wavenumber).toFixed(1) }} cm⁻¹
                </span>
              </div>
            </div>
            <pre>{{ JSON.stringify(previewData.processed, null, 2).substring(0, 800) }}...</pre>
          </template>
        </div>
      </div>
    </div>
  </Dialog>

  <!-- Full Metadata Modal -->
  <Dialog
    v-model:visible="showMetadataModal"
    header="Full Metadata"
    :style="{ width: '700px', maxHeight: '80vh' }"
    :modal="true"
    class="metadata-dialog"
  >
    <div v-if="!nodeOutput" class="metadata-modal-empty">
      <i class="pi pi-info-circle"></i>
      <span>No output available for this node. Run the workflow first.</span>
    </div>
    <div v-else class="metadata-modal-content">
      <!-- Instrument Metadata Section (if available) -->
      <div v-if="outputMetadata.instrument_metadata || outputMetadata.acquisition_params" class="metadata-section">
        <h4 class="section-title">
          <i class="pi pi-cog"></i>
          Instrument &amp; Acquisition
        </h4>
        <div class="instrument-grid">
          <template v-if="outputMetadata.instrument_metadata">
            <div v-for="(value, key) in outputMetadata.instrument_metadata" :key="'inst-' + key" class="metadata-item">
              <span class="item-label">{{ formatLabel(String(key)) }}:</span>
              <span class="item-value">{{ value }}</span>
            </div>
          </template>
          <template v-if="outputMetadata.acquisition_params">
            <div v-for="(value, key) in outputMetadata.acquisition_params" :key="'acq-' + key" class="metadata-item">
              <span class="item-label">{{ formatLabel(String(key)) }}:</span>
              <span class="item-value">{{ formatAcquisitionValue(String(key), value) }}</span>
            </div>
          </template>
        </div>
      </div>

      <!-- Processing History Section -->
      <div v-if="outputMetadata.processing_history?.length || processingOperations.length" class="metadata-section">
        <h4 class="section-title">
          <i class="pi pi-history"></i>
          Processing History
        </h4>
        <div class="processing-timeline">
          <div
            v-for="(step, index) in sortedProcessingHistory"
            :key="index"
            class="timeline-item"
          >
            <span class="step-number">{{ index + 1 }}</span>
            <div class="step-content">
              <span class="step-operation">{{ typeof step === 'string' ? step : (step.op_id || step.operation || 'Unknown') }}</span>
              <span v-if="typeof step === 'object' && step.timestamp" class="step-timestamp">
                {{ formatStepTimestamp(step.timestamp, index) }}
              </span>
              <div v-if="typeof step === 'object' && step.node_id" class="step-node-id">
                Node: {{ step.node_id }}
              </div>
              <div v-if="typeof step === 'object' && step.parameters && Object.keys(step.parameters).length > 0" class="step-params">
                <span v-for="(pVal, pKey) in step.parameters" :key="pKey" class="param-chip" v-show="pVal !== null">
                  {{ pKey }}: {{ pVal }}
                </span>
              </div>
              <div v-if="typeof step === 'object' && (step.input_shape || step.output_shape)" class="step-shapes">
                <span v-if="step.input_shape" class="shape-badge">In: {{ step.input_shape?.join('×') }}</span>
                <span v-if="step.output_shape" class="shape-badge">Out: {{ step.output_shape?.join('×') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Spectra Metadata Section -->
      <div v-if="outputMetadata.spectra" class="metadata-section">
        <h4 class="section-title">
          <i class="pi pi-chart-line"></i>
          Spectral Metadata
        </h4>
        <pre class="metadata-json">{{ JSON.stringify(outputMetadata.spectra, null, 2) }}</pre>
      </div>

      <!-- Raw Metadata Section -->
      <div class="metadata-section">
        <h4 class="section-title">
          <i class="pi pi-code"></i>
          Raw Metadata (JSON)
        </h4>
        <pre class="metadata-json">{{ JSON.stringify(nodeOutput.metadata ?? {}, null, 2) }}</pre>
      </div>

      <!-- Per-port Metadata Section (for multi-port outputs like PCA) -->
      <div v-if="nodeOutput.ports && Object.keys(nodeOutput.ports).length > 0" class="metadata-section">
        <h4 class="section-title">
          <i class="pi pi-sitemap"></i>
          Output Ports
        </h4>
        <div v-for="(port, portName) in nodeOutput.ports" :key="String(portName)" class="port-metadata-block">
          <h5 class="port-metadata-title">
            {{ portName }}<span v-if="portName === nodeOutput.primary_port" class="primary-port-tag"> (primary)</span>
          </h5>
          <pre class="metadata-json">{{ JSON.stringify(port.metadata ?? {}, null, 2) }}</pre>
        </div>
      </div>
    </div>
  </Dialog>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- inspector renders heterogeneous node params and outputs across the full DAG surface. */
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import Accordion from "primevue/accordion";
import AccordionTab from "primevue/accordiontab";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Slider from "primevue/slider";
import TreeSelect from "primevue/treeselect";
import { useToast } from "primevue/usetoast";
import { useWorkflowStore, type WorkflowNode } from "@/stores/workflow";
import { useProjectStore } from "@/stores/project";
import { useDemoMode } from "@/composables/useDemoMode";
import QuickPlotModal from "./modals/QuickPlotModal.vue";
import DataTableModal from "./modals/DataTableModal.vue";
import type { NodeOutput, PortOutput } from "@/utils/nodeOutput";
import type { NodeParameterMetadata } from "@/types";
import { getErrorMessage } from "@/utils/errors";

type ParamsMap = Record<string, any>;

interface NodeParameterDefinition {
  name: string;
  label: string;
  type: string;
  min?: number;
  max?: number;
  step?: number;
  options?: Array<{ label: string; value: unknown }>;
  description?: string;
  default?: unknown;
  required?: boolean;
}

interface DatasetRefData extends Record<string, unknown> {
  source?: string;
  experiment_id?: number;
  stage?: string;
  file_id?: number;
  file_path?: string;
  library_id?: number;
}

interface DatasetTreeNode {
  key: string;
  label: string;
  selectable?: boolean;
  children?: DatasetTreeNode[];
  data?: DatasetRefData;
}

interface StatsRow extends Record<string, unknown> {
  sample?: string | number;
  mean?: number;
  std?: number;
  min?: number;
  max?: number;
  // PeakFinding stats fields
  peak?: number;
  position?: number;
  pos_std?: number;
  height?: number;
  detected?: string;
}

interface MetadataSummary {
  n_samples?: number;
  n_features?: number;
  n_peaks?: number;
}

interface MetadataProvenance {
  source_type?: string;
  operations?: string[];
}

interface SpectraSnapshot {
  species?: Array<{ name?: string }>;
  provenance?: MetadataProvenance;
  conditions?: { temperature_c?: number };
  acquisition?: { resolution_cm?: number };
}

interface InspectorMetadata extends Record<string, unknown> {
  summary?: MetadataSummary;
  spectra?: SpectraSnapshot;
  provenance?: MetadataProvenance;
  processing_history?: Array<Record<string, unknown> | string>;
  diagnostics?: Record<string, unknown>;
  instrument_metadata?: Record<string, unknown>;
  acquisition_params?: Record<string, unknown>;
  isPCA?: boolean;
  type?: string;
  input_type?: string;
  loadings?: unknown;
  wavenumbers?: unknown;
  St?: unknown;
  H?: unknown;
  A?: unknown;
}

interface InputConnection {
  nodeId: string;
  nodeType: string;
  nodeLabel: string;
  port: string;
  toPort?: string;  // Input port name for multi-input nodes (e.g., "X", "y")
  data?: NodeOutput | PortOutput | null;
}

interface Props {
  selectedNode: WorkflowNode | null;
  nodeOutput: NodeOutput | null;
  inputConnections?: InputConnection[];
  isOpen?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  isOpen: false,
  inputConnections: () => [],
});

const emit = defineEmits<{
  (e: 'update-params', nodeId: string, params: ParamsMap): void;
  (e: 'execute-node', nodeId: string): void;
  (e: 'delete-node', nodeId: string): void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- reuses the existing NodeDetailView payload shape.
  (e: 'open-trial', nodeData: any): void;
  (e: 'close'): void;
}>();

const toast = useToast();
const workflowStore = useWorkflowStore();
const projectStore = useProjectStore();
const { isDemoMode } = useDemoMode();
const selectedNodeType = computed(() => props.selectedNode?.type || '');

const asObject = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
};

const asKeyPart = (value: unknown): string | null => {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return null;
};

const getStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
};

const outputMetadata = computed<InspectorMetadata>(() => {
  const metadata = asObject(props.nodeOutput?.metadata);
  return (metadata as InspectorMetadata) ?? {};
});

const isPeakFindingStats = computed(() => {
  if (selectedNodeType.value !== "stats.summary") return false;
  const meta = outputMetadata.value;
  return meta.type === "PeakFinding" || meta.input_type === "PeakFinding";
});

const diagnosticEntries = computed<Array<{ key: string; value: unknown }>>(() => {
  const diagnostics = asObject(outputMetadata.value.diagnostics);
  if (!diagnostics) {
    return [];
  }
  return Object.entries(diagnostics).map(([key, value]) => ({ key, value }));
});

const formatDiagnosticValue = (value: unknown): string => {
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(4);
  }
  if (Array.isArray(value)) {
    const preview = value.slice(0, 4).map((item) => {
      if (typeof item === "number") {
        return Number.isInteger(item) ? String(item) : item.toFixed(4);
      }
      // Arrays of row dicts (e.g. HoldoutEvaluation's ``data`` /
      // ``per_target``) used to render as ``[object Object]`` via
      // ``String(item)`` — JSON-stringify instead so the preview
      // actually shows the row contents.
      if (item && typeof item === "object") {
        try {
          return JSON.stringify(item);
        } catch {
          return String(item);
        }
      }
      return String(item);
    });
    const suffix = value.length > 4 ? `, ... (${value.length})` : "";
    return `[${preview.join(", ")}${suffix}]`;
  }
  if (value && typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
};

const outputStatsRows = computed<StatsRow[]>(() => {
  if (!Array.isArray(props.nodeOutput?.data)) {
    return [];
  }
  return props.nodeOutput.data
    .filter((row): row is StatsRow => !!asObject(row));
});

const spectraMetadata = computed<SpectraSnapshot>(() => {
  const spectra = asObject(outputMetadata.value.spectra);
  return (spectra as SpectraSnapshot) ?? {};
});

const spectraSpeciesNames = computed<string[]>(() => {
  const species = Array.isArray(spectraMetadata.value.species) ? spectraMetadata.value.species : [];
  return species
    .map((item) => (item && typeof item.name === "string" ? item.name : ""))
    .filter((name) => name.length > 0);
});

const processingOperations = computed<string[]>(() => {
  const topLevel = getStringArray(outputMetadata.value.provenance?.operations);
  if (topLevel.length > 0) {
    return topLevel;
  }
  return getStringArray(spectraMetadata.value.provenance?.operations);
});

const getNodeLabel = (nodeType: string): string => {
  const metadata = workflowStore.getNodeMetadata(nodeType);
  if (metadata?.label) {
    return metadata.label;
  }
  return NODE_LABELS[nodeType] || nodeType;
};

// Close inspector
const closeInspector = () => {
  emit('close');
};

const NODE_ICONS: Record<string, string> = {
  // Data source
  'data.source': '📊',
  'data.my_dataset': '📁',

  // Preprocessing - atomic
  'preprocess.cosmic_ray': '✨',
  'preprocess.clip_range': '✂️',
  'preprocess.clip_floor': '⬇️',
  'preprocess.wavenumber_align': '📐',
  'preprocess.scale': '📏',
  'preprocess.normalize': '⚖️',

  // Preprocessing - existing
  'baseline.penalized_ls': '📉',
  'baseline.rubberband': '📉',
  'preprocess.smooth': '〰️',
  'preprocess.derivative': '📈',
  'preprocess.emsc': '🔧',

  // Synthesis / Blend
  'synthesis.blend': '🔀',
  'synthesis.species': '🧬',
  'synthesis.merge': '📚',

  // Analysis
  'model.pca': '🔀',
  'model.pls': '📈',
  'model.mcr_als': '🧩',
  'model.efa': '🔬',
  'model.simplisma': '🎯',

  // Output
  'stats.summary': '📊',
  'output.plot': '📈',
  'output.contour': '🗺️',
  'output.export': '💾',

  // Deploy
  'deploy.input': '📥',
  'deploy.output': '📤',
};

const NODE_LABELS: Record<string, string> = {
  // Data source
  'data.source': 'Load Data',
  'data.my_dataset': 'My Dataset',

  // Preprocessing - atomic
  'preprocess.cosmic_ray': 'Cosmic Ray Removal',
  'preprocess.clip_range': 'Clip Range',
  'preprocess.clip_floor': 'Clip Floor',
  'preprocess.wavenumber_align': 'Wavenumber Align',

  // Preprocessing - existing
  'preprocess.normalize': 'Normalize',
  'preprocess.scale': 'Scale',
  'baseline.penalized_ls': 'Baseline (ALS)',
  'baseline.rubberband': 'Baseline (Rubberband)',
  'preprocess.smooth': 'Smooth (S-G)',
  'preprocess.derivative': 'Derivative',
  'preprocess.emsc': 'MSC',

  // Synthesis / Blend
  'synthesis.blend': 'Blend',
  'synthesis.species': 'Species',
  'synthesis.merge': 'Merge Spectra',

  // Analysis
  'model.pca': 'PCA',
  'model.pls': 'PLS',
  'model.mcr_als': 'MCR-ALS',
  'model.efa': 'EFA',
  'model.simplisma': 'SIMPLISMA',

  // Output
  'stats.summary': 'Statistics',
  'output.plot': 'Scatter Plot',
  'output.contour': 'Contour Plot',
  'output.export': 'Export',

  // Deploy
  'deploy.input': 'Deploy Input',
  'deploy.output': 'Deploy Output',
};

// Local params copy for editing
const localParams = ref<ParamsMap>({});

// Validation state
const validationErrors = ref<Array<{ param_name: string; message: string }>>([]);

// Get validation error for a specific parameter
const getParamError = (paramName: string): string | null => {
  const error = validationErrors.value.find((e) => e.param_name === paramName);
  return error ? error.message : null;
};

// Check if parameters are valid
const hasValidationErrors = computed(() => validationErrors.value.length > 0);

// Check if node is a preprocessing node (eligible for preview)
const isPreprocessingNode = computed(() => {
  if (!props.selectedNode) return false;
  const preprocessingTypes = ['preprocess.smooth', 'baseline.penalized_ls', 'baseline.rubberband', 'preprocess.normalize', 'preprocess.scale', 'preprocess.emsc', 'preprocess.derivative'];
  return preprocessingTypes.includes(selectedNodeType.value);
});

// Get node metadata and separate basic/advanced params
const nodeMetadata = computed(() => {
  if (!props.selectedNode) return null;
  return workflowStore.getNodeMetadata(props.selectedNode.type);
});

const normalizeOptions = (options: any[] | undefined): any[] | undefined => {
  if (!options) return options;
  return options.map((opt: any) => typeof opt === 'string' ? { label: opt, value: opt } : opt);
};

const mapMetadataParamNames = (
  _nodeType: string,
  parameters: NodeParameterMetadata[]
): NodeParameterMetadata[] => {
  return parameters;
};

const mappedMetadataParams = computed(() => {
  if (!nodeMetadata.value || !props.selectedNode) return [];
  return mapMetadataParamNames(props.selectedNode.type, nodeMetadata.value.parameters);
});

const basicParams = computed(() => {
  if (!mappedMetadataParams.value.length) return [];
  return mappedMetadataParams.value.filter(p => !p.category || p.category === 'basic');
});

const advancedParams = computed(() => {
  if (!mappedMetadataParams.value.length) return [];
  return mappedMetadataParams.value.filter(p => p.category === 'advanced');
});

const hasAdvancedParams = computed(() => advancedParams.value.length > 0);

// Processing history helpers
const sortedProcessingHistory = computed<any[]>(() => {
  const history = outputMetadata.value.processing_history ||
                  outputMetadata.value.provenance?.operations ||
                  spectraMetadata.value.provenance?.operations ||
                  [];
  // Sort by timestamp if available
  if (history.length > 0 && typeof history[0] === "object" && history[0] !== null && "timestamp" in history[0]) {
    const withTimestamp = history.filter(
      (item): item is { timestamp: string } =>
        typeof item === "object" && item !== null && "timestamp" in item && typeof item.timestamp === "string"
    );
    return [...history].sort((a, b) => {
      const dateA = withTimestamp.find((item) => item === a)?.timestamp ?? "";
      const dateB = withTimestamp.find((item) => item === b)?.timestamp ?? "";
      if (!dateA || !dateB) return 0;
      const timeA = new Date(dateA).getTime();
      const timeB = new Date(dateB).getTime();
      return timeA - timeB;
    });
  }

  if (Array.isArray(history)) {
    return history;
  }
  return [];
});

const getHistoryTimestamp = (entry: unknown): string | null => {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
    return null;
  }
  const timestamp = (entry as Record<string, unknown>).timestamp;
  return typeof timestamp === "string" ? timestamp : null;
};

// Format timestamp - show full date if steps span multiple days
const formatStepTimestamp = (timestamp: string, _index: number): string => {
  const date = new Date(timestamp);
  const history = sortedProcessingHistory.value;

  // Check if we need to show date (steps span multiple days)
  if (history.length > 1) {
    const firstTimestamp = getHistoryTimestamp(history[0]);
    const lastTimestamp = getHistoryTimestamp(history[history.length - 1]);
    if (firstTimestamp && lastTimestamp) {
      const firstDate = new Date(firstTimestamp);
      const lastDate = new Date(lastTimestamp);
      const daysDiff = Math.abs(lastDate.getTime() - firstDate.getTime()) / (1000 * 60 * 60 * 24);

      if (daysDiff >= 1) {
        // Steps span multiple days - show full date+time
        return date.toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        });
      }
    }
  }
  // Same day - just show time
  return date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
};

// Format snake_case keys to readable labels
const formatLabel = (key: string): string => {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/Cm$/, '(cm⁻¹)')
    .replace(/Khz$/, '(kHz)')
    .replace(/^N /, 'Number of ');
};

// Format acquisition values with appropriate units
const formatAcquisitionValue = (key: string, value: unknown): string => {
  if (value === null || value === undefined) return '—';

  // Add units based on key
  if (key.includes('resolution') && typeof value === 'number') {
    return `${value} cm⁻¹`;
  }
  if (key.includes('velocity') && typeof value === 'number') {
    return `${value} kHz`;
  }
  if (key.includes('wavenumber') && typeof value === 'number') {
    return `${value.toFixed(1)} cm⁻¹`;
  }
  if ((key === 'n_scans' || key === 'n_points') && typeof value === "number") {
    return value.toLocaleString();
  }

  return String(value);
};

// Modal state
const showQuickPlotModal = ref(false);
const showDataTableModal = ref(false);
const showMetadataModal = ref(false);
const showErrorDetails = ref(false);
const showPreviewModal = ref(false);
const previewData = ref<{ original: any; processed: any } | null>(null);

// Debug: watch nodeOutput changes
watch(() => props.nodeOutput, (output) => {
  if (output) {
    console.log('[WorkflowInspector] nodeOutput updated:', {
      hasData: !!output.data,
      dataLength: Array.isArray(output.data) ? output.data.length : 'N/A',
      dataType: output.data ? (Array.isArray(output.data) ? 'array' : typeof output.data) : 'none',
      firstRow: Array.isArray(output.data) && output.data[0] ?
        (Array.isArray(output.data[0]) ? `array[${output.data[0].length}]` : typeof output.data[0]) : 'N/A',
    });
  }
}, { immediate: true });

// ============================================================================
// SPECTROCHEMPY FILE DROPDOWN STATE
// ============================================================================

// SpectroChemPy file dropdown state
const scpFileOptions = ref<Array<{label: string; value: string; path: string}>>([]);
const isLoadingScpFiles = ref(false);

const loadSpectroChemPyFiles = async (dataset: string) => {
  console.log(`[WorkflowInspector] Fetching files for ${dataset}...`);
  isLoadingScpFiles.value = true;
  try {
    const files = await workflowStore.fetchSpectroChemPyFiles(dataset);
    scpFileOptions.value = files;
    console.log(`[WorkflowInspector] Loaded ${files.length} files for ${dataset}`);
  } catch (error) {
    console.error("[WorkflowInspector] Failed to load SpectroChemPy files:", error);
    scpFileOptions.value = [];
  } finally {
    isLoadingScpFiles.value = false;
  }
};

// Watch example_dataset to fetch files when it changes
watch(
  () => localParams.value.example_dataset,
  async (newDataset, oldDataset) => {
    console.log(`[WorkflowInspector] example_dataset changed:`, {old: oldDataset, new: newDataset, source: localParams.value.source});

    if (newDataset && localParams.value.source === 'spectrochempy') {
      // Clear example_file when dataset changes (but not on initial load if it has a value)
      if (newDataset !== oldDataset && oldDataset !== undefined) {
        localParams.value.example_file = "";
      }

      // Fetch available files for new dataset
      await loadSpectroChemPyFiles(newDataset);
    } else {
      console.log(`[WorkflowInspector] Not fetching files - newDataset: ${newDataset}, source: ${localParams.value.source}`);
    }
  },
  { immediate: true }
);

watch(
  () => localParams.value.source,
  async (newSource, oldSource) => {
    if (newSource !== 'spectrochempy' || newSource === oldSource) {
      return;
    }
    const dataset = localParams.value.example_dataset;
    if (!dataset) {
      return;
    }
    console.log(`[WorkflowInspector] source changed to spectrochempy, loading files for ${dataset}`);
    await loadSpectroChemPyFiles(dataset);
  }
);

// ============================================================================
// METADATA EDITOR STATE
// ============================================================================

// Default empty metadata structure matching SpectraMeta schema
const createEmptyMetadata = () => ({
  species: [] as Array<{
    name: string;
    cas_number?: string;
    molecular_formula?: string;
    state?: string;
  }>,
  conditions: {
    temperature_c: null as number | null,
    pressure_atm: null as number | null,
    purge_gas: null as string | null,
    ambient_humidity_percent: null as number | null,
  },
  instrument: {
    manufacturer: null as string | null,
    model: null as string | null,
    detector_type: null as string | null,
    source_type: null as string | null,
  },
  acquisition: {
    resolution_cm: null as number | null,
    n_scans: null as number | null,
    wavenumber_min: null as number | null,
    wavenumber_max: null as number | null,
    apodization: null as string | null,
  },
  cell: {
    cell_type: null as string | null,
    pathlength_mm: null as number | null,
    window_material: null as string | null,
    cell_volume_ml: null as number | null,
  },
  audit: {
    operator: null as string | null,
    operator_id: null as string | null,
    lab_id: null as string | null,
    project_id: null as string | null,
    sop_id: null as string | null,
    sample_id: null as string | null,
    batch_id: null as string | null,
  },
});

type SpectraMetadata = ReturnType<typeof createEmptyMetadata>;

const withMetadataDefaults = (metadataValue: unknown): SpectraMetadata => {
  const defaults = createEmptyMetadata();
  const metadata = asObject(metadataValue);
  if (!metadata) {
    return defaults;
  }

  const conditions = asObject(metadata.conditions);
  const instrument = asObject(metadata.instrument);
  const acquisition = asObject(metadata.acquisition);
  const cell = asObject(metadata.cell);
  const audit = asObject(metadata.audit);

  return {
    ...defaults,
    ...metadata,
    species: Array.isArray(metadata.species)
      ? (metadata.species as SpectraMetadata["species"])
      : defaults.species,
    conditions: { ...defaults.conditions, ...(conditions ?? {}) },
    instrument: { ...defaults.instrument, ...(instrument ?? {}) },
    acquisition: { ...defaults.acquisition, ...(acquisition ?? {}) },
    cell: { ...defaults.cell, ...(cell ?? {}) },
    audit: { ...defaults.audit, ...(audit ?? {}) },
  };
};

const localMetadata = ref(createEmptyMetadata());

// Data source node types that can edit metadata
const DATA_SOURCE_NODES = ['data.source', 'data.nist_library', 'data.synthetic_curve', 'doe_plate'];

const isDataSourceNode = computed(() => {
  return props.selectedNode && DATA_SOURCE_NODES.includes(selectedNodeType.value);
});

// ============================================================================
// METADATA DROPDOWN OPTIONS
// ============================================================================

const physicalStateOptions = [
  'gas', 'liquid', 'solid', 'plasma', 'solution', 'film',
  'powder', 'kbr_pellet', 'mull', 'gel', 'suspension', 'unknown'
];

const purgeGasOptions = ['N2', 'dry_air', 'Ar', 'none'];

const instrumentManufacturers = [
  'Bruker', 'Thermo Scientific', 'Agilent', 'PerkinElmer',
  'JASCO', 'Shimadzu', 'ABB', 'Nicolet', 'Bio-Rad'
];

const detectorTypeOptions = [
  'mct', 'mct_a', 'mct_b', 'dtgs', 'dtgs_kbr', 'dtgs_pe',
  'ingaas', 'insb', 'pbse', 'si', 'ge', 'bolometer', 'unknown'
];

const apodizationOptions = [
  'Happ-Genzel', 'Boxcar', 'Blackman-Harris', 'Norton-Beer', 'triangular'
];

const cellTypeOptions = [
  'gas_cell', 'liquid_cell', 'demountable', 'flow_cell', 'cuvette', 'ATR'
];

const windowMaterialOptions = [
  'kbr', 'nacl', 'caf2', 'baf2', 'znse', 'zns', 'diamond',
  'ge', 'si', 'sapphire', 'krs5', 'agcl', 'pe', 'unknown'
];

// ============================================================================
// METADATA HELPERS
// ============================================================================

const addSpecies = () => {
  localMetadata.value.species.push({
    name: '',
    cas_number: '',
    molecular_formula: '',
    state: 'unknown',
  });
  emitMetadata();
};

const removeSpecies = (index: number) => {
  localMetadata.value.species.splice(index, 1);
  emitMetadata();
};

const emitMetadata = () => {
  if (props.selectedNode) {
    // Merge metadata into params
    emit('update-params', props.selectedNode.id, {
      ...localParams.value,
      metadata: localMetadata.value,
    });
  }
};

// Watch for node changes to load existing metadata
watch(() => props.selectedNode, (node) => {
  if (node && node.params?.metadata) {
    localMetadata.value = withMetadataDefaults(node.params.metadata);
  } else {
    localMetadata.value = createEmptyMetadata();
  }
}, { immediate: true });

// Dataset selection (uses workflowStore initialized above)
const selectedDatasetKey = ref<string | null>(null);

onMounted(async () => {
  await workflowStore.fetchAvailableDatasets();
  // Preload reference dataset catalogs (eigenvector + sklearn) once.
  // This keeps dropdowns in sync with backend catalogs without requiring a source toggle.
  void workflowStore.fetchReferenceDatasets();
});

// Build TreeSelect nodes from available datasets
const datasetTreeNodes = computed(() => {
  const datasets = workflowStore.availableDatasets;
  if (!datasets) return [];

  const nodes: DatasetTreeNode[] = [];

  // Experiments section
  if (datasets.experiments.length > 0) {
    const experimentNode = {
      key: 'experiments',
      label: `Experiments (${datasets.experiments.length})`,
      selectable: false,
      children: datasets.experiments.map(exp => {
        const stageChildren: DatasetTreeNode[] = [];

        // Add stages with files
        for (const stage of ['raw', 'preprocessed', 'synthetic'] as const) {
          const files = exp.stages[stage];
          if (files.length > 0) {
            stageChildren.push({
              key: `exp-${exp.id}-${stage}`,
              label: `${stage}/ (${files.length} file${files.length !== 1 ? 's' : ''})`,
              selectable: false,
              children: files.map(file => ({
                key: `exp-${exp.id}-${stage}-${file.id}`,
                label: file.file_path.split('/').pop() || file.file_path,
                data: {
                  source: 'experiment',
                  experiment_id: exp.id,
                  stage: stage,
                  file_id: file.id,
                  file_path: file.file_path,
                },
              })),
            });
          }
        }

        return {
          key: `exp-${exp.id}`,
          label: `exp_${String(exp.id).padStart(3, '0')}: ${exp.name}`,
          selectable: false,
          children: stageChildren,
        };
      }),
    };
    nodes.push(experimentNode);
  }

  // Library section
  if (datasets.library.length > 0) {
    const libraryNode = {
      key: 'library',
      label: `NIST Library (${datasets.library.length})`,
      selectable: false,
      children: datasets.library.map(entry => ({
        key: `lib-${entry.id}`,
        label: `${entry.compound_name} (${entry.cas_number})`,
        data: {
          source: 'library',
          library_id: entry.id,
          compound_name: entry.compound_name,
          cas_number: entry.cas_number,
          file_path: entry.file_path,
        },
      })),
    };
    nodes.push(libraryNode);
  }

  // Builder outputs section (placeholder)
  if (datasets.builder.length > 0) {
    const builderNode = {
      key: 'builder',
      label: `Builder Outputs (${datasets.builder.length})`,
      selectable: false,
      children: datasets.builder.map((output, idx) => ({
        key: `builder-${idx}`,
        label: typeof output.name === "string" ? output.name : `Output ${idx + 1}`,
        data: {
          source: 'builder',
          ...output,
        },
      })),
    };
    nodes.push(builderNode);
  }

  return nodes;
});

// My Dataset node: flat experiment options for simple Dropdown
const myDatasetExperimentOptions = computed(() => {
  const datasets = workflowStore.availableDatasets;
  if (!datasets) return [];
  return datasets.experiments.map(exp => ({
    label: exp.name,
    value: exp.id,
  }));
});

// Track current node ID to avoid resetting params on every update
const currentNodeId = ref<string | null>(null);

// Helper to get defaults for a node type
const getDefaultsForNodeType = (nodeType: string): ParamsMap => {
  const definitions = getParamDefinitions(nodeType);
  const defaults: ParamsMap = {};
  for (const param of definitions) {
    if (param.default !== undefined) {
      defaults[param.name] = param.default;
    }
  }
  return defaults;
};

// Watch for selected node changes - only reset params when node ID changes
watch(() => props.selectedNode?.id, (newId, oldId) => {
  const node = props.selectedNode;
  if (node && newId !== oldId) {
    // Node selection changed - reset local params with defaults first, then stored values
    currentNodeId.value = newId ?? null;
    const defaults = getDefaultsForNodeType(node.type);
    localParams.value = { ...defaults, ...node.params };
    // Reconstruct selectedDatasetKey from params if available
    const ref = asObject(node.params.dataset_ref);
    if (node.type === 'data.source' && ref) {
      if (ref.source === 'experiment') {
        const experimentId = asKeyPart(ref.experiment_id);
        const stage = asKeyPart(ref.stage);
        const fileId = asKeyPart(ref.file_id);
        selectedDatasetKey.value = experimentId && stage && fileId
          ? `exp-${experimentId}-${stage}-${fileId}`
          : null;
      } else if (ref.source === 'library') {
        const libraryId = asKeyPart(ref.library_id);
        selectedDatasetKey.value = libraryId ? `lib-${libraryId}` : null;
      }
    } else if (node.type === 'data.my_dataset') {
      // Params (dataset_id, file_id, stage) are set directly via localParams — no key needed
      if (!localParams.value.stage) {
        localParams.value.stage = 'raw';
      }
    } else {
      selectedDatasetKey.value = null;
    }

    if (localParams.value.source === 'eigenvector' || localParams.value.source === 'sklearn') {
      void workflowStore.fetchReferenceDatasets();
    }
  } else if (!node) {
    // Node deselected
    currentNodeId.value = null;
    localParams.value = {};
    selectedDatasetKey.value = null;
  }
}, { immediate: true });

// Handle dataset selection change
const onDatasetSelect = (nodeData: Record<string, unknown>) => {
  if (!nodeData) return;

  // Find the selected node's data
  const findNodeData = (nodes: DatasetTreeNode[], key: string): DatasetRefData | null => {
    for (const node of nodes) {
      if (node.key === key && node.data) {
        return node.data;
      }
      if (node.children) {
        const found = findNodeData(node.children, key);
        if (found) return found;
      }
    }
    return null;
  };

  const selectedKey = Object.keys(nodeData)[0];
  const data = findNodeData(datasetTreeNodes.value, selectedKey);

  if (data) {
    localParams.value.dataset_ref = data;
    // Also set legacy fields for backward compatibility
    localParams.value.source = data.source;
    if (data.source === 'experiment') {
      localParams.value.experiment_id = data.experiment_id;
      localParams.value.stage = data.stage;
      localParams.value.file_id = data.file_id;
      localParams.value.file_path = data.file_path;
    } else if (data.source === 'library') {
      localParams.value.library_id = data.library_id;
      localParams.value.file_path = data.file_path;
    }
    emitParams();
  }
};

// Get selected dataset label for display
const _selectedDatasetLabel = computed(() => {
  if (!selectedDatasetKey.value) return 'Select a dataset...';

  const findLabel = (nodes: DatasetTreeNode[], key: string): string | null => {
    for (const node of nodes) {
      if (node.key === key) {
        return node.label;
      }
      if (node.children) {
        const found = findLabel(node.children, key);
        if (found) return found;
      }
    }
    return null;
  };

  return findLabel(datasetTreeNodes.value, selectedDatasetKey.value) || 'Select a dataset...';
});

const normalizeMethodOptions = ['mean', 'median', 'snv', 'msc'];

// DATA node source options — keep reference/file paths only in the primary selector.
// Legacy sources remain executable for existing workflows but are not listed here.
const allDataSourceOptions = [
  { label: 'Direct File', value: 'file' },
  { label: 'SpectroChemPy Dataset', value: 'spectrochempy' },
  { label: 'Sklearn Dataset', value: 'sklearn' },
  { label: 'Eigenvector Dataset', value: 'eigenvector' },
];
const dataSourceOptions = computed(() => {
  const options = (
    isDemoMode.value
      ? allDataSourceOptions.filter(o => o.value !== 'file')
      : allDataSourceOptions
  ).map(option => ({ ...option }));

  // Preserve editability for legacy workflows that still carry old source values.
  const currentSource = localParams.value.source;
  if (typeof currentSource === 'string' && currentSource.trim() !== '' &&
      !options.some(option => option.value === currentSource)) {
    options.push({ label: `Legacy: ${currentSource}`, value: currentSource });
  }

  return options;
});

const getSelectedDatasetFallback = (value: unknown): Array<{label: string; value: string}> => {
  if (typeof value === 'string' && value.trim() !== '') {
    return [{ label: value, value }];
  }
  return [];
};

// Sklearn dataset options (fetched dynamically from API)
const sklearnDatasetOptions = computed(() => {
  const cached = workflowStore.sklearnDatasetCache;
  if (cached.length > 0) return cached;
  // Avoid hardcoded catalog drift: keep currently-selected value visible until cache loads.
  return getSelectedDatasetFallback(localParams.value.sklearn_dataset);
});

// Eigenvector Research public dataset options (fetched dynamically from API)
const eigenvectorDatasetOptions = computed(() => {
  const cached = workflowStore.eigenvectorDatasetCache;
  if (cached.length > 0) return cached;
  // Avoid hardcoded catalog drift: keep currently-selected value visible until cache loads.
  return getSelectedDatasetFallback(localParams.value.eigenvector_dataset);
});

// Dynamic dataset options from API (populated on initial file fetch)
const scpExampleOptions = computed(() => {
  const datasets = workflowStore.availableSpectroChemPyDatasets;
  // Fall back to known datasets if cache is empty (pre-fetch)
  return datasets.length > 0 ? datasets : [
    'irdata',
    'ramandata',
    'nmrdata',
    'galacticdata',
    'agirdata',
    'matlabdata',
    'msdata',
  ];
});

// Handle source type change
const onSourceChange = () => {
  // Clear source-specific params when changing source
  if (localParams.value.source === 'file') {
    localParams.value.experiment_id = undefined;
    localParams.value.file_id = undefined;
    localParams.value.dataset_ref = undefined;
  } else if (localParams.value.source === 'experiment') {
    localParams.value.file_path = undefined;
  } else if (localParams.value.source === 'library') {
    localParams.value.file_path = undefined;
    localParams.value.experiment_id = undefined;
    localParams.value.file_id = undefined;
  } else if (localParams.value.source === 'spectrochempy') {
    localParams.value.file_path = undefined;
    localParams.value.experiment_id = undefined;
    localParams.value.file_id = undefined;
    localParams.value.dataset_ref = undefined;
    if (!localParams.value.example_dataset) {
      localParams.value.example_dataset = 'irdata';
    }
  } else if (localParams.value.source === 'sklearn') {
    localParams.value.file_path = undefined;
    localParams.value.experiment_id = undefined;
    localParams.value.file_id = undefined;
    localParams.value.dataset_ref = undefined;
    localParams.value.example_dataset = undefined;
    if (!localParams.value.sklearn_dataset) {
      localParams.value.sklearn_dataset = 'iris';
    }
    void workflowStore.fetchReferenceDatasets();
  } else if (localParams.value.source === 'eigenvector') {
    localParams.value.file_path = undefined;
    localParams.value.experiment_id = undefined;
    localParams.value.file_id = undefined;
    localParams.value.dataset_ref = undefined;
    localParams.value.example_dataset = undefined;
    localParams.value.sklearn_dataset = undefined;
    if (!localParams.value.eigenvector_dataset) {
      localParams.value.eigenvector_dataset = 'diesel_nir';
    }
    void workflowStore.fetchReferenceDatasets();
  }
  emitParams();
};

// Contour plot options
const colorscaleOptions = ['Viridis', 'Hot', 'RdBu', 'Blues', 'Greys', 'Jet', 'Spectral'];
const contourPlotTypeOptions = ['heatmap', 'contour', 'surface'];

// Helper to format parameter labels (snake_case -> Title Case)
const formatParamLabel = (key: string): string => {
  return key
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};

const axisOptions = computed(() => {
  const firstRow = Array.isArray(props.nodeOutput?.data?.[0])
    ? props.nodeOutput.data[0]
    : [];
  const numFeatures = Math.max((firstRow.length || 1) - 1, 1);
  const isPCA = outputMetadata.value.isPCA;
  return Array.from({ length: numFeatures }, (_, i) => ({
    label: isPCA ? `PC${i + 1}` : `Feature ${i + 1}`,
    value: i,
  }));
});

// Should show scatter plot
const _shouldShowPlot = computed(() => {
  if (!props.selectedNode || !props.nodeOutput) return false;
  return ['output.plot', 'model.pca', 'data.source', 'preprocess.normalize', 'preprocess.scale'].includes(selectedNodeType.value) &&
         Array.isArray(props.nodeOutput.data) &&
         props.nodeOutput.data.length > 0;
});

// Calculate plot points
const _plotPoints = computed(() => {
  if (!props.nodeOutput?.data) return [];

  const data = props.nodeOutput.data.filter((row): row is unknown[] => Array.isArray(row));
  const xIdx = localParams.value.x_axis ?? 0;
  const yIdx = localParams.value.y_axis ?? 1;

  const xValues = data.map((row) => row[xIdx]).filter((v): v is number => typeof v === 'number');
  const yValues = data.map((row) => row[yIdx]).filter((v): v is number => typeof v === 'number');

  if (xValues.length === 0 || yValues.length === 0) return [];

  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);

  const colors: Record<string, string> = {
    'setosa': '#ef4444',
    'versicolor': '#3b82f6',
    'virginica': '#22c55e',
  };

  return data.map((row) => {
    const xValue = typeof row[xIdx] === "number" ? row[xIdx] : xMin;
    const yValue = typeof row[yIdx] === "number" ? row[yIdx] : yMin;
    const x = ((xValue - xMin) / (xMax - xMin || 1)) * 180 + 10;
    const y = 140 - ((yValue - yMin) / (yMax - yMin || 1)) * 130;
    const label = row[row.length - 1];
    const labelKey = typeof label === "string" ? label : String(label ?? "");
    return {
      x,
      y,
      color: colors[labelKey] || '#94a3b8',
    };
  });
});

// Plot points for full-size modal (larger coordinate space)
const _plotPointsFull = computed(() => {
  if (!props.nodeOutput?.data) return [];

  const data = props.nodeOutput.data.filter((row): row is unknown[] => Array.isArray(row));
  const xIdx = localParams.value.x_axis ?? 0;
  const yIdx = localParams.value.y_axis ?? 1;

  const xValues = data.map((row) => row[xIdx]).filter((v): v is number => typeof v === 'number');
  const yValues = data.map((row) => row[yIdx]).filter((v): v is number => typeof v === 'number');

  if (xValues.length === 0 || yValues.length === 0) return [];

  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);

  const colors: Record<string, string> = {
    'setosa': '#ef4444',
    'versicolor': '#3b82f6',
    'virginica': '#22c55e',
  };

  // Scale to fit in 600x400 viewBox with margins (60px left, 20px right, 50px top/bottom)
  return data.map((row) => {
    const xValue = typeof row[xIdx] === "number" ? row[xIdx] : xMin;
    const yValue = typeof row[yIdx] === "number" ? row[yIdx] : yMin;
    const x = ((xValue - xMin) / (xMax - xMin || 1)) * 500 + 70;
    const y = 340 - ((yValue - yMin) / (yMax - yMin || 1)) * 280;
    const label = row[row.length - 1];
    const labelKey = typeof label === "string" ? label : String(label ?? "");
    return {
      x,
      y,
      color: colors[labelKey] || '#3b82f6',
    };
  });
});

// Validate current parameters
const validateParams = () => {
  if (!props.selectedNode) {
    validationErrors.value = [];
    return;
  }

  // Run validation using workflow store
  validationErrors.value = workflowStore.validateNodeParams(
    props.selectedNode.type,
    localParams.value
  );
};

// Emit params update
const emitParams = () => {
  if (props.selectedNode) {
    // Validate before emitting
    validateParams();
    emit('update-params', props.selectedNode.id, { ...localParams.value });
  }
};

// Execute node
const executeNode = () => {
  if (props.selectedNode) {
    // Validate before execution
    validateParams();

    // If there are validation errors, don't execute
    if (validationErrors.value.length > 0) {
      return;
    }

    // Emit params first to ensure latest values are saved before execution
    emit('update-params', props.selectedNode.id, { ...localParams.value });
    // Then execute
    emit('execute-node', props.selectedNode.id);
  }
};

// Delete node
const deleteNode = () => {
  if (props.selectedNode) {
    emit('delete-node', props.selectedNode.id);
  }
};

// Run preview (before/after comparison)
const runPreview = async () => {
  if (!props.selectedNode || !isPreprocessingNode.value) return;

  // Validate params first
  validateParams();
  if (validationErrors.value.length > 0) {
    toast.add({
      severity: 'error',
      summary: 'Validation Error',
      detail: 'Please fix parameter errors before previewing',
      life: 3000
    });
    return;
  }

  try {
    // Get the input data from the first input connection
    const inputConn = props.inputConnections[0];
    if (!inputConn || !inputConn.data) {
      toast.add({
        severity: 'warn',
        summary: 'No Input Data',
        detail: 'This node needs input data to preview. Run the previous node first.',
        life: 4000
      });
      return;
    }

    // Store original data
    previewData.value = {
      original: inputConn.data,
      processed: null
    };

    // Show modal with loading state
    showPreviewModal.value = true;

    // Execute trial run with current params
    const nodeIdStr = String(props.selectedNode.id);
    const result = await workflowStore.executeTrial(nodeIdStr, localParams.value);

    if (result.status === 'error') {
      toast.add({
        severity: 'error',
        summary: 'Preview Failed',
        detail: result.error || 'Could not generate preview',
        life: 5000
      });
      showPreviewModal.value = false;
      return;
    }

    // Store processed data
    previewData.value.processed = result.result;

  } catch (error: unknown) {
    console.error('[WorkflowInspector] Preview error:', error);
    toast.add({
      severity: 'error',
      summary: 'Preview Error',
      detail: getErrorMessage(error, 'Failed to generate preview'),
      life: 5000
    });
    showPreviewModal.value = false;
  }
};

// Open node detail in a temporary builder sheet for trial execution.
const STORAGE_KEY = "node_detail_data";

const openToRunTrials = () => {
  if (!props.selectedNode) return;

  // Build input connections with icons and labels
  const inputConns = props.inputConnections.map(conn => ({
    nodeId: conn.nodeId,
    icon: NODE_ICONS[conn.nodeType] || '📦',
    label: conn.nodeLabel,
    port: conn.port,
    toPort: conn.toPort,  // Include input port name for multi-input nodes
  }));

  // Build input data summary from first connected node's output
  let inputData = null;
  if (props.inputConnections.length > 0) {
    const firstInput = props.inputConnections[0];
    if (firstInput.data?.data) {
      const data = firstInput.data.data;
      inputData = {
        shape: Array.isArray(data) ? [data.length, Array.isArray(data[0]) ? data[0].length : 1] : null,
        source: `${firstInput.nodeLabel} (${firstInput.nodeType})`,
        dataType: Array.isArray(data) ? 'dataset' : typeof data,
        data: data, // Include actual data for preview
      };
    }
  }

  // Get workflow nodes and edges from the store for isolated trial execution.
  const workflowNodes = workflowStore.nodes.map(node => ({
    id: node.id,
    type: node.type,
    params: node.params || {},
  }));
  const workflowEdges = workflowStore.edges.map(edge => ({
    from: edge.from,
    to: edge.to,
    fromPort: edge.fromPort || 'default',
    toPort: edge.toPort || 'default',
  }));

  // Pick the ports we want to preserve across reduced-tier fallbacks.
  // Plot computeds on the Detail View read these directly (loadings for
  // PCA/PLS/PLSDA; St/H/A for MCR/NMF/ICA/SIMPLISMA). They're all small
  // matrices (n_components × n_features) and stripping them makes those
  // plots render empty even when the primary payload fits.
  const PRESERVED_PORT_NAMES = new Set(["loadings", "St", "H", "A"]);

  const buildReducedPorts = (
    level: "full" | "primary" | "minimal",
    ports: NodeOutput["ports"] | null | undefined,
  ): NodeOutput["ports"] | null => {
    if (!ports) return null;
    if (level === "full") return ports;
    const reduced: Record<string, PortOutput> = {};
    for (const [name, port] of Object.entries(ports)) {
      if (PRESERVED_PORT_NAMES.has(name)) reduced[name] = port;
    }
    return Object.keys(reduced).length > 0 ? reduced : null;
  };

  // detail level: "full" = all data+ports, "primary" = data+metadata+small-plot-ports, "minimal" = no data
  const buildNodeDetailData = (level: "full" | "primary" | "minimal") => {
    if (!props.selectedNode) return null;
    const includeData = level !== "minimal";

    // Strip large metadata fields to avoid sessionStorage quota.
    // Visualization nodes (output.*) embed Plotly traces in metadata.data
    // which duplicates the top-level data array — strip it in non-full tiers.
    let metadata = outputMetadata.value;
    const nt = props.selectedNode.type;
    if (level !== "full" && metadata && nt.startsWith("output.")) {
      const lightMetadata = { ...metadata };
      delete lightMetadata.data; // Plotly traces (duplicated in output.data)
      metadata = lightMetadata;
    }
    if (level === "minimal" && metadata) {
      const lightMetadata = { ...metadata };
      // Remove large arrays from PCA metadata (loadings can be very large)
      if (nt.includes('pca')) {
        delete lightMetadata.loadings;
        delete lightMetadata.wavenumbers;
      }
      // Remove large arrays from decomposition methods
      if (['model.simplisma', 'model.nmf', 'model.ica', 'model.mcr_als'].includes(nt)) {
        delete lightMetadata.St;
        delete lightMetadata.H;
        delete lightMetadata.A;
        delete lightMetadata.wavenumbers;
        delete lightMetadata.spectral_wavenumbers;
      }
      // For visualization nodes, trace data has already been removed above;
      // drop remaining large fields but keep layout and plot_type.
      if (nt.startsWith("output.")) {
        delete lightMetadata.data;
      }
      metadata = lightMetadata;
    }

    return {
      id: props.selectedNode.id,
      type: props.selectedNode.type,
      label: getNodeLabel(props.selectedNode.type),
      params: { ...localParams.value },
      output: props.nodeOutput ? {
        // For output.* nodes in reduced tiers, top-level data duplicates
        // the Plotly traces already stripped from metadata — omit it too.
        data: (includeData && !(level !== "full" && nt.startsWith("output.")))
          ? props.nodeOutput.data : null,
        metadata: metadata,
        plots: props.nodeOutput.plots || null,
        ports: buildReducedPorts(level, props.nodeOutput.ports),
        primary_port: props.nodeOutput.primary_port || null,
      } : null,
      // Include input connections with their data
      inputConnections: inputConns,
      inputData: includeData ? inputData : (inputData ? { ...inputData, data: null } : null),
      // Include param definitions for the settings form
      paramDefinitions: getParamDefinitions(props.selectedNode.type),
      // Include full workflow context for isolated trial execution.
      workflowNodes: workflowNodes,
      workflowEdges: workflowEdges,
      // Carry project context into the trial surface.
      projectId: projectStore.currentProjectId,
    };
  };

  emit("open-trial", buildNodeDetailData("full"));
};

const mapMetadataParams = (
  _nodeType: string,
  parameters: NodeParameterMetadata[]
): NodeParameterDefinition[] => {
  return parameters.map((param) => {
    return {
      name: param.name,
      label: param.label,
      type: param.param_type,
      min: param.min_value,
      max: param.max_value,
      step: param.step,
      options: normalizeOptions(param.options),
      description: param.description,
      default: param.default,
      required: param.required,
    };
  });
};

// Get parameter definitions for a node type (for the detail view form)
const getParamDefinitions = (nodeType: string): NodeParameterDefinition[] => {
  const metadata = workflowStore.getNodeMetadata(nodeType);
  if (metadata?.parameters?.length) {
    return mapMetadataParams(nodeType, metadata.parameters);
  }

  const definitions: Record<string, NodeParameterDefinition[]> = {
    'data.source': [
      { name: 'source', label: 'Source', type: 'select', options: dataSourceOptions.value },
      { name: 'file_path', label: 'File Path', type: 'text' },
      { name: 'transpose_on_load', label: 'Transpose on Load', type: 'boolean', default: false },
      { name: 'sample_axis_title', label: 'Sample Axis Title', type: 'text', default: 'Sample' },
      { name: 'spectral_axis_title', label: 'Spectral Axis Title', type: 'text', default: 'Wavenumber' },
    ],
    'preprocess.normalize': [
      { name: 'method', label: 'Method', type: 'select', options: normalizeMethodOptions.map(m => ({ label: m, value: m })) },
    ],
    'baseline.penalized_ls': [
      { name: 'lam', label: 'Lambda (λ)', type: 'number', min: 1000, max: 1000000, step: 1000, default: 100000 },
      { name: 'p', label: 'Asymmetry (p)', type: 'number', min: 0.001, max: 0.1, step: 0.001, default: 0.001 },
    ],
    'preprocess.smooth': [
      { name: 'window', label: 'Window Size', type: 'number', min: 5, max: 51, step: 2, default: 11 },
      { name: 'poly', label: 'Polynomial Order', type: 'number', min: 1, max: 5, step: 1, default: 2 },
    ],
    'model.pca': [
      { name: 'n_components', label: 'Number of Components', type: 'text', default: "5", description: "Number of components: integer (e.g., '5'), 'mle' (auto-select via Maximum Likelihood), or float 0-1 (e.g., '0.95' for 95% variance)" },
      { name: 'standardized', label: 'Standardize (mean center + unit variance)', type: 'boolean', default: false },
      { name: 'scaled', label: 'Scale (unit variance)', type: 'boolean', default: false },
    ],
    'model.pls': [
      { name: 'n_components', label: 'Number of Components', type: 'number', min: 1, max: 15, step: 1, default: 3 },
    ],
    'model.mcr_als': [
      { name: 'n_components', label: 'Number of Components', type: 'number', min: 1, max: 10, step: 1, default: 3 },
    ],
    'stats.summary': [
      { name: 'max_samples', label: 'Max Samples', type: 'number', min: 10, max: 500, step: 10, default: 50 },
    ],
    'output.contour': [
      { name: 'colorscale', label: 'Color Scale', type: 'select', options: colorscaleOptions.map(c => ({ label: c, value: c })) },
      { name: 'plot_type', label: 'Plot Type', type: 'select', options: contourPlotTypeOptions.map(t => ({ label: t, value: t })) },
      { name: 'reverse_x', label: 'Reverse X-axis', type: 'boolean', default: true },
      { name: 'transpose', label: 'Transpose Data', type: 'boolean', default: false },
    ],
    'output.export': [
      { name: 'filename', label: 'Filename', type: 'text', default: 'output.csv' },
    ],
  };

  return definitions[nodeType] || [];
};

// Listen for storage changes from the detail view (when user saves)
const handleStorageChange = (event: StorageEvent) => {
  if (event.key === STORAGE_KEY && event.newValue) {
    try {
      const updatedData = JSON.parse(event.newValue);
      if (updatedData._saved && updatedData.id === props.selectedNode?.id) {
        // Update local params with defaults merged with saved values
        const defaults = getDefaultsForNodeType(updatedData.type || props.selectedNode?.type || '');
        localParams.value = { ...defaults, ...updatedData.params };
        emitParams();
      }
    } catch (e) {
      console.error('Failed to parse updated node data:', e);
    }
  }
};

// BroadcastChannel for cross-tab communication (more reliable than storage events)
// Note: Execution requests are handled in WorkflowBuilderContent which has access to all nodes.
// This inspector only handles param updates to keep localParams in sync when a DetailView
// updates params for the currently selected node.
const broadcastChannel = ref<BroadcastChannel | null>(null);

const handleBroadcastMessage = async (event: MessageEvent) => {
  const { type, nodeId, params, nodeType } = event.data;

  // Only handle param updates for the currently selected node
  // (Execution requests are handled by WorkflowBuilderContent)
  if (type === 'node_params_updated' && nodeId === props.selectedNode?.id) {
    // Update local params with defaults merged with saved values
    const defaults = getDefaultsForNodeType(nodeType || props.selectedNode?.type || '');
    localParams.value = { ...defaults, ...params };
    if (localParams.value.source === 'eigenvector' || localParams.value.source === 'sklearn') {
      void workflowStore.fetchReferenceDatasets();
    }
    emitParams();
  }
};

onMounted(() => {
  window.addEventListener('storage', handleStorageChange);

  // Set up BroadcastChannel for more reliable cross-tab communication
  try {
    broadcastChannel.value = new BroadcastChannel('workflow_node_updates');
    broadcastChannel.value.onmessage = handleBroadcastMessage;
  } catch {
    // BroadcastChannel not supported in this browser
    console.warn('BroadcastChannel not supported, falling back to storage events only');
  }
});

onUnmounted(() => {
  window.removeEventListener('storage', handleStorageChange);

  if (broadcastChannel.value) {
    broadcastChannel.value.close();
    broadcastChannel.value = null;
  }
});
</script>

<style scoped>
/* Vertical Sidebar Layout */
.workflow-inspector {
  background: #1e293b;
  border-radius: 8px;
  border: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
  transition: width 0.3s ease, opacity 0.3s ease;
}

.workflow-inspector.hidden {
  display: none;
  width: 0;
  min-width: 0;
  opacity: 0;
  border: none;
  padding: 0;
  overflow: hidden;
}

.workflow-inspector.collapsed {
  width: 48px;
  min-width: 48px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #64748b;
  padding: 20px 12px;
  font-size: 0.8rem;
  text-align: center;
}

.empty-state i {
  font-size: 1.2rem;
}

/* Header with close button */
.inspector-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #334155;
  background: #0f172a;
  position: sticky;
  top: 0;
  z-index: 10;
}

.node-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.node-icon {
  font-size: 1.3rem;
  flex-shrink: 0;
}

.node-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.node-details h3 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: #f8fafc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-id {
  font-size: 0.7rem;
  color: #64748b;
}

.header-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

/* "Open to Run Trials" — the previous icon `pi pi-flask` is not part of the
   primeicons 7 set in this project, so it rendered as an empty glyph (the
   adjacent `pi pi-times` X was visible because that icon does exist). The
   icon is now `pi pi-sliders-h` (parameter tuning — semantically a trial)
   and the front color is forced white to win against PrimeVue's muted
   secondary-text default on dark backgrounds. */
.header-actions :deep(.trial-launch-btn),
.header-actions :deep(.trial-launch-btn:hover),
.header-actions :deep(.trial-launch-btn:focus),
.header-actions :deep(.trial-launch-btn .p-button-icon),
.header-actions :deep(.trial-launch-btn:hover .p-button-icon),
.header-actions :deep(.trial-launch-btn:focus .p-button-icon) {
  color: #ffffff !important;
}

.header-actions :deep(.trial-launch-btn:hover) {
  background: rgba(96, 165, 250, 0.18) !important;
}

/* Action buttons row */
.inspector-actions {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #334155;
}

.inspector-actions .p-button {
  flex: 1;
}

/* Parameters section - vertical */
.inspector-params {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid #334155;
}

.section-label {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
  margin-bottom: 4px;
}

.parameters-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 0.8rem;
  font-weight: 500;
  color: #94a3b8;
}

.field-group {
  margin-top: 16px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid #334155;
  border-radius: 6px;
}

.field-group-title {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
  margin: 0 0 12px 0;
  padding-bottom: 8px;
  border-bottom: 1px solid #334155;
}

.range-inputs {
  display: flex;
  align-items: center;
  gap: 8px;
}

.range-inputs span {
  color: #64748b;
  font-size: 0.8rem;
}

.param-hint {
  font-size: 0.7rem;
  color: #64748b;
  background: rgba(255, 255, 255, 0.05);
  padding: 4px 8px;
  border-radius: 4px;
  margin-top: 4px;
}

.no-params {
  color: #64748b;
  font-size: 0.8rem;
  font-style: italic;
}

.checkbox-row {
  flex-direction: row;
  align-items: center;
  gap: 10px;
}

.checkbox-row label {
  margin: 0;
  cursor: pointer;
}

.generic-params {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Dataset field styling */
.dataset-field {
  width: 100%;
}

.dataset-tree-select {
  min-width: 180px;
}

.dataset-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dataset-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
}

.dataset-badge.experiment {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}

.dataset-badge.library {
  background: rgba(59, 130, 246, 0.2);
  color: #3b82f6;
}

.dataset-badge.builder {
  background: rgba(168, 85, 247, 0.2);
  color: #a855f7;
}

.dataset-badge.file {
  background: rgba(251, 146, 60, 0.2);
  color: #fb923c;
}

.dataset-path {
  font-size: 0.8rem;
  color: #94a3b8;
  font-family: 'SF Mono', Monaco, monospace;
}

/* TreeSelect styling for dark theme */
:deep(.p-treeselect) {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}

:deep(.p-treeselect:hover) {
  border-color: #475569;
}

:deep(.p-treeselect-panel) {
  background: #1e293b;
  border: 1px solid #334155;
}

:deep(.p-treeselect-items-wrapper) {
  max-height: 350px;
}

:deep(.p-treenode) {
  padding: 2px 0;
}

:deep(.p-treenode-content) {
  padding: 6px 8px;
  border-radius: 4px;
}

:deep(.p-treenode-content:hover) {
  background: #334155;
}

:deep(.p-treenode-content.p-highlight) {
  background: rgba(59, 130, 246, 0.2);
}

:deep(.p-treenode-label) {
  color: #f8fafc;
  font-size: 0.85rem;
}

:deep(.p-treenode-toggler) {
  color: #64748b;
}

:deep(.p-treenode-toggler:hover) {
  background: #334155;
  color: #f8fafc;
}

/* Output section - vertical */
.inspector-output {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  flex: 1;
}

.no-output {
  color: #64748b;
  font-size: 0.8rem;
}

.no-output p {
  margin: 0;
}

.output-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Data shape summary */
.data-shape-summary {
  display: flex;
  gap: 16px;
  background: rgba(255, 255, 255, 0.03);
  padding: 10px 12px;
  border-radius: 6px;
}

.shape-stat {
  font-size: 0.85rem;
  color: #94a3b8;
}

.shape-stat strong {
  color: #f8fafc;
  font-weight: 600;
}

.diagnostics-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 10px 12px;
}

.diagnostics-title {
  font-size: 0.78rem;
  color: #cbd5e1;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.diagnostics-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
}

.diagnostics-item {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
}

.diagnostics-key {
  font-size: 0.8rem;
  color: #94a3b8;
  font-family: 'SF Mono', Monaco, monospace;
}

.diagnostics-value {
  font-size: 0.8rem;
  color: #f8fafc;
  text-align: right;
  font-family: 'SF Mono', Monaco, monospace;
}

/* Output action buttons - vertical stack */
.output-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.output-actions .p-button {
  width: 100%;
  justify-content: flex-start;
}

.stats-more {
  font-size: 0.7rem;
  color: #64748b;
  font-style: italic;
}

/* Stats table - vertical */
.stats-table {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 0.7rem;
  max-height: 200px;
  overflow-y: auto;
}

.stat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 8px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 4px;
  align-items: center;
}

.stat-sample {
  color: #60a5fa;
  font-weight: 600;
  min-width: 70px;
}

.stat-value {
  color: #94a3b8;
  font-size: 0.7rem;
}

.stats-summary {
  margin-top: 8px;
  padding: 8px 10px;
  background: rgba(59, 130, 246, 0.1);
  border-radius: 4px;
  font-size: 0.8rem;
  color: #94a3b8;
}

.summary-label {
  font-weight: 600;
  color: #60a5fa;
  margin-right: 8px;
}

/* Scatter plot - compact */
.scatter-plot {
  background: #0f172a;
  border-radius: 6px;
  border: 1px solid #334155;
  padding: 8px;
  max-width: 200px;
}

.plot-svg {
  width: 100%;
  height: 80px;
}

.plot-legend {
  display: none;
}

/* Data info - horizontal */
.data-info {
  display: flex;
  gap: 16px;
  font-size: 0.8rem;
}

.info-row {
  display: flex;
  gap: 6px;
}

.info-label {
  color: #64748b;
}

.info-value {
  color: #e2e8f0;
  font-weight: 500;
}

/* PrimeVue component overrides for dark theme */
:deep(.p-dropdown),
:deep(.p-inputtext),
:deep(.p-inputnumber-input) {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}

:deep(.p-dropdown:hover),
:deep(.p-inputtext:hover),
:deep(.p-inputnumber-input:hover) {
  border-color: #475569;
}

:deep(.p-slider) {
  background: #334155;
}

:deep(.p-slider .p-slider-range) {
  background: #3b82f6;
}

:deep(.p-slider .p-slider-handle) {
  background: #3b82f6;
  border-color: #3b82f6;
}

/* Plot preview - clickable mini plot */
.plot-preview {
  background: #0f172a;
  border-radius: 6px;
  border: 1px solid #334155;
  padding: 6px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.plot-preview:hover {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.plot-svg-mini {
  width: 100px;
  height: 60px;
}

.view-hint {
  font-size: 0.65rem;
  color: #64748b;
  margin-top: 2px;
}

.plot-preview:hover .view-hint {
  color: #3b82f6;
}

/* Full plot modal */
.plot-modal-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.plot-svg-full {
  width: 100%;
  height: 400px;
  background: #0f172a;
  border-radius: 8px;
  border: 1px solid #334155;
}

.plot-svg-full .data-point {
  transition: r 0.15s;
}

.plot-svg-full .data-point:hover {
  r: 8;
}

.plot-info {
  display: flex;
  gap: 24px;
  justify-content: center;
  padding: 8px;
  background: #1e293b;
  border-radius: 6px;
}

.plot-info .info-item {
  color: #94a3b8;
  font-size: 0.85rem;
}

.plot-info .info-item strong {
  color: #f8fafc;
  font-weight: 600;
}

/* Dialog overrides for dark theme */
:deep(.p-dialog) {
  background: #1e293b;
  border: 1px solid #334155;
}

:deep(.p-dialog .p-dialog-header) {
  background: #1e293b;
  color: #f8fafc;
  border-bottom: 1px solid #334155;
}

:deep(.p-dialog .p-dialog-content) {
  background: #1e293b;
  color: #f8fafc;
}

:deep(.p-dialog .p-dialog-header-icon) {
  color: #94a3b8;
}

:deep(.p-dialog .p-dialog-header-icon:hover) {
  background: #334155;
  color: #f8fafc;
}

/* ============================================================================
   METADATA EDITOR SECTION
   ============================================================================ */

.inspector-metadata {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-top: 1px solid #334155;
}

.inspector-metadata.readonly {
  background: rgba(255, 255, 255, 0.02);
}

.metadata-accordion {
  margin-top: 8px;
}

/* Accordion dark theme overrides */
:deep(.metadata-accordion .p-accordion-header-link) {
  background: #0f172a;
  border-color: #334155;
  color: #e2e8f0;
  padding: 10px 12px;
  font-size: 0.85rem;
  font-weight: 500;
}

:deep(.metadata-accordion .p-accordion-header-link:hover) {
  background: #1e293b;
  border-color: #475569;
}

:deep(.metadata-accordion .p-accordion-header-link:focus) {
  box-shadow: none;
}

:deep(.metadata-accordion .p-accordion-content) {
  background: #0f172a;
  border-color: #334155;
  padding: 12px;
}

:deep(.metadata-accordion .p-accordion-header .p-accordion-toggle-icon) {
  color: #64748b;
}

.metadata-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.meta-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-field label {
  font-size: 0.75rem;
  font-weight: 500;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

/* Species entries */
.species-entry {
  background: rgba(59, 130, 246, 0.05);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.species-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.species-index {
  font-size: 0.7rem;
  font-weight: 600;
  color: #3b82f6;
  text-transform: uppercase;
}

.add-species-btn {
  width: 100%;
  margin-top: 4px;
}

/* Metadata preview (read-only) */
.metadata-preview {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.meta-preview-item {
  display: flex;
  gap: 8px;
  font-size: 0.8rem;
}

.meta-key {
  color: #64748b;
  flex-shrink: 0;
}

.meta-value {
  color: #e2e8f0;
  font-weight: 500;
}

.meta-value.processing-history {
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 0.75rem;
  color: #94a3b8;
}

.more-ops {
  color: #64748b;
  font-style: italic;
  margin-left: 4px;
}

/* Input styling within metadata */
.metadata-group :deep(.p-inputtext),
.metadata-group :deep(.p-inputnumber-input),
.metadata-group :deep(.p-dropdown) {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
  font-size: 0.85rem;
  padding: 8px 10px;
}

.metadata-group :deep(.p-inputtext:hover),
.metadata-group :deep(.p-inputnumber-input:hover),
.metadata-group :deep(.p-dropdown:hover) {
  border-color: #475569;
}

.metadata-group :deep(.p-inputtext:focus),
.metadata-group :deep(.p-inputnumber-input:focus),
.metadata-group :deep(.p-dropdown:focus) {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.metadata-group :deep(.p-dropdown-panel) {
  background: #1e293b;
  border-color: #334155;
}

.metadata-group :deep(.p-dropdown-item) {
  color: #e2e8f0;
  font-size: 0.85rem;
}

.metadata-group :deep(.p-dropdown-item:hover) {
  background: #334155;
}

.metadata-group :deep(.p-dropdown-item.p-highlight) {
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
}

/* ============================================================================
   NODE EXECUTION ERROR DISPLAY
   ============================================================================ */

.execution-error-banner {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  padding: 14px;
  margin: 0 16px 16px 16px;
}

.error-header {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.error-header i {
  color: #ef4444;
  font-size: 1.1rem;
  flex-shrink: 0;
  margin-top: 2px;
}

.error-content {
  flex: 1;
}

.error-content strong {
  display: block;
  color: #ef4444;
  font-size: 0.9rem;
  margin-bottom: 6px;
}

.error-content p {
  color: #f87171;
  font-size: 0.8rem;
  margin: 0;
  line-height: 1.4;
}

.error-details-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(239, 68, 68, 0.2);
}

.show-details-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  color: #ef4444;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  padding: 4px 0;
  transition: color 0.2s;
}

.show-details-btn:hover {
  color: #dc2626;
}

.show-details-btn i {
  font-size: 0.7rem;
}

.error-details-content {
  margin-top: 8px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 4px;
  padding: 10px;
  max-height: 200px;
  overflow-y: auto;
}

.error-details-content pre {
  margin: 0;
  font-family: 'SF Mono', Monaco, 'Courier New', monospace;
  font-size: 0.7rem;
  line-height: 1.4;
  color: #fca5a5;
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* ============================================================================
   VALIDATION ERROR STYLING
   ============================================================================ */

/* Validation error summary banner */
.validation-summary {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  margin-bottom: 12px;
}

.validation-summary i {
  color: #ef4444;
  font-size: 1rem;
  margin-top: 2px;
  flex-shrink: 0;
}

.validation-message {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.validation-message strong {
  color: #ef4444;
  font-size: 0.85rem;
}

.validation-message span {
  color: #f87171;
  font-size: 0.75rem;
}

/* Validation error list in summary */
.validation-error-list {
  margin: 8px 0 0 0;
  padding-left: 20px;
  list-style: none;
}

.validation-error-list li {
  margin: 4px 0;
  font-size: 0.8rem;
  color: #f87171;
  line-height: 1.4;
}

.validation-error-list li strong {
  color: #ef4444;
  font-weight: 600;
}

/* Field with validation error */
.field-error {
  position: relative;
}

.field-error label {
  color: #ef4444 !important;
}

/* Error message below field */
.param-error {
  display: block;
  color: #ef4444 !important;
  font-size: 0.7rem;
  font-weight: 500;
  margin-top: 4px;
  padding: 4px 6px;
  background: rgba(239, 68, 68, 0.1);
  border-left: 2px solid #ef4444;
  border-radius: 2px;
}

/* Red border for invalid inputs */
.field-error :deep(.p-inputtext),
.field-error :deep(.p-inputnumber-input),
.field-error :deep(.p-dropdown) {
  border-color: #ef4444 !important;
  background: rgba(239, 68, 68, 0.05);
}

.field-error :deep(.p-slider) {
  background: rgba(239, 68, 68, 0.2);
}

.field-error :deep(.p-slider .p-slider-range) {
  background: #ef4444;
}

.field-error :deep(.p-slider .p-slider-handle) {
  background: #ef4444;
  border-color: #ef4444;
}

/* ============================================================================
   SCIENTIFIC PARAMETER TOOLTIPS
   ============================================================================ */

/* Parameter label with info icon */
.param-label-with-info {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: space-between;
}

/* Info icon styling */
.param-info-icon {
  color: #3b82f6;
  font-size: 0.85rem;
  cursor: help;
  transition: color 0.2s;
  flex-shrink: 0;
}

.param-info-icon:hover {
  color: #60a5fa;
}

/* Scientific tooltip custom styling */
:deep(.scientific-tooltip) {
  max-width: 300px !important;
  font-size: 0.8rem !important;
  line-height: 1.5 !important;
  padding: 10px 12px !important;
  background: #1e293b !important;
  border: 1px solid #3b82f6 !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4) !important;
}

:deep(.scientific-tooltip .p-tooltip-text) {
  color: #e2e8f0 !important;
}

/* ============================================================================
   PREVIEW MODAL
   ============================================================================ */

.preview-container {
  display: flex;
  gap: 16px;
  min-height: 450px;
}

.preview-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.preview-pane h4 {
  margin: 0 0 12px 0;
  color: #3b82f6;
  font-size: 0.95rem;
  font-weight: 600;
}

.preview-content {
  flex: 1;
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  padding: 12px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.preview-content pre {
  margin: 0;
  font-family: 'SF Mono', Monaco, 'Courier New', monospace;
  font-size: 0.7rem;
  color: #e2e8f0;
  line-height: 1.4;
  overflow-x: auto;
}

.preview-divider {
  width: 1px;
  background: rgba(255, 255, 255, 0.15);
  flex-shrink: 0;
}

.loading-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: #64748b;
}

.loading-preview i {
  font-size: 2rem;
}

.loading-preview span {
  font-size: 0.9rem;
  font-weight: 500;
}

.data-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 8px;
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 4px;
  margin-bottom: 8px;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
}

.summary-label {
  color: #94a3b8;
  font-weight: 500;
}

.summary-value {
  color: #e2e8f0;
  font-weight: 600;
  font-family: 'SF Mono', Monaco, monospace;
}

/* Preview dialog custom styling */
:deep(.preview-dialog .p-dialog-content) {
  padding: 1rem;
}

:deep(.preview-dialog .p-dialog-header) {
  background: #1e293b;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

:deep(.preview-dialog .p-dialog-title) {
  color: #3b82f6;
  font-weight: 600;
}

/* ============================================================================
   ADVANCED PARAMETERS ACCORDION
   ============================================================================ */

.advanced-params-accordion {
  margin-top: 16px;
}

.advanced-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #64748b;
}

.advanced-header i {
  color: #64748b;
  font-size: 0.85rem;
}

.advanced-header .param-count {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 500;
  padding: 2px 6px;
  background: rgba(100, 116, 139, 0.1);
  border-radius: 10px;
}

:deep(.advanced-params-accordion .p-accordion-header-link) {
  background: rgba(100, 116, 139, 0.05);
  border: 1px solid rgba(100, 116, 139, 0.1);
  padding: 10px 14px;
  transition: all 0.2s;
}

:deep(.advanced-params-accordion .p-accordion-header-link:hover) {
  background: rgba(100, 116, 139, 0.1);
  border-color: rgba(100, 116, 139, 0.2);
}

:deep(.advanced-params-accordion .p-accordion-content) {
  padding: 16px;
  background: rgba(30, 41, 59, 0.3);
  border: 1px solid rgba(100, 116, 139, 0.1);
  border-top: none;
}

.params-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Required field indicator */
.required-indicator {
  color: #ef4444;
  margin-left: 2px;
  font-weight: bold;
}

/* No params message styling */
.no-params {
  display: block;
  text-align: center;
  padding: 24px;
  color: #94a3b8;
  font-size: 0.85rem;
  font-style: italic;
}

/* Metadata Modal Styles */
.metadata-modal-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-height: 60vh;
  overflow-y: auto;
}

.metadata-section {
  background: #1e293b;
  border-radius: 8px;
  padding: 16px;
  border: 1px solid #334155;
}

.metadata-section .section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 12px 0;
  color: #f1f5f9;
  font-size: 0.95rem;
  font-weight: 600;
}

.metadata-section .section-title i {
  color: #3b82f6;
}

.processing-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.timeline-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 12px;
  background: #0f172a;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
}

.step-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: #3b82f6;
  color: white;
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
}

.step-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.step-operation {
  color: #e2e8f0;
  font-weight: 500;
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 0.85rem;
}

.step-timestamp {
  color: #64748b;
  font-size: 0.75rem;
}

.step-params {
  margin-top: 4px;
}

.step-params {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.step-params code {
  display: block;
  background: #1e293b;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  color: #94a3b8;
  word-break: break-all;
}

.param-chip {
  display: inline-block;
  background: #1e293b;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  color: #94a3b8;
  font-family: 'SF Mono', 'Consolas', monospace;
}

.step-node-id {
  color: #64748b;
  font-size: 0.7rem;
  font-style: italic;
}

.step-shapes {
  display: flex;
  gap: 8px;
  margin-top: 2px;
}

.shape-badge {
  display: inline-block;
  background: #1e3a5f;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.65rem;
  color: #60a5fa;
  font-family: 'SF Mono', 'Consolas', monospace;
}

/* Instrument metadata grid */
.instrument-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.metadata-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  background: #0f172a;
  border-radius: 4px;
}

.item-label {
  color: #64748b;
  font-size: 0.7rem;
  text-transform: uppercase;
}

.item-value {
  color: #e2e8f0;
  font-size: 0.85rem;
}

.metadata-json {
  background: #0f172a;
  padding: 12px;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 0.8rem;
  overflow-x: auto;
  max-height: 300px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.metadata-modal-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 24px;
  color: #94a3b8;
  font-size: 0.9rem;
}

.metadata-modal-empty i {
  color: #3b82f6;
  font-size: 1.2rem;
}

.port-metadata-block {
  margin-top: 12px;
}

.port-metadata-block:first-child {
  margin-top: 0;
}

.port-metadata-title {
  margin: 0 0 6px 0;
  color: #cbd5e1;
  font-size: 0.85rem;
  font-weight: 600;
  font-family: ui-monospace, monospace;
}

.primary-port-tag {
  color: #3b82f6;
  font-weight: 400;
  font-size: 0.75rem;
}

/* Metadata dialog styling */
:deep(.metadata-dialog .p-dialog-content) {
  background: #0f172a;
  padding: 20px;
}

:deep(.metadata-dialog .p-dialog-header) {
  background: #1e293b;
  border-bottom: 1px solid #334155;
}
</style>
