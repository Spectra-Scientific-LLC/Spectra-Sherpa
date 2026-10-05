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
          <span class="node-icon">{{ NODE_ICONS[selectedNodeType] || "📦" }}</span>
          <div class="node-details">
            <h3>
              {{
                selectedNode ? selectedNode.label || getNodeLabel(selectedNode.type) : "Inspector"
              }}
            </h3>
            <span v-if="selectedNode" class="node-id" data-testid="inspector-node-instance">
              Instance ID: {{ selectedNode.id }}
            </span>
            <span
              v-if="selectedNode"
              class="node-type"
              data-testid="inspector-canonical-node-type"
              :title="selectedNode.type"
            >
              Canonical node: {{ selectedNode.type }}
            </span>
          </div>
        </div>
        <div class="header-actions">
          <Button
            icon="pi pi-sliders-h"
            class="p-button-sm inspector-action-btn"
            @click="openToRunTrials"
            title="Open to Run Trials"
            aria-label="Open to Run Trials"
          />
          <Button
            icon="pi pi-times"
            class="p-button-sm inspector-action-btn"
            @click="closeInspector"
            title="Close inspector"
          />
        </div>
      </div>

      <!-- Action buttons -->
      <div v-if="selectedNode" class="inspector-actions">
        <Button
          v-if="selectedNodeType === 'data.collection_load'"
          label="Configure data"
          icon="pi pi-database"
          class="p-button-sm p-button-outlined"
          :loading="configuringSheetData"
          :disabled="projectStore.currentProjectId === null || configuringSheetData"
          title="Choose files, target, and groups for this workflow sheet"
          data-testid="configure-sheet-data"
          @click="configureSheetData"
        />
        <Button
          label="Run Node"
          icon="pi pi-play"
          class="p-button-sm inspector-action-btn"
          :disabled="executionDisabled || hasValidationErrors"
          :title="
            executionDisabledReason ||
            (hasValidationErrors
              ? 'Resolve the parameter validation error before running'
              : 'Run this node and its dependencies')
          "
          @click="executeNode"
        />
        <Button
          label="Delete"
          icon="pi pi-trash"
          class="p-button-sm inspector-action-btn"
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
        <a
          v-if="selectedNodeHelpUrl"
          class="inspector-help-link"
          :href="selectedNodeHelpUrl"
          target="_blank"
          rel="noopener noreferrer"
          title="Learn about this node (opens in a new tab)"
          aria-label="Learn about this node (opens in a new tab)"
          data-testid="inspector-node-help"
        >
          <span aria-hidden="true">?</span>
        </a>
      </div>

      <!-- Node Execution Error Display -->
      <div v-if="selectedNode?.executionState?.status === 'error'" class="execution-error-banner">
        <div class="error-header">
          <i class="pi pi-times-circle"></i>
          <div class="error-content">
            <strong>Execution Failed</strong>
            <p>{{ selectedNode.executionState.error_message || "An unknown error occurred" }}</p>
          </div>
        </div>
        <div v-if="selectedNode.executionState.error_details" class="error-details-section">
          <button class="show-details-btn" @click="showErrorDetails = !showErrorDetails">
            <i :class="showErrorDetails ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"></i>
            {{ showErrorDetails ? "Hide" : "Show" }} Details
          </button>
          <div v-if="showErrorDetails" class="error-details-content">
            <pre>{{ selectedNode.executionState.error_details }}</pre>
          </div>
        </div>
      </div>

      <!-- Parameters section (vertical) -->
      <div v-if="selectedNode" class="inspector-params">
        <span class="section-label">Parameters</span>

        <div
          v-if="activeValidationGroupColumn"
          class="group-split-guidance"
          role="status"
          data-testid="group-split-guidance"
        >
          <i class="pi pi-shield" aria-hidden="true"></i>
          <div>
            <strong>Validation groups active: {{ activeValidationGroupColumn }}</strong>
            <span>
              Random, stratified, and sequential splits hold out whole groups. Kennard–Stone,
              DUPLEX, and SPXY select individual samples by spectral distance and cover the extremes
              across every group instead of holding one out.
            </span>
          </div>
        </div>

        <!-- Validation error summary -->
        <div v-if="hasValidationErrors" class="validation-summary">
          <i class="pi pi-exclamation-triangle"></i>
          <div class="validation-message">
            <strong
              >{{ validationErrors.length }} validation error{{
                validationErrors.length > 1 ? "s" : ""
              }}</strong
            >
            <span>Please fix the following errors:</span>
            <ul class="validation-error-list">
              <li v-for="error in validationErrors" :key="error.param_name">
                <strong>{{ error.param_name }}:</strong> {{ error.message }}
              </li>
            </ul>
          </div>
        </div>

        <div class="parameters-form">
          <!-- FILTER_SAMPLES node -->
          <template v-if="selectedNodeType === 'data.filter_samples'">
            <div class="filter-samples-panel">
              <div v-if="!filterHasInput" class="filter-empty-state">
                <i class="pi pi-filter" aria-hidden="true"></i>
                <strong>Connect a dataset first</strong>
                <span>Filter choices are populated from the dataset connected to this node.</span>
              </div>

              <template v-else>
                <div class="filter-dataset-summary">
                  <div>
                    <span class="summary-kicker">Dataset</span>
                    <strong
                      >{{ filterSampleCount }} sample{{
                        filterSampleCount === 1 ? "" : "s"
                      }}</strong
                    >
                  </div>
                  <div v-if="filterFeatureCount !== null">
                    <span class="summary-kicker">Variables</span>
                    <strong>{{ filterFeatureCount }}</strong>
                  </div>
                </div>
                <div v-if="filterMatrixPreviewOnly" class="filter-scope-warning">
                  <i class="pi pi-info-circle" aria-hidden="true"></i>
                  <span>
                    This panel has only a saved preview of the upstream matrix. Index filters are
                    still available; intensity filters need a fresh run with the full matrix in
                    memory.
                  </span>
                </div>

                <div class="filter-mode-grid" aria-label="Filter method">
                  <button
                    v-for="mode in sampleFilterModeOptions"
                    :key="mode.value"
                    type="button"
                    class="filter-mode-card"
                    :class="{ active: localParams.field === mode.value }"
                    :disabled="!mode.enabled"
                    @click="setSampleFilterField(mode.value)"
                  >
                    <i :class="mode.icon" aria-hidden="true"></i>
                    <span class="mode-label">{{ mode.label }}</span>
                    <span class="mode-hint">{{ mode.hint }}</span>
                  </button>
                </div>

                <div v-if="localParams.field === 'sample_index'" class="filter-rule-card">
                  <div class="field">
                    <label>Rows to keep</label>
                    <InputText
                      v-model="localParams.pattern"
                      :placeholder="filterSampleCount > 0 ? `1-${filterSampleCount}` : '1-10, 15'"
                      @update:model-value="onIndexPatternChange"
                    />
                    <small class="param-hint">
                      Use row numbers and ranges, such as 1-10, 15, 20-25.
                    </small>
                  </div>
                  <div class="filter-quick-actions">
                    <Button
                      label="All"
                      class="p-button-sm p-button-text"
                      @click="setIndexRange('all')"
                    />
                    <Button
                      label="First 10"
                      class="p-button-sm p-button-text"
                      @click="setIndexRange('first10')"
                    />
                    <Button
                      label="Last 10"
                      class="p-button-sm p-button-text"
                      @click="setIndexRange('last10')"
                    />
                  </div>
                </div>

                <div v-else-if="localParams.field === 'intensity'" class="filter-rule-card">
                  <div class="field">
                    <label>Intensity metric</label>
                    <Dropdown
                      v-model="localParams.intensity_metric"
                      :options="intensityMetricOptions"
                      optionLabel="label"
                      optionValue="value"
                      appendTo="body"
                      @change="onIntensityMetricChange"
                    />
                  </div>
                  <div class="field">
                    <label>Condition</label>
                    <Dropdown
                      v-model="localParams.intensity_operator"
                      :options="intensityOperatorOptions"
                      optionLabel="label"
                      optionValue="value"
                      appendTo="body"
                      @change="emitParams"
                    />
                  </div>
                  <div class="field">
                    <label for="intensity-threshold">Threshold</label>
                    <ScientificNumberInput
                      id="intensity-threshold"
                      v-model="localParams.intensity_threshold"
                      @update:model-value="emitParams"
                    />
                    <small class="param-hint">
                      {{ intensitySummaryText }}
                    </small>
                  </div>
                  <div v-if="localParams.intensity_operator === 'between'" class="field">
                    <label for="intensity-upper-threshold">Upper threshold</label>
                    <ScientificNumberInput
                      id="intensity-upper-threshold"
                      v-model="localParams.intensity_upper_threshold"
                      @update:model-value="emitParams"
                    />
                  </div>
                </div>

                <div v-else class="filter-rule-card">
                  <div v-if="localParams.field === 'sample_table'" class="field">
                    <label>Metadata column</label>
                    <Dropdown
                      v-model="localParams.sample_table_column"
                      :options="sampleTableColumnOptions"
                      optionLabel="label"
                      optionValue="value"
                      appendTo="body"
                      @change="onSampleTableColumnChange"
                    />
                  </div>

                  <div class="field">
                    <label>{{ categoricalFilterLabel }}</label>
                    <div class="filter-value-toolbar">
                      <InputText
                        v-model="filterValueSearch"
                        class="filter-value-search"
                        placeholder="Search available values"
                      />
                      <Button
                        label="All"
                        class="p-button-sm p-button-text"
                        @click="selectAllFilterValues"
                      />
                      <Button
                        label="None"
                        class="p-button-sm p-button-text"
                        @click="clearFilterValues"
                      />
                    </div>
                    <div class="filter-value-list">
                      <label
                        v-for="option in visibleFilterValueOptions"
                        :key="option.value"
                        class="filter-value-row"
                      >
                        <Checkbox
                          :binary="true"
                          :model-value="isFilterValueSelected(option.value)"
                          @change="toggleFilterValue(option.value)"
                        />
                        <span>{{ option.label }}</span>
                      </label>
                    </div>
                    <small class="param-hint">
                      Choices are populated from the connected dataset.
                    </small>
                    <small
                      v-if="filterValueOptions.length > visibleFilterValueOptions.length"
                      class="param-hint"
                    >
                      Showing {{ visibleFilterValueOptions.length }} of
                      {{ filterValueOptions.length }} values. Search to narrow the list.
                    </small>
                  </div>
                </div>

                <div class="filter-preview" :class="{ warning: filterPreview.empty }">
                  <div class="filter-preview-main">
                    <i
                      :class="
                        filterPreview.empty ? 'pi pi-exclamation-triangle' : 'pi pi-check-circle'
                      "
                      aria-hidden="true"
                    ></i>
                    <strong>{{ filterPreview.summary }}</strong>
                  </div>
                  <div v-if="filterPreview.keptLabels.length" class="filter-preview-list">
                    <span>Kept:</span>
                    <em>{{ filterPreview.keptLabels.join(", ") }}</em>
                  </div>
                  <div v-if="filterPreview.excludedLabels.length" class="filter-preview-list muted">
                    <span>Excluded:</span>
                    <em>{{ filterPreview.excludedLabels.join(", ") }}</em>
                  </div>
                </div>

                <Accordion class="advanced-params-accordion">
                  <AccordionTab>
                    <template #header>
                      <span class="advanced-header">
                        <i class="pi pi-cog"></i>
                        Advanced Settings
                      </span>
                    </template>

                    <div class="params-section">
                      <div class="field checkbox-row">
                        <Checkbox
                          v-model="localParams.invert"
                          :binary="true"
                          inputId="filter_invert"
                          @change="emitParams"
                        />
                        <label for="filter_invert">Invert selection</label>
                      </div>
                      <div class="field">
                        <label>Pattern</label>
                        <InputText
                          v-model="localParams.pattern"
                          placeholder="Optional text, range, or regular expression"
                          @update:model-value="onAdvancedPatternChange"
                        />
                      </div>
                      <div
                        v-if="
                          localParams.field !== 'sample_index' && localParams.field !== 'intensity'
                        "
                        class="field"
                      >
                        <label>Match mode</label>
                        <Dropdown
                          v-model="localParams.match_mode"
                          :options="sampleFilterMatchModeOptions"
                          optionLabel="label"
                          optionValue="value"
                          appendTo="body"
                          @change="onAdvancedPatternChange"
                        />
                      </div>
                      <div
                        v-if="
                          localParams.field !== 'sample_index' && localParams.field !== 'intensity'
                        "
                        class="field checkbox-row"
                      >
                        <Checkbox
                          v-model="localParams.case_sensitive"
                          :binary="true"
                          inputId="filter_case_sensitive"
                          @change="emitParams"
                        />
                        <label for="filter_case_sensitive">Case sensitive</label>
                      </div>
                      <div class="field checkbox-row">
                        <Checkbox
                          v-model="localParams.allow_empty"
                          :binary="true"
                          inputId="filter_allow_empty"
                          @change="emitParams"
                        />
                        <label for="filter_allow_empty">Allow empty result</label>
                      </div>
                    </div>
                  </AccordionTab>
                </Accordion>
              </template>
            </div>
          </template>

          <!-- NORMALIZE uses the backend's method and scoped scale/SNV parameters. -->

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
                    value:
                      'Savitzky-Golay filter window size. Larger values produce smoother spectra but may remove fine features. Must be odd number. Typical range: 5-21.',
                    showDelay: 300,
                    hideDelay: 100,
                    class: 'scientific-tooltip',
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
                {{ getParamError("size") }}
              </small>
            </div>
            <div class="field" :class="{ 'field-error': getParamError('order') }">
              <label class="param-label-with-info">
                Polynomial Order: {{ localParams.order }}
                <i
                  class="pi pi-info-circle param-info-icon"
                  v-tooltip.right="{
                    value:
                      'Polynomial degree used to fit data within window. Higher order fits data more closely but may amplify noise. Typically 2-4 for spectral data.',
                    showDelay: 300,
                    hideDelay: 100,
                    class: 'scientific-tooltip',
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
                {{ getParamError("order") }}
              </small>
            </div>
          </template>

          <!-- PCA, PLS, and MCR nodes now use metadata-driven rendering (removed hardcoded templates) -->

          <!-- PLOT node -->
          <template v-else-if="selectedNodeType === 'output.plot'">
            <div v-if="tablePlotColumnOptions.length" class="field">
              <label>Column (vs. row index)</label>
              <Dropdown
                v-model="localParams.plot_key"
                :options="tablePlotColumnOptions"
                optionLabel="label"
                optionValue="value"
                @change="emitParams"
              />
              <small>Missing values are gaps; row indices are preserved.</small>
            </div>
            <div v-else-if="showPlotAxisParameters" class="field">
              <label>X-Axis</label>
              <Dropdown
                v-model="localParams.x_axis"
                :options="axisOptions"
                optionLabel="label"
                optionValue="value"
                @change="emitParams"
              />
            </div>
            <div v-if="!tablePlotColumnOptions.length && showPlotAxisParameters" class="field">
              <label>Y-Axis</label>
              <Dropdown
                v-model="localParams.y_axis"
                :options="axisOptions"
                optionLabel="label"
                optionValue="value"
                @change="emitParams"
              />
            </div>
            <span v-if="!tablePlotColumnOptions.length && !showPlotAxisParameters" class="no-params">No adjustable parameters</span>
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
              <small class="param-hint"> Number of sample rows to return in statistics </small>
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
                <label :for="`parameter-${param.name}`">
                  {{ param.label }}
                  <span v-if="param.required" class="required-indicator">*</span>
                </label>

                <!-- Number input -->
                <template v-if="param.param_type === 'number'">
                  <ScientificNumberInput
                    v-model="localParams[param.name]"
                    :min="param.min_value"
                    :max="param.max_value"
                    :step="param.step"
                    :id="`parameter-${param.name}`"
                    :required="param.required"
                    @update:model-value="emitParams"
                  />
                </template>

                <!-- Boolean checkbox -->
                <template v-else-if="param.param_type === 'boolean'">
                  <Checkbox v-model="localParams[param.name]" :binary="true" @change="emitParams" />
                </template>

                <!-- Select dropdown -->
                <template v-else-if="param.param_type === 'select' && param.options">
                  <Dropdown
                    v-model="localParams[param.name]"
                    :options="parameterOptions(param)"
                    optionLabel="label"
                    optionValue="value"
                    optionDisabled="disabled"
                    :placeholder="`Select ${param.label.toLowerCase()}`"
                    @change="emitParams"
                  />
                </template>

                <!-- Exact string list (comma-separated, or dropdown when values are known) -->
                <template v-else-if="param.param_type === 'string_list'">
                  <MultiSelect
                    v-if="selectedNodeType === 'selection.select_columns' && param.name === 'columns' && selectableFeatureColumns.length"
                    v-model="localParams[param.name]"
                    :options="selectableFeatureColumns"
                    filter
                    :maxSelectedLabels="0"
                    selectedItemsLabel="{0} columns selected"
                    placeholder="Select feature columns"
                    @change="emitParams"
                  />
                  <MultiSelect
                    v-else-if="param.name === 'held_out_groups' && groupValuesFromInputs"
                    v-model="localParams[param.name]"
                    :options="groupValuesFromInputs"
                    placeholder="Select groups to hold out"
                    display="chip"
                    @change="emitParams"
                  />
                  <InputText
                    v-else
                    :model-value="stringListText(localParams[param.name])"
                    :placeholder="param.description"
                    @update:model-value="updateStringList(param.name, $event)"
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
                <small
                  v-if="param.description && !getParamError(param.name)"
                  class="param-hint"
                  :class="{
                    'param-warning':
                      param.name === 'held_out_groups' && isGroupHoldoutMissingSelection,
                  }"
                >
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
                    <label :for="`parameter-${param.name}`">
                      {{ param.label }}
                      <span v-if="param.required" class="required-indicator">*</span>
                    </label>

                    <!-- Number input -->
                    <template v-if="param.param_type === 'number'">
                      <ScientificNumberInput
                        v-model="localParams[param.name]"
                        :min="param.min_value"
                        :max="param.max_value"
                        :step="param.step"
                        :id="`parameter-${param.name}`"
                        :required="param.required"
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
                        :options="parameterOptions(param)"
                        optionLabel="label"
                        optionValue="value"
                        optionDisabled="disabled"
                        :placeholder="`Select ${param.label.toLowerCase()}`"
                        @change="emitParams"
                      />
                    </template>

                    <!-- Exact string list (comma-separated, or dropdown when values are known) -->
                    <template v-else-if="param.param_type === 'string_list'">
                      <MultiSelect
                        v-if="selectedNodeType === 'selection.select_columns' && param.name === 'columns' && selectableFeatureColumns.length"
                        v-model="localParams[param.name]"
                        :options="selectableFeatureColumns"
                        filter
                        :maxSelectedLabels="0"
                        selectedItemsLabel="{0} columns selected"
                        placeholder="Select feature columns"
                        @change="emitParams"
                      />
                      <MultiSelect
                        v-else-if="param.name === 'held_out_groups' && groupValuesFromInputs"
                        v-model="localParams[param.name]"
                        :options="groupValuesFromInputs"
                        placeholder="Select groups to hold out"
                        display="chip"
                        @change="emitParams"
                      />
                      <InputText
                        v-else
                        :model-value="stringListText(localParams[param.name])"
                        :placeholder="param.description"
                        @update:model-value="updateStringList(param.name, $event)"
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
                    <small
                      v-if="param.description && !getParamError(param.name)"
                      class="param-hint"
                      :class="{
                        'param-warning':
                          param.name === 'held_out_groups' && isGroupHoldoutMissingSelection,
                      }"
                    >
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
                <label :for="`legacy-parameter-${key}`">{{ formatParamLabel(key) }}</label>
                <template v-if="typeof value === 'boolean'">
                  <Checkbox :input-id="`legacy-parameter-${key}`" v-model="localParams[key]" :binary="true" @change="emitParams" />
                </template>
                <template v-else-if="typeof value === 'number'">
                  <ScientificNumberInput :id="`legacy-parameter-${key}`" v-model="localParams[key]" @update:model-value="emitParams" />
                </template>
                <template v-else>
                  <InputText :id="`legacy-parameter-${key}`" v-model="localParams[key]" @update:model-value="emitParams" />
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
          <div v-if="presentationOptions.length > 1" class="field">
            <label for="scientific-presentation">Scientific result</label>
            <Dropdown
              id="scientific-presentation"
              v-model="selectedPresentationId"
              :options="presentationOptions"
              optionLabel="label"
              optionValue="value"
              class="scientific-result-dropdown"
              panelClass="scientific-result-dropdown-panel"
              appendTo="body"
            />
          </div>
          <div v-if="presentationError" class="diagnostics-card diagnostics-card--error">
            <span class="diagnostics-title">Scientific result unavailable</span>
            <p>{{ presentationError }}</p>
          </div>
          <div
            v-if="executedGroupedSplit"
            class="diagnostics-card grouped-split-evidence"
            data-testid="grouped-split-evidence"
          >
            <span class="diagnostics-title">Whole-group holdout</span>
            <p>
              Held out {{ executedGroupedSplit.heldOutGroups.length }} of
              {{ executedGroupedSplit.nGroups }} groups:
              <strong>{{ executedGroupedSplit.heldOutGroups.join(", ") }}</strong>
            </p>
            <span class="group-split-method">
              {{ formatParamLabel(executedGroupedSplit.method) }} split; no held-out group is in
              training.
            </span>
            <span
              v-if="executedGroupedSplit.digest"
              class="group-split-digest"
              :title="`Exact split-plan SHA-256: ${executedGroupedSplit.digest}`"
            >
              Verified split plan
            </span>
          </div>
          <div
            v-if="selectedNodeType === 'output.export' && preparedExportSummary"
            class="diagnostics-card"
          >
            <span class="diagnostics-title">Prepared Export</span>
            <div class="diagnostics-grid">
              <div class="diagnostics-item">
                <span class="diagnostics-key">File</span>
                <span class="diagnostics-value">{{ preparedExportSummary.filename }}</span>
              </div>
              <div class="diagnostics-item">
                <span class="diagnostics-key">Format</span>
                <span class="diagnostics-value">{{ preparedExportSummary.format }}</span>
              </div>
              <div class="diagnostics-item">
                <span class="diagnostics-key">Shape</span>
                <span class="diagnostics-value">{{ preparedExportSummary.shape }}</span>
              </div>
              <div class="diagnostics-item">
                <span class="diagnostics-key">Bytes</span>
                <span class="diagnostics-value">{{ preparedExportSummary.byteLength }}</span>
              </div>
              <div class="diagnostics-item">
                <span class="diagnostics-key">SHA-256</span>
                <span class="diagnostics-value" :title="preparedExportSummary.digest">
                  {{ preparedExportSummary.digest.slice(0, 16) }}…
                </span>
              </div>
            </div>
          </div>
          <RepeatedValidationSummary :record="asObject(selectedPortOutput?.value)" />
          <!-- Data shape summary - always show for any output -->
          <div v-if="selectedNodeType !== 'output.export'" class="data-shape-summary">
            <template v-if="selectedResultDimensions.length">
              <span
                v-for="dimension in selectedResultDimensions"
                :key="dimension.role"
                class="shape-stat"
              >
                <strong>{{ dimension.size }}</strong> {{ formatDimensionRole(dimension.role) }}
              </span>
            </template>
            <span v-else class="shape-stat">{{ selectedResultFormLabel }}</span>
          </div>

          <div v-if="selectedOutputPreviewNotice" class="persisted-preview-notice">
            <i class="pi pi-info-circle" aria-hidden="true"></i>
            <span>{{ selectedOutputPreviewNotice }}</span>
          </div>

          <div v-if="selectedResultEntries.length > 0" class="diagnostics-card">
            <span class="diagnostics-title">Selected Result Summary</span>
            <div class="diagnostics-grid">
              <div v-for="entry in selectedResultEntries" :key="entry.key" class="diagnostics-item">
                <span class="diagnostics-key">{{ entry.label }}</span>
                <span class="diagnostics-value" :title="entry.detail || entry.displayValue">
                  {{ entry.displayValue }}
                </span>
              </div>
            </div>
          </div>

          <PeakExecutionDetails
            v-if="selectedNodeType === 'analysis.peak_finding'"
            :diagnostics="outputMetadata.diagnostics"
          />

          <div v-if="diagnosticEntries.length > 0" class="diagnostics-card">
            <span class="diagnostics-title">Scientific Diagnostics</span>
            <div class="diagnostics-grid">
              <div v-for="entry in diagnosticEntries" :key="entry.key" class="diagnostics-item">
                <span class="diagnostics-key">{{ entry.label }}</span>
                <span class="diagnostics-value" :title="entry.detail || entry.displayValue">
                  {{ entry.displayValue }}
                </span>
              </div>
            </div>
          </div>

          <!-- Universal Quick Plot and View Data buttons -->
          <div class="output-actions">
            <Button
              v-if="selectedNodeType === 'output.export'"
              icon="pi pi-download"
              label="Download Prepared File"
              class="p-button-sm p-button-outlined"
              :disabled="!preparedExportArtifact"
              @click="downloadPreparedExport"
            />
            <Button
              v-if="
                selectedNodeType !== 'output.export' &&
                selectedOutputHasData &&
                selectedOutputSupportsPlot
              "
              icon="pi pi-chart-line"
              label="Quick Plot"
              class="p-button-sm p-button-outlined"
              @click="showQuickPlotModal = true"
            />
            <Button
              v-if="
                selectedNodeType !== 'output.export' &&
                selectedOutputHasData &&
                selectedOutputSupportsTable
              "
              icon="pi pi-table"
              label="View Data"
              class="p-button-sm p-button-outlined"
              @click="showDataTableModal = true"
            />
            <span
              v-if="
                selectedPresentation && !selectedOutputSupportsPlot && !selectedOutputSupportsTable
              "
              class="no-params"
            >
              {{ selectedResultNoninteractiveNote }}
            </span>
          </div>

          <!-- Statistics output (compact inline) -->
          <template v-if="selectedNodeType === 'stats.summary' && Array.isArray(nodeOutput.data)">
            <!-- PeakFinding stats -->
            <template v-if="isPeakFindingStats">
              <div class="stats-table" style="max-height: 200px; overflow-y: auto">
                <div v-for="(stat, index) in outputStatsRows" :key="index" class="stat-row">
                  <span class="stat-sample">Peak {{ stat.peak }}</span>
                  <span class="stat-value"
                    >pos:
                    {{ typeof stat.position === "number" ? stat.position.toFixed(1) : "—" }}</span
                  >
                  <span class="stat-value"
                    >σ: {{ typeof stat.pos_std === "number" ? stat.pos_std.toFixed(2) : "—" }}</span
                  >
                  <span class="stat-value"
                    >h: {{ typeof stat.height === "number" ? stat.height.toFixed(4) : "—" }}</span
                  >
                  <span class="stat-value">{{ stat.detected || "—" }}</span>
                </div>
              </div>
              <div v-if="outputMetadata.summary" class="stats-summary">
                <span class="summary-label">Peaks:</span>
                <span
                  >{{ outputMetadata.summary?.n_peaks ?? 0 }} consensus peaks from
                  {{ outputMetadata.summary?.n_samples ?? 0 }} spectra</span
                >
              </div>
            </template>
            <!-- Standard spectral/array stats -->
            <template v-else>
              <div class="stats-table" style="max-height: 200px; overflow-y: auto">
                <div v-for="(stat, index) in outputStatsRows" :key="index" class="stat-row">
                  <span class="stat-sample">{{ statsRowLabel(stat, index) }}</span>
                  <span class="stat-value"
                    >μ: {{ typeof stat.mean === "number" ? stat.mean.toFixed(4) : "—" }}</span
                  >
                  <span class="stat-value"
                    >σ: {{ typeof stat.std === "number" ? stat.std.toFixed(4) : "—" }}</span
                  >
                </div>
              </div>
              <div v-if="outputMetadata.summary" class="stats-summary">
                <span class="summary-label">Overall:</span>
                <span>{{ statsOverallSummary }}</span>
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
                <label for="metadata-conditions-temperature_c">Temperature (°C)</label>
                <ScientificNumberInput
                  id="metadata-conditions-temperature_c"
                  v-model="localMetadata.conditions.temperature_c"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label for="metadata-conditions-pressure_atm">Pressure (atm)</label>
                <ScientificNumberInput
                  id="metadata-conditions-pressure_atm"
                  v-model="localMetadata.conditions.pressure_atm"
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
                <label for="metadata-conditions-ambient_humidity_percent">Humidity (%RH)</label>
                <ScientificNumberInput
                  id="metadata-conditions-ambient_humidity_percent"
                  v-model="localMetadata.conditions.ambient_humidity_percent"
                  :min="0"
                  :max="100"
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
                <label for="metadata-acquisition-resolution_cm">Resolution (cm⁻¹)</label>
                <ScientificNumberInput
                  id="metadata-acquisition-resolution_cm"
                  v-model="localMetadata.acquisition.resolution_cm"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label for="metadata-acquisition-n_scans">Number of Scans</label>
                <ScientificNumberInput
                  id="metadata-acquisition-n_scans"
                  integer
                  v-model="localMetadata.acquisition.n_scans"
                  :min="1"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label for="metadata-acquisition-wavenumber_min">Wavenumber Min (cm⁻¹)</label>
                <ScientificNumberInput
                  id="metadata-acquisition-wavenumber_min"
                  v-model="localMetadata.acquisition.wavenumber_min"
                  @update:model-value="emitMetadata"
                />
              </div>
              <div class="meta-field">
                <label for="metadata-acquisition-wavenumber_max">Wavenumber Max (cm⁻¹)</label>
                <ScientificNumberInput
                  id="metadata-acquisition-wavenumber_max"
                  v-model="localMetadata.acquisition.wavenumber_max"
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
                <label for="metadata-cell-pathlength_mm">Pathlength (mm)</label>
                <ScientificNumberInput
                  id="metadata-cell-pathlength_mm"
                  v-model="localMetadata.cell.pathlength_mm"
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
                <label for="metadata-cell-cell_volume_ml">Cell Volume (mL)</label>
                <ScientificNumberInput
                  id="metadata-cell-cell_volume_ml"
                  v-model="localMetadata.cell.cell_volume_ml"
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
      <div
        v-else-if="selectedNode && spectraMetadata && selectedResultShowsMetadata"
        class="inspector-metadata readonly"
      >
        <span class="section-label">Metadata (read-only)</span>
        <div class="metadata-preview">
          <div v-if="spectraSpeciesNames.length" class="meta-preview-item">
            <span class="meta-key">Species:</span>
            <span class="meta-value">
              {{ spectraSpeciesNames.join(", ") }}
            </span>
          </div>
          <div
            v-if="outputMetadata.provenance?.source_type || spectraMetadata.provenance?.source_type"
            class="meta-preview-item"
          >
            <span class="meta-key">Source:</span>
            <span class="meta-value">{{
              outputMetadata.provenance?.source_type || spectraMetadata.provenance?.source_type
            }}</span>
          </div>
          <div v-if="processingOperations.length" class="meta-preview-item">
            <span class="meta-key">Processing:</span>
            <span class="meta-value processing-history">
              {{ processingOperations.slice(-3).join(" → ") }}
              <span v-if="processingOperations.length > 3" class="more-ops">
                (+{{ processingOperations.length - 3 }} more)
              </span>
            </span>
          </div>
          <div v-if="outputMetadata.processing_history?.length" class="meta-preview-item">
            <span class="meta-key">Steps:</span>
            <span class="meta-value"
              >{{ outputMetadata.processing_history.length }} operations applied</span
            >
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
    :node-output="selectedNodeOutput"
    :node-type="selectedNode?.type || ''"
    :node-label="selectedNode ? getNodeLabel(selectedNode.type) : 'Node'"
    :node-input="inputConnections.length > 0 ? inputConnections[0].data : undefined"
    :node-inputs="quickPlotInputs"
  />

  <!-- Data Table Modal (Raw data viewer) -->
  <DataTableModal
    v-model="showDataTableModal"
    :node-output="selectedNodeOutput"
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
              <span class="summary-value">{{
                previewPayloadSampleCount(previewData.original)
              }}</span>
            </div>
            <div v-if="previewData.original.data[0]?.wavenumber" class="summary-item">
              <span class="summary-label">Points:</span>
              <span class="summary-value">{{
                previewPayloadFeatureCount(previewData.original)
              }}</span>
            </div>
            <div v-if="previewData.original.data[0]?.wavenumber" class="summary-item">
              <span class="summary-label">Range:</span>
              <span class="summary-value">
                {{ previewPayloadRange(previewData.original) }}
              </span>
            </div>
          </div>
          <pre v-if="previewData.original"
            >{{ JSON.stringify(previewData.original, null, 2).substring(0, 800) }}...</pre
          >
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
                <span class="summary-value">{{
                  previewPayloadSampleCount(previewData.processed)
                }}</span>
              </div>
              <div v-if="previewData.processed.data[0]?.wavenumber" class="summary-item">
                <span class="summary-label">Points:</span>
                <span class="summary-value">{{
                  previewPayloadFeatureCount(previewData.processed)
                }}</span>
              </div>
              <div v-if="previewData.processed.data[0]?.wavenumber" class="summary-item">
                <span class="summary-label">Range:</span>
                <span class="summary-value">
                  {{ previewPayloadRange(previewData.processed) }}
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
      <div
        v-if="outputMetadata.instrument_metadata || outputMetadata.acquisition_params"
        class="metadata-section"
      >
        <h4 class="section-title">
          <i class="pi pi-cog"></i>
          Instrument &amp; Acquisition
        </h4>
        <div class="instrument-grid">
          <template v-if="outputMetadata.instrument_metadata">
            <div
              v-for="(value, key) in outputMetadata.instrument_metadata"
              :key="'inst-' + key"
              class="metadata-item"
            >
              <span class="item-label">{{ formatLabel(String(key)) }}:</span>
              <span class="item-value">{{ value }}</span>
            </div>
          </template>
          <template v-if="outputMetadata.acquisition_params">
            <div
              v-for="(value, key) in outputMetadata.acquisition_params"
              :key="'acq-' + key"
              class="metadata-item"
            >
              <span class="item-label">{{ formatLabel(String(key)) }}:</span>
              <span class="item-value">{{ formatAcquisitionValue(String(key), value) }}</span>
            </div>
          </template>
        </div>
      </div>

      <!-- Processing History Section -->
      <div
        v-if="outputMetadata.processing_history?.length || processingOperations.length"
        class="metadata-section"
      >
        <h4 class="section-title">
          <i class="pi pi-history"></i>
          Processing History
        </h4>
        <div class="processing-timeline">
          <div v-for="(step, index) in sortedProcessingHistory" :key="index" class="timeline-item">
            <span class="step-number">{{ index + 1 }}</span>
            <div class="step-content">
              <span class="step-operation">{{
                typeof step === "string" ? step : step.op_id || step.operation || "Unknown"
              }}</span>
              <span v-if="typeof step === 'object' && step.timestamp" class="step-timestamp">
                {{ formatStepTimestamp(step.timestamp, index) }}
              </span>
              <div v-if="typeof step === 'object' && step.node_id" class="step-node-id">
                Node: {{ step.node_id }}
              </div>
              <div
                v-if="
                  typeof step === 'object' &&
                  step.parameters &&
                  Object.keys(step.parameters).length > 0
                "
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
                <span v-if="step.input_shape" class="shape-badge"
                  >In: {{ step.input_shape?.join("×") }}</span
                >
                <span v-if="step.output_shape" class="shape-badge"
                  >Out: {{ step.output_shape?.join("×") }}</span
                >
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
      <div
        v-if="nodeOutput.ports && Object.keys(nodeOutput.ports).length > 0"
        class="metadata-section"
      >
        <h4 class="section-title">
          <i class="pi pi-sitemap"></i>
          Output Ports
        </h4>
        <div
          v-for="(port, portName) in nodeOutput.ports"
          :key="String(portName)"
          class="port-metadata-block"
        >
          <h5 class="port-metadata-title">
            {{ portName
            }}<span v-if="portName === nodeOutput.primary_port" class="primary-port-tag">
              (primary)</span
            >
          </h5>
          <pre class="metadata-json">{{ JSON.stringify(port.metadata ?? {}, null, 2) }}</pre>
        </div>
      </div>
    </div>
  </Dialog>
</template>

<script setup lang="ts">
import RepeatedValidationSummary from "@/components/results/RepeatedValidationSummary.vue";
/* eslint-disable @typescript-eslint/no-explicit-any -- inspector renders heterogeneous node params and outputs across the full DAG surface. */
import { toRaw, ref, computed, watch, onMounted, onUnmounted } from "vue";
import Accordion from "primevue/accordion";
import AccordionTab from "primevue/accordiontab";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import PeakExecutionDetails from "@/components/common/PeakExecutionDetails.vue";
import ScientificNumberInput from "@/components/common/ScientificNumberInput.vue";
import InputText from "primevue/inputtext";
import MultiSelect from "primevue/multiselect";
import { featureColumnOptions } from "@/utils/featureColumnOptions";
import Slider from "primevue/slider";
import { useToast } from "primevue/usetoast";
import { useRouter } from "vue-router";
import { useWorkflowStore, type WorkflowNode } from "@/stores/workflow";
import { useProjectStore } from "@/stores/project";
import QuickPlotModal from "./modals/QuickPlotModal.vue";
import DataTableModal from "./modals/DataTableModal.vue";
import type { NodeOutput, PortOutput } from "@/utils/nodeOutput";
import type { ScientificValueDescriptor } from "@/stores/workflow-types";
import type { NodeParameterMetadata } from "@/types";
import { getErrorMessage } from "@/utils/errors";
import { resolveNodeHelpUrl } from "@/utils/nodeHelp";
import { buildDiagnosticEntries } from "@/utils/diagnostics";
import { primaryClassificationMetricSummary } from "@/utils/classificationMetrics";
import { t2QDiagnosticRows } from "@/utils/scientificPlots";
import { downloadExportArtifact, extractExportArtifact } from "@/utils/exportArtifact";
import {
  groupColumnFromInputs,
  groupedSplitSummary,
  splitMethodOptions,
  splitMethodTargetConflict,
} from "@/utils/groupedSplit";
import {
  availableScientificPresentations,
  presentationSupports,
  presentationResolutionError,
  projectScientificPresentation,
  resolveScientificPresentation,
} from "@/utils/scientificPresentation";

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

interface StatsRow extends Record<string, unknown> {
  sample?: string | number;
  mean?: number;
  std?: number;
  min?: number;
  max?: number;
  pc?: number;
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
  n_observations?: number;
  n_components?: number;
  total_variance_explained?: number;
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
  toPort?: string; // Input port name for multi-input nodes (e.g., "X", "y")
  data?: NodeOutput | PortOutput | null;
}

interface Props {
  selectedNode: WorkflowNode | null;
  nodeOutput: NodeOutput | null;
  inputConnections?: InputConnection[];
  isOpen?: boolean;
  executionDisabled?: boolean;
  executionDisabledReason?: string;
}

const props = withDefaults(defineProps<Props>(), {
  isOpen: false,
  inputConnections: () => [],
  executionDisabled: false,
  executionDisabledReason: "",
});

const emit = defineEmits<{
  (e: "update-params", nodeId: string, params: ParamsMap): void;
  (e: "execute-node", nodeId: string): void;
  (e: "delete-node", nodeId: string): void;
  (e: "open-trial", nodeData: any): void;
  (e: "close"): void;
}>();

const toast = useToast();
const router = useRouter();
const workflowStore = useWorkflowStore();
const projectStore = useProjectStore();
const selectedNodeType = computed(() => props.selectedNode?.type || "");
const configuringSheetData = ref(false);

async function configureSheetData(): Promise<void> {
  const node = props.selectedNode;
  if (!node || projectStore.currentProjectId === null) return;
  configuringSheetData.value = true;
  try {
    // Blank sheets are intentionally unsaved until their first meaningful
    // edit.  Data selection is that edit, so persist the graph first and then
    // let the server issue the initial append-only source revision.
    const workflowId =
      workflowStore.workflowId ??
      (await workflowStore.saveWorkflow({
        createVersion: false,
        projectId: projectStore.currentProjectId,
      }));
    const experimentId = Number(node.params?.experiment_id);
    await router.push({
      path: "/data",
      query: {
        tab: "my-dataset",
        workflow: String(workflowId),
        source_node: node.id,
        project_id: String(projectStore.currentProjectId),
        ...(Number.isSafeInteger(experimentId) && experimentId > 0
          ? { experiment: String(experimentId) }
          : {}),
      },
    });
  } catch (error: unknown) {
    toast.add({
      severity: "error",
      summary: "Data configuration could not open",
      detail: getErrorMessage(error, "Save this sheet and try configuring its data again."),
      life: 5000,
    });
  } finally {
    configuringSheetData.value = false;
  }
}
const nodeMetadata = computed(() => {
  if (!props.selectedNode) return null;
  return workflowStore.getNodeMetadata(props.selectedNode.type);
});
const selectedNodeHelpUrl = computed(() =>
  resolveNodeHelpUrl(nodeMetadata.value?.execution_contract?.payload.help_reference),
);
const selectedPresentationId = ref<string | null>(null);

const presentationOptions = computed(() =>
  availableScientificPresentations(nodeMetadata.value, props.nodeOutput).map((item) => ({
    value: item.presentation.presentation_id,
    label: item.presentation.label,
  })),
);

const selectedPresentation = computed(() =>
  resolveScientificPresentation(nodeMetadata.value, props.nodeOutput, selectedPresentationId.value),
);
const presentationError = computed(() =>
  presentationResolutionError(nodeMetadata.value, props.nodeOutput, selectedPresentationId.value),
);

const selectedPortOutput = computed<PortOutput | null>(() => {
  return selectedPresentation.value?.portOutput ?? null;
});

const selectedScientificDescriptor = computed<ScientificValueDescriptor | null>(
  () => selectedPortOutput.value?.descriptor ?? props.nodeOutput?.descriptor ?? null,
);

const selectedNodeOutput = computed<NodeOutput | null>(() => {
  return projectScientificPresentation(props.nodeOutput, selectedPresentation.value);
});

const executedGroupedSplit = computed(() => {
  if (selectedNodeType.value !== "data.train_test_split") return null;
  return groupedSplitSummary(props.nodeOutput);
});

const selectedOutputHasData = computed(() => {
  const output = selectedNodeOutput.value;
  if (Array.isArray(output?.data) && output.data.length > 0) return true;
  if (!selectedPresentation.value) return false;
  const value = output?.presentation_value;
  if (Array.isArray(value)) return value.length > 0;
  if (!value || typeof value !== "object") return false;
  return Object.values(value).some((entry) =>
    Array.isArray(entry) ? entry.length > 0 : entry !== null && entry !== undefined,
  );
});
const selectedOutputPreviewNotice = computed(() => {
  const metadata = asObject(selectedPortOutput.value?.metadata);
  const value = asObject(selectedPortOutput.value?.value);
  if (
    metadata?.persisted_preview !== true &&
    metadata?.data_truncated !== true &&
    value?.persisted_preview !== true &&
    value?.data_truncated !== true
  ) {
    return null;
  }
  return "Showing a bounded persisted preview. Re-run the workflow to inspect the complete numerical result.";
});
const selectedOutputSupportsTable = computed(() =>
  selectedPresentation.value
    ? presentationSupports(selectedPresentation.value, "table")
    : (selectedScientificDescriptor.value?.view_modes.includes("table") ??
      selectedOutputHasData.value),
);
const selectedOutputSupportsPlot = computed(() => {
  if (selectedPresentation.value) return presentationSupports(selectedPresentation.value, "plot");
  const descriptor = selectedScientificDescriptor.value;
  if (!descriptor) return selectedOutputHasData.value;
  const modes = descriptor.view_modes;
  return modes.some(
    (mode) => mode === "plot" || mode.endsWith("_plot") || mode === "variable_profile",
  );
});
const tablePlotColumnOptions = computed(() => {
  const input = props.inputConnections[0];
  if (selectedNodeType.value !== "output.plot" || input?.nodeType !== "output.data_table") return [];
  const value = asObject(asObject(input.data)?.value) || asObject(input.data);
  const names = asObject(value?.metadata)?.column_names;
  return Array.isArray(names) ? names.map(name => ({ label: String(name), value: `column:${name}` })) : [];
});
const selectableFeatureColumns = computed(() => featureColumnOptions(props.inputConnections[0]?.data));
const showPlotAxisParameters = computed(
  () => selectedPresentation.value?.presentation.kind !== "visualization",
);

const formatDimensionRole = (role: string): string => role.replace(/_/g, " ");

watch(
  () => [
    props.selectedNode?.id,
    props.nodeOutput?.primary_port,
    Object.keys(props.nodeOutput?.ports ?? {}),
    nodeMetadata.value?.presentation_contract?.digest,
  ],
  () => {
    const defaultPresentation =
      nodeMetadata.value?.presentation_contract?.payload.default_presentation;
    const availablePresentationIds = new Set(
      presentationOptions.value.map((option) => option.value),
    );
    selectedPresentationId.value =
      defaultPresentation && availablePresentationIds.has(defaultPresentation)
        ? defaultPresentation
        : (presentationOptions.value[0]?.value ?? null);
  },
  { immediate: true, deep: true },
);
const preparedExportArtifact = computed(() => extractExportArtifact(props.nodeOutput));

const downloadPreparedExport = async (): Promise<void> => {
  try {
    const artifact = await downloadExportArtifact(preparedExportArtifact.value);
    toast.add({
      severity: "success",
      summary: "Prepared export downloaded",
      detail: `${artifact.filename} (${artifact.content_sha256.slice(0, 12)}…)`,
      life: 3000,
    });
  } catch (error) {
    toast.add({
      severity: "error",
      summary: "Export verification failed",
      detail: error instanceof Error ? error.message : "Prepared export is invalid",
      life: 5000,
    });
  }
};

const asObject = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
};

const preparedExportSummary = computed(() => {
  const artifact = asObject(preparedExportArtifact.value);
  if (!artifact) return null;
  const shape = Array.isArray(artifact.shape) ? artifact.shape.join(" × ") : "unknown";
  return {
    filename: typeof artifact.filename === "string" ? artifact.filename : "unknown",
    format: typeof artifact.format === "string" ? artifact.format.toUpperCase() : "unknown",
    shape,
    byteLength:
      typeof artifact.byte_length === "number" ? artifact.byte_length.toLocaleString() : "unknown",
    digest: typeof artifact.content_sha256 === "string" ? artifact.content_sha256 : "unknown",
  };
});

const getStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
};

const outputMetadata = computed<InspectorMetadata>(() => {
  const metadata = asObject(selectedNodeOutput.value?.metadata);
  return (metadata as InspectorMetadata) ?? {};
});

const isPeakFindingStats = computed(() => {
  if (selectedNodeType.value !== "stats.summary") return false;
  const meta = outputMetadata.value;
  return meta.type === "PeakFinding" || meta.input_type === "PeakFinding";
});

const diagnosticEntries = computed(() => {
  const diagnostics = asObject(outputMetadata.value.diagnostics);
  return buildDiagnosticEntries(diagnostics);
});

const selectedResultEntries = computed(() => {
  const resolved = selectedPresentation.value;
  const port = selectedPortOutput.value;
  if (!resolved || !port) return [];
  const value = asObject(port.value);
  const metadata = asObject(value?.metadata) ?? asObject(port.metadata) ?? {};
  const summary: Record<string, unknown> = {};

  if (resolved.presentation.kind === "regression_comparison") {
    summary.role = metadata.role;
    summary.samples = metadata.n_samples;
    summary.targets = metadata.n_targets;
    summary.residual_definition = metadata.residual_definition;
  } else if (resolved.presentation.kind === "variable_profile") {
    const scores = Array.isArray(port.data)
      ? port.data.filter(
          (item): item is number => typeof item === "number" && Number.isFinite(item),
        )
      : [];
    summary.variables = scores.length;
    summary.vip_at_or_above_one = scores.filter((score) => score >= 1).length;
    summary.maximum_vip = scores.length > 0 ? Math.max(...scores) : null;
  } else if (resolved.presentation.kind === "pls_explained_variance") {
    const rows = Array.isArray(port.data) ? port.data : [];
    const finiteRows = rows.filter(
      (row): row is number[] =>
        Array.isArray(row) &&
        row.length >= 2 &&
        row.every((item) => typeof item === "number" && Number.isFinite(item)),
    );
    summary.components = finiteRows.length;
    summary.cumulative_x_variance = finiteRows.reduce((total, row) => total + row[0], 0);
    summary.cumulative_y_variance = finiteRows.reduce((total, row) => total + row[1], 0);
  } else if (resolved.presentation.kind === "pca_explained_variance") {
    const values = Array.isArray(port.data)
      ? port.data.filter(
          (item): item is number => typeof item === "number" && Number.isFinite(item),
        )
      : [];
    summary.components = values.length;
    summary.cumulative_explained_variance = values.reduce((total, value) => total + value, 0);
  } else if (
    ["metric_record", "statistics_summary", "validation_result"].includes(
      resolved.presentation.kind,
    )
  ) {
    const classificationSummary = primaryClassificationMetricSummary(value);
    if (classificationSummary) {
      Object.assign(summary, classificationSummary);
    } else {
      for (const key of [
        "task_type",
        "registry_version",
        "n_samples",
        "n_targets",
        "rmse",
        "mae",
        "bias",
        "r2",
        "sep",
        "slope",
        "intercept",
        "rer",
        "accuracy",
        "balanced_accuracy",
        "macro_precision",
        "macro_recall",
        "macro_specificity",
        "macro_f1",
      ]) {
        summary[key] = value?.[key];
      }
    }
  } else if (resolved.presentation.kind === "classification_responses") {
    const rows = Array.isArray(port.data) ? port.data : [];
    summary.calibration_samples = rows.length;
    summary.response_classes = rows.length > 0 && Array.isArray(rows[0]) ? rows[0].length : 0;
    summary.response_semantics = "PLS dummy-response scores, not probabilities";
  } else if (resolved.presentation.kind === "t2_q_diagnostics") {
    const rows = t2QDiagnosticRows(
      selectedNodeOutput.value?.presentation_value,
      outputMetadata.value,
    );
    summary.samples_screened = rows.length;
    summary.flagged_samples = rows.filter((row) => row.outlier).length;
    summary.maximum_t2 = rows.length > 0 ? Math.max(...rows.map((row) => row.t2)) : null;
    summary.maximum_q = rows.length > 0 ? Math.max(...rows.map((row) => row.q)) : null;
  } else if (resolved.presentation.kind === "model_summary") {
    const state = asObject(value?.state) ?? {};
    for (const key of [
      "algorithm_id",
      "algorithm_version",
      "n_components",
      "effective_n_components",
      "reference_samples",
      "features",
      "targets",
      "scale",
    ]) {
      summary[key] = state[key];
    }
    summary.serializer = value?.serializer;
    summary.state_content_digest = value?.state_content_digest;
  } else if (resolved.presentation.kind === "scalar") {
    const scalar =
      typeof port.data === "number"
        ? port.data
        : typeof port.value === "number"
          ? port.value
          : null;
    summary[resolved.sourcePort] = scalar;
  }
  return buildDiagnosticEntries(summary);
});

const selectedResultDimensions = computed(() => {
  const kind = selectedPresentation.value?.presentation.kind;
  const data = selectedPortOutput.value?.data;
  const descriptor = selectedScientificDescriptor.value;
  const declaredShape =
    descriptor?.shape_valid === true &&
    Array.isArray(descriptor.shape) &&
    descriptor.shape.every((size) => Number.isInteger(size) && size >= 0)
      ? descriptor.shape
      : null;
  if (
    kind === "spectral_dataset" &&
    outputMetadata.value.scientific_matrix_role === "component_concentrations" &&
    Array.isArray(data) &&
    Array.isArray(data[0])
  ) {
    return [
      { role: "samples", size: declaredShape?.[0] ?? data.length },
      { role: "components", size: declaredShape?.[1] ?? data[0].length },
    ];
  }
  if (
    kind === "spectral_dataset" &&
    outputMetadata.value.scientific_matrix_role === "component_spectra" &&
    Array.isArray(data) &&
    Array.isArray(data[0])
  ) {
    return [
      { role: "components", size: declaredShape?.[0] ?? data.length },
      { role: "spectral variables", size: declaredShape?.[1] ?? data[0].length },
    ];
  }
  if (kind === "pca_explained_variance" && Array.isArray(data)) {
    return [{ role: "components", size: data.length }];
  }
  if (kind === "variable_profile" && Array.isArray(data)) {
    return [{ role: "features", size: data.length }];
  }
  if (kind === "classification_responses" && Array.isArray(data) && Array.isArray(data[0])) {
    return [
      { role: "calibration samples", size: data.length },
      { role: "response classes", size: data[0].length },
    ];
  }
  if (
    kind === "spectral_dataset" &&
    outputMetadata.value.data_role === "X_features" &&
    Array.isArray(data) &&
    Array.isArray(data[0])
  ) {
    return [
      { role: "samples", size: data.length },
      { role: "features", size: data[0].length },
    ];
  }
  if (kind === "t2_q_diagnostics") {
    const rows = t2QDiagnosticRows(
      selectedNodeOutput.value?.presentation_value,
      outputMetadata.value,
    );
    return [
      { role: "samples", size: rows.length },
      { role: "statistics", size: 2 },
    ];
  }
  if (kind === "confusion_matrix" && Array.isArray(data) && Array.isArray(data[0])) {
    return [
      { role: "actual-class rows", size: data.length },
      { role: "prediction-class columns", size: data[0].length },
    ];
  }
  return selectedScientificDescriptor.value?.dimensions ?? [];
});

const selectedResultFormLabel = computed(() => {
  const kind = selectedPresentation.value?.presentation.kind;
  if (kind === "scalar") return "Scalar scientific result";
  if (["metric_record", "statistics_summary", "validation_result"].includes(kind ?? "")) {
    return "Structured scientific metrics";
  }
  if (kind?.includes("model")) return "Fitted scientific model";
  return "Structured scientific result";
});

const selectedResultNoninteractiveNote = computed(() =>
  selectedPresentation.value?.presentation.kind === "scalar"
    ? "This scalar result is reported in the selected result summary above."
    : "This fitted model record is summarized by its scientific diagnostics above.",
);

const selectedResultShowsMetadata = computed(() => {
  const kind = selectedPresentation.value?.presentation.kind;
  return !kind || (kind !== "scalar" && !kind.includes("model"));
});

const outputStatsRows = computed<StatsRow[]>(() => {
  if (!Array.isArray(props.nodeOutput?.data)) {
    return [];
  }
  return props.nodeOutput.data.filter((row): row is StatsRow => !!asObject(row));
});

const statsRowLabel = (stat: StatsRow, index: number): string => {
  if (typeof stat.pc === "number" && Number.isFinite(stat.pc)) return `PC${stat.pc}`;
  return stat.wavelength != null ? `λ ${stat.wavelength}` : `#${index + 1}`;
};

const statsOverallSummary = computed(() => {
  const summary = outputMetadata.value.summary;
  if (!summary) return "";
  if (summary.n_observations != null || summary.n_components != null) {
    const observations = summary.n_observations ?? 0;
    const components = summary.n_components ?? 0;
    const variance = summary.total_variance_explained;
    const varianceLabel =
      typeof variance === "number" && Number.isFinite(variance)
        ? `; ${(variance * 100).toFixed(1)}% variance explained`
        : "";
    return `${observations} samples × ${components} components${varianceLabel}`;
  }
  return `${summary.n_samples ?? 0} samples × ${summary.n_features ?? 0} features`;
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
  return nodeType;
};

// Close inspector
const closeInspector = () => {
  emit("close");
};

const NODE_ICONS: Record<string, string> = {
  // Data source
  "data.file_load": "📂",

  // Preprocessing - atomic
  "preprocess.cosmic_ray": "✨",
  "preprocess.clip_range": "✂️",
  "preprocess.clip_floor": "⬇️",
  "preprocess.wavenumber_align": "📐",
  "preprocess.scale": "📏",
  "preprocess.normalize": "⚖️",

  // Preprocessing - existing
  "baseline.penalized_ls": "📉",
  "baseline.rubberband": "📉",
  "preprocess.smooth": "〰️",
  "preprocess.derivative": "📈",
  "preprocess.emsc": "🔧",

  // Synthesis / Blend
  "synthesis.blend": "🔀",
  "synthesis.species": "🧬",
  "synthesis.merge": "📚",

  // Analysis
  "model.pca": "🔀",
  "model.fitted_pls": "📈",
  "model.apply_fitted_pls": "📈",
  "model.mcr_als": "🧩",
  "model.efa": "🔬",
  "model.simplisma": "🎯",

  // Output
  "stats.summary": "📊",
  "output.plot": "📈",
  "output.contour": "🗺️",
  "output.export": "💾",

  // Deploy
  "deploy.input": "📥",
  "deploy.output": "📤",
};

// Local params copy for editing
const localParams = ref<ParamsMap>({});
const currentNodeId = ref<string | null>(null);
const lastSyncedParamsSignature = ref("");

// Validation state
const validationErrors = ref<Array<{ param_name: string; message: string }>>([]);

// Get validation error for a specific parameter
const getParamError = (paramName: string): string | null => {
  const error = validationErrors.value.find((e) => e.param_name === paramName);
  return error ? error.message : null;
};

// Check if parameters are valid
const hasValidationErrors = computed(() => validationErrors.value.length > 0);

const stableParamSignature = (value: unknown): string => {
  const normalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(normalize);
    if (item && typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, child]) => [key, normalize(child)]),
      );
    }
    return item;
  };
  return JSON.stringify(normalize(value ?? {}));
};

const mergedNodeParams = (node: WorkflowNode): ParamsMap => ({
  ...getDefaultsForNodeType(node.type),
  ...node.params,
});

const syncLocalParamsFromNode = (node: WorkflowNode, options: { force?: boolean } = {}) => {
  const nextParams = mergedNodeParams(node);
  const nextSignature = stableParamSignature(nextParams);
  const localSignature = stableParamSignature(localParams.value);
  const isDirty = localSignature !== lastSyncedParamsSignature.value;
  if (!options.force && isDirty) return false;
  currentNodeId.value = node.id;
  localParams.value = nextParams;
  lastSyncedParamsSignature.value = nextSignature;
  return true;
};

const syncLocalParamsFromExternal = (
  nodeType: string,
  params: ParamsMap | undefined,
  options: { fetchReferenceDatasets?: boolean } = {},
) => {
  const nextParams = { ...getDefaultsForNodeType(nodeType), ...(params || {}) };
  const localSignature = stableParamSignature(localParams.value);
  if (localSignature !== lastSyncedParamsSignature.value) return false;
  localParams.value = nextParams;
  lastSyncedParamsSignature.value = stableParamSignature(nextParams);
  if (
    options.fetchReferenceDatasets &&
    (localParams.value.source === "eigenvector" || localParams.value.source === "sklearn")
  ) {
    void workflowStore.fetchReferenceDatasets();
  }
  return true;
};

type SampleFilterField =
  | "sample_index"
  | "sample_label"
  | "sample_class"
  | "sample_table"
  | "intensity";

interface FilterModeOption {
  value: SampleFilterField;
  label: string;
  hint: string;
  icon: string;
  enabled: boolean;
}

interface FilterValueOption {
  label: string;
  value: string;
}

const MAX_FILTER_VALUE_OPTIONS = 500;
const filterValueSearch = ref("");

const intensityMetricOptions = [
  { label: "Max intensity", value: "max" },
  { label: "Mean intensity", value: "mean" },
  { label: "Min intensity", value: "min" },
  { label: "Any point", value: "any" },
  { label: "All points", value: "all" },
];

const intensityOperatorOptions = [
  { label: ">= threshold", value: "gte" },
  { label: "> threshold", value: "gt" },
  { label: "<= threshold", value: "lte" },
  { label: "< threshold", value: "lt" },
  { label: "Between", value: "between" },
];

const sampleFilterMatchModeOptions = [
  { label: "Contains", value: "contains" },
  { label: "Equals", value: "equals" },
  { label: "In list", value: "in_list" },
  { label: "Regex", value: "regex" },
];

const filterInputOutput = computed<PortOutput | NodeOutput | null>(() => {
  if (selectedNodeType.value !== "data.filter_samples") return null;
  return (
    props.inputConnections.find((conn) => conn.toPort === "X")?.data ||
    props.inputConnections[0]?.data ||
    null
  );
});

const quickPlotInputs = computed<Record<string, PortOutput | NodeOutput | null>>(() =>
  Object.fromEntries(
    props.inputConnections.map((connection) => [
      connection.toPort || "default",
      connection.data ?? null,
    ]),
  ),
);

const filterOutputValue = (output: PortOutput | NodeOutput | null): unknown => {
  return output && "value" in output ? output.value : null;
};

const filterInputRecord = computed<Record<string, unknown> | null>(() => {
  return asObject(filterOutputValue(filterInputOutput.value));
});

const filterInputMetadata = computed<Record<string, unknown>>(() => {
  return (
    asObject(filterInputOutput.value?.metadata) ?? asObject(filterInputRecord.value?.metadata) ?? {}
  );
});

const filterDataRows = computed<unknown[][]>(() => {
  const data = filterInputOutput.value?.data;
  if (Array.isArray(data)) {
    return data.map((row) => (Array.isArray(row) ? row : [row]));
  }
  const recordData = filterInputRecord.value?.data;
  if (Array.isArray(recordData)) {
    return recordData.map((row) => (Array.isArray(row) ? row : [row]));
  }
  return [];
});

const filterHasInput = computed(() => !!filterInputOutput.value);

const toStringValues = (value: unknown, expectedLength?: number): string[] => {
  if (!Array.isArray(value)) return [];
  const values = value.map((item) => (item === null || item === undefined ? "" : String(item)));
  if (expectedLength !== undefined && values.length !== expectedLength) return [];
  return values;
};

const getNestedArray = (...candidates: unknown[]): unknown[] => {
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) return candidate;
  }
  return [];
};

const filterSampleCount = computed(() => {
  const metadataCount = filterInputMetadata.value.n_samples;
  if (typeof metadataCount === "number" && Number.isFinite(metadataCount)) return metadataCount;
  const recordCount = filterInputRecord.value?.n_samples;
  if (typeof recordCount === "number" && Number.isFinite(recordCount)) return recordCount;
  return filterDataRows.value.length;
});

const filterFeatureCount = computed<number | null>(() => {
  const metadataCount = filterInputMetadata.value.n_features;
  if (typeof metadataCount === "number" && Number.isFinite(metadataCount)) return metadataCount;
  const recordCount = filterInputRecord.value?.n_features;
  if (typeof recordCount === "number" && Number.isFinite(recordCount)) return recordCount;
  return filterDataRows.value[0]?.length ?? null;
});

const filterMatrixPreviewOnly = computed(() => {
  const rows = filterDataRows.value.length;
  if (rows <= 0) return false;
  const cols = filterDataRows.value[0]?.length ?? 0;
  const fullRows = filterSampleCount.value;
  const fullCols = filterFeatureCount.value;
  return rows < fullRows || (fullCols !== null && cols < fullCols);
});

const filterSampleLabels = computed(() => {
  const record = filterInputRecord.value;
  const yAxis = asObject(record?.y_axis) ?? asObject(record?.sample_axis);
  const labels = toStringValues(
    getNestedArray(
      filterInputMetadata.value.sample_labels,
      filterInputMetadata.value.labels,
      yAxis?.labels,
    ),
    filterSampleCount.value,
  );
  if (labels.length) return labels;
  return Array.from({ length: filterSampleCount.value }, (_, index) => `Sample ${index + 1}`);
});

const filterHasRealSampleLabels = computed(() => {
  const record = filterInputRecord.value;
  const yAxis = asObject(record?.y_axis) ?? asObject(record?.sample_axis);
  return (
    toStringValues(
      getNestedArray(
        filterInputMetadata.value.sample_labels,
        filterInputMetadata.value.labels,
        yAxis?.labels,
      ),
      filterSampleCount.value,
    ).length > 0
  );
});

const filterSampleClasses = computed(() => {
  const record = filterInputRecord.value;
  const yAxis = asObject(record?.y_axis) ?? asObject(record?.sample_axis);
  return toStringValues(
    getNestedArray(
      filterInputMetadata.value.sample_classes,
      filterInputMetadata.value.classes,
      yAxis?.classes,
    ),
    filterSampleCount.value,
  );
});

const filterSampleTable = computed<Record<string, string[]>>(() => {
  const record = filterInputRecord.value;
  const yAxis = asObject(record?.y_axis) ?? asObject(record?.sample_axis);
  const rawTable =
    asObject(yAxis?.sample_table) ?? asObject(filterInputMetadata.value.sample_table);
  const table: Record<string, string[]> = {};
  if (!rawTable) return table;
  for (const [key, value] of Object.entries(rawTable)) {
    const values = toStringValues(value, filterSampleCount.value);
    if (values.length > 0) {
      table[key] = values;
    }
  }
  return table;
});

const sampleTableColumnOptions = computed(() =>
  Object.keys(filterSampleTable.value).map((column) => ({
    label: formatLabel(column),
    value: column,
  })),
);

const uniqueOptions = (values: string[]): FilterValueOption[] => {
  const seen = new Set<string>();
  const result: FilterValueOption[] = [];
  for (const value of values) {
    if (seen.has(value)) continue;
    seen.add(value);
    result.push({ label: value || "(blank)", value });
  }
  return result;
};

const currentCategoricalValues = computed(() => {
  const field = String(localParams.value.field || "sample_index");
  if (field === "sample_label")
    return filterHasRealSampleLabels.value ? filterSampleLabels.value : [];
  if (field === "sample_class") return filterSampleClasses.value;
  if (field === "sample_table") {
    const column = String(localParams.value.sample_table_column || "");
    return column ? (filterSampleTable.value[column] ?? []) : [];
  }
  return [];
});

const filterValueOptions = computed(() => uniqueOptions(currentCategoricalValues.value));

const visibleFilterValueOptions = computed(() => {
  const query = filterValueSearch.value.trim().toLowerCase();
  const options = query
    ? filterValueOptions.value.filter((option) => option.label.toLowerCase().includes(query))
    : filterValueOptions.value;
  return options.slice(0, MAX_FILTER_VALUE_OPTIONS);
});

const categoricalFilterLabel = computed(() => {
  const field = String(localParams.value.field || "");
  if (field === "sample_label") return "Sample names to keep";
  if (field === "sample_class") return "Classes to keep";
  if (field === "sample_table") return "Metadata values to keep";
  return "Values to keep";
});

const splitFilterTerms = (pattern: string): string[] =>
  pattern
    .split(/[\n,]+/)
    .map((term) => term.trim())
    .filter(Boolean);

const explicitFilterValues = (): string[] | null => {
  const explicit = localParams.value.filter_values;
  if (!Array.isArray(explicit)) return null;
  return explicit.map((value) => String(value));
};

const selectedFilterValues = computed<string[]>(() => {
  const explicit = explicitFilterValues();
  if (explicit !== null) {
    return explicit;
  }
  if (!String(localParams.value.pattern || "").trim()) {
    return filterValueOptions.value.map((option) => option.value);
  }
  if (String(localParams.value.match_mode || "") === "in_list") {
    return splitFilterTerms(String(localParams.value.pattern || ""));
  }
  const optionValues = filterValueOptions.value.map((option) => option.value);
  const mask = textMask(optionValues);
  return optionValues.filter((_, index) => mask[index]);
});

const selectedFilterValueSet = computed(() => new Set(selectedFilterValues.value));

const setSelectedFilterValues = (values: string[]) => {
  const allValues = filterValueOptions.value.map((option) => option.value);
  const unique = Array.from(new Set(values));
  if (unique.length === allValues.length && allValues.every((value) => unique.includes(value))) {
    delete localParams.value.filter_values;
    localParams.value.pattern = "";
    localParams.value.match_mode = "in_list";
    localParams.value.case_sensitive = false;
  } else if (unique.length === 0) {
    localParams.value.filter_values = [];
    localParams.value.pattern = "";
    localParams.value.match_mode = "in_list";
    localParams.value.case_sensitive = true;
  } else {
    localParams.value.filter_values = unique;
    localParams.value.pattern = "";
    localParams.value.match_mode = "in_list";
    localParams.value.case_sensitive = true;
  }
  emitParams();
};

const isFilterValueSelected = (value: string): boolean => selectedFilterValueSet.value.has(value);

const toggleFilterValue = (value: string) => {
  const selected = new Set(selectedFilterValues.value);
  if (selected.has(value)) {
    selected.delete(value);
  } else {
    selected.add(value);
  }
  setSelectedFilterValues(Array.from(selected));
};

const selectAllFilterValues = () =>
  setSelectedFilterValues(filterValueOptions.value.map((option) => option.value));
const clearFilterValues = () => setSelectedFilterValues([]);

const numericRows = computed(() =>
  filterDataRows.value.map((row) =>
    row
      .map((value) => (typeof value === "number" ? value : Number(value)))
      .filter((value) => Number.isFinite(value)),
  ),
);

const hasNumericIntensityData = computed(() => numericRows.value.some((row) => row.length > 0));

const rowIntensityValues = (metric: string): number[] => {
  return numericRows.value.map((row) => {
    if (row.length === 0) return Number.NaN;
    if (metric === "mean") return row.reduce((sum, value) => sum + value, 0) / row.length;
    if (metric === "min") return Math.min(...row);
    if (metric === "max") return Math.max(...row);
    return Number.NaN;
  });
};

const intensityReferenceValues = (metric: string): number[] => {
  if (metric === "any" || metric === "all") {
    return numericRows.value.flat().filter((value) => Number.isFinite(value));
  }
  return rowIntensityValues(metric).filter((value) => Number.isFinite(value));
};

const intensityMetricValues = computed(() => {
  const metric = String(localParams.value.intensity_metric || "max");
  return intensityReferenceValues(metric);
});

const intensitySummaryText = computed(() => {
  if (filterMatrixPreviewOnly.value) {
    return "Intensity filtering needs the full upstream matrix; rerun the workflow before setting this rule.";
  }
  const values = intensityMetricValues.value;
  if (!values.length) return "No numeric intensities are available for preview.";
  const min = Math.min(...values);
  const max = Math.max(...values);
  return `Available ${localParams.value.intensity_metric || "max"} range: ${min.toPrecision(5)} to ${max.toPrecision(5)}.`;
});

const sampleFilterModeOptions = computed<FilterModeOption[]>(() => [
  {
    value: "sample_index",
    label: "By index",
    hint: filterSampleCount.value ? `Rows 1-${filterSampleCount.value}` : "Rows",
    icon: "pi pi-list",
    enabled: filterSampleCount.value > 0,
  },
  {
    value: "sample_label",
    label: "By name",
    hint: filterHasRealSampleLabels.value ? `${filterSampleLabels.value.length} names` : "No names",
    icon: "pi pi-tag",
    enabled: filterHasRealSampleLabels.value,
  },
  {
    value: "sample_class",
    label: "By class",
    hint: filterSampleClasses.value.some((value) => value !== "")
      ? `${uniqueOptions(filterSampleClasses.value.filter((value) => value !== "")).length} classes`
      : "No classes",
    icon: "pi pi-sitemap",
    enabled: filterSampleClasses.value.some((value) => value !== ""),
  },
  {
    value: "sample_table",
    label: "By metadata",
    hint: sampleTableColumnOptions.value.length
      ? `${sampleTableColumnOptions.value.length} fields`
      : "No fields",
    icon: "pi pi-table",
    enabled: sampleTableColumnOptions.value.length > 0,
  },
  {
    value: "intensity",
    label: "By intensity",
    hint: filterMatrixPreviewOnly.value
      ? "Needs full matrix"
      : hasNumericIntensityData.value
        ? "Spectral values"
        : "No numeric data",
    icon: "pi pi-chart-line",
    enabled: hasNumericIntensityData.value && !filterMatrixPreviewOnly.value,
  },
]);

const isFilterFieldEnabled = (field: string): field is SampleFilterField =>
  sampleFilterModeOptions.value.some((option) => option.value === field && option.enabled);

const firstEnabledFilterField = (): SampleFilterField =>
  sampleFilterModeOptions.value.find((option) => option.enabled)?.value ?? "sample_index";

const initializeFilterFieldDefaults = (field: SampleFilterField) => {
  delete localParams.value.filter_values;
  filterValueSearch.value = "";
  localParams.value.field = field;
  localParams.value.allow_empty = Boolean(localParams.value.allow_empty ?? false);
  localParams.value.invert = Boolean(localParams.value.invert ?? false);

  if (field === "sample_index") {
    localParams.value.pattern = filterSampleCount.value > 0 ? `1-${filterSampleCount.value}` : "";
    localParams.value.match_mode = "in_list";
    localParams.value.case_sensitive = false;
    return;
  }

  if (field === "intensity") {
    localParams.value.intensity_metric = localParams.value.intensity_metric || "max";
    localParams.value.intensity_operator = localParams.value.intensity_operator || "gte";
    const values = intensityReferenceValues(String(localParams.value.intensity_metric || "max"));
    if (values.length > 0) {
      localParams.value.intensity_threshold = Math.min(...values);
      localParams.value.intensity_upper_threshold = Math.max(...values);
    } else {
      localParams.value.intensity_threshold = 0;
      localParams.value.intensity_upper_threshold = 1;
    }
    localParams.value.pattern = "";
    return;
  }

  if (field === "sample_table" && !localParams.value.sample_table_column) {
    localParams.value.sample_table_column = sampleTableColumnOptions.value[0]?.value || "";
  }
  localParams.value.pattern = "";
  localParams.value.match_mode = "in_list";
  localParams.value.case_sensitive = false;
};

const setSampleFilterField = (field: SampleFilterField) => {
  if (!isFilterFieldEnabled(field)) return;
  initializeFilterFieldDefaults(field);
  emitParams();
};

const ensureSampleFilterDefaults = (emit = false) => {
  if (selectedNodeType.value !== "data.filter_samples" || !filterHasInput.value) return;
  const currentField = String(localParams.value.field || "");
  if (!isFilterFieldEnabled(currentField)) {
    initializeFilterFieldDefaults(firstEnabledFilterField());
    if (emit) emitParams();
    return;
  }
  const sampleTableColumns = sampleTableColumnOptions.value.map((option) => option.value);
  if (
    currentField === "sample_table" &&
    sampleTableColumns.length &&
    (!localParams.value.sample_table_column ||
      !sampleTableColumns.includes(String(localParams.value.sample_table_column)))
  ) {
    localParams.value.sample_table_column = sampleTableColumns[0];
    if (emit) emitParams();
  }
};

const setIndexRange = (kind: "all" | "first10" | "last10") => {
  const count = filterSampleCount.value;
  if (count <= 0) return;
  if (kind === "all") {
    localParams.value.pattern = `1-${count}`;
  } else if (kind === "first10") {
    localParams.value.pattern = `1-${Math.min(10, count)}`;
  } else {
    localParams.value.pattern = `${Math.max(1, count - 9)}-${count}`;
  }
  localParams.value.match_mode = "in_list";
  emitParams();
};

const onIndexPatternChange = () => {
  localParams.value.match_mode = "in_list";
  emitParams();
};

const onIntensityMetricChange = () => {
  const values = intensityReferenceValues(String(localParams.value.intensity_metric || "max"));
  if (values.length > 0) {
    localParams.value.intensity_threshold = Math.min(...values);
    localParams.value.intensity_upper_threshold = Math.max(...values);
  }
  emitParams();
};

const onSampleTableColumnChange = () => {
  delete localParams.value.filter_values;
  localParams.value.pattern = "";
  localParams.value.match_mode = "in_list";
  emitParams();
};

const onAdvancedPatternChange = () => {
  delete localParams.value.filter_values;
  emitParams();
};

const parseIndexPattern = (pattern: string): Set<number> => {
  const selected = new Set<number>();
  for (const term of splitFilterTerms(pattern)) {
    if (term.includes("-")) {
      const [left, right] = term.split("-", 2).map((part) => Number.parseInt(part.trim(), 10));
      if (!Number.isFinite(left) || !Number.isFinite(right)) continue;
      const start = Math.max(1, Math.min(left, right));
      const stop = Math.min(filterSampleCount.value, Math.max(left, right));
      for (let index = start; index <= stop; index += 1) {
        selected.add(index);
      }
    } else {
      const value = Number.parseInt(term, 10);
      if (Number.isFinite(value) && value >= 1 && value <= filterSampleCount.value) {
        selected.add(value);
      }
    }
  }
  return selected;
};

const textMask = (values: string[]): boolean[] => {
  const pattern = String(localParams.value.pattern || "");
  if (!pattern.trim()) return values.map(() => true);
  const matchMode = String(localParams.value.match_mode || "contains");
  const caseSensitive = Boolean(localParams.value.case_sensitive);
  const normalizedValues = caseSensitive ? values : values.map((value) => value.toLowerCase());
  const normalizedPattern = caseSensitive ? pattern : pattern.toLowerCase();

  if (matchMode === "equals") return normalizedValues.map((value) => value === normalizedPattern);
  if (matchMode === "in_list") {
    const terms = new Set(splitFilterTerms(normalizedPattern));
    return normalizedValues.map((value) => terms.has(value));
  }
  if (matchMode === "regex") {
    try {
      const regex = new RegExp(pattern, caseSensitive ? "" : "i");
      return values.map((value) => regex.test(value));
    } catch {
      return values.map(() => false);
    }
  }
  return normalizedValues.map((value) => value.includes(normalizedPattern));
};

const categoricalMask = (values: string[]): boolean[] => {
  const explicit = explicitFilterValues();
  if (explicit !== null) {
    const selected = new Set(explicit);
    return values.map((value) => selected.has(value));
  }
  return textMask(values);
};

const normalizeMaskLength = (mask: boolean[], count: number): boolean[] =>
  Array.from({ length: count }, (_, index) => mask[index] === true);

const compareNumber = (
  value: number,
  operator: string,
  threshold: number,
  upper: number,
): boolean => {
  if (!Number.isFinite(value)) return false;
  if (operator === "gt") return value > threshold;
  if (operator === "gte") return value >= threshold;
  if (operator === "lt") return value < threshold;
  if (operator === "lte") return value <= threshold;
  if (operator === "between") {
    const low = Math.min(threshold, upper);
    const high = Math.max(threshold, upper);
    return value >= low && value <= high;
  }
  return Math.abs(value - threshold) < Number.EPSILON;
};

const intensityMask = (): boolean[] => {
  const metric = String(localParams.value.intensity_metric || "max");
  const operator = String(localParams.value.intensity_operator || "gte");
  const threshold = Number(localParams.value.intensity_threshold ?? 0);
  const upper = Number(localParams.value.intensity_upper_threshold ?? threshold);
  if (metric === "any" || metric === "all") {
    return numericRows.value.map((row) => {
      const matches = row.map((value) => compareNumber(value, operator, threshold, upper));
      return metric === "any"
        ? matches.some(Boolean)
        : matches.length > 0 && matches.every(Boolean);
    });
  }
  return rowIntensityValues(metric).map((value) =>
    compareNumber(value, operator, threshold, upper),
  );
};

const filterPreview = computed(() => {
  const count = filterSampleCount.value;
  if (!filterHasInput.value || count === 0) {
    return {
      empty: true,
      summary: "No input samples are available.",
      keptLabels: [],
      excludedLabels: [],
    };
  }

  let mask: boolean[];
  const field = String(localParams.value.field || "sample_index");
  if (field === "sample_index") {
    const pattern = String(localParams.value.pattern || "");
    if (!pattern.trim()) {
      mask = Array.from({ length: count }, () => true);
    } else {
      const selected = parseIndexPattern(pattern);
      mask = Array.from({ length: count }, (_, index) => selected.has(index + 1));
    }
  } else if (field === "intensity") {
    if (filterMatrixPreviewOnly.value) {
      return {
        empty: true,
        summary: "Intensity filtering is disabled because only preview rows are loaded.",
        keptLabels: [],
        excludedLabels: [],
      };
    }
    mask = intensityMask();
  } else {
    mask = categoricalMask(currentCategoricalValues.value);
  }

  mask = normalizeMaskLength(mask, count);
  if (localParams.value.invert === true) {
    mask = mask.map((value) => !value);
  }

  const labels = filterSampleLabels.value;
  const kept = labels.filter((_, index) => mask[index]).slice(0, 5);
  const excluded = labels.filter((_, index) => !mask[index]).slice(0, 5);
  const keptCount = mask.filter(Boolean).length;
  return {
    empty: keptCount === 0,
    summary:
      keptCount === 0
        ? `No samples match this rule.`
        : `This rule keeps ${keptCount} of ${count} samples.`,
    keptLabels: kept,
    excludedLabels: excluded,
  };
});

// Check if node is a preprocessing node (eligible for preview)
const isPreprocessingNode = computed(() => {
  if (!props.selectedNode) return false;
  const preprocessingTypes = [
    "preprocess.smooth",
    "baseline.penalized_ls",
    "baseline.rubberband",
    "preprocess.normalize",
    "preprocess.scale",
    "preprocess.emsc",
    "preprocess.derivative",
  ];
  return preprocessingTypes.includes(selectedNodeType.value);
});

const normalizeOptions = (options: any[] | undefined): any[] | undefined => {
  if (!options) return options;
  return options.map((opt: any) => (typeof opt === "string" ? { label: opt, value: opt } : opt));
};

const upstreamGroupColumn = (): string | null => {
  const selectedId = props.selectedNode?.id;
  if (!selectedId) return null;
  const pending = [selectedId];
  const visited = new Set<string>();
  while (pending.length > 0) {
    const targetId = pending.shift();
    if (!targetId || visited.has(targetId)) continue;
    visited.add(targetId);
    for (const edge of workflowStore.edges.filter((candidate) => candidate.to === targetId)) {
      const source = workflowStore.nodes.find((candidate) => candidate.id === edge.from);
      if (!source) continue;
      const groupColumn = source.params?.group_column;
      if (typeof groupColumn === "string" && groupColumn.trim()) return groupColumn.trim();
      pending.push(source.id);
    }
  }
  return null;
};

// Walk the same upstream chain as the group column to find the declared target
// type, so the split node can tell whether its method suits the bound response.
const upstreamTargetType = (): string | null => {
  const selectedId = props.selectedNode?.id;
  if (!selectedId) return null;
  const pending = [selectedId];
  const visited = new Set<string>();
  while (pending.length > 0) {
    const targetId = pending.shift();
    if (!targetId || visited.has(targetId)) continue;
    visited.add(targetId);
    for (const edge of workflowStore.edges.filter((candidate) => candidate.to === targetId)) {
      const source = workflowStore.nodes.find((candidate) => candidate.id === edge.from);
      if (!source) continue;
      const targetType = source.params?.target_type;
      if (typeof targetType === "string" && targetType.trim()) return targetType.trim();
      pending.push(source.id);
    }
  }
  return null;
};

const activeTargetType = computed(() => {
  if (selectedNodeType.value !== "data.train_test_split") return null;
  return upstreamTargetType();
});

const activeValidationGroupColumn = computed(() => {
  if (selectedNodeType.value !== "data.train_test_split") return null;
  return groupColumnFromInputs(props.inputConnections) ?? upstreamGroupColumn();
});

// When a grouping column is bound and the upstream dataset carries its sample
// table (as it does after execution), offer a dropdown of the exact group
// values. If the table is not on the wire, fall back to the free-entry string
// list; the planner will still validate the names and report the valid ones.
const groupValuesFromInputs = computed((): string[] | null => {
  const column = activeValidationGroupColumn.value;
  if (!column) return null;
  for (const connection of props.inputConnections ?? []) {
    const payload = connection?.data;
    const value =
      payload && typeof payload === "object"
        ? (payload as unknown as Record<string, unknown>).value
        : payload;
    const dataset =
      value && typeof value === "object" ? (value as unknown as Record<string, unknown>) : null;
    const sampleAxis =
      dataset?.sample_axis && typeof dataset.sample_axis === "object"
        ? (dataset.sample_axis as Record<string, unknown>)
        : null;
    const table = sampleAxis?.sample_table ?? dataset?.sample_table;
    if (!Array.isArray(table)) continue;
    const entry = table.find(
      (item: unknown) =>
        item && typeof item === "object" && (item as Record<string, unknown>).name === column,
    ) as Record<string, unknown> | undefined;
    const values = entry?.values;
    if (!Array.isArray(values)) continue;
    const seen = new Set<string>();
    const result: string[] = [];
    for (const raw of values) {
      const text = String(raw);
      if (seen.has(text)) continue;
      seen.add(text);
      result.push(text);
    }
    return result;
  }
  return null;
});

const parameterOptions = (param: NodeParameterMetadata): any[] | undefined => {
  const normalized = normalizeOptions(param.options);
  if (param.name !== "split_method" || selectedNodeType.value !== "data.train_test_split") {
    return normalized;
  }
  return splitMethodOptions(normalized, Boolean(activeValidationGroupColumn.value));
};

const mapMetadataParamNames = (
  _nodeType: string,
  parameters: NodeParameterMetadata[],
): NodeParameterMetadata[] => {
  return parameters;
};

const mappedMetadataParams = computed(() => {
  if (!nodeMetadata.value || !props.selectedNode) return [];
  return mapMetadataParamNames(props.selectedNode.type, nodeMetadata.value.parameters);
});

// A parameter declared visible only under certain control values does not apply
// outside them, so the inspector hides it exactly as the node detail view does.
// Leaving it on screen offered a setting the chosen method could not honour, and
// leaving a stale value behind it used to make the saved graph inadmissible over
// a field the scientist had no way to see. The node canonicalizer resets those
// values; hiding the control is the matching half.
const isParamVisible = (param: NodeParameterMetadata): boolean => {
  if (!param.visible_when) return true;
  return Object.entries(param.visible_when).every(([control, admitted]) =>
    admitted.includes(String(localParams.value[control] ?? "")),
  );
};

const basicParams = computed(() => {
  if (!mappedMetadataParams.value.length) return [];
  return mappedMetadataParams.value.filter(
    (p) => (!p.category || p.category === "basic") && isParamVisible(p),
  );
});

const advancedParams = computed(() => {
  if (!mappedMetadataParams.value.length) return [];
  return mappedMetadataParams.value.filter((p) => p.category === "advanced" && isParamVisible(p));
});

const hasAdvancedParams = computed(() => advancedParams.value.length > 0);

// Processing history helpers
const sortedProcessingHistory = computed<any[]>(() => {
  const history =
    outputMetadata.value.processing_history ||
    outputMetadata.value.provenance?.operations ||
    spectraMetadata.value.provenance?.operations ||
    [];
  // Sort by timestamp if available
  if (
    history.length > 0 &&
    typeof history[0] === "object" &&
    history[0] !== null &&
    "timestamp" in history[0]
  ) {
    const withTimestamp = history.filter(
      (item): item is { timestamp: string } =>
        typeof item === "object" &&
        item !== null &&
        "timestamp" in item &&
        typeof item.timestamp === "string",
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
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
      }
    }
  }
  // Same day - just show time
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

// Format snake_case keys to readable labels
const formatLabel = (key: string): string => {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/Cm$/, "(cm⁻¹)")
    .replace(/Khz$/, "(kHz)")
    .replace(/^N /, "Number of ");
};

// Format acquisition values with appropriate units
const formatAcquisitionValue = (key: string, value: unknown): string => {
  if (value === null || value === undefined) return "—";

  // Add units based on key
  if (key.includes("resolution") && typeof value === "number") {
    return `${value} cm⁻¹`;
  }
  if (key.includes("velocity") && typeof value === "number") {
    return `${value} kHz`;
  }
  if (key.includes("wavenumber") && typeof value === "number") {
    return `${value.toFixed(1)} cm⁻¹`;
  }
  if ((key === "n_scans" || key === "n_points") && typeof value === "number") {
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

const numericPreviewValue = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const previewPayloadMetadata = (payload: any): Record<string, unknown> =>
  asObject(payload?.metadata) ?? {};

const previewPayloadSampleCount = (payload: any): number => {
  const metadata = previewPayloadMetadata(payload);
  return (
    numericPreviewValue(metadata.n_samples ?? payload?.n_samples) ??
    (Array.isArray(payload?.data) ? payload.data.length : 0)
  );
};

const previewPayloadFeatureCount = (payload: any): number => {
  const metadata = previewPayloadMetadata(payload);
  const firstWavenumbers = payload?.data?.[0]?.wavenumber;
  return (
    numericPreviewValue(metadata.n_features ?? payload?.n_features) ??
    (Array.isArray(firstWavenumbers) ? firstWavenumbers.length : 0)
  );
};

const previewPayloadRange = (payload: any): string => {
  const metadata = previewPayloadMetadata(payload);
  const explicitRange = metadata.x_range;
  if (Array.isArray(explicitRange) && explicitRange.length >= 2) {
    const left = numericPreviewValue(explicitRange[0]);
    const right = numericPreviewValue(explicitRange[1]);
    if (left !== null && right !== null)
      return `${Math.min(left, right).toFixed(1)} - ${Math.max(left, right).toFixed(1)} cm⁻¹`;
  }
  const min = numericPreviewValue(metadata.wavenumber_min ?? metadata.x_min);
  const max = numericPreviewValue(metadata.wavenumber_max ?? metadata.x_max);
  if (min !== null && max !== null)
    return `${Math.min(min, max).toFixed(1)} - ${Math.max(min, max).toFixed(1)} cm⁻¹`;
  const wavenumbers = payload?.data?.[0]?.wavenumber;
  if (!Array.isArray(wavenumbers)) return "Unknown";
  const values = wavenumbers
    .map((value: unknown) => numericPreviewValue(value))
    .filter((value: number | null): value is number => value !== null);
  if (!values.length) return "Unknown";
  return `${Math.min(...values).toFixed(1)} - ${Math.max(...values).toFixed(1)} cm⁻¹`;
};

// Debug: watch nodeOutput changes
watch(
  () => props.nodeOutput,
  (output) => {
    if (output) {
      console.log("[WorkflowInspector] nodeOutput updated:", {
        hasData: !!output.data,
        dataLength: Array.isArray(output.data) ? output.data.length : "N/A",
        dataType: output.data
          ? Array.isArray(output.data)
            ? "array"
            : typeof output.data
          : "none",
        firstRow:
          Array.isArray(output.data) && output.data[0]
            ? Array.isArray(output.data[0])
              ? `array[${output.data[0].length}]`
              : typeof output.data[0]
            : "N/A",
      });
    }
  },
  { immediate: true },
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
    temperature_c: null as number | string | null,
    pressure_atm: null as number | string | null,
    purge_gas: null as string | null,
    ambient_humidity_percent: null as number | string | null,
  },
  instrument: {
    manufacturer: null as string | null,
    model: null as string | null,
    detector_type: null as string | null,
    source_type: null as string | null,
  },
  acquisition: {
    resolution_cm: null as number | string | null,
    n_scans: null as number | string | null,
    wavenumber_min: null as number | string | null,
    wavenumber_max: null as number | string | null,
    apodization: null as string | null,
  },
  cell: {
    cell_type: null as string | null,
    pathlength_mm: null as number | string | null,
    window_material: null as string | null,
    cell_volume_ml: null as number | string | null,
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
const DATA_SOURCE_NODES = [
  "data.file_load",
  "data.nist_library",
  "data.synthetic_curve",
  "doe_plate",
];

const isDataSourceNode = computed(() => {
  return props.selectedNode && DATA_SOURCE_NODES.includes(selectedNodeType.value);
});

// ============================================================================
// METADATA DROPDOWN OPTIONS
// ============================================================================

const physicalStateOptions = [
  "gas",
  "liquid",
  "solid",
  "plasma",
  "solution",
  "film",
  "powder",
  "kbr_pellet",
  "mull",
  "gel",
  "suspension",
  "unknown",
];

const purgeGasOptions = ["N2", "dry_air", "Ar", "none"];

const instrumentManufacturers = [
  "Bruker",
  "Thermo Scientific",
  "Agilent",
  "PerkinElmer",
  "JASCO",
  "Shimadzu",
  "ABB",
  "Nicolet",
  "Bio-Rad",
];

const detectorTypeOptions = [
  "mct",
  "mct_a",
  "mct_b",
  "dtgs",
  "dtgs_kbr",
  "dtgs_pe",
  "ingaas",
  "insb",
  "pbse",
  "si",
  "ge",
  "bolometer",
  "unknown",
];

const apodizationOptions = [
  "Happ-Genzel",
  "Boxcar",
  "Blackman-Harris",
  "Norton-Beer",
  "triangular",
];

const cellTypeOptions = ["gas_cell", "liquid_cell", "demountable", "flow_cell", "cuvette", "ATR"];

const windowMaterialOptions = [
  "kbr",
  "nacl",
  "caf2",
  "baf2",
  "znse",
  "zns",
  "diamond",
  "ge",
  "si",
  "sapphire",
  "krs5",
  "agcl",
  "pe",
  "unknown",
];

// ============================================================================
// METADATA HELPERS
// ============================================================================

const addSpecies = () => {
  localMetadata.value.species.push({
    name: "",
    cas_number: "",
    molecular_formula: "",
    state: "unknown",
  });
  emitMetadata();
};

const removeSpecies = (index: number) => {
  localMetadata.value.species.splice(index, 1);
  emitMetadata();
};

const emitMetadata = () => {
  if (props.selectedNode) {
    // Keep metadata drafts in the same graph and validation path as parameters.
    localParams.value.metadata = structuredClone(toRaw(localMetadata.value));
    emitParams();
  }
};

// Watch for node changes to load existing metadata
watch(
  () => props.selectedNode,
  (node) => {
    if (node && node.params?.metadata) {
      localMetadata.value = withMetadataDefaults(node.params.metadata);
    } else {
      localMetadata.value = createEmptyMetadata();
    }
  },
  { immediate: true },
);

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
watch(
  () => props.selectedNode?.id,
  (newId, oldId) => {
    const node = props.selectedNode;
    if (node && newId !== oldId) {
      // Node selection changed - reset local params with defaults first, then stored values
      syncLocalParamsFromNode(node, { force: true });
    } else if (!node) {
      // Node deselected
      currentNodeId.value = null;
      localParams.value = {};
      lastSyncedParamsSignature.value = "";
    }
  },
  { immediate: true },
);

watch(
  () => props.selectedNode?.params,
  () => {
    const node = props.selectedNode;
    if (!node || node.id !== currentNodeId.value) return;
    syncLocalParamsFromNode(node);
  },
  { deep: true },
);

watch(
  () => [
    selectedNodeType.value,
    filterSampleCount.value,
    filterHasRealSampleLabels.value,
    filterSampleClasses.value.some((value) => value !== ""),
    sampleTableColumnOptions.value.map((option) => option.value).join("\u0001"),
  ],
  () => ensureSampleFilterDefaults(true),
);


// Contour plot options
const colorscaleOptions = ["Viridis", "Hot", "RdBu", "Blues", "Greys", "Jet", "Spectral"];
const contourPlotTypeOptions = ["heatmap", "contour", "surface"];

// Helper to format parameter labels (snake_case -> Title Case)
const formatParamLabel = (key: string): string => {
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
};

const axisOptions = computed(() => {
  const firstRow = Array.isArray(props.nodeOutput?.data?.[0]) ? props.nodeOutput.data[0] : [];
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
  return (
    [
      "output.plot",
      "model.pca",
      "data.file_load",
      "preprocess.normalize",
      "preprocess.scale",
    ].includes(selectedNodeType.value) &&
    Array.isArray(props.nodeOutput.data) &&
    props.nodeOutput.data.length > 0
  );
});

// Calculate plot points
const _plotPoints = computed(() => {
  if (!props.nodeOutput?.data) return [];

  const data = props.nodeOutput.data.filter((row): row is unknown[] => Array.isArray(row));
  const xIdx = localParams.value.x_axis ?? 0;
  const yIdx = localParams.value.y_axis ?? 1;

  const xValues = data.map((row) => row[xIdx]).filter((v): v is number => typeof v === "number");
  const yValues = data.map((row) => row[yIdx]).filter((v): v is number => typeof v === "number");

  if (xValues.length === 0 || yValues.length === 0) return [];

  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);

  const colors: Record<string, string> = {
    setosa: "#ef4444",
    versicolor: "#3b82f6",
    virginica: "#22c55e",
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
      color: colors[labelKey] || "#94a3b8",
    };
  });
});

// Plot points for full-size modal (larger coordinate space)
const _plotPointsFull = computed(() => {
  if (!props.nodeOutput?.data) return [];

  const data = props.nodeOutput.data.filter((row): row is unknown[] => Array.isArray(row));
  const xIdx = localParams.value.x_axis ?? 0;
  const yIdx = localParams.value.y_axis ?? 1;

  const xValues = data.map((row) => row[xIdx]).filter((v): v is number => typeof v === "number");
  const yValues = data.map((row) => row[yIdx]).filter((v): v is number => typeof v === "number");

  if (xValues.length === 0 || yValues.length === 0) return [];

  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);

  const colors: Record<string, string> = {
    setosa: "#ef4444",
    versicolor: "#3b82f6",
    virginica: "#22c55e",
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
      color: colors[labelKey] || "#3b82f6",
    };
  });
});

// Validate current parameters
const validateParams = () => {
  if (!props.selectedNode) {
    validationErrors.value = [];
    return;
  }

  const errors = workflowStore.validateNodeParams(props.selectedNode.type, localParams.value);
  const targetConflict = splitMethodTargetConflict(
    selectedNodeType.value === "data.train_test_split"
      ? String(localParams.value.split_method ?? "")
      : null,
    activeTargetType.value,
  );
  if (targetConflict) {
    errors.push({ param_name: "split_method", message: targetConflict });
  }
  // Named group holdout needs a grouping column on the input dataset. The
  // absence of a selected group is treated as a soft hint, not a validation
  // error, so the user can switch methods and fill the holdout list without
  // being blocked by the "local draft" save behavior.
  if (
    selectedNodeType.value === "data.train_test_split" &&
    String(localParams.value.split_method ?? "") === "group_holdout" &&
    !activeValidationGroupColumn.value
  ) {
    errors.push({
      param_name: "split_method",
      message:
        "Group holdout requires a grouping column bound to the input dataset; select one in the dataset's target and grouping fields.",
    });
  }
  validationErrors.value = errors;
};

// string_list parameters store an exact list; the editor presents it as one
// comma-separated line and parses it back the same way.
const stringListText = (value: unknown): string =>
  Array.isArray(value) ? value.map(String).join(", ") : String(value ?? "");

const updateStringList = (name: string, text: string | undefined) => {
  localParams.value[name] = (text ?? "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
  emitParams();
};

// A named group holdout is not complete until at least one group is selected.
// Keep this as a soft hint (yellow) rather than a hard validation error so the
// user can draft the method choice before naming the groups, and so saving
// does not produce the "local draft" toast before they have finished editing.
const isGroupHoldoutMissingSelection = computed(
  () =>
    selectedNodeType.value === "data.train_test_split" &&
    String(localParams.value.split_method ?? "") === "group_holdout" &&
    (!Array.isArray(localParams.value.held_out_groups) ||
      localParams.value.held_out_groups.length === 0),
);

watch(
  () => [
    props.selectedNode?.id,
    activeValidationGroupColumn.value,
    activeTargetType.value,
    localParams.value.split_method,
  ],
  () => validateParams(),
  { immediate: true },
);

// Emit params update
// Return the declared default for every parameter the current control values put
// out of scope, so a setting left behind by an earlier choice does not travel on
// in the saved graph behind a control that is no longer shown. The node
// canonicalizer applies the same rule as the single authority; doing it here keeps
// what is stored equal to what will run.
const resetParamsOutOfScope = (params: ParamsMap): ParamsMap => {
  const next = { ...params };
  for (const parameter of mappedMetadataParams.value) {
    if (!parameter.visible_when) continue;
    const inScope = Object.entries(parameter.visible_when).every(([control, admitted]) =>
      admitted.includes(String(next[control] ?? "")),
    );
    if (!inScope && parameter.default !== undefined) next[parameter.name] = parameter.default;
  }
  return next;
};

const emitParams = () => {
  if (props.selectedNode) {
    const scoped = resetParamsOutOfScope(localParams.value);
    if (stableParamSignature(scoped) !== stableParamSignature(localParams.value)) {
      localParams.value = scoped;
    }
    // Validate before emitting
    validateParams();
    const params = { ...localParams.value };
    lastSyncedParamsSignature.value = stableParamSignature(params);
    emit("update-params", props.selectedNode.id, params);
  }
};

// Execute node
const executeNode = () => {
  if (props.selectedNode && !props.executionDisabled) {
    // Validate before execution
    validateParams();

    // If there are validation errors, don't execute
    if (validationErrors.value.length > 0) {
      return;
    }

    // Emit params first to ensure latest values are saved before execution
    emit("update-params", props.selectedNode.id, resetParamsOutOfScope(localParams.value));
    // Then execute
    emit("execute-node", props.selectedNode.id);
  }
};

// Delete node
const deleteNode = () => {
  if (props.selectedNode) {
    emit("delete-node", props.selectedNode.id);
  }
};

// Run preview (before/after comparison)
const runPreview = async () => {
  if (!props.selectedNode || !isPreprocessingNode.value) return;

  // Validate params first
  validateParams();
  if (validationErrors.value.length > 0) {
    toast.add({
      severity: "error",
      summary: "Validation Error",
      detail: "Please fix parameter errors before previewing",
      life: 3000,
    });
    return;
  }

  try {
    // Get the input data from the first input connection
    const inputConn = props.inputConnections[0];
    if (!inputConn || !inputConn.data) {
      toast.add({
        severity: "warn",
        summary: "No Input Data",
        detail: "This node needs input data to preview. Run the previous node first.",
        life: 4000,
      });
      return;
    }

    // Store original data
    previewData.value = {
      original: inputConn.data,
      processed: null,
    };

    // Show modal with loading state
    showPreviewModal.value = true;

    // Execute trial run with current params
    const nodeIdStr = String(props.selectedNode.id);
    const result = await workflowStore.executeTrial(nodeIdStr, localParams.value);

    if (result.status === "error") {
      toast.add({
        severity: "error",
        summary: "Preview Failed",
        detail: result.error || "Could not generate preview",
        life: 5000,
      });
      showPreviewModal.value = false;
      return;
    }

    // Store processed data
    previewData.value.processed = result.result;
  } catch (error: unknown) {
    console.error("[WorkflowInspector] Preview error:", error);
    toast.add({
      severity: "error",
      summary: "Preview Error",
      detail: getErrorMessage(error, "Failed to generate preview"),
      life: 5000,
    });
    showPreviewModal.value = false;
  }
};

// Open node detail in a temporary builder sheet for trial execution.
const STORAGE_KEY = "node_detail_data";

const openToRunTrials = () => {
  if (!props.selectedNode) return;

  // Build input data summary from first connected node's output
  let inputData = null;
  if (props.inputConnections.length > 0) {
    const firstInput = props.inputConnections[0];
    if (firstInput.data?.data) {
      const data = firstInput.data.data;
      inputData = {
        shape: Array.isArray(data)
          ? [data.length, Array.isArray(data[0]) ? data[0].length : 1]
          : null,
        source: `${firstInput.nodeLabel} (${firstInput.nodeType})`,
        dataType: Array.isArray(data) ? "dataset" : typeof data,
        data: data, // Include actual data for preview
      };
    }
  }

  // Get workflow nodes and edges from the store for isolated trial execution.
  const workflowNodes = workflowStore.nodes.map((node) => ({
    id: node.id,
    type: node.type,
    params: node.params || {},
  }));
  const workflowEdges = workflowStore.edges.map((edge) => ({
    from: edge.from,
    to: edge.to,
    fromPort: edge.fromPort || "default",
    toPort: edge.toPort || "default",
  }));

  // Pick the ports we want to preserve across reduced-tier fallbacks.
  // Plot computeds on the Detail View read these directly (loadings for
  // PCA/PLS/PLSDA; St/H/A for MCR/NMF/ICA/SIMPLISMA). They're all small
  // matrices (n_components × n_features) and stripping them makes those
  // plots render empty even when the primary payload fits.
  const PRESERVED_PORT_NAMES = new Set([
    "loadings",
    "St",
    "H",
    "A",
    ...(nodeMetadata.value?.presentation_contract?.payload.presentations.flatMap(
      (presentation) => presentation.source_ports,
    ) ?? []),
  ]);

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
      if (nt.includes("pca")) {
        delete lightMetadata.loadings;
        delete lightMetadata.wavenumbers;
      }
      // Remove large arrays from decomposition methods
      if (["model.simplisma", "model.nmf", "model.ica", "model.mcr_als"].includes(nt)) {
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
      label: props.selectedNode.label || getNodeLabel(props.selectedNode.type),
      workflowId: workflowStore.workflowId,
      params: { ...localParams.value },
      output: props.nodeOutput
        ? {
            // For output.* nodes in reduced tiers, top-level data duplicates
            // the Plotly traces already stripped from metadata — omit it too.
            data:
              includeData && !(level !== "full" && nt.startsWith("output."))
                ? props.nodeOutput.data
                : null,
            metadata: metadata,
            plots: props.nodeOutput.plots || null,
            // Detailed View must receive the same authoritative shape and
            // content-category projection shown by the Inspector.
            descriptor: props.nodeOutput.descriptor ?? null,
            ports: buildReducedPorts(level, props.nodeOutput.ports),
            primary_port: props.nodeOutput.primary_port || null,
            // Carry the executor-lifted artifact UID through to sessionStorage
            // so the NodeDetailView's "Saved Model Artifact" section can render
            // (gated on `v-if="modelId"` after the OutputPanel inject chain).
            // Without this, the section is invisible on every run regardless of
            // whether the artifact was actually persisted.
            model_id: props.nodeOutput.model_id ?? null,
          }
        : null,
      presentationContract: nodeMetadata.value?.presentation_contract ?? null,
      selectedPresentationId: selectedPresentation.value?.presentation.presentation_id ?? null,
      // Include input connections with their data
      inputConnections: props.inputConnections.map((conn) => ({
        nodeId: conn.nodeId,
        nodeType: conn.nodeType,
        icon: NODE_ICONS[conn.nodeType] || "📦",
        label: conn.nodeLabel,
        port: conn.port,
        toPort: conn.toPort,
        // Embedded trial sheets are an in-memory workbench surface. Retain
        // each typed input payload at the full tier so plot adapters can join
        // a model's predictions to the actual target connected at `y`.
        // Reduced/session-storage tiers intentionally omit these arrays.
        data: level === "full" ? (conn.data ?? null) : null,
      })),
      inputData: includeData ? inputData : inputData ? { ...inputData, data: null } : null,
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
  parameters: NodeParameterMetadata[],
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
    "baseline.penalized_ls": [
      {
        name: "lam",
        label: "Lambda (λ)",
        type: "number",
        min: 1000,
        max: 1000000,
        step: 1000,
        default: 100000,
      },
      {
        name: "p",
        label: "Asymmetry (p)",
        type: "number",
        min: 0.001,
        max: 0.1,
        step: 0.001,
        default: 0.001,
      },
    ],
    "preprocess.smooth": [
      {
        name: "window",
        label: "Window Size",
        type: "number",
        min: 5,
        max: 51,
        step: 2,
        default: 11,
      },
      {
        name: "poly",
        label: "Polynomial Order",
        type: "number",
        min: 1,
        max: 5,
        step: 1,
        default: 2,
      },
    ],
    "model.pca": [
      {
        name: "n_components",
        label: "Number of Components",
        type: "text",
        default: "5",
        description:
          "Number of components: integer (e.g., '5'), 'mle' (auto-select via Maximum Likelihood), or float 0-1 (e.g., '0.95' for 95% variance)",
      },
      {
        name: "standardized",
        label: "Standardize (mean center + unit variance)",
        type: "boolean",
        default: false,
      },
      { name: "scaled", label: "Scale (unit variance)", type: "boolean", default: false },
    ],
    "model.fitted_pls": [
      {
        name: "n_components",
        label: "Number of Components",
        type: "number",
        min: 1,
        max: 15,
        step: 1,
        default: 3,
      },
    ],
    "model.mcr_als": [
      {
        name: "n_components",
        label: "Number of Components",
        type: "number",
        min: 1,
        max: 10,
        step: 1,
        default: 3,
      },
      {
        name: "normSpec",
        label: "Spectra Normalization",
        type: "select",
        default: "euclid",
        options: [
          { label: "Euclidean norm", value: "euclid" },
          { label: "Maximum intensity", value: "max" },
          { label: "None", value: "none" },
        ],
      },
      {
        name: "max_iter",
        label: "Maximum Iterations",
        type: "number",
        min: 10,
        max: 1000,
        step: 10,
        default: 200,
      },
      {
        name: "tol",
        label: "Convergence Tolerance",
        type: "number",
        min: 1e-8,
        step: 1e-6,
        default: 1e-5,
      },
      {
        name: "non_negative_C",
        label: "Non-negative Concentrations",
        type: "boolean",
        default: true,
      },
      { name: "non_negative_St", label: "Non-negative Spectra", type: "boolean", default: true },
      {
        name: "validation_target_index",
        label: "Validation Target",
        type: "number",
        min: 1,
        step: 1,
        default: 1,
      },
      {
        name: "validation_component_index",
        label: "Validation MCR Component",
        type: "number",
        min: 1,
        step: 1,
        default: 1,
      },
    ],
    "stats.summary": [
      {
        name: "max_samples",
        label: "Max Samples",
        type: "number",
        min: 10,
        max: 500,
        step: 10,
        default: 50,
      },
    ],
    "output.contour": [
      {
        name: "colorscale",
        label: "Color Scale",
        type: "select",
        options: colorscaleOptions.map((c) => ({ label: c, value: c })),
      },
      {
        name: "plot_type",
        label: "Plot Type",
        type: "select",
        options: contourPlotTypeOptions.map((t) => ({ label: t, value: t })),
      },
      { name: "reverse_x", label: "Reverse X-axis", type: "boolean", default: true },
      { name: "transpose", label: "Transpose Data", type: "boolean", default: false },
    ],
    "output.export": [{ name: "filename", label: "Filename", type: "text", default: "output.csv" }],
  };

  return definitions[nodeType] || [];
};

// Listen for storage changes from the detail view (when user saves)
const handleStorageChange = (event: StorageEvent) => {
  if (event.key === STORAGE_KEY && event.newValue) {
    try {
      const updatedData = JSON.parse(event.newValue);
      const messageWorkflowId = updatedData.workflowId ?? null;
      const currentWorkflowId = workflowStore.workflowId ?? null;
      if (
        updatedData._saved &&
        updatedData.id === props.selectedNode?.id &&
        (messageWorkflowId == null ||
          currentWorkflowId == null ||
          Number(messageWorkflowId) === Number(currentWorkflowId))
      ) {
        syncLocalParamsFromExternal(
          updatedData.type || props.selectedNode?.type || "",
          updatedData.params,
        );
      }
    } catch (e) {
      console.error("Failed to parse updated node data:", e);
    }
  }
};

// BroadcastChannel for cross-tab communication (more reliable than storage events)
// Note: Execution requests are handled in WorkflowBuilderContent which has access to all nodes.
// This inspector only handles param updates to keep localParams in sync when a DetailView
// updates params for the currently selected node.
const broadcastChannel = ref<BroadcastChannel | null>(null);

const handleBroadcastMessage = async (event: MessageEvent) => {
  const { type, nodeId, params, nodeType, workflowId } = event.data;

  // Only handle param updates for the currently selected node
  // (Execution requests are handled by WorkflowBuilderContent)
  if (
    type === "node_params_updated" &&
    nodeId === props.selectedNode?.id &&
    (workflowId == null ||
      workflowStore.workflowId == null ||
      Number(workflowId) === Number(workflowStore.workflowId))
  ) {
    syncLocalParamsFromExternal(nodeType || props.selectedNode?.type || "", params, {
      fetchReferenceDatasets: true,
    });
  }
};

onMounted(() => {
  window.addEventListener("storage", handleStorageChange);

  // Set up BroadcastChannel for more reliable cross-tab communication
  try {
    broadcastChannel.value = new BroadcastChannel("workflow_node_updates");
    broadcastChannel.value.onmessage = handleBroadcastMessage;
  } catch {
    // BroadcastChannel not supported in this browser
    console.warn("BroadcastChannel not supported, falling back to storage events only");
  }
});

onUnmounted(() => {
  window.removeEventListener("storage", handleStorageChange);

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
  transition:
    width 0.3s ease,
    opacity 0.3s ease;
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

.node-type,
.node-id {
  font-size: 0.7rem;
  color: #64748b;
}

.node-type {
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  overflow-wrap: anywhere;
}

.header-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

/* Inspector quick-view action buttons — unified style across the four
 * buttons that sit on the dark inspector chrome (Open trial / Close X
 * in the header, Run Node / Delete in the action bar). White text on
 * the dark slate background showing through, with a blue (primary)
 * outline. Overrides PrimeVue's filled/secondary defaults that would
 * otherwise paint a white background on a dark surface. */
:deep(.inspector-action-btn.p-button) {
  background: transparent !important;
  color: #ffffff !important;
  border: 1px solid #3b82f6 !important;
  box-shadow: none !important;
}

:deep(.inspector-action-btn.p-button .p-button-icon),
:deep(.inspector-action-btn.p-button .p-button-label) {
  color: #ffffff !important;
}

:deep(.inspector-action-btn.p-button:hover),
:deep(.inspector-action-btn.p-button:focus),
:deep(.inspector-action-btn.p-button:enabled:hover),
:deep(.inspector-action-btn.p-button:enabled:focus) {
  background: rgba(59, 130, 246, 0.18) !important;
  border-color: #60a5fa !important;
}

:deep(.inspector-action-btn.p-button:disabled) {
  opacity: 0.45;
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

.inspector-help-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 32px;
  width: 32px;
  min-height: 31px;
  padding: 0;
  border: 1px solid #3b82f6;
  border-radius: 6px;
  color: #ffffff;
  font-family: inherit;
  font-size: 0.875rem;
  font-weight: 600;
  line-height: 1;
  text-decoration: none;
}

.inspector-help-link:hover,
.inspector-help-link:focus-visible {
  border-color: #60a5fa;
  background: rgba(59, 130, 246, 0.18);
  color: #ffffff;
  outline: none;
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

.param-warning {
  font-size: 0.7rem;
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.1);
  padding: 4px 8px;
  border-radius: 4px;
  margin-top: 4px;
}

.dataset-target-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid rgba(99, 102, 241, 0.24);
  border-radius: 6px;
  background: rgba(99, 102, 241, 0.1);
  color: #c7d2fe;
  font-size: 0.75rem;
  line-height: 1.35;
}

.dataset-target-note--warn {
  border-color: rgba(245, 158, 11, 0.32);
  background: rgba(245, 158, 11, 0.12);
  color: #fde68a;
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

.filter-samples-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.filter-empty-state {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
  text-align: center;
  padding: 18px 12px;
  color: #94a3b8;
  background: rgba(15, 23, 42, 0.45);
  border: 1px dashed #475569;
  border-radius: 6px;
}

.filter-empty-state i {
  color: #818cf8;
  font-size: 1.25rem;
}

.filter-empty-state span {
  color: #64748b;
  font-size: 0.78rem;
}

.filter-dataset-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.filter-dataset-summary > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 9px 10px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(129, 140, 248, 0.22);
  border-radius: 6px;
}

.summary-kicker {
  color: #94a3b8;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.filter-dataset-summary strong {
  color: #e0e7ff;
  font-size: 0.9rem;
}

.filter-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.filter-scope-warning {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 11px;
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 6px;
  background: rgba(59, 130, 246, 0.1);
  color: #bfdbfe;
  font-size: 0.76rem;
  line-height: 1.35;
}

.filter-scope-warning i {
  margin-top: 1px;
}

.filter-mode-card {
  display: grid;
  grid-template-columns: 18px 1fr;
  grid-template-areas:
    "icon label"
    "icon hint";
  column-gap: 8px;
  row-gap: 1px;
  width: 100%;
  min-height: 58px;
  padding: 9px 10px;
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.55);
  border: 1px solid #334155;
  border-radius: 6px;
  text-align: left;
  cursor: pointer;
}

.filter-mode-card:hover:not(:disabled) {
  border-color: rgba(129, 140, 248, 0.6);
  background: rgba(30, 41, 59, 0.72);
}

.filter-mode-card.active {
  border-color: #818cf8;
  box-shadow: inset 0 0 0 1px rgba(129, 140, 248, 0.35);
  background: rgba(67, 56, 202, 0.22);
}

.filter-mode-card:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.filter-mode-card i {
  grid-area: icon;
  align-self: start;
  margin-top: 2px;
  color: #a5b4fc;
  font-size: 0.9rem;
}

.mode-label {
  grid-area: label;
  font-weight: 600;
  font-size: 0.8rem;
}

.mode-hint {
  grid-area: hint;
  color: #94a3b8;
  font-size: 0.68rem;
  line-height: 1.2;
}

.filter-rule-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.45);
  border: 1px solid #334155;
  border-radius: 6px;
}

.filter-quick-actions,
.filter-value-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-value-search {
  flex: 1 1 150px;
  min-width: 0;
}

.filter-value-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 180px;
  overflow: auto;
  padding: 5px;
  background: rgba(2, 6, 23, 0.35);
  border: 1px solid rgba(51, 65, 85, 0.9);
  border-radius: 6px;
}

.filter-value-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 4px 6px;
  color: #cbd5e1;
  border-radius: 4px;
  cursor: pointer;
}

.filter-value-row:hover {
  background: rgba(99, 102, 241, 0.12);
}

.filter-value-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.filter-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.26);
  border-radius: 6px;
  color: #d1fae5;
}

.filter-preview.warning {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.35);
  color: #fde68a;
}

.filter-preview-main {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
}

.filter-preview-list {
  display: flex;
  gap: 6px;
  min-width: 0;
  font-size: 0.72rem;
  color: #a7f3d0;
}

.filter-preview.warning .filter-preview-list {
  color: #fcd34d;
}

.filter-preview-list.muted {
  color: #94a3b8;
}

.filter-preview-list em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-style: normal;
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
  font-family: "SF Mono", Monaco, monospace;
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

.scientific-result-dropdown {
  width: 100%;
  min-width: 0;
}

.scientific-result-dropdown :deep(.p-dropdown-label) {
  min-width: 0;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.scientific-result-dropdown-panel .p-dropdown-item) {
  justify-content: flex-start;
  text-align: left;
  white-space: normal;
}

.persisted-preview-notice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  color: #bfdbfe;
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 6px;
  font-size: 0.75rem;
  line-height: 1.35;
}

.group-split-guidance {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  margin-bottom: 0.75rem;
  padding: 0.7rem 0.75rem;
  border: 1px solid #2563eb;
  border-radius: 6px;
  background: rgb(30 64 175 / 18%);
  color: #dbeafe;
  font-size: 0.78rem;
  line-height: 1.35;
}

.group-split-guidance i {
  margin-top: 0.12rem;
  color: #60a5fa;
}

.group-split-guidance div {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.grouped-split-evidence p {
  margin: 0.35rem 0;
  color: #e2e8f0;
  line-height: 1.4;
}

.group-split-method,
.group-split-digest {
  display: block;
  color: #94a3b8;
  font-size: 0.75rem;
}

.group-split-digest {
  width: fit-content;
  margin-top: 0.35rem;
  border-bottom: 1px dotted #64748b;
  cursor: help;
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
  font-family: "SF Mono", Monaco, monospace;
}

.diagnostics-value {
  font-size: 0.8rem;
  color: #f8fafc;
  text-align: right;
  font-family: "SF Mono", Monaco, monospace;
  max-width: 55%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  font-family: "SF Mono", Monaco, monospace;
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
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
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
  font-family: "SF Mono", "Consolas", monospace;
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
  font-family: "SF Mono", Monaco, "Courier New", monospace;
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
  font-family: "SF Mono", Monaco, "Courier New", monospace;
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
  font-family: "SF Mono", Monaco, monospace;
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
  font-family: "SF Mono", "Consolas", monospace;
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
  font-family: "SF Mono", "Consolas", monospace;
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
  font-family: "SF Mono", "Consolas", monospace;
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
