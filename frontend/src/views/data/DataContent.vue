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
      <TabPanel header="Load">
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
            <div class="ref-source-group">
              <h5 class="ref-group-title">
                <i class="pi pi-chart-bar"></i>
                Eigenvector Research (NIR)
              </h5>
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
            </div>

            <!-- SpectroChemPy (file-level entries grouped by category) -->
            <div class="ref-source-group">
              <h5 class="ref-group-title">
                <i class="pi pi-wave-pulse"></i>
                SpectroChemPy Datasets
              </h5>
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
            </div>

            <!-- sklearn -->
            <div class="ref-source-group">
              <h5 class="ref-group-title">
                <i class="pi pi-cog"></i>
                Scikit-learn Datasets
              </h5>
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
            </div>
          </div>

          <!-- Action bar -->
          <div class="ref-action-bar" v-if="selectedRefDatasets.size > 0">
            <span class="ref-selection-count">{{ selectedRefDatasets.size }} selected</span>
            <Button
              label="Add to My Dataset"
              icon="pi pi-plus"
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
                label="Upload File"
                icon="pi pi-upload"
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
            <Button
              label="Back to Load"
              icon="pi pi-arrow-left"
              class="p-button-text p-button-sm"
              @click="activeTab = 0; dataStore.clearCatalogExploration()"
            />
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

          <!-- Data Story section -->
          <div class="data-story-panel">
            <div class="data-story-header">
              <h4 class="panel-title">
                <i class="pi pi-book"></i>
                Data Story
              </h4>
              <Button
                v-if="!dataStore.dataStoryText"
                label="Generate Data Story"
                icon="pi pi-sparkles"
                class="p-button-sm p-button-outlined"
                :loading="dataStore.dataStoryLoading"
                @click="dataStore.generateDataStory()"
              />
            </div>
            <div v-if="dataStore.dataStoryLoading" class="data-story-loading">
              <ProgressSpinner style="width: 24px; height: 24px" />
              <span>Generating narrative...</span>
            </div>
            <div v-else-if="dataStore.dataStoryText" class="data-story-text">
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
            <Button
              label="Back to Load"
              icon="pi pi-arrow-left"
              class="p-button-text p-button-sm"
              @click="activeTab = 0"
            />
          </div>

          <!-- Spectral preview plot -->
          <div
            v-if="dataStore.fileInfo.preview_wavenumber && dataStore.fileInfo.preview_spectra"
            class="explore-plot"
          >
            <PlotlyChart
              :data="previewPlotData"
              :layout="previewPlotLayout"
              :config="{ displayModeBar: true, displaylogo: false }"
            />
          </div>

          <div class="explore-panels">
            <!-- Metadata table -->
            <div class="metadata-panel">
              <h4 class="panel-title">File Metadata</h4>
              <div class="metadata-table">
                <div class="meta-row">
                  <span class="meta-key">Source</span>
                  <span class="meta-val">{{ dataStore.fileInfo.source }}</span>
                </div>
                <div class="meta-row">
                  <span class="meta-key">Status</span>
                  <Tag
                    :value="dataStore.fileInfo.status"
                    :severity="dataStore.fileInfo.status === 'ok' ? 'success' : 'warning'"
                  />
                </div>
                <div class="meta-row">
                  <span class="meta-key">Spectra</span>
                  <span class="meta-val">{{ dataStore.fileInfo.num_spectra.toLocaleString() }}</span>
                </div>
                <div class="meta-row">
                  <span class="meta-key">Wavenumbers</span>
                  <span class="meta-val">{{ dataStore.fileInfo.num_wavenumbers.toLocaleString() }}</span>
                </div>
                <div
                  v-if="dataStore.fileInfo.wavenumber_min !== null"
                  class="meta-row"
                >
                  <span class="meta-key">Wavenumber Range</span>
                  <span class="meta-val">
                    {{ dataStore.fileInfo.wavenumber_min.toFixed(1) }} &ndash;
                    {{ dataStore.fileInfo.wavenumber_max?.toFixed(1) }} cm<sup>-1</sup>
                  </span>
                </div>
                <div
                  v-if="dataStore.fileInfo.absorbance_min !== null"
                  class="meta-row"
                >
                  <span class="meta-key">Absorbance Range</span>
                  <span class="meta-val">
                    {{ dataStore.fileInfo.absorbance_min.toFixed(4) }} &ndash;
                    {{ dataStore.fileInfo.absorbance_max?.toFixed(4) }} AU
                  </span>
                </div>
              </div>
            </div>

            <!-- QC panel -->
            <DataQualityPanel
              :fileInfo="dataStore.fileInfo"
              :loading="dataStore.fileInfoLoading"
            />
          </div>
        </div>
      </TabPanel>

      <!-- ======================== SYNTHESIS TAB ======================== -->
      <TabPanel header="Synthesis">
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
          :loading="deleting"
          @click="onDeleteFile"
        />
      </template>
    </Dialog>
  </section>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
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
import { useDataStore } from "@/stores/data";
import { useToast } from "primevue/usetoast";
import type { ExperimentFile, ExperimentSummary } from "@/types";
import DataQualityPanel from "./DataQualityPanel.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";

const dataStore = useDataStore();
const toast = useToast();
const activeTab = ref(0);

// --- Load tab state ---
const libraryCollapsed = ref(true);
const librarySearch = ref("");
const selectedRefDatasets = reactive(new Set<string>());
const importing = ref(false);
const showCreateDialog = ref(false);
const showUploadDialog = ref(false);
const showDeleteDialog = ref(false);
const newExpName = ref("");
const newExpDescription = ref("");
const createSubmitted = ref(false);
const creating = ref(false);
const uploading = ref(false);
const deleting = ref(false);
const uploadStage = ref("raw");
const selectedFile = ref<File | null>(null);
const deleteTarget = ref<ExperimentFile | null>(null);

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

function toggleRefDataset(ds: { source?: string; name: string }) {
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
  } catch (err: any) {
    toast.add({
      severity: "error",
      summary: "Import Failed",
      detail: err?.response?.data?.detail || "Failed to import datasets",
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
  const cats = new Set(scp.map((d: any) => d.category || "other"));
  return Array.from(cats);
});

function scpByCategory(category: string) {
  const scp = dataStore.referenceCatalog?.spectrochempy ?? [];
  return scp.filter((d: any) => (d.category || "other") === category);
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

const previewPlotData = computed(() => {
  const fi = dataStore.fileInfo;
  if (!fi?.preview_wavenumber || !fi?.preview_spectra) return [];
  const wn = fi.preview_wavenumber;
  return fi.preview_spectra.map((s, i) => ({
    x: wn,
    y: s.absorbance,
    type: "scatter" as const,
    mode: "lines" as const,
    name: s.label,
    line: { color: PLOT_COLORS[i % PLOT_COLORS.length], width: 1.2 },
  }));
});

const isReversedXAxis = computed(() => {
  const src = (dataStore.fileInfo?.source ?? "").toLowerCase();
  // FTIR / IR data: reversed wavenumber axis. Everything else: normal.
  return src.includes("spa") || src.includes("spg") || src.includes("jdx")
    || src.includes("opus") || src.includes("dx");
});

const xAxisLabel = computed(() => {
  const src = (dataStore.fileInfo?.source ?? "").toLowerCase();
  if (src.includes("spa") || src.includes("spg") || src.includes("jdx")
    || src.includes("opus") || src.includes("dx")) {
    return "Wavenumber (cm\u207B\u00B9)";
  }
  if (src.includes("wdf") || src.includes("spc")) {
    return "Raman Shift (cm\u207B\u00B9)";
  }
  return "Variable Index";
});

const previewPlotLayout = computed(() => ({
  title: { text: "Spectra Preview", font: { size: 14 } },
  xaxis: {
    title: xAxisLabel.value,
    autorange: isReversedXAxis.value ? ("reversed" as const) : (true as const),
  },
  yaxis: { title: "Intensity" },
  autosize: true,
  height: 380,
  margin: { t: 40, r: 20, b: 50, l: 60 },
  showlegend: (dataStore.fileInfo?.preview_spectra?.length ?? 0) <= 20,
  legend: { font: { size: 10 }, orientation: "h" as const, y: -0.25 },
  plot_bgcolor: "#fafafa",
  paper_bgcolor: "#ffffff",
}));

// --- Lifecycle ---

onMounted(async () => {
  await Promise.all([
    dataStore.fetchCatalog(),
    dataStore.fetchExperiments(),
    dataStore.fetchReferenceCatalog(),
  ]);
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
      newExpDescription.value.trim() || undefined
    );
    showCreateDialog.value = false;
    newExpName.value = "";
    newExpDescription.value = "";
    createSubmitted.value = false;
    // Auto-select the new experiment
    if (created?.id) {
      await dataStore.selectExperiment(created.id);
    }
  } catch (err: any) {
    toast.add({
      severity: "error",
      summary: "Create Failed",
      detail: err?.response?.data?.detail || "Failed to create dataset",
      life: 5000,
    });
  } finally {
    creating.value = false;
  }
}

// --- File operations ---

function onFileSelect(event: any) {
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

async function onExploreReference(source: string, name: string) {
  await dataStore.exploreCatalogDataset(source, name);
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
  grid-template-columns: 2fr 3fr;
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

.explore-plot {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px;
  width: 100%;
  box-sizing: border-box;
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
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.ref-source-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ref-group-title {
  margin: 0 0 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 6px;
}

.ref-group-title i {
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

/* ---- Data story ---- */
.data-story-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px;
}

.data-story-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.data-story-header .panel-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.data-story-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 0;
  color: #64748b;
  font-size: 0.9rem;
}

.data-story-text {
  font-size: 0.9rem;
  color: #334155;
  line-height: 1.7;
  white-space: pre-line;
}

.data-story-hint {
  font-size: 0.85rem;
  color: #94a3b8;
  margin: 0;
  font-style: italic;
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
  .ref-catalog-groups {
    grid-template-columns: 1fr;
  }

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
