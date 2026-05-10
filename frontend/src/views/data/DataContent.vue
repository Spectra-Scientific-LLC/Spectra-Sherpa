<template>
  <section class="data-content">
    <div class="section-header">
      <div>
        <h1>Data</h1>
        <p class="section-subtitle">
          Import, inspect, and prepare spectral data for analysis
        </p>
      </div>
      <div class="header-actions">
        <Button
          label="Refresh"
          icon="pi pi-refresh"
          class="p-button-outlined p-button-sm"
          :loading="dataStore.catalogLoading"
          @click="refresh"
        />
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab">
      <!-- ======================== LOAD TAB ======================== -->
      <TabPanel header="Load" :disabled="isGuidedExampleSession">
        <!-- ============ REFERENCE DATASETS (top, prominent) ============ -->
        <div class="ref-catalog-section">
          <h3 class="ref-catalog-title">
            <i class="pi pi-database"></i>
            Reference Datasets
          </h3>

          <div v-if="dataStore.referenceCatalogLoading" class="empty-state-sm">
            <ProgressSpinner style="width: 24px; height: 24px" />
            Loading catalog...
          </div>

          <div v-else-if="dataStore.referenceCatalogError" class="ref-catalog-error">
            <i class="pi pi-exclamation-triangle"></i>
            <span>{{ dataStore.referenceCatalogError }}</span>
            <Button
              label="Retry"
              icon="pi pi-refresh"
              class="p-button-sm p-button-outlined"
              :loading="dataStore.referenceCatalogLoading"
              @click="dataStore.fetchReferenceCatalog()"
            />
          </div>

          <div v-else-if="dataStore.referenceCatalog" class="ref-catalog-groups">
            <!-- Eigenvector -->
            <Panel
              :toggleable="true"
              :collapsed="eigenvectorCollapsed"
              @update:collapsed="eigenvectorCollapsed = $event"
              class="ref-group-panel"
            >
              <template #header>
                <span class="ref-panel-header">
                  <i class="pi pi-chart-bar"></i>
                  Eigenvector Research (NIR)
                  <Tag :value="String(dataStore.referenceCatalog.eigenvector.length)" severity="info" rounded />
                </span>
              </template>
              <div
                v-for="ds in dataStore.referenceCatalog.eigenvector"
                :key="ds.name"
                class="ref-dataset-item"
                :class="{ selected: selectedRefDatasets.has(dsKey(ds)) }"
                @click="toggleRefDataset(ds)"
              >
                <Checkbox
                  :modelValue="selectedRefDatasets.has(dsKey(ds))"
                  :binary="true"
                  @click.stop
                  @update:model-value="toggleRefDataset(ds)"
                />
                <span class="ref-ds-label">{{ ds.label }}</span>
                <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
                <Button
                  icon="pi pi-search"
                  class="p-button-text p-button-sm p-button-rounded ref-explore-btn"
                  title="Explore"
                  @click.stop="onExploreReference(ds.source, ds.name)"
                />
              </div>
            </Panel>

            <!-- OES Datasets -->
            <Panel
              v-if="dataStore.referenceCatalog?.oes?.length"
              :toggleable="true"
              :collapsed="oesCollapsed"
              @update:collapsed="oesCollapsed = $event"
              class="ref-group-panel"
            >
              <template #header>
                <span class="ref-panel-header">
                  <i class="pi pi-bolt"></i>
                  OES Datasets
                  <Tag :value="String(dataStore.referenceCatalog.oes.length)" severity="info" rounded />
                </span>
              </template>
              <div
                v-for="ds in dataStore.referenceCatalog.oes"
                :key="ds.name"
                class="ref-dataset-item"
                :class="{ selected: selectedRefDatasets.has(dsKey(ds)) }"
                @click="toggleRefDataset(ds)"
              >
                <Checkbox
                  :modelValue="selectedRefDatasets.has(dsKey(ds))"
                  :binary="true"
                  @click.stop
                  @update:model-value="toggleRefDataset(ds)"
                />
                <span class="ref-ds-label">{{ ds.label }}</span>
                <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
                <Button
                  icon="pi pi-search"
                  class="p-button-text p-button-sm p-button-rounded ref-explore-btn"
                  title="Explore"
                  @click.stop="onExploreReference(ds.source, ds.name)"
                />
              </div>
            </Panel>

            <!-- SpectroChemPy -->
            <Panel
              :toggleable="true"
              :collapsed="scpCollapsed"
              @update:collapsed="scpCollapsed = $event"
              class="ref-group-panel"
            >
              <template #header>
                <span class="ref-panel-header">
                  <i class="pi pi-wave-pulse"></i>
                  SpectroChemPy Datasets
                  <Tag :value="String(dataStore.referenceCatalog.spectrochempy.length)" severity="info" rounded />
                </span>
              </template>
              <template v-for="cat in scpCategories" :key="cat">
                <div class="ref-scp-category">{{ scpCategoryLabel(cat) }}</div>
                <div
                  v-for="ds in scpByCategory(cat)"
                  :key="ds.name"
                  class="ref-dataset-item"
                  :class="{ selected: selectedRefDatasets.has(dsKey(ds)) }"
                  @click="toggleRefDataset(ds)"
                >
                  <Checkbox
                    :modelValue="selectedRefDatasets.has(dsKey(ds))"
                    :binary="true"
                    @click.stop
                    @update:model-value="toggleRefDataset(ds)"
                  />
                  <span class="ref-ds-label">{{ ds.label }}</span>
                  <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
                  <Button
                    icon="pi pi-search"
                    class="p-button-text p-button-sm p-button-rounded ref-explore-btn"
                    title="Explore"
                    @click.stop="onExploreReference(ds.source || 'spectrochempy', ds.name)"
                  />
                </div>
              </template>
            </Panel>

            <!-- sklearn -->
            <Panel
              :toggleable="true"
              :collapsed="sklearnCollapsed"
              @update:collapsed="sklearnCollapsed = $event"
              class="ref-group-panel"
            >
              <template #header>
                <span class="ref-panel-header">
                  <i class="pi pi-cog"></i>
                  Scikit-learn Datasets
                  <Tag :value="String(dataStore.referenceCatalog.sklearn.length)" severity="info" rounded />
                </span>
              </template>
              <div
                v-for="ds in dataStore.referenceCatalog.sklearn"
                :key="ds.name"
                class="ref-dataset-item"
                :class="{ selected: selectedRefDatasets.has(dsKey(ds)) }"
                @click="toggleRefDataset(ds)"
              >
                <Checkbox
                  :modelValue="selectedRefDatasets.has(dsKey(ds))"
                  :binary="true"
                  @click.stop
                  @update:model-value="toggleRefDataset(ds)"
                />
                <span class="ref-ds-label">{{ ds.label }}</span>
                <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
                <Button
                  icon="pi pi-search"
                  class="p-button-text p-button-sm p-button-rounded ref-explore-btn"
                  title="Explore"
                  @click.stop="onExploreReference(ds.source, ds.name)"
                />
              </div>
            </Panel>
          </div>

          <!-- Action bar -->
          <div class="ref-action-bar" v-if="selectedRefDatasets.size > 0">
            <span class="ref-selection-count">{{ selectedRefDatasets.size }} selected</span>
            <Button
              label="Add to My Dataset"
              icon="pi pi-plus"
              data-action="import_data"
              class="p-button-sm"
              :disabled="!dataStore.activeExperimentId"
              :loading="importing"
              @click="onImportSelectedDatasets"
            />
            <small v-if="!dataStore.activeExperimentId" class="ref-hint">
              Create or select a dataset first
            </small>
          </div>
        </div>

        <!-- ============ MY DATASET (middle) ============ -->
        <div class="my-dataset-section">
          <div class="my-dataset-header">
            <h3 class="my-dataset-title">
              <i class="pi pi-folder"></i>
              My Dataset
            </h3>
            <div class="my-dataset-actions">
              <Button
                label="New Dataset"
                icon="pi pi-plus"
                class="p-button-sm"
                @click="showCreateDialog = true"
              />
              <Button
                label="Delete Dataset"
                icon="pi pi-trash"
                class="p-button-sm p-button-danger p-button-outlined"
                :disabled="!dataStore.activeExperimentId"
                @click="showDeleteExpDialog = true"
              />
              <Button
                label="Upload File"
                icon="pi pi-upload"
                data-action="import_data"
                class="p-button-text p-button-sm"
                :disabled="!dataStore.activeExperimentId"
                @click="showUploadDialog = true"
              />
            </div>
          </div>

          <div class="load-panels">
            <!-- Dataset list (left) -->
            <div class="experiment-list-panel">
              <DataTable
                :value="dataStore.experiments"
                :loading="dataStore.experimentsLoading"
                selectionMode="single"
                :selection="selectedExperiment"
                @update:selection="onExperimentSelect"
                dataKey="id"
                :rows="20"
                scrollable
                scrollHeight="400px"
                size="small"
                stripedRows
                class="exp-table"
              >
                <template #empty>
                  <div class="empty-state-sm">No datasets yet</div>
                </template>
                <Column field="name" header="Name" :sortable="true" />
                <Column field="file_count" header="Files" :sortable="true" style="width: 70px" />
                <Column header="Created" :sortable="true" style="width: 180px">
                  <template #body="{ data }">
                    {{ formatDate(data.created_at) }}
                  </template>
                </Column>
              </DataTable>
            </div>

            <!-- Files panel (right) -->
            <div class="files-panel">
              <div v-if="!dataStore.activeExperimentId" class="empty-state">
                <i class="pi pi-arrow-left"></i>
                <span>Select a dataset to view its files</span>
              </div>

              <div v-else-if="dataStore.experimentFilesLoading" class="empty-state">
                <ProgressSpinner style="width: 28px; height: 28px" />
                <span>Loading files...</span>
              </div>

              <div v-else-if="dataStore.experimentFiles.length === 0" class="empty-state">
                <i class="pi pi-inbox"></i>
                <span>No files in this dataset</span>
                <small>Select reference datasets above and click "Add to My Dataset"</small>
              </div>

              <div v-else class="file-groups">
                <div
                  v-for="stage in fileStages"
                  :key="stage.key"
                  class="file-stage"
                >
                  <div
                    v-if="filesForStage(stage.key).length > 0"
                    class="stage-section"
                  >
                    <h4 class="stage-header">
                      <i :class="stage.icon"></i>
                      {{ stage.label }} ({{ filesForStage(stage.key).length }})
                    </h4>
                    <div class="file-list">
                      <div
                        v-for="file in filesForStage(stage.key)"
                        :key="file.id"
                        class="file-row"
                      >
                        <div class="file-info">
                          <span class="file-name">{{ extractFileName(file.file_path) }}</span>
                          <span v-if="file.file_size_bytes" class="file-size">
                            {{ formatFileSize(file.file_size_bytes) }}
                          </span>
                        </div>
                        <div class="file-actions">
                          <Button
                            icon="pi pi-search"
                            class="p-button-text p-button-sm p-button-rounded"
                            title="Inspect"
                            @click="onInspectFile(file)"
                          />
                          <Button
                            icon="pi pi-download"
                            class="p-button-text p-button-sm p-button-rounded"
                            title="Download"
                            @click="dataStore.downloadFile(file.id, extractFileName(file.file_path))"
                          />
                          <Button
                            icon="pi pi-trash"
                            class="p-button-text p-button-sm p-button-rounded p-button-danger"
                            title="Delete"
                            @click="confirmDeleteFile(file)"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- NIST Library (collapsible, de-emphasized) -->
        <Panel
          header="Reference Library"
          :toggleable="true"
          :collapsed="libraryCollapsed"
          @update:collapsed="libraryCollapsed = $event"
          class="library-panel"
        >
          <div class="library-toolbar">
            <span class="p-input-icon-left" style="width: 300px">
              <i class="pi pi-search" />
              <InputText
                v-model="librarySearch"
                placeholder="Search compounds..."
                class="p-inputtext-sm"
                style="width: 100%"
              />
            </span>
          </div>
          <DataTable
            :value="filteredLibrary"
            :rows="10"
            :paginator="filteredLibrary.length > 10"
            size="small"
            stripedRows
            class="library-table"
          >
            <template #empty>
              <div class="empty-state-sm">No library entries</div>
            </template>
            <Column field="compound_name" header="Compound" :sortable="true" />
            <Column field="cas_number" header="CAS Number" style="width: 140px" />
            <Column field="resolution" header="Resolution" style="width: 100px" />
            <Column field="file_path" header="File" style="width: 160px">
              <template #body="{ data }">
                <span class="file-size">{{ data.file_path.split('/').pop() }}</span>
              </template>
            </Column>
          </DataTable>
        </Panel>
      </TabPanel>

      <!-- ======================== EXPLORE TAB ======================== -->
      <TabPanel header="Explore">
        <div v-if="dataStore.fileInfoLoading" class="explore-loading">
          <ProgressSpinner style="width: 36px; height: 36px" />
          <span>Analyzing file...</span>
        </div>

        <div v-else-if="dataStore.fileInfoError" class="explore-error">
          <i class="pi pi-exclamation-triangle"></i>
          <span>{{ dataStore.fileInfoError }}</span>
          <Button
            v-if="!isGuidedExampleSession"
            label="Back to Load"
            icon="pi pi-arrow-left"
            class="p-button-sm p-button-outlined"
            @click="activeTab = 0"
          />
        </div>

        <div v-else-if="dataStore.catalogDatasetLoading" class="explore-loading">
          <ProgressSpinner style="width: 36px; height: 36px" />
          <span>Loading dataset info...</span>
        </div>

        <div v-else-if="dataStore.catalogDatasetError" class="explore-error">
          <i class="pi pi-exclamation-triangle"></i>
          <span>{{ dataStore.catalogDatasetError }}</span>
          <Button
            v-if="!isGuidedExampleSession"
            label="Back to Load"
            icon="pi pi-arrow-left"
            class="p-button-sm p-button-outlined"
            @click="activeTab = 0; dataStore.clearCatalogExploration()"
          />
        </div>

        <div v-else-if="dataStore.catalogDatasetInfo" class="explore-content">
          <!-- Catalog dataset info card -->
          <div class="explore-header">
            <div class="explore-title">
              <i class="pi pi-database"></i>
              <span>{{ dataStore.catalogDatasetInfo.label }}</span>
              <Tag
                v-if="dataStore.catalogDatasetInfo.technique"
                :value="dataStore.catalogDatasetInfo.technique"
                severity="info"
              />
            </div>
            <div class="explore-actions">
              <Button
                v-if="!isGuidedExampleSession"
                label="Back to Load"
                icon="pi pi-arrow-left"
                class="p-button-text p-button-sm"
                @click="activeTab = 0; dataStore.clearCatalogExploration()"
              />
              <Button
                label="Next: Workflow"
                icon="pi pi-arrow-right"
                iconPos="right"
                class="p-button-sm"
                @click="goToWorkflow"
              />
            </div>
          </div>

          <div class="explore-panels">
            <!-- Metadata card -->
            <div class="metadata-panel">
              <h4 class="panel-title">Dataset Metadata</h4>
              <div class="metadata-table">
                <div v-if="dataStore.catalogDatasetInfo.source" class="meta-row">
                  <span class="meta-key">Source</span>
                  <span class="meta-val">{{ dataStore.catalogDatasetInfo.source }}</span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.file_metadata?.name" class="meta-row">
                  <span class="meta-key">Title</span>
                  <span class="meta-val">{{ dataStore.catalogDatasetInfo.file_metadata.name }}</span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.file_metadata?.author" class="meta-row">
                  <span class="meta-key">Author</span>
                  <span class="meta-val">{{ dataStore.catalogDatasetInfo.file_metadata.author }}</span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.file_metadata?.date" class="meta-row">
                  <span class="meta-key">Date</span>
                  <span class="meta-val">{{ dataStore.catalogDatasetInfo.file_metadata.date }}</span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.n_samples" class="meta-row">
                  <span class="meta-key">Samples</span>
                  <span class="meta-val">{{ dataStore.catalogDatasetInfo.n_samples.toLocaleString() }}</span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.n_features" class="meta-row">
                  <span class="meta-key">Features</span>
                  <span class="meta-val">{{ dataStore.catalogDatasetInfo.n_features.toLocaleString() }}</span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.wavelength_min != null" class="meta-row">
                  <span class="meta-key">Spectral Range</span>
                  <span class="meta-val">
                    {{ dataStore.catalogDatasetInfo.wavelength_min.toFixed(1) }} &ndash;
                    {{ dataStore.catalogDatasetInfo.wavelength_max?.toFixed(1) }}
                    {{ dataStore.catalogDatasetInfo.x_units || '' }}
                  </span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.task_type" class="meta-row">
                  <span class="meta-key">Task Type</span>
                  <span class="meta-val">{{ dataStore.catalogDatasetInfo.task_type }}</span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.feature_names?.length" class="meta-row">
                  <span class="meta-key">Features</span>
                  <span class="meta-val meta-wrap">{{ dataStore.catalogDatasetInfo.feature_names.join(', ') }}</span>
                </div>
                <div v-if="dataStore.catalogDatasetInfo.target_names?.length" class="meta-row">
                  <span class="meta-key">Classes</span>
                  <span class="meta-val">{{ dataStore.catalogDatasetInfo.target_names.join(', ') }}</span>
                </div>
                <div class="meta-row">
                  <span class="meta-key">X-Axis</span>
                  <Dropdown
                    v-model="editXTitle"
                    :options="xTitleOptions"
                    editable
                    placeholder="Select or type..."
                    class="meta-dropdown"
                  />
                </div>
                <div class="meta-row">
                  <span class="meta-key">X Units</span>
                  <Dropdown
                    v-model="editXUnits"
                    :options="xUnitsOptions"
                    editable
                    placeholder="Units"
                    class="meta-dropdown"
                  />
                </div>
                <div class="meta-row">
                  <span class="meta-key">Y-Axis</span>
                  <Dropdown
                    v-model="editYTitle"
                    :options="yTitleOptions"
                    editable
                    placeholder="Select or type..."
                    class="meta-dropdown"
                  />
                </div>
                <div class="meta-row">
                  <span class="meta-key">Time Series</span>
                  <InputSwitch v-model="isTimeSeriesToggle" />
                </div>
              </div>
            </div>

            <!-- Properties table (Eigenvector) or Description panel -->
            <div class="metadata-panel">
              <div v-if="dataStore.catalogDatasetInfo.property_stats?.length">
                <h4 class="panel-title">Reference Properties</h4>
                <DataTable
                  :value="dataStore.catalogDatasetInfo.property_stats"
                  size="small"
                  stripedRows
                  class="prop-stats-table"
                >
                  <Column field="name" header="Property" />
                  <Column header="Range">
                    <template #body="{ data }">
                      <span v-if="data.min != null">
                        {{ data.min.toFixed(2) }} &ndash; {{ data.max.toFixed(2) }}
                      </span>
                      <span v-else class="meta-key">N/A</span>
                    </template>
                  </Column>
                  <Column header="Mean">
                    <template #body="{ data }">
                      {{ data.mean != null ? data.mean.toFixed(2) : 'N/A' }}
                    </template>
                  </Column>
                  <Column header="Missing">
                    <template #body="{ data }">
                      <span :class="{ 'text-warn': data.nan_pct > 10 }">
                        {{ data.nan_pct }}%
                      </span>
                    </template>
                  </Column>
                </DataTable>
              </div>
              <div v-else>
                <h4 class="panel-title">Description</h4>
                <p class="dataset-description">
                  {{ dataStore.catalogDatasetInfo.description }}
                </p>
              </div>
            </div>
          </div>

          <!-- Data Story section (catalog) — enterprise/demo only -->
          <div v-if="isFeatureEnabled('sherpaDataStory')" class="data-story-panel">
            <div class="data-story-header">
              <h4 class="panel-title">
                <i class="pi pi-book"></i>
                Data Story
              </h4>
              <div class="data-story-actions">
                <span class="ai-feature-note">AI Feature</span>
                <span
                  class="data-story-button-wrap"
                  :title="dataStoryButtonHoverText"
                >
                  <Button
                    :label="dataStoryButtonLabel"
                    icon="pi pi-sparkles"
                    class="p-button-sm p-button-outlined"
                    :loading="dataStore.dataStoryLoading"
                    :disabled="isDataStoryButtonDisabled"
                    @click="dataStore.generateDataStory()"
                  />
                </span>
              </div>
            </div>
            <div class="data-story-context">
              <label class="data-story-context-label" for="catalog-data-story-context">
                Additional Context
              </label>
              <Textarea
                id="catalog-data-story-context"
                v-model="dataStore.dataStoryContext"
                rows="3"
                autoResize
                class="data-story-context-input"
                placeholder="Optional: add domain context, process background, sample type, or what you want the story to emphasize."
              />
              <p class="data-story-context-hint">
                This will be passed to the LLM as extra context for a more relevant narrative.
              </p>
            </div>
            <div v-if="dataStore.dataStoryLoading" class="data-story-loading">
              <ProgressSpinner style="width: 24px; height: 24px" />
              <span>Generating narrative...</span>
            </div>
            <div v-else-if="dataStore.dataStoryText" class="data-story-text">
              <MemoryAttribution :scopes="dataStore.dataStoryMemoryScopes" />
              {{ dataStore.dataStoryText }}
            </div>
            <p v-else class="data-story-hint">
              Click "Generate Data Story" to create an LLM-powered narrative
              describing this dataset's scientific context and characteristics.
            </p>
          </div>

        </div>

        <div v-else-if="!dataStore.fileInfo" class="explore-empty">
          <i class="pi pi-search"></i>
          <h3>No data selected</h3>
          <p>
            Go to the <strong>Load</strong> tab and click the inspect button
            <i class="pi pi-search" style="font-size: 0.9rem"></i>
            on any file, or select a reference dataset from the catalog.
          </p>
          <Button
            v-if="!isGuidedExampleSession"
            label="Go to Load"
            icon="pi pi-arrow-left"
            class="p-button-sm p-button-outlined"
            @click="activeTab = 0"
          />
        </div>

        <div v-else class="explore-content">
          <div class="explore-header">
            <div class="explore-title">
              <i class="pi pi-file"></i>
              <span>{{ extractFileName(dataStore.activeFilePath || '') }}</span>
            </div>
            <div class="explore-actions">
              <Button
                v-if="!isGuidedExampleSession"
                label="Back to Load"
                icon="pi pi-arrow-left"
                class="p-button-text p-button-sm"
                @click="activeTab = 0"
              />
              <Button
                label="Next: Workflow"
                icon="pi pi-arrow-right"
                iconPos="right"
                class="p-button-sm"
                @click="goToWorkflow"
              />
            </div>
          </div>

          <!-- ── Box plots (tabular data with string labels on feature axis) ── -->
          <div v-if="isTabular" class="explore-table">
            <div class="table-summary">
              <Tag value="Properties" severity="info" />
              <span class="meta-val">
                {{ dataStore.fileInfo.n_samples?.toLocaleString() }} samples
                &times;
                {{ dataStore.fileInfo.n_features }} properties
              </span>
            </div>
            <PlotlyChart
              :data="boxPlotData"
              :layout="boxPlotLayout"
              :config="{ displayModeBar: true, displaylogo: false }"
            />
          </div>

          <!-- ── Spectral overlay plot ── -->
          <div v-else-if="hasSpectra" class="explore-plot">
            <PlotlyChart
              :data="previewPlotData"
              :layout="previewPlotLayout"
              :config="{ displayModeBar: true, displaylogo: false }"
            />
          </div>

          <!-- ── Reference Properties table (when properties exist alongside spectra) ── -->
          <div v-if="propertyStats.length > 0" class="explore-panels">
            <div class="metadata-panel" style="flex: 1">
              <h4 class="panel-title">Reference Properties</h4>
              <DataTable
                :value="propertyStats"
                size="small"
                stripedRows
                class="prop-stats-table"
              >
                <Column field="name" header="Property" />
                <Column header="Range">
                  <template #body="{ data }">
                    <span v-if="data.min != null">
                      {{ data.min.toFixed(2) }} &ndash; {{ data.max.toFixed(2) }}
                    </span>
                    <span v-else class="meta-key">N/A</span>
                  </template>
                </Column>
                <Column header="Mean">
                  <template #body="{ data }">
                    {{ data.mean != null ? data.mean.toFixed(2) : 'N/A' }}
                  </template>
                </Column>
              </DataTable>
            </div>
          </div>

          <!-- ── Metadata + QC panels (spectra only) ── -->
          <div v-if="hasSpectra" class="explore-panels">
            <div class="metadata-panel">
              <h4 class="panel-title">File Metadata</h4>
              <div class="metadata-table">
                <div class="meta-row">
                  <span class="meta-key">Samples</span>
                  <span class="meta-val">{{ dataStore.fileInfo.n_samples?.toLocaleString() }}</span>
                </div>
                <div class="meta-row">
                  <span class="meta-key">Features</span>
                  <span class="meta-val">{{ dataStore.fileInfo.n_features?.toLocaleString() }}</span>
                </div>
                <div v-if="sdMeta.spectral_technique" class="meta-row">
                  <span class="meta-key">Technique</span>
                  <Tag :value="String(sdMeta.spectral_technique)" severity="info" />
                </div>
                <div class="meta-row">
                  <span class="meta-key">X-Axis</span>
                  <Dropdown
                    v-model="editXTitle"
                    :options="xTitleOptions"
                    editable
                    placeholder="Select or type..."
                    class="meta-dropdown"
                  />
                </div>
                <div class="meta-row">
                  <span class="meta-key">X Units</span>
                  <Dropdown
                    v-model="editXUnits"
                    :options="xUnitsOptions"
                    editable
                    placeholder="Units"
                    class="meta-dropdown"
                  />
                </div>
                <div class="meta-row">
                  <span class="meta-key">Y-Axis</span>
                  <Dropdown
                    v-model="editYTitle"
                    :options="yTitleOptions"
                    editable
                    placeholder="Select or type..."
                    class="meta-dropdown"
                  />
                </div>
                <div class="meta-row">
                  <span class="meta-key">Time Series</span>
                  <InputSwitch v-model="isTimeSeriesToggle" />
                </div>
              </div>
            </div>

            <DataQualityPanel
              :datasetDict="dataStore.fileInfo"
              :loading="dataStore.fileInfoLoading"
            />
          </div>

          <!-- Data Story section (file) — enterprise/demo only -->
          <div v-if="isFeatureEnabled('sherpaDataStory')" class="data-story-panel">
            <div class="data-story-header">
              <h4 class="panel-title">
                <i class="pi pi-book"></i>
                Data Story
              </h4>
              <div class="data-story-actions">
                <span class="ai-feature-note">AI Feature</span>
                <span
                  class="data-story-button-wrap"
                  :title="dataStoryButtonHoverText"
                >
                  <Button
                    :label="dataStoryButtonLabel"
                    icon="pi pi-sparkles"
                    class="p-button-sm p-button-outlined"
                    :loading="dataStore.dataStoryLoading"
                    :disabled="isDataStoryButtonDisabled"
                    @click="dataStore.generateDataStory()"
                  />
                </span>
              </div>
            </div>
            <div class="data-story-context">
              <label class="data-story-context-label" for="file-data-story-context">
                Additional Context
              </label>
              <Textarea
                id="file-data-story-context"
                v-model="dataStore.dataStoryContext"
                rows="3"
                autoResize
                class="data-story-context-input"
                placeholder="Optional: add domain context, process background, sample type, or what you want the story to emphasize."
              />
              <p class="data-story-context-hint">
                This will be passed to the LLM as extra context for a more relevant narrative.
              </p>
            </div>
            <div v-if="dataStore.dataStoryLoading" class="data-story-loading">
              <ProgressSpinner style="width: 24px; height: 24px" />
              <span>Generating narrative...</span>
            </div>
            <div v-else-if="dataStore.dataStoryText" class="data-story-text">
              <MemoryAttribution :scopes="dataStore.dataStoryMemoryScopes" />
              {{ dataStore.dataStoryText }}
            </div>
            <p v-else class="data-story-hint">
              Click "Generate Data Story" to create an LLM-powered narrative
              describing this dataset's scientific context and characteristics.
            </p>
          </div>

        </div>
      </TabPanel>

      <!-- ======================== SYNTHESIS TAB ======================== -->
      <TabPanel header="Synthesis" :disabled="isGuidedExampleSession">
        <div class="synthesis-info">
          <i class="pi pi-info-circle"></i>
          <span>
            Synthesis operations are performed within the Workflow Builder
            using specialized nodes.
          </span>
        </div>

        <div class="synthesis-cards">
          <div class="synth-card">
            <div class="synth-icon">
              <i class="pi pi-sliders-h"></i>
            </div>
            <h4>Beer-Lambert Blending</h4>
            <p>
              Combine pure component spectra using Beer-Lambert law
              with custom concentration profiles.
            </p>
            <Button
              label="Open Workflow"
              icon="pi pi-arrow-right"
              iconPos="right"
              class="p-button-sm p-button-outlined"
              @click="$router.push('/workflow')"
            />
          </div>

          <div class="synth-card">
            <div class="synth-icon">
              <i class="pi pi-chart-line"></i>
            </div>
            <h4>Concentration Curves</h4>
            <p>
              Generate concentration profiles (linear, exponential, step)
              for time-resolved experiments.
            </p>
            <Button
              label="Open Workflow"
              icon="pi pi-arrow-right"
              iconPos="right"
              class="p-button-sm p-button-outlined"
              @click="$router.push('/workflow')"
            />
          </div>

          <div class="synth-card">
            <div class="synth-icon">
              <i class="pi pi-clone"></i>
            </div>
            <h4>Merge Datasets</h4>
            <p>
              Concatenate multiple spectral files into a single dataset
              for unified analysis.
            </p>
            <Button
              label="Open Workflow"
              icon="pi pi-arrow-right"
              iconPos="right"
              class="p-button-sm p-button-outlined"
              @click="$router.push('/workflow')"
            />
          </div>
        </div>
      </TabPanel>
    </TabView>

    <!-- ======================== DIALOGS ======================== -->

    <!-- Create Experiment -->
    <Dialog
      v-model:visible="showCreateDialog"
      header="New Dataset"
      :modal="true"
      :style="{ width: '420px' }"
    >
      <div class="dialog-form">
        <div class="field">
          <label for="exp-name">Name <span class="required">*</span></label>
          <InputText
            id="exp-name"
            v-model="newExpName"
            placeholder="e.g. IR Ethanol Samples"
            :class="{ 'p-invalid': createSubmitted && !newExpName.trim() }"
          />
          <small v-if="createSubmitted && !newExpName.trim()" class="p-error">
            Name is required
          </small>
        </div>
        <div class="field">
          <label for="exp-desc">Description</label>
          <Textarea
            id="exp-desc"
            v-model="newExpDescription"
            rows="2"
            placeholder="Optional description"
          />
        </div>
      </div>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="showCreateDialog = false"
        />
        <Button
          label="Create"
          icon="pi pi-plus"
          :loading="creating"
          @click="onCreateExperiment"
        />
      </template>
    </Dialog>

    <!-- Upload File -->
    <Dialog
      v-model:visible="showUploadDialog"
      header="Upload File"
      :modal="true"
      :style="{ width: '480px' }"
    >
      <div class="dialog-form">
        <div class="field">
          <label>Stage</label>
          <Dropdown
            v-model="uploadStage"
            :options="stageOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="Select stage"
            class="w-full"
          />
        </div>
        <div class="field">
          <label>File</label>
          <FileUpload
            mode="basic"
            :auto="false"
            accept=".csv,.mat,.jdx,.spa,.spc,.spg,.dx,.txt,.wdf,.opus,.dat"
            :maxFileSize="52428800"
            chooseLabel="Choose File"
            @select="onFileSelect"
          />
          <small class="field-hint">
            Supported: CSV, MAT, JDX, SPA, SPG, SPC, OPUS, WDF (max 50 MB)
          </small>
        </div>
      </div>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="showUploadDialog = false"
        />
        <Button
          label="Upload"
          icon="pi pi-upload"
          :disabled="!selectedFile"
          :loading="uploading"
          @click="onUploadFile"
        />
      </template>
    </Dialog>

    <!-- Delete Confirmation -->
    <Dialog
      v-model:visible="showDeleteDialog"
      header="Delete File"
      :modal="true"
      :style="{ width: '380px' }"
      @keydown.enter.capture.prevent="onDeleteFile"
    >
      <p>
        Are you sure you want to delete
        <strong>{{ deleteTarget ? extractFileName(deleteTarget.file_path) : '' }}</strong>?
      </p>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="showDeleteDialog = false"
        />
        <Button
          label="Delete"
          icon="pi pi-trash"
          class="p-button-danger"
          autofocus
          :loading="deleting"
          @click="onDeleteFile"
        />
      </template>
    </Dialog>

    <!-- Delete Dataset Confirmation -->
    <Dialog
      v-model:visible="showDeleteExpDialog"
      header="Delete Dataset"
      :modal="true"
      :style="{ width: '380px' }"
      @keydown.enter.capture.prevent="onDeleteExperiment"
    >
      <p>
        Are you sure you want to delete
        <strong>{{ selectedExperiment?.name }}</strong>
        and all its files?
      </p>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="showDeleteExpDialog = false"
        />
        <Button
          label="Delete"
          icon="pi pi-trash"
          class="p-button-danger"
          autofocus
          :loading="deletingExp"
          @click="onDeleteExperiment"
        />
      </template>
    </Dialog>
  </section>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import Dropdown from "primevue/dropdown";
import FileUpload from "primevue/fileupload";
import Panel from "primevue/panel";
import ProgressSpinner from "primevue/progressspinner";
import Tag from "primevue/tag";
import InputSwitch from "primevue/inputswitch";
import api from "@/api/client";
import { useAppConfig } from "@/composables/useAppConfig";
import {
  useDataStore,
  type CatalogDatasetInfo,
} from "@/stores/data";
import { useAdvisorStore } from "@/stores/advisor";
import { useProjectStore } from "@/stores/project";
import { useSherpaStore } from "@/stores/sherpa";
import { getErrorMessage } from "@/utils/errors";
import { useToast } from "primevue/usetoast";
import type { ExperimentFile, ExperimentSummary } from "@/types";
import type { ReferenceDatasetOption } from "@/stores/workflow";
import MemoryAttribution from "@/components/MemoryAttribution.vue";
import DataQualityPanel from "./DataQualityPanel.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";

const DATA_ENTRY_MODE_KEY = "sherpa:data-entry-mode";
const DATA_ENTRY_PROJECT_KEY = "sherpa:data-entry-project-id";

const { isFeatureEnabled } = useAppConfig();
const dataStore = useDataStore();
const projectStore = useProjectStore();
const sherpaStore = useSherpaStore();
const advisorStore = useAdvisorStore();
const toast = useToast();
const route = useRoute();
const router = useRouter();
const activeTab = ref(0);
const isGuidedExampleSession = ref(false);

// R3 — Sherpa Advisor scope routing for the Data tab.  Maps the local
// TabView index to the canonical subscope key so each subtab gets its
// own conversation thread.  Server validates the scope vocabulary; we
// just send the triple.
const DATA_SUBSCOPE_KEYS = ["load", "explore", "synthesis"] as const;
const DATA_SUBSCOPE_TITLES: Record<(typeof DATA_SUBSCOPE_KEYS)[number], string> = {
  load: "Load",
  explore: "Explore",
  synthesis: "Synthesis",
};

async function syncAdvisorForDataSubtab(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null) return;
  const subscopeKey = DATA_SUBSCOPE_KEYS[activeTab.value] ?? "load";
  try {
    await advisorStore.switchScope({
      projectId,
      tabKey: "data",
      subscopeKey,
      title: DATA_SUBSCOPE_TITLES[subscopeKey],
    });
  } catch (err) {
    console.warn("[data] switchScope failed", err);
  }
}

// Fire on mount and on every Data subtab change.  Project switches are
// covered by the projectId watcher below.
watch(activeTab, () => {
  void syncAdvisorForDataSubtab();
});
watch(
  () => projectStore.currentProjectId,
  (next) => {
    if (next != null) void syncAdvisorForDataSubtab();
  },
);
onMounted(() => {
  void syncAdvisorForDataSubtab();
});

// --- Load tab state ---
const libraryCollapsed = ref(true);
const librarySearch = ref("");
const selectedRefDatasets = reactive(new Set<string>());
const eigenvectorCollapsed = ref(false);
const oesCollapsed = ref(false);
const scpCollapsed = ref(true);
const sklearnCollapsed = ref(true);
const importing = ref(false);
const showCreateDialog = ref(false);
const showUploadDialog = ref(false);
const showDeleteDialog = ref(false);
const showDeleteExpDialog = ref(false);
const deletingExp = ref(false);
const newExpName = ref("");
const newExpDescription = ref("");
const createSubmitted = ref(false);
const creating = ref(false);
const uploading = ref(false);
const deleting = ref(false);
const uploadStage = ref("raw");
const selectedFile = ref<File | null>(null);
const deleteTarget = ref<ExperimentFile | null>(null);

// ── Editable metadata dropdowns ──────────────────────────────────────

const xTitleOptions = [
  "Wavenumber", "Wavelength", "Raman Shift", "m/z", "Time",
  "Energy", "Channel", "Index",
];
const xUnitsMap: Record<string, string[]> = {
  "Wavenumber": ["cm\u207B\u00B9"],
  "Wavelength": ["nm", "\u00B5m"],
  "Raman Shift": ["cm\u207B\u00B9"],
  "m/z": ["Da", "Th"],
  "Time": ["s", "min", "h"],
  "Energy": ["eV", "keV"],
  "Channel": [""],
  "Index": [""],
};
const yTitleOptions = [
  "Intensity", "Absorbance", "Transmittance", "Reflectance", "Response",
];

const editXTitle = ref("");
const editXUnits = ref("");
const editYTitle = ref("");
const isTimeSeriesToggle = ref(false);

// Compute available X-units based on selected X-title
const xUnitsOptions = computed(() => {
  const units = xUnitsMap[editXTitle.value];
  if (units) return units.filter((u) => u !== "");
  return [];
});

// Sync editable fields when a new dataset loads
function _syncFromFileInfo(fi: { metadata?: Record<string, unknown> } | null) {
  const m = fi?.metadata as Record<string, unknown> | undefined;
  editXTitle.value = (m?.x_title ?? "") as string;
  editXUnits.value = (m?.x_units ?? "") as string;
  editYTitle.value = (m?.data_quantity ?? "") as string;
  isTimeSeriesToggle.value = !!(m?.is_time_series);
}
function _syncFromCatalog(info: CatalogDatasetInfo | null) {
  editXTitle.value = (info?.x_title ?? "") as string;
  editXUnits.value = (info?.x_units ?? "") as string;
  editYTitle.value = (info?.data_quantity ?? "") as string;
  isTimeSeriesToggle.value = !!(info?.metadata as Record<string, unknown> | undefined)?.is_time_series
    || !!(info?.is_time_series);
}

watch(() => dataStore.fileInfo, _syncFromFileInfo);
watch(() => dataStore.catalogDatasetInfo, _syncFromCatalog);

// Persist changes to backend + update in-memory metadata
async function persistMetadataOverride() {
  // Plot labels update reactively via sdMeta reading editXTitle/editXUnits/editYTitle
  // — those refs feed sdMeta directly, so the plot stays fast without us
  // touching dataStore.fileInfo.metadata as a whole.
  //
  // We DO mutate the specific override fields (x_title, x_units, data_quantity,
  // is_time_series) on the in-memory store after a successful PATCH so that
  // downstream consumers — Generate Data Story, workflow trial requests,
  // Detailed View — pick up the user's edits without a page refresh. Vue
  // tracks per-property reactivity, and these specific fields are not read
  // by sdMeta or previewPlotData, so the plot doesn't re-render.

  // Build request payload
  const xTitle = editXTitle.value || null;
  const xUnits = editXUnits.value || null;
  const yTitle = editYTitle.value || null;
  const isTimeSeries = isTimeSeriesToggle.value;

  const body: Record<string, unknown> = {
    x_title: xTitle,
    x_units: xUnits,
    y_title: yTitle,
    is_time_series: isTimeSeries,
  };
  const catInfo = dataStore.catalogDatasetInfo;
  if (catInfo?.source && catInfo?.name) {
    body.source = catInfo.source;
    body.name = catInfo.name;
  } else if (dataStore.activeFilePath) {
    body.file_path = dataStore.activeFilePath;
    if (dataStore.activeExperimentId) {
      body.experiment_id = dataStore.activeExperimentId;
    }
  } else {
    return; // nothing to persist
  }

  try {
    await api.patch("/builder/file-metadata", body);

    // Reflect the persisted values in the store so the same-session reads see
    // them. Without this, "Generate Data Story" and the Detail View report
    // stale values (the ones loaded before the user edited).
    const fi = dataStore.fileInfo;
    if (fi && typeof fi === "object") {
      const fiAny = fi as Record<string, unknown> & { metadata?: Record<string, unknown> };
      if (fiAny.metadata && typeof fiAny.metadata === "object") {
        fiAny.metadata.x_title = xTitle;
        fiAny.metadata.x_units = xUnits;
        fiAny.metadata.data_quantity = yTitle;
        fiAny.metadata.is_time_series = isTimeSeries;
      }
      // Some readers also check top-level fields on fileInfo.
      fiAny.x_title = xTitle;
      fiAny.x_units = xUnits;
      fiAny.data_quantity = yTitle;
      fiAny.is_time_series = isTimeSeries;
    }
    if (catInfo) {
      const ciAny = catInfo as Record<string, unknown>;
      ciAny.x_title = xTitle;
      ciAny.x_units = xUnits;
      ciAny.data_quantity = yTitle;
      ciAny.is_time_series = isTimeSeries;
    }
  } catch (err) {
    console.warn("Failed to persist metadata override", err);
  }
}

// Debounced persist on any editable field change
let _persistTimer: ReturnType<typeof setTimeout> | null = null;
function schedulePersist() {
  if (_persistTimer) clearTimeout(_persistTimer);
  _persistTimer = setTimeout(persistMetadataOverride, 500);
}

watch(editXTitle, schedulePersist);
watch(editXUnits, schedulePersist);
watch(editYTitle, schedulePersist);
watch(isTimeSeriesToggle, schedulePersist);

const fileStages = [
  { key: "raw", label: "Raw", icon: "pi pi-file" },
  { key: "preprocessed", label: "Preprocessed", icon: "pi pi-cog" },
  { key: "synthetic", label: "Synthetic", icon: "pi pi-sparkles" },
];

const stageOptions = [
  { label: "Raw", value: "raw" },
  { label: "Preprocessed", value: "preprocessed" },
  { label: "Synthetic", value: "synthetic" },
];

const selectedExperiment = computed(() => {
  if (!dataStore.activeExperimentId) return null;
  return (
    dataStore.experiments.find((e) => e.id === dataStore.activeExperimentId) ??
    null
  );
});

const filteredLibrary = computed(() => {
  const q = librarySearch.value.toLowerCase().trim();
  if (!q) return dataStore.libraryDatasets;
  return dataStore.libraryDatasets.filter(
    (d) =>
      d.compound_name.toLowerCase().includes(q) ||
      d.cas_number.toLowerCase().includes(q)
  );
});

function filesForStage(stage: string): ExperimentFile[] {
  return dataStore.experimentFiles.filter((f) => f.stage === stage);
}

// --- Reference dataset selection ---

function dsKey(ds: { source?: string; name: string }): string {
  return `${ds.source || "spectrochempy"}::${ds.name}`;
}

function toggleRefDataset(ds: ReferenceDatasetOption) {
  const key = dsKey(ds);
  if (selectedRefDatasets.has(key)) {
    selectedRefDatasets.delete(key);
  } else {
    selectedRefDatasets.add(key);
  }
}

async function onImportSelectedDatasets() {
  if (!dataStore.activeExperimentId || selectedRefDatasets.size === 0) return;
  importing.value = true;
  try {
    const datasets = Array.from(selectedRefDatasets).map((key) => {
      const [source, ...rest] = key.split("::");
      return { source, name: rest.join("::") };
    });
    const result = await dataStore.importReferenceDatasets(
      dataStore.activeExperimentId,
      datasets
    );
    toast.add({
      severity: "success",
      summary: "Import Complete",
      detail: `Imported ${result.imported} file(s) into your dataset`,
      life: 3000,
    });
    selectedRefDatasets.clear();
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Import Failed",
      detail: getErrorMessage(err, "Failed to import datasets"),
      life: 5000,
    });
  } finally {
    importing.value = false;
  }
}

// --- SCP category helpers ---

const SCP_CATEGORY_LABELS: Record<string, string> = {
  irdata: "IR Spectroscopy",
  ramandata: "Raman Spectroscopy",
  galacticdata: "Galactic / SPC",
  matlabdata: "MATLAB",
  msdata: "Mass Spectrometry",
  agirdata: "Agilent FTIR",
};

const scpCategories = computed(() => {
  const scp = dataStore.referenceCatalog?.spectrochempy ?? [];
  const cats = new Set(scp.map((d) => d.category || "other"));
  return Array.from(cats);
});

function scpByCategory(category: string) {
  const scp = dataStore.referenceCatalog?.spectrochempy ?? [];
  return scp.filter((d) => (d.category || "other") === category);
}

function scpCategoryLabel(category: string): string {
  return SCP_CATEGORY_LABELS[category] || category;
}

// --- Spectral preview plot ---

const PLOT_COLORS = [
  "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1",
  "#e11d48", "#84cc16", "#0ea5e9", "#d946ef", "#a3e635",
  "#2dd4bf", "#fb923c", "#818cf8", "#f472b6", "#34d399",
];

// --- Helpers reading to_dict() format from _serialize_sherpa_dataset ---

const sdMeta = computed(() => {
  const m = dataStore.fileInfo?.metadata as Record<string, unknown> | undefined;
  return {
    wavenumbers: (m?.wavenumbers ?? []) as number[],
    labels: (m?.labels ?? m?.sample_labels ?? []) as string[],
    x_title: editXTitle.value || (m?.x_title ?? "") as string,
    x_units: editXUnits.value || (m?.x_units ?? "") as string,
    spectral_technique: (m?.spectral_technique ?? null) as string | null,
    data_quantity: editYTitle.value || (m?.data_quantity ?? null) as string | null,
    value_units: (m?.value_units ?? null) as string | null,
    is_spectra: (m?.is_spectra ?? false) as boolean,
    prop_names: (m?.prop_names ?? []) as string[],
    properties: (m?.properties ?? null) as Record<string, number[]> | null,
  };
});

/** Compute property stats (min, max, mean) from metadata.properties */
const propertyStats = computed(() => {
  const { properties, prop_names } = sdMeta.value;
  if (!properties || !prop_names.length) return [];
  return prop_names.map((name) => {
    const vals = (properties[name] ?? []).filter((v) => v != null && isFinite(v));
    if (!vals.length) return { name, min: null, max: null, mean: null };
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    return { name, min, max, mean };
  });
});

const isTabular = computed(() => {
  const fi = dataStore.fileInfo;
  if (!fi) return false;
  return fi.x_axis?.labels != null && fi.x_axis.labels.length > 0;
});

const dataStoryButtonLabel = computed(() =>
  dataStore.dataStoryText ? "Regenerate Data Story" : "Generate Data Story"
);

const isDataStoryButtonDisabled = computed(() =>
  sherpaStore.isSyncing || sherpaStore.isChatting
);

const dataStoryButtonHoverText = computed(() =>
  isDataStoryButtonDisabled.value ? "Available when Sherpa Advisor finishes" : ""
);

const hasSpectra = computed(() => {
  const fi = dataStore.fileInfo;
  if (!fi?.data?.length) return false;
  return !isTabular.value;
});

// --- Spectral overlay (same pattern as NodeDetailView) ---

const previewPlotData = computed(() => {
  const fi = dataStore.fileInfo;
  if (!fi?.data?.length) return [];
  const wavenumbers = sdMeta.value.wavenumbers.length
    ? sdMeta.value.wavenumbers
    : Array.from({ length: fi.n_features }, (_, i) => i);
  const labels = sdMeta.value.labels;
  const maxTraces = Math.min(fi.data.length, 50);
  return fi.data.slice(0, maxTraces).map((spectrum, i) => ({
    x: wavenumbers,
    y: spectrum,
    type: "scatter" as const,
    mode: "lines" as const,
    name: labels[i] || `Spectrum ${i + 1}`,
    line: { color: PLOT_COLORS[i % PLOT_COLORS.length], width: 1.2 },
  }));
});

const xAxisLabel = computed(() => {
  const { x_title, x_units, spectral_technique } = sdMeta.value;
  if (x_title && x_units) return `${x_title} (${x_units})`;
  if (x_title) return x_title;
  const tech = (spectral_technique ?? "").toUpperCase();
  if (tech === "IR" || tech === "NIR") return "Wavenumber (cm\u207B\u00B9)";
  if (tech === "RAMAN") return "Raman Shift (cm\u207B\u00B9)";
  return "Feature";
});

const yAxisLabel = computed(() => {
  const { data_quantity, value_units } = sdMeta.value;
  return data_quantity || value_units || "Intensity";
});

const previewPlotLayout = computed(() => ({
  title: { text: "Spectra Preview", font: { size: 14 } },
  xaxis: {
    title: xAxisLabel.value,
    autorange: true as const,
  },
  yaxis: { title: yAxisLabel.value },
  autosize: true,
  height: 380,
  margin: { t: 40, r: 20, b: 50, l: 60 },
  showlegend: (dataStore.fileInfo?.data?.length ?? 0) <= 20,
  legend: { font: { size: 10 }, orientation: "h" as const, y: -0.25 },
  plot_bgcolor: "#fafafa",
  paper_bgcolor: "#ffffff",
}));

// --- Peak identification ---

// --- Box plots for properties (feature axis has string labels) ---

const boxPlotData = computed(() => {
  const fi = dataStore.fileInfo;
  const labels = fi?.x_axis?.labels;
  if (!labels?.length || !fi?.data?.length) return [];

  return labels.map((col, colIdx) => {
    const values = fi.data
      .map((row) => row[colIdx])
      .filter((v): v is number => v !== null && typeof v === "number");
    return {
      type: "box" as const,
      y: values,
      name: col,
      marker: { color: PLOT_COLORS[colIdx % PLOT_COLORS.length] },
      boxpoints: false,
    };
  });
});

const boxPlotLayout = computed(() => {
  const { value_units, x_title } = sdMeta.value;
  const yLabel = value_units || x_title || "Value";
  return {
    title: { text: "Property Distributions", font: { size: 14 } },
    xaxis: { title: "Property" },
    yaxis: { title: yLabel },
    autosize: true,
    height: 400,
    margin: { t: 40, r: 20, b: 50, l: 60 },
    showlegend: false,
    plot_bgcolor: "#fafafa",
    paper_bgcolor: "#ffffff",
  };
});

function queryNumber(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function syncGuidedExampleSession() {
  const mode = window.sessionStorage.getItem(DATA_ENTRY_MODE_KEY);
  const projectId = window.sessionStorage.getItem(DATA_ENTRY_PROJECT_KEY);
  isGuidedExampleSession.value =
    mode === "template-example" &&
    projectId === String(projectStore.currentProjectId ?? "");
}

function sortFilesNewestFirst(items: ExperimentFile[]): ExperimentFile[] {
  return [...items].sort(
    (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
  );
}

async function inspectExperimentFile(experimentId: number, fileId: number | null): Promise<boolean> {
  await dataStore.selectExperiment(experimentId);
  if (fileId == null) {
    return false;
  }

  const file = dataStore.experimentFiles.find((entry) => entry.id === fileId);
  if (!file) {
    return false;
  }

  dataStore.clearCatalogExploration();
  await dataStore.inspectFile(file.id, file.file_path, experimentId);
  activeTab.value = 1;
  return true;
}

async function inspectLatestProjectFile(): Promise<boolean> {
  if (
    projectStore.currentProjectId != null &&
    (!projectStore.currentProject || projectStore.currentProject.id !== projectStore.currentProjectId)
  ) {
    await projectStore.fetchProject(projectStore.currentProjectId);
  }

  const experiments = [...(projectStore.currentProject?.experiments || [])].sort(
    (left, right) => right.id - left.id
  );
  for (const experiment of experiments) {
    await dataStore.selectExperiment(experiment.id);
    const latestFile = sortFilesNewestFirst(dataStore.experimentFiles)[0];
    if (!latestFile) {
      continue;
    }

    dataStore.clearCatalogExploration();
    await dataStore.inspectFile(latestFile.id, latestFile.file_path, experiment.id);
    activeTab.value = 1;
    return true;
  }

  return false;
}

async function inspectLatestExperimentFile(experimentId: number): Promise<boolean> {
  await dataStore.selectExperiment(experimentId);
  const latestFile = sortFilesNewestFirst(dataStore.experimentFiles)[0];
  if (!latestFile) {
    return false;
  }

  dataStore.clearCatalogExploration();
  await dataStore.inspectFile(latestFile.id, latestFile.file_path, experimentId);
  activeTab.value = 1;
  return true;
}

async function applyRouteExploreState() {
  syncGuidedExampleSession();
  const wantsExplore =
    route.query.tab === "explore" ||
    route.query.fromTemplate === "1" ||
    isGuidedExampleSession.value;
  if (!wantsExplore) {
    return;
  }

  const experimentId = queryNumber(route.query.experimentId);
  const fileId = queryNumber(route.query.fileId);

  try {
    if (experimentId != null && fileId != null) {
      const inspected = await inspectExperimentFile(experimentId, fileId);
      if (inspected) {
        return;
      }
    }

    if (experimentId != null) {
      const inspected = await inspectLatestExperimentFile(experimentId);
      if (inspected) {
        return;
      }
    }

    if (route.query.focus === "latest-project" || isGuidedExampleSession.value) {
      const inspected = await inspectLatestProjectFile();
      if (inspected) {
        return;
      }
    }
  } catch {
    // Errors are surfaced by the existing Explore tab states.
  }

  activeTab.value = 1;
}

function goToWorkflow() {
  router.push("/workflow");
}

// --- Lifecycle ---

onMounted(async () => {
  await Promise.all([
    dataStore.fetchCatalog(),
    dataStore.fetchExperiments(),
    dataStore.fetchReferenceCatalog(),
  ]);
  syncGuidedExampleSession();
  await applyRouteExploreState();

  // Restore the Explore tab if the Pinia store still has an active
  // exploration (i.e. the user left the Data page after inspecting a
  // reference or file). Route-driven state takes precedence.
  if (
    activeTab.value === 0 &&
    (dataStore.catalogDatasetInfo !== null || dataStore.fileInfo !== null)
  ) {
    activeTab.value = 1;
  }
});

watch(activeTab, (tabIndex) => {
  if (isGuidedExampleSession.value && tabIndex !== 1) {
    activeTab.value = 1;
  }
});

async function refresh() {
  await Promise.all([
    dataStore.fetchCatalog(),
    dataStore.fetchExperiments(),
    dataStore.fetchReferenceCatalog(),
  ]);
  if (dataStore.activeExperimentId) {
    await dataStore.selectExperiment(dataStore.activeExperimentId);
  }
}

// --- Experiment CRUD ---

function onExperimentSelect(exp: ExperimentSummary | null) {
  if (exp) {
    dataStore.selectExperiment(exp.id);
  }
}

async function onCreateExperiment() {
  createSubmitted.value = true;
  if (!newExpName.value.trim()) return;

  creating.value = true;
  try {
    const created = await dataStore.createExperiment(
      newExpName.value.trim(),
      newExpDescription.value.trim() || undefined,
      projectStore.currentProjectId,
    );
    showCreateDialog.value = false;
    newExpName.value = "";
    newExpDescription.value = "";
    createSubmitted.value = false;
    // Auto-select the new experiment
    if (created?.id) {
      await dataStore.selectExperiment(created.id);
    }
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Create Failed",
      detail: getErrorMessage(err, "Failed to create dataset"),
      life: 5000,
    });
  } finally {
    creating.value = false;
  }
}

// --- File operations ---

function onFileSelect(event: { files?: File[] }) {
  selectedFile.value = event.files?.[0] ?? null;
}

async function onUploadFile() {
  if (!selectedFile.value || !dataStore.activeExperimentId) return;
  uploading.value = true;
  try {
    await dataStore.uploadFile(
      dataStore.activeExperimentId,
      selectedFile.value,
      uploadStage.value
    );
    showUploadDialog.value = false;
    selectedFile.value = null;
    uploadStage.value = "raw";
    // Refresh experiment list to update file_count
    await dataStore.fetchExperiments();
  } catch (err) {
    console.error("Upload failed:", err);
  } finally {
    uploading.value = false;
  }
}

function confirmDeleteFile(file: ExperimentFile) {
  deleteTarget.value = file;
  showDeleteDialog.value = true;
}

async function onDeleteFile() {
  if (!deleteTarget.value || !dataStore.activeExperimentId) return;
  deleting.value = true;
  try {
    await dataStore.deleteFile(
      dataStore.activeExperimentId,
      deleteTarget.value.id
    );
    showDeleteDialog.value = false;
    deleteTarget.value = null;
    // Refresh experiment list to update file_count
    await dataStore.fetchExperiments();
  } catch (err) {
    console.error("Delete failed:", err);
  } finally {
    deleting.value = false;
  }
}

async function onDeleteExperiment() {
  if (!dataStore.activeExperimentId) return;
  deletingExp.value = true;
  try {
    await dataStore.deleteExperiment(dataStore.activeExperimentId);
    showDeleteExpDialog.value = false;
  } catch (err) {
    console.error("Delete dataset failed:", err);
  } finally {
    deletingExp.value = false;
  }
}

async function onInspectFile(file: ExperimentFile) {
  if (!dataStore.activeExperimentId) return;
  dataStore.clearCatalogExploration();
  try {
    await dataStore.inspectFile(file.id, file.file_path, dataStore.activeExperimentId);
  } catch {
    // Error is stored in dataStore.fileInfoError
  }
  activeTab.value = 1;
}

async function onExploreReference(source: string | undefined, name: string) {
  await dataStore.exploreCatalogDataset(source || "spectrochempy", name);
  activeTab.value = 1;
}

// --- Helpers ---

function extractFileName(filePath: string): string {
  return filePath.split("/").pop() || filePath;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}
</script>

<style scoped>
.data-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.section-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 8px;
}

/* ---- Load tab ---- */
.load-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.load-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  min-height: 420px;
}

.experiment-list-panel,
.files-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px;
}

.exp-table :deep(.p-datatable-tbody > tr.p-highlight) {
  background: #dbeafe;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 16px;
  color: #94a3b8;
  text-align: center;
}

.empty-state i {
  font-size: 1.8rem;
}

.empty-state-sm {
  text-align: center;
  padding: 16px;
  color: #94a3b8;
}

.file-groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.stage-header {
  margin: 0 0 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 6px;
}

.stage-header i {
  color: #64748b;
  font-size: 0.85rem;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.file-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid transparent;
  transition: all 0.15s;
}

.file-row:hover {
  background: #f1f5f9;
  border-color: #e2e8f0;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.file-name {
  font-size: 0.9rem;
  color: #1e293b;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 0.75rem;
  color: #94a3b8;
  white-space: nowrap;
}

.file-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

/* Library panel */
.library-panel {
  margin-top: 16px;
}

.library-toolbar {
  margin-bottom: 12px;
}

/* ---- Explore tab ---- */
.explore-loading,
.explore-error,
.explore-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 24px;
  color: #94a3b8;
  text-align: center;
}

.explore-empty i {
  font-size: 2.5rem;
}

.explore-empty h3 {
  margin: 0;
  color: #475569;
}

.explore-empty p {
  max-width: 400px;
  line-height: 1.5;
  color: #64748b;
}

.explore-error i {
  font-size: 2rem;
  color: #f59e0b;
}

.explore-error span {
  color: #dc2626;
}

.explore-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.explore-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.explore-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.explore-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
}

.explore-title i {
  color: #3b82f6;
}

.explore-table {
  margin-bottom: 16px;
}

.table-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.explore-plot {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px;
  width: 100%;
  box-sizing: border-box;
}

.plot-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 8px;
}

.peak-analysis-panel {
  margin-top: 12px;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.peak-analysis-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

.explore-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.metadata-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px;
}

.panel-title {
  margin: 0 0 12px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
}

.metadata-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid #f1f5f9;
}

.meta-row:last-child {
  border-bottom: none;
}

.meta-key {
  font-size: 0.85rem;
  color: #64748b;
}

.meta-val {
  font-size: 0.9rem;
  color: #1e293b;
  font-weight: 500;
}

.meta-dropdown {
  width: 160px;
  font-size: 0.85rem;
}

.meta-dropdown :deep(.p-dropdown-label) {
  padding: 4px 8px;
  font-size: 0.85rem;
}

.meta-dropdown :deep(.p-dropdown-trigger) {
  width: 1.8rem;
}

/* ---- Data Story section ---- */
.data-story-panel {
  margin-top: 16px;
  padding: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.data-story-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.data-story-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.data-story-button-wrap {
  display: inline-flex;
}

.data-story-header .panel-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.data-story-context {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.data-story-context-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.data-story-context-input {
  width: 100%;
}

.data-story-context-hint {
  margin: 0;
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.4;
}

.ai-feature-note {
  font-size: 0.75rem;
  color: #8b5cf6;
  font-weight: 500;
  background: #ede9fe;
  padding: 2px 8px;
  border-radius: 4px;
}

.data-story-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 0.9rem;
}

.data-story-text {
  font-size: 0.9rem;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

.data-story-hint {
  color: #94a3b8;
  font-size: 0.85rem;
  font-style: italic;
  margin: 0;
}

/* ---- Reference catalog section ---- */
.ref-catalog-section {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px;
  margin-bottom: 20px;
}

.ref-catalog-title {
  margin: 0 0 16px;
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}

.ref-catalog-title i {
  color: #3b82f6;
}

.ref-catalog-error {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  font-size: 0.9rem;
}

.ref-catalog-error i {
  color: #dc2626;
  font-size: 1.1rem;
  flex-shrink: 0;
}

.ref-catalog-error span {
  flex: 1;
}

.ref-catalog-groups {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ref-group-panel {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.ref-panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
}

.ref-panel-header i {
  color: #64748b;
  font-size: 0.85rem;
}

.ref-dataset-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.ref-dataset-item:hover {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.ref-dataset-item.selected {
  background: #dbeafe;
  border-color: #93c5fd;
}

.ref-ds-label {
  font-size: 0.85rem;
  color: #1e293b;
  font-weight: 500;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-ds-tag {
  font-size: 0.7rem;
  flex-shrink: 0;
}

.ref-explore-btn {
  flex-shrink: 0;
  opacity: 0.5;
  transition: opacity 0.15s;
}

.ref-dataset-item:hover .ref-explore-btn {
  opacity: 1;
}

.ref-scp-category {
  font-size: 0.75rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-top: 8px;
  margin-bottom: 2px;
  padding-left: 4px;
}

.ref-action-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  padding: 12px 16px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 8px;
}

.ref-selection-count {
  font-size: 0.9rem;
  font-weight: 600;
  color: #0369a1;
}

.ref-hint {
  color: #64748b;
  font-style: italic;
}

/* ---- My Dataset section ---- */
.my-dataset-section {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px;
  margin-bottom: 16px;
}

.my-dataset-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.my-dataset-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}

.my-dataset-title i {
  color: #3b82f6;
}

.my-dataset-actions {
  display: flex;
  gap: 8px;
}

/* ---- Catalog explore card ---- */
.dataset-description {
  font-size: 0.9rem;
  color: #475569;
  line-height: 1.6;
  margin: 0;
  white-space: pre-line;
}

.meta-wrap {
  word-break: break-word;
  text-align: right;
  max-width: 300px;
}

.text-warn {
  color: #f59e0b;
  font-weight: 600;
}

.prop-stats-table {
  font-size: 0.85rem;
}

/* ---- Synthesis tab ---- */
.synthesis-info {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  color: #1e40af;
  font-size: 0.9rem;
  margin-bottom: 20px;
}

.synthesis-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.synth-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.synth-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
}

.synth-icon i {
  font-size: 1.2rem;
  color: #3b82f6;
}

.synth-card h4 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
}

.synth-card p {
  margin: 0;
  font-size: 0.85rem;
  color: #64748b;
  line-height: 1.5;
  flex: 1;
}

/* ---- Dialogs ---- */
.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-weight: 500;
  font-size: 0.9rem;
  color: #334155;
}

.required {
  color: #ef4444;
}

.field-hint {
  font-size: 0.8rem;
  color: #94a3b8;
}

/* ---- Responsive ---- */
@media (max-width: 900px) {
  .load-panels {
    grid-template-columns: 1fr;
  }

  .explore-panels {
    grid-template-columns: 1fr;
  }

  .synthesis-cards {
    grid-template-columns: 1fr;
  }
}
</style>
