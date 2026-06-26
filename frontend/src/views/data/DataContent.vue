<template>
  <section class="data-content">
    <header class="tab-header">
      <h1>Data</h1>
      <ResponsiveHeaderActions :items="headerActionItems">
        <Button
          label="Refresh"
          icon="pi pi-refresh"
          class="p-button-text p-button-sm"
          :loading="dataStore.catalogLoading"
          @click="refresh"
        />
        <Button
          label="Next: Workflow"
          icon="pi pi-arrow-right"
          iconPos="right"
          class="p-button-sm"
          @click="goToWorkflow"
        />
      </ResponsiveHeaderActions>
    </header>

    <!-- Two-cell context strip: Project always on the left; the right cell
         reflects only what the user is doing in the active subtab. -->
    <div class="data-context-strip" aria-label="Data workspace context">
      <button class="data-context-item" type="button" @click="router.push('/project')">
        <span class="context-label">Project</span>
        <strong>{{ activeProjectName }}</strong>
        <small>{{ projectDataCount }} data · {{ projectWorkflowCount }} workflows</small>
      </button>
      <div class="data-context-item active-context" aria-live="polite">
        <span class="context-label">{{ activeSubtabLabel }}</span>
        <strong>{{ activeSubtabValue }}</strong>
        <small>{{ activeSubtabDetail }}</small>
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab">
      <!-- ======================== IMPORT TAB ======================== -->
      <TabPanel header="Import">
        <div class="source-side-layout">
        <!-- ============ REFERENCE DATASETS (top, prominent) ============ -->
        <div class="ref-catalog-section source-list-pane">
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
            <!-- Spectra Scientific synthetic benchmarks -->
            <Panel
              :toggleable="true"
              :collapsed="syntheticCollapsed"
              @update:collapsed="syntheticCollapsed = $event"
              class="ref-group-panel"
            >
              <template #header>
                <span class="ref-panel-header">
                  <i class="pi pi-sparkles"></i>
                  Spectra Scientific Synthetic Benchmarks
                  <Tag :value="String(dataStore.referenceCatalog.synthetic.length)" severity="info" rounded />
                </span>
              </template>
              <div
                v-for="ds in dataStore.referenceCatalog.synthetic"
                :key="ds.name"
                class="ref-dataset-item"
                :class="{ selected: selectedRefDatasets.has(dsKey(ds)), previewed: previewRefKey === dsKey(ds) }"
                @click="previewReferenceDataset(ds)"
              >
                <Checkbox
                  :modelValue="selectedRefDatasets.has(dsKey(ds))"
                  :binary="true"
                  @click.stop
                  @update:model-value="toggleRefDataset(ds)"
                />
                <span class="ref-ds-label">{{ ds.label }}</span>
                <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
              </div>
            </Panel>

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
                :class="{ selected: selectedRefDatasets.has(dsKey(ds)), previewed: previewRefKey === dsKey(ds) }"
                @click="previewReferenceDataset(ds)"
              >
                <Checkbox
                  :modelValue="selectedRefDatasets.has(dsKey(ds))"
                  :binary="true"
                  @click.stop
                  @update:model-value="toggleRefDataset(ds)"
                />
                <span class="ref-ds-label">{{ ds.label }}</span>
                <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
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
                :class="{ selected: selectedRefDatasets.has(dsKey(ds)), previewed: previewRefKey === dsKey(ds) }"
                @click="previewReferenceDataset(ds)"
              >
                <Checkbox
                  :modelValue="selectedRefDatasets.has(dsKey(ds))"
                  :binary="true"
                  @click.stop
                  @update:model-value="toggleRefDataset(ds)"
                />
                <span class="ref-ds-label">{{ ds.label }}</span>
                <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
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
                  :class="{ selected: selectedRefDatasets.has(dsKey(ds)), previewed: previewRefKey === dsKey(ds) }"
                  @click="previewReferenceDataset(ds)"
                >
                  <Checkbox
                    :modelValue="selectedRefDatasets.has(dsKey(ds))"
                    :binary="true"
                    @click.stop
                    @update:model-value="toggleRefDataset(ds)"
                  />
                  <span class="ref-ds-label">{{ ds.label }}</span>
                  <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
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
                :class="{ selected: selectedRefDatasets.has(dsKey(ds)), previewed: previewRefKey === dsKey(ds) }"
                @click="previewReferenceDataset(ds)"
              >
                <Checkbox
                  :modelValue="selectedRefDatasets.has(dsKey(ds))"
                  :binary="true"
                  @click.stop
                  @update:model-value="toggleRefDataset(ds)"
                />
                <span class="ref-ds-label">{{ ds.label }}</span>
                <Tag :value="ds.technique" severity="info" class="ref-ds-tag" />
              </div>
            </Panel>
          </div>

          <!-- Action bar -->
          <div class="ref-action-bar" v-if="selectedRefDatasets.size > 0">
            <span class="ref-selection-count">{{ selectedRefDatasets.size }} selected</span>
            <div class="selected-member-rows">
              <div v-for="member in selectedReferenceMembers" :key="member.key" class="selected-member-row">
                <span>{{ member.label }}</span>
                <Button
                  icon="pi pi-times"
                  class="p-button-text p-button-sm p-button-rounded"
                  title="Remove"
                  @click="removeReferenceSelection(member.key)"
                />
              </div>
            </div>
            <div class="field ref-action-name">
              <label for="import-dataset-name">Dataset name</label>
              <InputText
                id="import-dataset-name"
                v-model="importDatasetName"
                :placeholder="defaultImportDatasetName()"
              />
            </div>
            <Button
              label="Add to My Dataset"
              icon="pi pi-plus"
              data-action="import_data"
              class="p-button-sm"
              :loading="importing"
              @click="onImportSelectedDatasets"
            />
          </div>
        </div>
        <DatasetSourcePreview
          class="source-preview-pane"
          :sourceRef="previewRefSource"
          :title="previewRefTitle"
          :files="previewRefFiles"
          :overrides="previewRefOverrides"
          @update:overrides="onPreviewRefOverrides"
        />
        </div>

      </TabPanel>

      <!-- ======================== SYNTHESIS TAB ======================== -->
      <TabPanel>
        <!-- #header slot is required so the open_synthesis click target
             (used by Sherpa Advisor's action ontology) lives on the tab
             header. Add the `p-tabview-title` class explicitly so the
             span picks up the same baseline / line-height PrimeVue
             auto-applies for header="…" tabs — without it, the active
             underline sits a couple pixels lower than the others. -->
        <template #header>
          <span class="p-tabview-title" data-action="open_synthesis">Synthesis</span>
        </template>
        <SynthesisPanel ref="synthesisPanelRef" @saved="onSynthesisSaved" />
      </TabPanel>

      <!-- ======================== UPLOAD TAB ======================== -->
      <TabPanel header="Upload">
        <section class="upload-panel source-side-layout">
          <div class="source-list-pane">
          <div v-if="dataUploadDisabled" class="upload-disabled-notice">
            {{ uploadDisabledMessage }}
          </div>
          <div class="upload-form">
            <div class="field">
              <label>Stage</label>
              <Dropdown
                v-model="uploadStage"
                :options="stageOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Select stage"
                class="upload-stage"
                :disabled="dataUploadDisabled"
              />
            </div>
            <div class="upload-shape-grid">
              <div class="field">
                <label>CSV data shape</label>
                <Dropdown
                  v-model="uploadDataRole"
                  :options="uploadDataRoleOptions"
                  optionLabel="label"
                  optionValue="value"
                  class="upload-shape-control"
                  :disabled="dataUploadDisabled"
                />
              </div>
              <div class="field">
                <label>Target column</label>
                <InputText
                  v-model.trim="uploadTargetColumn"
                  placeholder="Optional column name"
                  class="upload-shape-control"
                  :disabled="dataUploadDisabled"
                />
              </div>
              <div class="field">
                <label>Target type</label>
                <Dropdown
                  v-model="uploadTargetType"
                  :options="uploadTargetTypeOptions"
                  optionLabel="label"
                  optionValue="value"
                  class="upload-shape-control"
                  :disabled="dataUploadDisabled"
                />
              </div>
            </div>
            <div class="field">
              <label>File</label>
              <FileUpload
                ref="uploadFileUploadRef"
                mode="basic"
                :auto="false"
                :accept="uploadAcceptList"
                :maxFileSize="52428800"
                chooseLabel="Choose File"
                :disabled="dataUploadDisabled"
                @select="onFileSelect"
              />
              <small class="field-hint">
                {{ uploadFormatHint }}
              </small>
              <div v-if="disabledUploadFormats.length" class="upload-format-chips" aria-label="SCP-only formats">
                <span
                  v-for="format in disabledUploadFormats"
                  :key="format.key"
                  class="upload-format-chip disabled"
                  :title="disabledUploadFormatTitle(format)"
                >
                  {{ format.name }}
                </span>
              </div>
            </div>
            <div v-if="stagedUploadMembers.length" class="selected-member-rows upload-members">
              <div
                v-for="member in stagedUploadMembers"
                :key="member.staging_id"
                class="selected-member-row"
                :class="{ previewed: previewUploadId === member.staging_id }"
                @click="previewUploadMember(member.staging_id)"
              >
                <span>{{ member.filename }}</span>
                <Button
                  icon="pi pi-trash"
                  class="p-button-text p-button-sm p-button-rounded p-button-danger"
                  title="Remove"
                  @click.stop="removeStagedUpload(member.staging_id)"
                />
              </div>
            </div>
            <div class="upload-action">
              <div class="field upload-name">
                <label for="upload-dataset-name">Dataset name</label>
                <InputText
                  id="upload-dataset-name"
                  v-model="uploadDatasetName"
                  :placeholder="defaultUploadDatasetName()"
                  :disabled="dataUploadDisabled"
                />
              </div>
              <Button
                label="Add to My Dataset"
                icon="pi pi-plus"
                data-action="import_data"
                :disabled="dataUploadDisabled || stagedUploadMembers.length === 0"
                :loading="uploading"
                @click="onUploadFile"
              />
            </div>
          </div>
          </div>
          <DatasetSourcePreview
            class="source-preview-pane"
            :sourceRef="previewUploadSource"
            :title="previewUploadTitle"
            :files="previewUploadFiles"
            :overrides="previewUploadOverrides"
            :csvPlan="selectedUploadCsvPlan"
            @update:overrides="onPreviewUploadOverrides"
          />
        </section>
      </TabPanel>

      <!-- ======================== LIBRARY TAB ======================== -->
      <TabPanel>
        <template #header>
          <span class="p-tabview-title" data-action="open_library">Library</span>
        </template>
        <section class="library-panel">
          <div class="library-header">
            <div>
              <h3 class="library-title">
                <i class="pi pi-book"></i>
                Reference Library
              </h3>
              <p>
                Search local reference entries and packaged compound records. Use Import for datasets
                you want to copy into My Dataset.
              </p>
            </div>
            <span class="library-count">{{ filteredLibrary.length }} entries</span>
          </div>
          <div class="library-toolbar">
            <div class="field compact-field">
              <label for="library-source">Database</label>
              <Dropdown
                inputId="library-source"
                v-model="librarySource"
                :options="librarySourceOptions"
                optionLabel="label"
                optionValue="value"
                class="p-inputtext-sm"
                @change="onLibrarySourceChange"
              />
            </div>
            <span class="p-input-icon-left" style="width: 300px">
              <i class="pi pi-search" />
              <InputText
                v-model="librarySearch"
                :placeholder="isHitranLibrarySource(librarySource) ? 'Search HITRAN species...' : 'Search compounds...'"
                class="p-inputtext-sm"
                style="width: 100%"
                @keyup.enter="searchHitranLibrary"
              />
            </span>
            <Button
              v-if="isHitranLibrarySource(librarySource)"
              label="Search"
              icon="pi pi-search"
              class="p-button-sm"
              :loading="librarySearching"
              @click="searchHitranLibrary"
            />
            <Button
              v-if="librarySource === 'nist'"
              :label="nistAddAllButtonLabel"
              icon="pi pi-plus-circle"
              class="p-button-sm p-button-outlined"
              :loading="importingLibrary && selectedLibraryKeys.size === 0"
              :disabled="filteredLibrary.length === 0 || importingLibrary"
              title="Add every visible NIST entry to the library basket"
              @click="onAddAllVisibleNistToBasket"
            />
            <div v-if="librarySource === 'hitran'" class="hitran-settings-row">
              <div class="field compact-field">
                <label for="library-resolution">Resolution</label>
                <InputNumber inputId="library-resolution" v-model="libraryResolutionCm1" :min="0.001" :maxFractionDigits="4" :useGrouping="false" />
              </div>
              <div class="field compact-field">
                <label for="library-wmin">Min cm^-1</label>
                <InputNumber inputId="library-wmin" v-model="libraryWavenumberMin" :min="1" :useGrouping="false" />
              </div>
              <div class="field compact-field">
                <label for="library-wmax">Max cm^-1</label>
                <InputNumber inputId="library-wmax" v-model="libraryWavenumberMax" :min="2" :useGrouping="false" />
              </div>
              <div class="field compact-field">
                <label for="library-temperature">Temperature (K)</label>
                <InputNumber inputId="library-temperature" v-model="libraryTemperatureK" :min="50" :max="5000" :maxFractionDigits="2" :useGrouping="false" />
              </div>
              <div class="field compact-field">
                <label for="library-pressure">Pressure (atm)</label>
                <InputNumber inputId="library-pressure" v-model="libraryPressureAtm" :min="0.000001" :maxFractionDigits="6" :useGrouping="false" />
              </div>
            </div>
          </div>
          <div class="synthesis-note warn" v-if="isHitranLibrarySource(librarySource)">
            <i class="pi pi-info-circle" />
            <span>HITRAN spectra are fetched live when needed and require your own HITRAN API key in Settings > API Keys.</span>
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
            <Column header="Review / Basket" style="width: 210px">
              <template #body="{ data }">
                <div class="library-spectrum-action">
                  <Button
                    icon="pi pi-cloud-download"
                    :label="librarySpectrumButtonLabel(data)"
                    class="p-button-sm p-button-outlined"
                    data-action="library_load_spectrum"
                    :loading="librarySpectrumLoadingKeys.has(data.key)"
                    :disabled="isLibrarySpectrumQueued(data)"
                    @click="loadLibrarySpectrum(data)"
                  />
                  <Button
                    icon="pi pi-plus"
                    :label="libraryBasketButtonLabel(data)"
                    class="p-button-sm p-button-text"
                    data-action="library_add_to_basket"
                    :disabled="!librarySpectra[data.key] || selectedLibraryKeys.has(data.key) || hitranLibraryImportActive"
                    :title="librarySpectra[data.key] ? 'Add to the library basket' : 'Load spectrum before adding to the library basket'"
                    @click="addLibraryToBasket(data)"
                  />
                  <Tag
                    v-if="librarySpectra[data.key]"
                    value="loaded"
                    severity="success"
                    class="library-spectrum-tag"
                  />
                  <div
                    v-if="librarySpectrumProgress[data.key]"
                    class="library-spectrum-progress"
                    aria-live="polite"
                  >
                    <ProgressBar :value="librarySpectrumProgress[data.key].progress" :showValue="false" />
                    <small>
                      {{ librarySpectrumProgress[data.key].progress }}%
                      {{ librarySpectrumProgress[data.key].message || "Loading spectrum" }}
                    </small>
                  </div>
                </div>
              </template>
            </Column>
            <Column field="compound_name" header="Compound" :sortable="true" />
            <Column field="formula" header="Formula" :sortable="true" style="width: 100px" />
            <Column field="cas_number" header="CAS Number" :sortable="true" style="width: 140px" />
            <Column v-if="librarySource === 'hitran_xsec'" header="Measurement" style="min-width: 260px">
              <template #body="{ data }">
                <Dropdown
                  v-model="data.selected_xsec_option"
                  :options="hitranXsecOptionChoices(data)"
                  optionLabel="label"
                  optionValue="value"
                  class="p-inputtext-sm xsec-option-dropdown"
                  @change="onHitranXsecOptionChange(data)"
                  @click.stop
                />
              </template>
            </Column>
            <Column field="resolution" header="Resolution" style="width: 100px" />
            <Column field="source_label" header="Database" style="width: 110px" />
            <Column field="file_path" header="File" style="width: 160px" v-if="librarySource === 'nist'">
              <template #body="{ data }">
                <span class="file-size">{{ data.file_path.split('/').pop() }}</span>
              </template>
            </Column>
          </DataTable>
          <div v-if="activeLibraryPreview" class="library-preview-panel">
            <div class="library-preview-header">
              <div>
                <strong>{{ activeLibraryPreview.name }}</strong>
                <span>{{ activeLibraryPreviewMeta }}</span>
              </div>
              <Button
                label="Clear Preview"
                icon="pi pi-times"
                class="p-button-sm p-button-text"
                @click="activeLibraryPreviewKey = null"
              />
            </div>
            <PlotlyChart :data="libraryPreviewPlotData" :layout="libraryPreviewPlotLayout" />
          </div>
          <div class="ref-action-bar library-basket-bar" v-if="selectedLibraryKeys.size > 0">
            <span class="ref-selection-count">{{ selectedLibraryKeys.size }} in basket</span>
            <div class="selected-member-rows">
              <div
                v-for="member in selectedLibraryMembers"
                :key="member.key"
                class="selected-member-row"
              >
                <span>{{ member.label }}</span>
                <small v-if="member.detail" class="selected-member-detail">{{ member.detail }}</small>
                <Tag
                  v-if="libraryMemberStatus(member.key)"
                  :value="libraryMemberStatus(member.key)"
                  :severity="libraryMemberStatusSeverity(member.key)"
                  class="selected-member-status"
                />
                <Button
                  icon="pi pi-times"
                  class="p-button-text p-button-sm p-button-rounded"
                  title="Remove from basket"
                  @click="removeLibrarySelection(member.key)"
                />
              </div>
            </div>
            <div class="field ref-action-name">
              <label for="library-dataset-name">Dataset name</label>
              <InputText
                id="library-dataset-name"
                v-model="libraryDatasetName"
                :placeholder="defaultLibraryDatasetName()"
              />
            </div>
            <div v-if="activeLibraryImportJob" class="library-import-progress" aria-live="polite">
              <Tag
                :value="activeLibraryImportJob.status === 'pending' ? 'In queue' : activeLibraryImportJob.status"
                :severity="libraryJobSeverity"
              />
              <span>{{ activeLibraryImportJob.progress }}%</span>
              <span>{{ activeLibraryImportJob.progress_message || 'Preparing HITRAN import' }}</span>
            </div>
            <Button
              :label="libraryImportButtonLabel"
              icon="pi pi-plus"
              data-action="import_library"
              class="p-button-sm"
              :loading="importingLibrary"
              :disabled="hitranLibraryImportActive"
              @click="onImportSelectedLibraryDatasets"
            />
          </div>
        </section>
      </TabPanel>

      <!-- ======================== MY DATASET TAB ======================== -->
      <!-- Persistent store. The four left-group source tabs all funnel
           into the dataset selected here via "Add to My Dataset" actions.
           Right-justified in the tab strip to mark the source / store
           distinction. -->
      <TabPanel header="My Dataset">
        <div class="my-dataset-section">
          <p class="my-dataset-summary">
            {{ dataStore.experiments.length }} dataset{{ dataStore.experiments.length === 1 ? "" : "s" }}
            containing {{ totalExperimentFiles }} file{{ totalExperimentFiles === 1 ? "" : "s" }} from Import, Synthesis, Upload, and Library.
          </p>

          <div class="load-panels">
            <!-- Dataset list (left) -->
            <div class="experiment-list-panel">
              <div class="panel-heading">
                <div>
                  <strong>Packaged Datasets</strong>
                  <span>One package can contain one or many files.</span>
                </div>
              </div>
              <DataTable
                :value="dataStore.experiments"
                :loading="dataStore.experimentsLoading"
                selectionMode="single"
                :selection="selectedExperiment"
                @update:selection="onExperimentSelect"
                dataKey="id"
                :rows="20"
                scrollable
                scrollHeight="170px"
                size="small"
                stripedRows
                class="exp-table"
              >
                <template #empty>
                  <div class="empty-state-sm">No datasets yet</div>
                </template>
                <Column field="name" header="Name" :sortable="true">
                  <template #body="{ data }">
                    <button
                      type="button"
                      class="dataset-name-button"
                      @click.stop="onExperimentSelect(data)"
                    >
                      {{ data.name }}
                    </button>
                  </template>
                </Column>
                <Column field="file_count" header="Files" :sortable="true" style="width: 70px" />
                <Column header="Created" :sortable="true" style="width: 145px">
                  <template #body="{ data }">
                    {{ formatDate(data.created_at) }}
                  </template>
                </Column>
                <Column header="" style="width: 86px">
                  <template #body="{ data }">
                    <div class="dataset-row-actions">
                      <Button
                        icon="pi pi-pencil"
                        class="p-button-text p-button-sm p-button-rounded"
                        title="Rename dataset"
                        aria-label="Rename dataset"
                        @click.stop="openEditDatasetDialog(data)"
                      />
                      <Button
                        icon="pi pi-trash"
                        class="p-button-text p-button-sm p-button-rounded p-button-danger"
                        title="Delete dataset"
                        aria-label="Delete dataset"
                        @click.stop="confirmDeleteExperiment(data)"
                      />
                    </div>
                  </template>
                </Column>
              </DataTable>
            </div>

            <!-- Files panel (right) -->
            <div class="files-panel">
              <div class="panel-heading">
                <div>
                  <strong>Files in Dataset</strong>
                  <span>{{ selectedExperimentName }}</span>
                </div>
              </div>
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
                <small>Use Import, Synthesis, Upload, or Library to add data to this record.</small>
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
                        :class="{ selected: dataStore.activeFileId === file.id }"
                        role="button"
                        tabindex="0"
                        @click="onInspectFile(file)"
                        @keydown.enter.prevent="onInspectFile(file)"
                        @keydown.space.prevent="onInspectFile(file)"
                      >
                        <div class="file-info">
                          <span class="file-name">{{ extractFileName(file.file_path) }}</span>
                          <span v-if="formatDatasetFileShape(file)" class="file-size">
                            {{ formatDatasetFileShape(file) }}
                          </span>
                          <span v-if="file.file_size_bytes" class="file-size">
                            {{ formatFileSize(file.file_size_bytes) }}
                          </span>
                        </div>
                        <div class="file-actions">
                          <Button
                            icon="pi pi-download"
                            class="p-button-text p-button-sm p-button-rounded"
                            title="Download"
                            @click.stop="dataStore.downloadFile(file.id, extractFileName(file.file_path))"
                          />
                          <Button
                            icon="pi pi-trash"
                            class="p-button-text p-button-sm p-button-rounded p-button-danger"
                            title="Delete"
                            @click.stop="confirmDeleteFile(file)"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-if="canReopenSynthesisRecipe || canReopenLibraryBasket" class="builder-reopen-actions">
            <Button
              v-if="canReopenSynthesisRecipe"
              label="Reopen Synthesis Recipe"
              icon="pi pi-history"
              class="p-button-sm p-button-outlined"
              @click="reopenInspectedSynthesisRecipe"
            />
            <Button
              v-if="canReopenLibraryBasket"
              label="Reopen Library Basket"
              icon="pi pi-history"
              class="p-button-sm p-button-outlined"
              @click="reopenSelectedLibraryBasket"
            />
          </div>
          <DataContentsPanel />
        </div>
      </TabPanel>

    </TabView>

    <!-- ======================== DIALOGS ======================== -->

    <!-- Edit Dataset -->
    <Dialog
      v-model:visible="showEditDatasetDialog"
      header="Edit Dataset"
      :modal="true"
      :style="{ width: '420px' }"
    >
      <div class="dialog-form">
        <div class="field">
          <label for="edit-exp-name">Name <span class="required">*</span></label>
          <InputText
            id="edit-exp-name"
            v-model="editExpName"
            placeholder="e.g. IR Ethanol Samples"
            :class="{ 'p-invalid': editSubmitted && !editExpName.trim() }"
          />
          <small v-if="editSubmitted && !editExpName.trim()" class="p-error">
            Name is required
          </small>
        </div>
        <div class="field">
          <label for="edit-exp-desc">Description</label>
          <Textarea
            id="edit-exp-desc"
            v-model="editExpDescription"
            rows="2"
            placeholder="Optional description"
          />
        </div>
      </div>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="showEditDatasetDialog = false"
        />
        <Button
          label="Save"
          icon="pi pi-check"
          :loading="editingExp"
          @click="onEditExperiment"
        />
      </template>
    </Dialog>

    <!-- Upload File dialog removed — Upload is now its own subtab. -->


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
        <strong>{{ deleteExperimentTarget?.name }}</strong>
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
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch } from "vue";
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
import InputNumber from "primevue/inputnumber";
import FileUpload from "primevue/fileupload";
import Panel from "primevue/panel";
import ProgressSpinner from "primevue/progressspinner";
import ProgressBar from "primevue/progressbar";
import Tag from "primevue/tag";
import api from "@/api/client";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";
import {
  useDataStore,
  type CsvImportPlan,
  type DataMatrixRef,
  type PreparedDataOverrides,
  type StagedUpload,
} from "@/stores/data";
import { useAdvisorStore } from "@/stores/advisor";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { getErrorMessage } from "@/utils/errors";
import { useToast } from "primevue/usetoast";
import type { ExperimentFile, ExperimentSummary, JobInfo } from "@/types";
import type { ReferenceDatasetOption } from "@/stores/workflow";
import ResponsiveHeaderActions from "@/components/ResponsiveHeaderActions.vue";
import DataContentsPanel from "./DataContentsPanel.vue";
import DatasetSourcePreview from "./DatasetSourcePreview.vue";
import SynthesisPanel from "./SynthesisPanel.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import type { SpectrumPayload } from "@/stores/synthesis";

const DATA_ENTRY_MODE_KEY = "sherpa:data-entry-mode";
const DATA_ENTRY_PROJECT_KEY = "sherpa:data-entry-project-id";
const DATA_ACTIVE_TAB_PREFIX = "spectra_sherpa_data_active_tab_v2";
const DATA_DRAFT_PREFIX = "spectra_sherpa_data_draft_v1";
const TAB_IMPORT = 0;
const TAB_SYNTHESIS = 1;
const TAB_UPLOAD = 2;
const TAB_LIBRARY = 3;
const TAB_MY_DATASET = 4;

const appConfigApi = useAppConfig();
const appConfig = computed(() => appConfigApi.config?.value ?? appConfigApi.appConfig?.value ?? null);
const { isCapabilityDisabled } = appConfigApi;
const { isDemoMode, uploadsLastWeek, uploadsLimitWeek, uploadsResetWeekAt, fetchQuota } = useDemoMode();
const dataStore = useDataStore();
const authStore = useAuthStore();
const projectStore = useProjectStore();
const advisorStore = useAdvisorStore();
const toast = useToast();
const route = useRoute();
const router = useRouter();
const synthesisPanelRef = ref<InstanceType<typeof SynthesisPanel> | null>(null);
const uploadFileUploadRef = ref<InstanceType<typeof FileUpload> | null>(null);
const activeExperimentMetadata = ref<Record<string, unknown> | null>(null);
const activeTab = ref(0);
const isGuidedExampleSession = ref(false);
const headerActionItems = computed(() => [
  {
    label: "Refresh",
    icon: "pi pi-refresh",
    disabled: dataStore.catalogLoading,
    command: refresh,
  },
  {
    label: "Next: Workflow",
    icon: "pi pi-arrow-right",
    command: goToWorkflow,
  },
]);

// R3 — Sherpa Advisor scope routing for the Data tab.  The UI now has
// clearer Data workspace tabs, while the server still owns the stable
// memory vocabulary (`load`, `explore`, `synthesis`).
const DATA_SUBSCOPE_KEYS = ["load", "synthesis", "load", "load", "explore"] as const;
const DATA_SUBSCOPE_TITLES = ["Import", "Synthesis", "Upload", "Library", "Contents"] as const;

type LibrarySource = "nist" | "hitran" | "hitran_xsec";
type LibraryRangeMode = "common" | "widest";
interface HitranXsecOption {
  temperature_k?: [number, number] | null;
  pressure_torr?: [number, number] | null;
  wavenumber_cm1?: [number, number] | null;
  sets?: number | null;
  resolution_cm1?: number | null;
  npts?: number | null;
  broadener?: string | null;
}
interface LibraryFrozenSettings {
  component_id?: string;
  resolution_cm1?: number | null;
  wavenumber_min?: number | null;
  wavenumber_max?: number | null;
  temperature_k?: number | null;
  pressure_atm?: number | null;
  xsec_option?: number | null;
  points?: number | null;
  y_quantity?: string | null;
  y_units?: string | null;
}
interface LibraryRow {
  key: string;
  source: LibrarySource;
  id?: number;
  component_id?: string;
  compound_name: string;
  formula?: string | null;
  cas_number: string;
  resolution: string | null;
  source_label: string;
  file_path?: string;
  xsec_options?: HitranXsecOption[];
  selected_xsec_option?: number;
  frozen_settings?: LibraryFrozenSettings;
}
interface LibrarySearchComponent {
  id: string;
  name?: string | null;
  formula?: string | null;
  cas?: string | null;
  xsec_options?: HitranXsecOption[];
}
interface NistLibrarySpectrumResponse {
  component_id: string;
  name: string;
  source: "nist";
  x: number[];
  y: number[];
  x_title: string;
  x_units?: string | null;
  y_title: string;
  y_units?: string | null;
  metadata?: Record<string, unknown>;
}
interface LibrarySpectrumQueueItem {
  entry: LibraryRow;
  resolve: () => void;
}
interface SourcePreviewFile {
  name: string;
  extension?: string | null;
}
interface DataDraftSnapshot {
  version: 1;
  saved_at: string;
  import: {
    selected_keys: string[];
    preview_key: string | null;
    overrides: Record<string, PreparedDataOverrides>;
    dataset_name: string;
    collapsed: {
      synthetic: boolean;
      eigenvector: boolean;
      oes: boolean;
      spectrochempy: boolean;
      sklearn: boolean;
    };
  };
  library: {
    source: LibrarySource;
    range_mode: LibraryRangeMode;
    search: string;
    dataset_name: string;
    resolution_cm1: number;
    wavenumber_min: number;
    wavenumber_max: number;
    temperature_k: number;
    pressure_atm: number;
    selected_keys: string[];
    selected_rows: Record<string, LibraryRow>;
  };
}

function dataActiveTabStorageKey(): string {
  return `${DATA_ACTIVE_TAB_PREFIX}_${authStore.user?.id ?? "local"}_${
    projectStore.currentProjectId ?? "no-project"
  }`;
}

function dataDraftStorageKey(): string {
  return `${DATA_DRAFT_PREFIX}:${authStore.user?.id ?? "local"}:${
    projectStore.currentProjectId ?? "no-project"
  }`;
}

function restoreActiveDataTab(): void {
  try {
    const raw = localStorage.getItem(dataActiveTabStorageKey());
    const parsed = raw === null ? NaN : Number(raw);
    if (Number.isInteger(parsed) && parsed >= 0 && parsed < DATA_SUBSCOPE_KEYS.length) {
      activeTab.value = parsed;
    }
  } catch {
    /* localStorage may be unavailable. */
  }
}

function persistActiveDataTab(): void {
  try {
    localStorage.setItem(dataActiveTabStorageKey(), String(activeTab.value));
  } catch {
    /* localStorage may be unavailable. */
  }
}

async function syncAdvisorForDataSubtab(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null) return;
  const tabIndex = activeTab.value;
  const subscopeKey = DATA_SUBSCOPE_KEYS[tabIndex] ?? "load";
  try {
    await advisorStore.switchScope({
      projectId,
      tabKey: "data",
      subscopeKey,
      title: DATA_SUBSCOPE_TITLES[tabIndex] ?? "Import",
    });
  } catch (err) {
    console.warn("[data] switchScope failed", err);
  }
}

// Fire on mount and on every Data subtab change.  Project switches are
// covered by the projectId watcher below.
watch(activeTab, () => {
  persistActiveDataTab();
  void syncAdvisorForDataSubtab();
});
watch(
  () => projectStore.currentProjectId,
  async (next, prev) => {
    // Skip the initial boot resolution (null/undefined -> id). onMounted
    // already owns first-load setup (restoreActiveDataTab +
    // restoreActiveExperimentForCurrentProject + applyRouteExploreState).
    // On slow managed-auth deployments the identity rehydration can resolve
    // the project a few seconds after mount. If the user is already viewing
    // Contents, running the reset below would clear the active experiment and
    // snap back to the persisted tab. Only react to a genuine project switch.
    if (prev == null) {
      return;
    }
    persistDataDraftNow(currentDataDraftStorageKey);
    currentDataDraftStorageKey = dataDraftStorageKey();
    restoreActiveDataTab();
    restoreDataDraft(currentDataDraftStorageKey);
    dataStore.clearActiveExperimentSelection();
    await Promise.all([dataStore.fetchCatalog(), dataStore.fetchExperiments()]);
    await dataStore.restoreActiveExperimentForCurrentProject();
    if (next != null) void syncAdvisorForDataSubtab();
  },
);
onMounted(() => {
  void syncAdvisorForDataSubtab();
});

onBeforeUnmount(() => {
  persistDataDraftNow();
  stopLibraryImportPolling();
  clearLibrarySpectrumLoadQueue();
});

// --- Load tab state ---
const librarySearch = ref("");
const librarySource = ref<LibrarySource>("nist");
const libraryRangeMode = ref<LibraryRangeMode>("widest");
const selectedLibraryKeys = reactive(new Set<string>());
const selectedLibraryRows = reactive<Record<string, LibraryRow>>({});
const hitranLibraryRows = ref<LibraryRow[]>([]);
const hitranXsecLibraryRows = ref<LibraryRow[]>([]);
const librarySearching = ref(false);
const libraryResolutionCm1 = ref(0.1);
const libraryWavenumberMin = ref(400);
const libraryWavenumberMax = ref(4000);
const libraryTemperatureK = ref(293);
const libraryPressureAtm = ref(1);
const activeLibraryImportJob = ref<JobInfo | null>(null);
const activeLibraryImportExperimentId = ref<number | null>(null);
const librarySpectra = reactive<Record<string, SpectrumPayload>>({});
const librarySpectrumLoadingKeys = reactive(new Set<string>());
const librarySpectrumProgress = reactive<Record<string, { progress: number; message: string | null }>>({});
const librarySpectrumLoadQueue = ref<LibrarySpectrumQueueItem[]>([]);
const activeLibrarySpectrumLoadKey = ref<string | null>(null);
const activeLibraryPreviewKey = ref<string | null>(null);
let libraryImportPollTimer: ReturnType<typeof window.setInterval> | null = null;
const selectedRefDatasets = reactive(new Set<string>());
const previewRefKey = ref<string | null>(null);
const refOverrides = reactive<Record<string, PreparedDataOverrides>>({});
const syntheticCollapsed = ref(false);
const eigenvectorCollapsed = ref(false);
const oesCollapsed = ref(false);
const scpCollapsed = ref(true);
const sklearnCollapsed = ref(true);
const importing = ref(false);
const importingLibrary = ref(false);
const showEditDatasetDialog = ref(false);
const showDeleteDialog = ref(false);
const showDeleteExpDialog = ref(false);
const deletingExp = ref(false);
const deleteExperimentTarget = ref<ExperimentSummary | null>(null);
const editExperimentTarget = ref<ExperimentSummary | null>(null);
const editExpName = ref("");
const editExpDescription = ref("");
const editSubmitted = ref(false);
const editingExp = ref(false);
const uploading = ref(false);
const uploadQuotaExhausted = computed(() => (
  isDemoMode.value
  && uploadsLastWeek.value !== null
  && uploadsLimitWeek.value > 0
  && uploadsLimitWeek.value < 999999
  && uploadsLastWeek.value >= uploadsLimitWeek.value
));
const uploadDisabledMessage = computed(() => {
  if (isCapabilityDisabled("data_upload")) return "File upload is disabled for this deployment.";
  if (uploadQuotaExhausted.value) {
    const reset = uploadsResetWeekAt.value ? new Date(uploadsResetWeekAt.value).toLocaleString() : "later";
    return `Demo upload limit reached. Your next upload is available ${reset}.`;
  }
  return "";
});
const dataUploadDisabled = computed(() => isCapabilityDisabled("data_upload") || uploadQuotaExhausted.value);
const uploadDataFormats = computed(() => appConfig.value?.dataFormats ?? null);
const uploadScpInstallCommand = computed(() => uploadDataFormats.value?.installScpCommand ?? "pip install spectra-sherpa[scp]");
const uploadAcceptList = computed(() => {
  const accepted = uploadDataFormats.value?.acceptedExtensions;
  if (accepted?.length) return accepted.join(",");
  return ".csv,.mat,.jdx,.dx,.npy,.npz";
});
const availableUploadFormats = computed(() => {
  const formats = uploadDataFormats.value?.formats;
  if (!formats?.length) return ["CSV", "MAT", "JCAMP-DX", "NumPy"];
  return formats.filter((format) => format.available).map((format) => format.name);
});
const disabledUploadFormats = computed(() => {
  const formats = uploadDataFormats.value?.formats ?? [];
  return formats.filter((format) => !format.available);
});
function disabledUploadFormatTitle(format: { name: string; unsupportedReason?: string; requiresScp?: boolean }): string {
  if (format.unsupportedReason) return format.unsupportedReason;
  if (format.requiresScp) return `${format.name} requires ${uploadScpInstallCommand.value}`;
  return `${format.name} is not available in this deployment.`;
}
const uploadFormatHint = computed(() => {
  const supported = availableUploadFormats.value.join(", ");
  const disabled = disabledUploadFormats.value;
  if (!disabled.length) return `Supported: ${supported} (max 50 MB)`;
  const hints: string[] = [];
  if (disabled.some((format) => format.requiresScp)) hints.push(`vendor formats require ${uploadScpInstallCommand.value}`);
  if (disabled.some((format) => format.requiresExport)) hints.push("OMNICxi/Paradigm containers require spectrum export first");
  return `Supported: ${supported} (max 50 MB). ${hints.join("; ")}.`;
});
const deleting = ref(false);
const uploadStage = ref("raw");
const uploadDataRole = ref("auto");
const uploadTargetColumn = ref("");
const uploadTargetType = ref("auto");
const selectedFile = ref<File | null>(null);
const stagedUploadMembers = ref<StagedUpload[]>([]);
const previewUploadId = ref<string | null>(null);
const uploadOverrides = reactive<Record<string, PreparedDataOverrides>>({});
const deleteTarget = ref<ExperimentFile | null>(null);

// Inline "Dataset name" inputs on Import + Upload subtabs. Mirror the
// Synthesis pattern: name the new My Dataset before clicking "Add to
// My Dataset"; the click creates the Experiment and ingests in one step.
const importDatasetName = ref("");
const libraryDatasetName = ref("");
const uploadDatasetName = ref("");

function clearUploadFileSelection() {
  selectedFile.value = null;
  (uploadFileUploadRef.value as { clear?: () => void } | null)?.clear?.();
}

const librarySourceOptions = [
  { label: "NIST", value: "nist" },
  { label: "HITRAN Line-by-Line", value: "hitran" },
  { label: "HITRAN Absorption X-section", value: "hitran_xsec" },
];

let dataDraftHydrating = false;
let dataDraftPersistTimer: ReturnType<typeof window.setTimeout> | null = null;
let currentDataDraftStorageKey = dataDraftStorageKey();

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function replaceReactiveRecord<T>(target: Record<string, T>, source: Record<string, T> | undefined): void {
  for (const key of Object.keys(target)) {
    delete target[key];
  }
  if (!source) return;
  for (const [key, value] of Object.entries(source)) {
    target[key] = value;
  }
}

function replaceReactiveSet(target: Set<string>, source: unknown): void {
  target.clear();
  if (!Array.isArray(source)) return;
  for (const value of source) {
    if (typeof value === "string" && value.trim()) target.add(value);
  }
}

function isLibrarySource(value: unknown): value is LibrarySource {
  return value === "nist" || value === "hitran" || value === "hitran_xsec";
}

function isLibraryRangeMode(value: unknown): value is LibraryRangeMode {
  return value === "common" || value === "widest";
}

function finiteNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function stringOrEmpty(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function objectOrNull(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function applyLibraryDraft(libraryDraft: DataDraftSnapshot["library"] | undefined): void {
  if (!libraryDraft) return;
  librarySource.value = isLibrarySource(libraryDraft.source) ? libraryDraft.source : "nist";
  libraryRangeMode.value = isLibraryRangeMode(libraryDraft.range_mode) ? libraryDraft.range_mode : "widest";
  librarySearch.value = stringOrEmpty(libraryDraft.search);
  libraryDatasetName.value = stringOrEmpty(libraryDraft.dataset_name);
  libraryResolutionCm1.value = finiteNumber(libraryDraft.resolution_cm1, 0.1);
  libraryWavenumberMin.value = finiteNumber(libraryDraft.wavenumber_min, 400);
  libraryWavenumberMax.value = finiteNumber(libraryDraft.wavenumber_max, 4000);
  libraryTemperatureK.value = finiteNumber(libraryDraft.temperature_k, 293);
  libraryPressureAtm.value = finiteNumber(libraryDraft.pressure_atm, 1);
  replaceReactiveRecord(selectedLibraryRows, libraryDraft.selected_rows);
  selectedLibraryKeys.clear();
  for (const key of Array.isArray(libraryDraft.selected_keys) ? libraryDraft.selected_keys : []) {
    if (typeof key === "string" && selectedLibraryRows[key]) selectedLibraryKeys.add(key);
  }
  if (activeLibraryPreviewKey.value && !selectedLibraryRows[activeLibraryPreviewKey.value]) {
    activeLibraryPreviewKey.value = null;
  }
}

function dataDraftSnapshot(): DataDraftSnapshot {
  return {
    version: 1,
    saved_at: new Date().toISOString(),
    import: {
      selected_keys: Array.from(selectedRefDatasets),
      preview_key: previewRefKey.value,
      overrides: cloneJson(refOverrides),
      dataset_name: importDatasetName.value,
      collapsed: {
        synthetic: syntheticCollapsed.value,
        eigenvector: eigenvectorCollapsed.value,
        oes: oesCollapsed.value,
        spectrochempy: scpCollapsed.value,
        sklearn: sklearnCollapsed.value,
      },
    },
    library: {
      source: librarySource.value,
      range_mode: libraryRangeMode.value,
      search: librarySearch.value,
      dataset_name: libraryDatasetName.value,
      resolution_cm1: libraryResolutionCm1.value,
      wavenumber_min: libraryWavenumberMin.value,
      wavenumber_max: libraryWavenumberMax.value,
      temperature_k: libraryTemperatureK.value,
      pressure_atm: libraryPressureAtm.value,
      selected_keys: Array.from(selectedLibraryKeys),
      selected_rows: cloneJson(selectedLibraryRows),
    },
  };
}

function applyDataDraft(raw: unknown): void {
  if (!raw || typeof raw !== "object" || (raw as { version?: unknown }).version !== 1) return;
  const draft = raw as Partial<DataDraftSnapshot>;
  dataDraftHydrating = true;
  try {
    const importDraft = draft.import;
    if (importDraft) {
      replaceReactiveSet(selectedRefDatasets, importDraft.selected_keys);
      previewRefKey.value = typeof importDraft.preview_key === "string" ? importDraft.preview_key : null;
      replaceReactiveRecord(refOverrides, importDraft.overrides);
      importDatasetName.value = stringOrEmpty(importDraft.dataset_name);
      syntheticCollapsed.value = Boolean(importDraft.collapsed?.synthetic);
      eigenvectorCollapsed.value = Boolean(importDraft.collapsed?.eigenvector);
      oesCollapsed.value = Boolean(importDraft.collapsed?.oes);
      scpCollapsed.value = importDraft.collapsed?.spectrochempy ?? true;
      sklearnCollapsed.value = importDraft.collapsed?.sklearn ?? true;
    }

    applyLibraryDraft(draft.library);
  } finally {
    dataDraftHydrating = false;
  }
}

function restoreDataDraft(key = dataDraftStorageKey()): void {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return;
    applyDataDraft(JSON.parse(raw));
  } catch {
    /* Ignore corrupt or unavailable browser storage. */
  }
}

function persistDataDraftNow(key = currentDataDraftStorageKey): void {
  if (dataDraftPersistTimer !== null) {
    window.clearTimeout(dataDraftPersistTimer);
    dataDraftPersistTimer = null;
  }
  try {
    localStorage.setItem(key, JSON.stringify(dataDraftSnapshot()));
  } catch {
    /* Ignore full or unavailable browser storage. */
  }
}

function scheduleDataDraftPersist(): void {
  if (dataDraftHydrating) return;
  if (dataDraftPersistTimer !== null) window.clearTimeout(dataDraftPersistTimer);
  dataDraftPersistTimer = window.setTimeout(() => {
    persistDataDraftNow();
  }, 150);
}

function defaultImportDatasetName(): string {
  if (selectedRefDatasets.size === 0) return "Imported references";
  // Use the first selected dataset's label as a sensible default; multi-select
  // appends " (+N more)" so the count is obvious before saving.
  const first = Array.from(selectedRefDatasets)[0];
  const [, ...rest] = first.split("::");
  const label = rest.join("::");
  if (selectedRefDatasets.size === 1) return label;
  return `${label} (+${selectedRefDatasets.size - 1} more)`;
}

function defaultUploadDatasetName(): string {
  const first = stagedUploadMembers.value[0]?.filename ?? selectedFile.value?.name;
  if (!first) return "Uploaded dataset";
  if (stagedUploadMembers.value.length > 1) {
    return `${first.replace(/\.[^.]+$/, "")} (+${stagedUploadMembers.value.length - 1} more)`;
  }
  return first.replace(/\.[^.]+$/, "");
}

function defaultLibraryDatasetName(): string {
  const now = new Date();
  const stamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
    "_",
    String(now.getHours()).padStart(2, "0"),
    String(now.getMinutes()).padStart(2, "0"),
    String(now.getSeconds()).padStart(2, "0"),
  ].join("");
  return `Library_${stamp}`;
}

const uploadDataRoleOptions = [
  { label: "Auto-detect", value: "auto" },
  { label: "Spectra / ordered variables", value: "X_spectra" },
  { label: "Feature table", value: "X_features" },
];

const uploadTargetTypeOptions = [
  { label: "Auto", value: "auto" },
  { label: "Categorical", value: "categorical" },
  { label: "Continuous", value: "continuous" },
];

const selectedUploadMember = computed(() =>
  stagedUploadMembers.value.find((member) => member.staging_id === previewUploadId.value) ??
  stagedUploadMembers.value[0] ??
  null
);
const previewUploadSource = computed<DataMatrixRef | null>(() => {
  const member = selectedUploadMember.value;
  if (!member) return null;
  return {
    kind: "staged",
    staging_id: member.staging_id,
    overrides: uploadOverrides[member.staging_id] ?? null,
  };
});
const previewUploadTitle = computed(() => selectedUploadMember.value?.filename ?? "Upload preview");
const previewUploadFiles = computed<SourcePreviewFile[]>(() =>
  selectedUploadMember.value ? sourcePreviewFilesFromNames([selectedUploadMember.value.filename]) : []
);
const previewUploadOverrides = computed(() =>
  selectedUploadMember.value ? uploadOverrides[selectedUploadMember.value.staging_id] ?? {} : {}
);
const selectedUploadCsvPlan = computed<CsvImportPlan | null>(() => selectedUploadMember.value?.csv_import_plan ?? null);

let uploadControlsHydrating = false;
let uploadControlsHydrationRun = 0;

function uploadControlOverrides(member: StagedUpload, existing: PreparedDataOverrides = {}): PreparedDataOverrides {
  const overrides: PreparedDataOverrides = {
    ...existing,
    title: existing.title ?? member.filename.replace(/\.[^.]+$/, ""),
  };
  if (uploadDataRole.value === "auto") {
    delete overrides.data_role;
  } else {
    overrides.data_role = uploadDataRole.value;
  }
  const targetColumn = uploadTargetColumn.value.trim();
  if (targetColumn) {
    overrides.target_column = targetColumn;
  } else {
    delete overrides.target_column;
  }
  if (uploadTargetType.value && uploadTargetType.value !== "auto") {
    overrides.target_type = uploadTargetType.value;
  } else {
    delete overrides.target_type;
  }
  return overrides;
}

function syncUploadControlsFromOverrides(overrides: PreparedDataOverrides | undefined) {
  const hydrationRun = ++uploadControlsHydrationRun;
  uploadControlsHydrating = true;
  uploadDataRole.value = overrides?.data_role || "auto";
  uploadTargetColumn.value = overrides?.target_column || "";
  uploadTargetType.value = overrides?.target_type || "auto";
  nextTick(() => {
    if (hydrationRun === uploadControlsHydrationRun) {
      uploadControlsHydrating = false;
    }
  });
}

watch(
  () => selectedUploadMember.value?.staging_id ?? null,
  () => {
    const member = selectedUploadMember.value;
    syncUploadControlsFromOverrides(member ? uploadOverrides[member.staging_id] : undefined);
  },
);

watch(
  [uploadDataRole, uploadTargetColumn, uploadTargetType],
  () => {
    if (uploadControlsHydrating) return;
    const member = selectedUploadMember.value;
    if (!member) return;
    uploadOverrides[member.staging_id] = uploadControlOverrides(member, uploadOverrides[member.staging_id] ?? {});
  },
);

const fileStages = [
  { key: "raw", label: "Contents", icon: "pi pi-file" },
  { key: "preprocessed", label: "Preprocessed", icon: "pi pi-cog" },
  { key: "synthetic", label: "Synthetic", icon: "pi pi-sparkles" },
];

const stageOptions = [
  { label: "Contents", value: "raw" },
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

const activeProjectName = computed(() =>
  projectStore.currentProject?.name ?? "No project selected"
);

const projectDataCount = computed(() =>
  projectStore.currentProject?.experiment_count ??
  projectStore.currentProject?.experiments.length ??
  0
);

const projectWorkflowCount = computed(() =>
  projectStore.currentProject?.workflow_count ??
  projectStore.currentProject?.workflows.length ??
  0
);

const selectedExperimentName = computed(() =>
  selectedExperiment.value?.name ?? "No dataset selected"
);

const selectedExperimentFileCount = computed(() =>
  selectedExperiment.value?.file_count ?? dataStore.experimentFiles.length
);

const activeExperimentBuilderState = computed(() => {
  const metadata = activeExperimentMetadata.value;
  return objectOrNull(metadata?.builder_state);
});

const inspectedSynthesisRecipe = computed(() => {
  const fileRecipe = objectOrNull(dataStore.fileInfo?.metadata?.recipe);
  if (fileRecipe) return fileRecipe;
  const state = activeExperimentBuilderState.value;
  return state?.kind === "synthesis_recipe" ? objectOrNull(state.recipe) : null;
});

const inspectedSynthesisTitle = computed(() => {
  const metadata = dataStore.fileInfo?.metadata;
  const title = typeof metadata?.title === "string" ? metadata.title : selectedExperimentName.value;
  return title || selectedExperimentName.value;
});

const savedLibraryDraft = computed<DataDraftSnapshot["library"] | null>(() => {
  const state = activeExperimentBuilderState.value;
  if (state?.kind !== "library_basket") return null;
  const library = objectOrNull(state.library);
  return library ? (library as unknown as DataDraftSnapshot["library"]) : null;
});

const canReopenSynthesisRecipe = computed(() => inspectedSynthesisRecipe.value !== null);
const canReopenLibraryBasket = computed(() => savedLibraryDraft.value !== null);

const totalExperimentFiles = computed(() =>
  dataStore.experiments.reduce((total, experiment) => total + (experiment.file_count ?? 0), 0)
);

const inspectedDatasetShape = computed(() => {
  if (dataStore.fileInfo) {
    return `${dataStore.fileInfo.n_samples} samples × ${dataStore.fileInfo.n_features} features`;
  }
  if (dataStore.catalogDatasetInfo?.n_samples || dataStore.catalogDatasetInfo?.n_features) {
    return `${dataStore.catalogDatasetInfo.n_samples ?? "?"} samples × ${dataStore.catalogDatasetInfo.n_features ?? "?"} features`;
  }
  return `${selectedExperimentFileCount.value} file${selectedExperimentFileCount.value === 1 ? "" : "s"}`;
});

const syntheticFileCount = computed(() => filesForStage("synthetic").length);

const synthesisStateLabel = computed(() =>
  syntheticFileCount.value > 0 ? `${syntheticFileCount.value} synthetic file${syntheticFileCount.value === 1 ? "" : "s"}` : "Ready to generate"
);

const synthesisStateDetail = computed(() =>
  selectedExperiment.value
    ? "Create time-series mixtures for downstream models"
    : "Select or create a dataset record first"
);

// Two-cell context strip: which subtab am I on, and what should the
// right-side label / value / detail mirror for that subtab? All four
// non-"My Dataset" subtabs are means of producing or interacting with
// My Dataset, so each one is a transient working surface; My Dataset
// is the persistent store and gets its own right-justified tab.
// Tab indices after IA split:
//   0 Import, 1 Synthesis, 2 Upload, 3 Library  (source group, left)
//   4 My Dataset                                (store + contents, right)
const activeSubtabLabel = computed(() => {
  switch (activeTab.value) {
    case TAB_IMPORT: return "Import";
    case TAB_SYNTHESIS: return "Synthesis";
    case TAB_UPLOAD: return "Upload";
    case TAB_LIBRARY: return "Library";
    case TAB_MY_DATASET: return "My Dataset";
    default: return "—";
  }
});

const activeSubtabValue = computed(() => {
  switch (activeTab.value) {
    case TAB_IMPORT: return "Reference catalog";
    case TAB_SYNTHESIS: return synthesisStateLabel.value;
    case TAB_UPLOAD: return dataStore.activeExperimentId
      ? `Add to ${selectedExperimentName.value}`
      : "Pick a dataset first";
    case TAB_LIBRARY: return selectedLibraryKeys.size
      ? `${selectedLibraryKeys.size} in basket`
      : "Pure compound library";
    case TAB_MY_DATASET: return selectedExperimentName.value;
    default: return "—";
  }
});

const activeSubtabDetail = computed(() => {
  switch (activeTab.value) {
    case TAB_IMPORT: return "Browse reference datasets — Add to My Dataset";
    case TAB_SYNTHESIS: return synthesisStateDetail.value;
    case TAB_UPLOAD: return selectedFile.value
      ? `Ready to add ${selectedFile.value.name}`
      : stagedUploadMembers.value.length
        ? `${stagedUploadMembers.value.length} staged file${stagedUploadMembers.value.length === 1 ? "" : "s"}`
      : "Stage + file → Add to My Dataset";
    case TAB_LIBRARY: return selectedLibraryKeys.size
      ? "Review basket — Add to My Dataset"
      : "Browse pure-compound reference spectra";
    case TAB_MY_DATASET: return inspectedDatasetShape.value || `${selectedExperimentFileCount.value} file${selectedExperimentFileCount.value === 1 ? "" : "s"}`;
    default: return "";
  }
});

const nistLibraryRows = computed<LibraryRow[]>(() =>
  dataStore.libraryDatasets.map((entry) => ({
    key: `nist:${entry.id}`,
    source: "nist",
    id: entry.id,
    compound_name: entry.compound_name,
    cas_number: entry.cas_number,
    resolution: entry.resolution,
    source_label: "NIST",
    file_path: entry.file_path,
  }))
);

function isHitranLibrarySource(source: LibrarySource): boolean {
  return source === "hitran" || source === "hitran_xsec";
}

const activeLibraryRows = computed<LibraryRow[]>(() =>
  librarySource.value === "hitran"
    ? hitranLibraryRows.value
    : librarySource.value === "hitran_xsec"
      ? hitranXsecLibraryRows.value
      : nistLibraryRows.value
);

const filteredLibrary = computed<LibraryRow[]>(() => {
  const q = librarySearch.value.toLowerCase().trim();
  if (isHitranLibrarySource(librarySource.value)) return activeLibraryRows.value;
  if (!q) return activeLibraryRows.value;
  return activeLibraryRows.value.filter(
    (d) =>
      d.compound_name.toLowerCase().includes(q) ||
      d.cas_number.toLowerCase().includes(q) ||
      (d.formula || "").toLowerCase().includes(q)
  );
});

const activeLibraryPreview = computed<SpectrumPayload | null>(() => {
  if (!activeLibraryPreviewKey.value) return null;
  return librarySpectra[activeLibraryPreviewKey.value] || null;
});

const activeLibraryPreviewMeta = computed(() => {
  const spectrum = activeLibraryPreview.value;
  if (!spectrum) return "";
  const n = spectrum.wavenumber.length;
  const min = Math.min(...spectrum.wavenumber);
  const max = Math.max(...spectrum.wavenumber);
  return [ `${n} pts`, `${min.toFixed(2)}-${max.toFixed(2)} cm^-1`, spectrum.y_quantity ]
    .filter((part): part is string => typeof part === "string" && part.length > 0)
    .join(" · ");
});

const libraryPreviewPlotData = computed(() => {
  const spectrum = activeLibraryPreview.value;
  if (!spectrum) return [];
  const maxAbs = Math.max(...spectrum.intensity.map((value) => Math.abs(value)), 1e-30);
  return [
    {
      x: [...spectrum.wavenumber].reverse(),
      y: spectrum.intensity.map((value) => value / maxAbs).reverse(),
      type: "scatter",
      mode: "lines",
      name: spectrum.name,
      line: { color: "#2563eb", width: 2 },
      hovertemplate: `${spectrum.name}<br>%{x:.2f} cm^-1<br>normalized=%{y:.4f}<extra></extra>`,
    },
  ];
});

const libraryPreviewPlotLayout = computed(() => ({
  height: 320,
  margin: { l: 55, r: 20, t: 20, b: 45 },
  xaxis: { title: "Wavenumber (cm^-1)", autorange: "reversed" },
  yaxis: { title: "Normalized intensity" },
  showlegend: true,
}));

function libraryLabel(entry: LibraryRow): string {
  return entry.cas_number ? `${entry.compound_name} (${entry.cas_number})` : entry.compound_name;
}

function nistCompoundKey(entry: LibraryRow): string {
  const cas = entry.cas_number.trim().toLowerCase();
  if (cas) return `cas:${cas}`;
  return `name:${entry.compound_name.trim().toLowerCase()}`;
}

function nistResolutionValue(entry: LibraryRow): number {
  const match = String(entry.resolution || "").match(/[\d.]+/);
  return match ? Number(match[0]) : Number.POSITIVE_INFINITY;
}

function dedupeNistRowsByCompound(rows: LibraryRow[]): LibraryRow[] {
  const byCompound = new Map<string, LibraryRow>();
  for (const row of rows) {
    const key = nistCompoundKey(row);
    const current = byCompound.get(key);
    if (!current || nistResolutionValue(row) < nistResolutionValue(current)) {
      byCompound.set(key, row);
    }
  }
  return Array.from(byCompound.values());
}

function formatRange(values?: [number, number] | null, suffix = ""): string {
  if (!values || values.length !== 2) return "blank";
  const [low, high] = values;
  const body = Math.abs(low - high) < 1e-9 ? formatNumber(low) : `${formatNumber(low)}-${formatNumber(high)}`;
  return suffix ? `${body} ${suffix}` : body;
}

function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "blank";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 4, useGrouping: false });
}

function hitranXsecOptionLabel(option: HitranXsecOption, index: number): string {
  const temp = formatRange(option.temperature_k, "K");
  const pressure = formatRange(option.pressure_torr, "Torr");
  const resolution = option.resolution_cm1 ? `${formatNumber(option.resolution_cm1)} cm^-1` : "blank res.";
  const broadener = option.broadener || "blank broadener";
  return `${index + 1}. T ${temp} · p ${pressure} · ${resolution} · ${broadener}`;
}

function hitranXsecOptionChoices(entry: LibraryRow): Array<{ label: string; value: number }> {
  const options = entry.xsec_options?.length ? entry.xsec_options : [{}];
  return options.map((option, index) => ({ label: hitranXsecOptionLabel(option, index), value: index }));
}

const selectedLibraryMembers = computed(() =>
  Object.values(selectedLibraryRows)
    .filter((entry) => selectedLibraryKeys.has(entry.key))
    .map((entry) => ({
      key: entry.key,
      label: libraryLabel(entry),
      detail: libraryBasketDetail(entry),
    }))
);

const hitranLibraryImportActive = computed(() =>
  activeLibraryImportJob.value !== null &&
  ["pending", "running"].includes(activeLibraryImportJob.value.status)
);

const libraryImportButtonLabel = computed(() => {
  if (!hitranLibraryImportActive.value) return "Add to My Dataset";
  return activeLibraryImportJob.value?.status === "pending" ? "In queue" : "Loading";
});

const nistAddAllButtonLabel = computed(() => {
  const count = filteredLibrary.value.length;
  if (librarySearch.value.trim()) return `Add ${count} Filtered to Basket`;
  return `Add All ${count} to Basket`;
});

const libraryJobSeverity = computed(() => {
  const status = activeLibraryImportJob.value?.status;
  if (status === "completed") return "success";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "running") return "info";
  return "warning";
});

function activeLibraryImportPosition(): number {
  const message = activeLibraryImportJob.value?.progress_message ?? "";
  const match = message.match(/Loading\s+(\d+)\/\d+:/);
  if (!match) return 0;
  return Number(match[1]) || 0;
}

function libraryMemberStatus(key: string): string {
  const job = activeLibraryImportJob.value;
  if (!isHitranLibrarySource(librarySource.value) || !job) return "";
  const index = selectedLibraryMembers.value.findIndex((member) => member.key === key);
  if (index < 0) return "";
  if (job.status === "completed") return "Imported";
  if (job.status === "failed" || job.status === "cancelled") return "Failed";
  if (job.status === "pending") return "In queue";
  const current = activeLibraryImportPosition();
  if (current <= 0) return "In queue";
  if (index < current - 1) return "Imported";
  if (index === current - 1) return "Loading";
  return "In queue";
}

function libraryMemberStatusSeverity(key: string): "success" | "info" | "warning" | "danger" {
  const status = libraryMemberStatus(key);
  if (status === "Imported") return "success";
  if (status === "Loading") return "info";
  if (status === "Failed") return "danger";
  return "warning";
}

function isLibrarySpectrumQueued(entry: LibraryRow): boolean {
  return librarySpectrumLoadQueue.value.some((item) => item.entry.key === entry.key);
}

function librarySpectrumButtonLabel(entry: LibraryRow): string {
  if (librarySpectrumLoadingKeys.has(entry.key)) return "Loading";
  if (isLibrarySpectrumQueued(entry)) return "In queue";
  if (librarySpectra[entry.key]) return "Preview";
  return "Load spectrum";
}

function libraryBasketButtonLabel(entry: LibraryRow): string {
  return selectedLibraryKeys.has(entry.key) ? "In Basket" : "Add to the Library Basket";
}

function clearLibrarySpectrumLoadQueue(): void {
  for (const item of librarySpectrumLoadQueue.value) item.resolve();
  librarySpectrumLoadQueue.value = [];
}

function clearHitranLibrarySpectra(): void {
  for (const key of Object.keys(librarySpectra)) {
    if (key.startsWith("hitran")) delete librarySpectra[key];
  }
  for (const key of Object.keys(librarySpectrumProgress)) {
    if (key.startsWith("hitran")) delete librarySpectrumProgress[key];
  }
  if (activeLibraryPreviewKey.value?.startsWith("hitran")) {
    activeLibraryPreviewKey.value = null;
  }
  clearLibrarySpectrumLoadQueue();
}

function queueLibrarySpectrumLoad(entry: LibraryRow): Promise<void> {
  if (isLibrarySpectrumQueued(entry)) return Promise.resolve();
  return new Promise((resolve) => {
    librarySpectrumLoadQueue.value.push({ entry, resolve });
  });
}

function librarySpectrumParams(entry: LibraryRow): Record<string, string | number> {
  const componentId =
    entry.source === "hitran_xsec"
      ? `${String(entry.component_id)}#${entry.selected_xsec_option ?? 0}`
      : String(entry.component_id);
  const params: Record<string, string | number> = {
    source: entry.source,
    component_id: componentId,
  };
  if (entry.source === "hitran") {
    params.resolution_cm1 = libraryResolutionCm1.value;
    params.wavenumber_min = libraryWavenumberMin.value;
    params.wavenumber_max = libraryWavenumberMax.value;
    params.temperature_k = libraryTemperatureK.value;
    params.pressure_atm = libraryPressureAtm.value;
  }
  return params;
}

function freezeLibrarySettings(entry: LibraryRow): LibraryFrozenSettings {
  const spectrum = librarySpectra[entry.key];
  const settings: LibraryFrozenSettings = {
    component_id:
      entry.source === "hitran_xsec"
        ? `${String(entry.component_id)}#${entry.selected_xsec_option ?? 0}`
        : entry.component_id,
    xsec_option: entry.source === "hitran_xsec" ? entry.selected_xsec_option ?? 0 : null,
    points: spectrum?.wavenumber?.length ?? null,
    y_quantity: spectrum?.y_quantity ?? null,
    y_units: spectrum?.y_units ?? null,
  };
  if (entry.source === "hitran") {
    settings.resolution_cm1 = libraryResolutionCm1.value;
    settings.wavenumber_min = libraryWavenumberMin.value;
    settings.wavenumber_max = libraryWavenumberMax.value;
    settings.temperature_k = libraryTemperatureK.value;
    settings.pressure_atm = libraryPressureAtm.value;
  } else if (entry.source === "hitran_xsec") {
    const option = entry.xsec_options?.[entry.selected_xsec_option ?? 0] ?? {};
    settings.resolution_cm1 = option.resolution_cm1 ?? null;
    settings.wavenumber_min = option.wavenumber_cm1?.[0] ?? null;
    settings.wavenumber_max = option.wavenumber_cm1?.[1] ?? null;
    settings.temperature_k = option.temperature_k
      ? (option.temperature_k[0] + option.temperature_k[1]) / 2
      : null;
    settings.pressure_atm = option.pressure_torr
      ? ((option.pressure_torr[0] + option.pressure_torr[1]) / 2) / 760
      : null;
  }
  if (spectrum?.wavenumber?.length) {
    settings.wavenumber_min = Math.min(...spectrum.wavenumber);
    settings.wavenumber_max = Math.max(...spectrum.wavenumber);
  }
  return settings;
}

function compactFrozenRange(settings?: LibraryFrozenSettings): string {
  if (settings?.wavenumber_min === null || settings?.wavenumber_min === undefined) return "";
  if (settings.wavenumber_max === null || settings.wavenumber_max === undefined) return "";
  return `${formatNumber(settings.wavenumber_min)}-${formatNumber(settings.wavenumber_max)} cm^-1`;
}

function libraryBasketDetail(entry: LibraryRow): string {
  const settings = entry.frozen_settings;
  const parts: string[] = [];
  parts.push(entry.source_label);
  if (!settings) {
    if (entry.resolution) parts.push(entry.resolution);
    return parts.join(" · ");
  }
  const range = compactFrozenRange(settings);
  if (range) parts.push(range);
  if (settings.resolution_cm1) parts.push(`Δ ${formatNumber(settings.resolution_cm1)} cm^-1`);
  if (entry.source === "hitran") {
    if (settings.temperature_k) parts.push(`${formatNumber(settings.temperature_k)} K`);
    if (settings.pressure_atm) parts.push(`${formatNumber(settings.pressure_atm)} atm`);
  }
  if (entry.source === "hitran_xsec" && settings.xsec_option !== null && settings.xsec_option !== undefined) {
    parts.push(`measurement ${settings.xsec_option + 1}`);
  }
  if (settings.points) parts.push(`${settings.points} pts`);
  if (settings.y_quantity) parts.push(settings.y_quantity);
  return parts.join(" · ");
}

function nistSpectrumToPayload(entry: LibraryRow, spectrum: NistLibrarySpectrumResponse): SpectrumPayload {
  return {
    component_id: spectrum.component_id,
    name: spectrum.name || entry.compound_name,
    source: "nist_quant_ir",
    wavenumber: spectrum.x,
    intensity: spectrum.y,
    y_quantity: spectrum.y_title || null,
    y_units: spectrum.y_units || null,
    resolution_cm1: null,
    apodization: null,
    cached: true,
  };
}

async function pollLibrarySpectrumLoadJob(jobId: number, entry: LibraryRow): Promise<JobInfo> {
  while (true) {
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
    const response = await api.get<JobInfo>(`/jobs/${jobId}`);
    const status = response.data.status;
    librarySpectrumProgress[entry.key] = {
      progress: response.data.progress,
      message: response.data.progress_message || null,
    };
    if (status === "completed") return response.data;
    if (status === "failed" || status === "cancelled") {
      throw new Error(response.data.error_message || response.data.progress_message || "Spectrum load failed");
    }
  }
}

async function fetchLibrarySpectrum(entry: LibraryRow): Promise<SpectrumPayload> {
  if (entry.source === "nist") {
    if (entry.id == null) throw new Error("NIST library row is missing an id");
    const response = await api.get<NistLibrarySpectrumResponse>(`/datasets/library/${entry.id}/spectrum`);
    return nistSpectrumToPayload(entry, response.data);
  }

  const params = librarySpectrumParams(entry);
  const loadResponse = await api.post<{
    queued: boolean;
    job_id?: number | null;
    message?: string | null;
    spectrum?: SpectrumPayload | null;
  }>("/synthesis/spectrum/load", params);
  if (loadResponse.data.spectrum) return loadResponse.data.spectrum;
  if (!loadResponse.data.queued || !loadResponse.data.job_id) {
    throw new Error(loadResponse.data.message || "Spectrum load did not return a spectrum or job id.");
  }
  librarySpectrumProgress[entry.key] = {
    progress: 0,
    message: loadResponse.data.message || "HITRAN spectrum queued",
  };
  await pollLibrarySpectrumLoadJob(loadResponse.data.job_id, entry);
  const cached = await api.get<SpectrumPayload>("/synthesis/spectrum", { params });
  return cached.data;
}

async function loadLibrarySpectrum(entry: LibraryRow): Promise<void> {
  if (librarySpectra[entry.key]) {
    activeLibraryPreviewKey.value = entry.key;
    return;
  }
  if (librarySpectrumLoadingKeys.has(entry.key) || isLibrarySpectrumQueued(entry)) return;
  if (isHitranLibrarySource(entry.source) && activeLibrarySpectrumLoadKey.value && activeLibrarySpectrumLoadKey.value !== entry.key) {
    await queueLibrarySpectrumLoad(entry);
    return;
  }
  await runLibrarySpectrumLoad(entry);
}

async function runLibrarySpectrumLoad(entry: LibraryRow): Promise<void> {
  activeLibrarySpectrumLoadKey.value = entry.key;
  librarySpectrumLoadingKeys.add(entry.key);
  try {
    librarySpectra[entry.key] = await fetchLibrarySpectrum(entry);
    activeLibraryPreviewKey.value = entry.key;
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Spectrum Load Failed",
      detail: getErrorMessage(err, "Could not load the selected library spectrum."),
      life: 7000,
    });
  } finally {
    librarySpectrumLoadingKeys.delete(entry.key);
    delete librarySpectrumProgress[entry.key];
    if (activeLibrarySpectrumLoadKey.value === entry.key) {
      activeLibrarySpectrumLoadKey.value = null;
    }
    if (isHitranLibrarySource(entry.source)) {
      drainLibrarySpectrumLoadQueue();
    }
  }
}

function drainLibrarySpectrumLoadQueue(): void {
  if (activeLibrarySpectrumLoadKey.value || librarySpectrumLoadQueue.value.length === 0) return;
  const next = librarySpectrumLoadQueue.value.shift();
  if (!next) return;
  void runLibrarySpectrumLoad(next.entry).finally(next.resolve);
}

function clearLibraryBasket(): void {
  selectedLibraryKeys.clear();
  for (const key of Object.keys(selectedLibraryRows)) {
    delete selectedLibraryRows[key];
  }
}

function addLibraryToBasket(entry: LibraryRow) {
  if (hitranLibraryImportActive.value) return;
  if (!librarySpectra[entry.key]) return;
  selectedLibraryKeys.add(entry.key);
  selectedLibraryRows[entry.key] = { ...entry, frozen_settings: freezeLibrarySettings(entry) };
  if (!libraryDatasetName.value.trim()) {
    libraryDatasetName.value = defaultLibraryDatasetName();
  }
}

function removeLibrarySelection(key: string) {
  if (hitranLibraryImportActive.value) return;
  selectedLibraryKeys.delete(key);
  delete selectedLibraryRows[key];
}

function onHitranXsecOptionChange(entry: LibraryRow) {
  delete librarySpectra[entry.key];
  delete librarySpectrumProgress[entry.key];
  removeLibrarySelection(entry.key);
  if (activeLibraryPreviewKey.value === entry.key) {
    activeLibraryPreviewKey.value = null;
  }
}

function onLibrarySourceChange() {
  clearLibraryBasket();
  libraryDatasetName.value = "";
  activeLibraryPreviewKey.value = null;
  clearLibrarySpectrumLoadQueue();
  if (librarySource.value === "hitran" && !hitranLibraryRows.value.length) {
    void searchHitranLibrary();
  }
  if (librarySource.value === "hitran_xsec" && !hitranXsecLibraryRows.value.length) {
    void searchHitranLibrary();
  }
}

async function searchHitranLibrary() {
  if (!isHitranLibrarySource(librarySource.value)) return;
  librarySearching.value = true;
  try {
    const response = await api.get("/synthesis/search", {
      params: {
        source: librarySource.value,
        query: librarySearch.value,
        limit: 1000,
      },
    });
    const components = (response.data.components || []) as LibrarySearchComponent[];
    const mappedRows = components.map((component) => {
      const options = Array.isArray(component.xsec_options) ? component.xsec_options : [];
      const firstOption = options[0] || {};
      return {
        key: String(component.id),
        source: librarySource.value,
        component_id: String(component.id),
        compound_name: String(component.name || component.id),
        formula: component.formula || null,
        cas_number: component.cas || "",
        resolution:
          librarySource.value === "hitran_xsec"
            ? (firstOption.resolution_cm1 ? `${formatNumber(firstOption.resolution_cm1)} cm^-1` : "measured")
            : `${libraryResolutionCm1.value} cm^-1`,
        source_label: librarySource.value === "hitran_xsec" ? "HITRAN X-section" : "HITRAN LBL",
        xsec_options: options,
        selected_xsec_option: 0,
      } as LibraryRow;
    });
    if (librarySource.value === "hitran_xsec") {
      hitranXsecLibraryRows.value = mappedRows;
    } else {
      hitranLibraryRows.value = mappedRows;
    }
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "HITRAN Search Failed",
      detail: getErrorMessage(err, "Could not search HITRAN species"),
      life: 5000,
    });
  } finally {
    librarySearching.value = false;
  }
}

function filesForStage(stage: string): ExperimentFile[] {
  return dataStore.experimentFiles.filter((f) => f.stage === stage);
}

// --- Reference dataset selection ---

const allReferenceDatasets = computed<ReferenceDatasetOption[]>(() => {
  const catalog = dataStore.referenceCatalog;
  if (!catalog) return [];
  return [
    ...catalog.synthetic,
    ...catalog.eigenvector,
    ...catalog.oes,
    ...catalog.spectrochempy,
    ...catalog.sklearn,
  ];
});

function dsKey(ds: { source?: string; name: string }): string {
  return `${ds.source || "spectrochempy"}::${ds.name}`;
}

function referenceByKey(key: string): ReferenceDatasetOption | null {
  return allReferenceDatasets.value.find((dataset) => dsKey(dataset) === key) ?? null;
}

const selectedReferenceMembers = computed(() =>
  Array.from(selectedRefDatasets).map((key) => {
    const dataset = referenceByKey(key);
    return {
      key,
      label: dataset?.label ?? key.split("::").slice(1).join("::"),
    };
  })
);

const previewRefDataset = computed(() => previewRefKey.value ? referenceByKey(previewRefKey.value) : null);
const previewRefSource = computed<DataMatrixRef | null>(() => {
  const dataset = previewRefDataset.value;
  if (!dataset) return null;
  return {
    kind: "reference",
    source: dataset.source || "spectrochempy",
    name: dataset.name,
    overrides: refOverrides[dsKey(dataset)] ?? null,
  };
});
const previewRefTitle = computed(() => previewRefDataset.value?.label ?? "Reference preview");
const previewRefFiles = computed<SourcePreviewFile[]>(() => {
  const dataset = previewRefDataset.value;
  if (!dataset) return [];
  if (dataset.files?.length) return sourcePreviewFilesFromNames(dataset.files);
  if (dataset.file_path) return sourcePreviewFilesFromNames([dataset.file_path]);
  return [];
});
const previewRefOverrides = computed(() =>
  previewRefKey.value ? refOverrides[previewRefKey.value] ?? {} : {}
);

function toggleRefDataset(ds: ReferenceDatasetOption) {
  const key = dsKey(ds);
  if (selectedRefDatasets.has(key)) {
    selectedRefDatasets.delete(key);
  } else {
    selectedRefDatasets.add(key);
  }
}

function previewReferenceDataset(ds: ReferenceDatasetOption) {
  previewRefKey.value = dsKey(ds);
}

function removeReferenceSelection(key: string) {
  selectedRefDatasets.delete(key);
  if (previewRefKey.value === key) {
    const nextKey = selectedRefDatasets.values().next().value;
    previewRefKey.value = typeof nextKey === "string" ? nextKey : null;
  }
}

function onPreviewRefOverrides(overrides: PreparedDataOverrides) {
  if (!previewRefKey.value) return;
  refOverrides[previewRefKey.value] = { ...overrides };
}

async function onImportSelectedDatasets() {
  if (selectedRefDatasets.size === 0) return;
  importing.value = true;
  try {
    // Synthesis-style flow: each click creates a new My Dataset with the
    // typed name (or a sensible default if blank), then ingests the
    // selected references into it. The user no longer has to pre-create a
    // dataset via the dialog.
    const name = importDatasetName.value.trim() || defaultImportDatasetName();
    const created = await dataStore.createExperiment(name, undefined, projectStore.currentProjectId);
    await dataStore.selectExperiment(created.id);

    const datasets = Array.from(selectedRefDatasets).map((key) => {
      const [source, ...rest] = key.split("::");
      return { source, name: rest.join("::"), overrides: refOverrides[key] ?? null };
    });
    const result = await dataStore.importReferenceDatasets(created.id, datasets);
    toast.add({
      severity: "success",
      summary: "Import Complete",
      detail: `Imported ${result.imported} file(s) into "${name}"`,
      life: 3000,
    });
    selectedRefDatasets.clear();
    importDatasetName.value = "";
    await refreshProjectContext();
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    await showExperimentContents(created.id);
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

function stopLibraryImportPolling() {
  if (libraryImportPollTimer !== null) {
    window.clearInterval(libraryImportPollTimer);
    libraryImportPollTimer = null;
  }
}

async function pollLibraryImportJob(jobId: number, experimentId: number, datasetName: string) {
  let response;
  try {
    response = await api.get<JobInfo>(`/jobs/${jobId}`);
  } catch (error) {
    const currentJob = activeLibraryImportJob.value;
    activeLibraryImportJob.value = {
      id: jobId,
      job_type: "library_import_hitran",
      progress: currentJob?.progress ?? 0,
      progress_message: currentJob?.progress_message ?? null,
      result_path: null,
      compute_location: "local",
      compute_node: null,
      created_at: currentJob?.created_at ?? new Date().toISOString(),
      started_at: currentJob?.started_at ?? null,
      completed_at: currentJob?.completed_at ?? null,
      last_heartbeat: currentJob?.last_heartbeat ?? null,
      status: "failed",
      error_message: getErrorMessage(error),
    };
    stopLibraryImportPolling();
    importingLibrary.value = false;
    toast.add({
      severity: "error",
      summary: "HITRAN Import Status Failed",
      detail: getErrorMessage(error),
      life: 7000,
    });
    return;
  }
  activeLibraryImportJob.value = response.data;
  const status = response.data.status;
  if (!["completed", "failed", "cancelled"].includes(status)) return;

  stopLibraryImportPolling();
  importingLibrary.value = false;

  if (status === "completed") {
    toast.add({
      severity: "success",
      summary: "HITRAN Import Complete",
      detail: response.data.progress_message || `Imported HITRAN spectra into "${datasetName}"`,
      life: 5000,
    });
    clearLibraryBasket();
    libraryDatasetName.value = "";
    await refreshProjectContext();
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    await showExperimentContents(experimentId);
    window.setTimeout(() => {
      activeLibraryImportJob.value = null;
      activeLibraryImportExperimentId.value = null;
    }, 1500);
  } else {
    toast.add({
      severity: "error",
      summary: status === "cancelled" ? "HITRAN Import Cancelled" : "HITRAN Import Failed",
      detail: response.data.error_message || response.data.progress_message || "Failed to import HITRAN spectra",
      life: 7000,
    });
  }
}

function startLibraryImportPolling(jobId: number, experimentId: number, datasetName: string) {
  stopLibraryImportPolling();
  activeLibraryImportExperimentId.value = experimentId;
  importingLibrary.value = true;
  void pollLibraryImportJob(jobId, experimentId, datasetName);
  libraryImportPollTimer = window.setInterval(() => {
    void pollLibraryImportJob(jobId, experimentId, datasetName);
  }, 2000);
}

async function importLibraryRows(selectedRows: LibraryRow[]) {
  if (selectedRows.length === 0) return;
  if (hitranLibraryImportActive.value) return;
  importingLibrary.value = true;
  try {
    const name = libraryDatasetName.value.trim() || defaultLibraryDatasetName();
    const libraryDraft = dataDraftSnapshot().library;
    const created = await dataStore.createExperiment(name, undefined, projectStore.currentProjectId, {
      builder_state: {
        kind: "library_basket",
        version: 1,
        title: name,
        library: libraryDraft,
      },
    });
    await dataStore.selectExperiment(created.id);

    const hitranRows = selectedRows.filter((entry) => isHitranLibrarySource(entry.source) && entry.component_id);
    const componentSpecs = hitranRows.map((entry) => {
      const frozen = entry.frozen_settings ?? freezeLibrarySettings(entry);
      return {
        component_id:
          entry.source === "hitran_xsec"
            ? frozen.component_id || `${String(entry.component_id)}#${entry.selected_xsec_option ?? 0}`
            : String(entry.component_id),
        resolution_cm1: frozen.resolution_cm1 ?? (entry.source === "hitran" ? libraryResolutionCm1.value : null),
        wavenumber_min: frozen.wavenumber_min ?? (entry.source === "hitran" ? libraryWavenumberMin.value : null),
        wavenumber_max: frozen.wavenumber_max ?? (entry.source === "hitran" ? libraryWavenumberMax.value : null),
        temperature_k: frozen.temperature_k ?? (entry.source === "hitran" ? libraryTemperatureK.value : null),
        pressure_atm: frozen.pressure_atm ?? (entry.source === "hitran" ? libraryPressureAtm.value : null),
      };
    });
    const loadedSpectra = hitranRows
      .map((entry) => librarySpectra[entry.key])
      .filter((spectrum): spectrum is SpectrumPayload => Boolean(spectrum))
      .map((spectrum) => ({
        component_id: spectrum.component_id,
        name: spectrum.name,
        source: spectrum.source,
        wavenumber: spectrum.wavenumber,
        intensity: spectrum.intensity,
        y_quantity: spectrum.y_quantity,
        y_units: spectrum.y_units,
        resolution_cm1: spectrum.resolution_cm1 ?? null,
        apodization: spectrum.apodization ?? null,
      }));
    const result = await dataStore.importLibraryDatasets(created.id, {
      source: librarySource.value,
      library_ids: selectedRows
        .filter((entry) => entry.source === "nist" && entry.id != null)
        .map((entry) => Number(entry.id)),
      component_ids: hitranRows
        .map((entry) =>
          entry.source === "hitran_xsec"
            ? `${String(entry.component_id)}#${entry.selected_xsec_option ?? 0}`
            : String(entry.component_id)
        ),
      component_specs: componentSpecs,
      spectra: loadedSpectra,
      range_mode: libraryRangeMode.value,
      resolution_cm1: librarySource.value === "hitran_xsec" ? null : libraryResolutionCm1.value,
      wavenumber_min: librarySource.value === "hitran_xsec" ? null : libraryWavenumberMin.value,
      wavenumber_max: librarySource.value === "hitran_xsec" ? null : libraryWavenumberMax.value,
      ...(librarySource.value === "hitran"
        ? {
            temperature_k: libraryTemperatureK.value,
            pressure_atm: libraryPressureAtm.value,
          }
        : {}),
    });
    if (result?.queued && result?.job_id) {
      activeLibraryImportJob.value = {
        id: result.job_id,
        job_type: "library_import_hitran",
        status: "pending",
        progress: 0,
        progress_message: result.message || "HITRAN spectra queued",
        result_path: null,
        error_message: null,
        compute_location: "local",
        compute_node: null,
        created_at: new Date().toISOString(),
        started_at: null,
        completed_at: null,
        last_heartbeat: null,
      };
      toast.add({
        severity: "info",
        summary: "HITRAN Import Queued",
        detail: result.message || "HITRAN spectra will import in the background.",
        life: 4000,
      });
      startLibraryImportPolling(result.job_id, created.id, name);
      return;
    }
    toast.add({
      severity: "success",
      summary: "Library Import Complete",
      detail: `Imported ${result.imported} file(s) into "${name}"`,
      life: 3000,
    });
    clearLibraryBasket();
    libraryDatasetName.value = "";
    await refreshProjectContext();
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    await showExperimentContents(created.id);
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Library Import Failed",
      detail: getErrorMessage(err, "Failed to import library spectra"),
      life: 5000,
    });
  } finally {
    if (!hitranLibraryImportActive.value) importingLibrary.value = false;
  }
}

async function onImportSelectedLibraryDatasets() {
  if (selectedLibraryKeys.size === 0) return;
  await importLibraryRows(Object.values(selectedLibraryRows).filter((entry) => selectedLibraryKeys.has(entry.key)));
}

function onAddAllVisibleNistToBasket() {
  if (librarySource.value !== "nist") return;
  for (const entry of dedupeNistRowsByCompound(filteredLibrary.value.filter((entry) => entry.source === "nist"))) {
    selectedLibraryKeys.add(entry.key);
    selectedLibraryRows[entry.key] = { ...entry, frozen_settings: freezeLibrarySettings(entry) };
  }
  if (selectedLibraryKeys.size > 0 && !libraryDatasetName.value.trim()) {
    libraryDatasetName.value = defaultLibraryDatasetName();
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

function queryNumber(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function routeTabIndex(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === "import") return TAB_IMPORT;
  if (normalized === "synthesis") return TAB_SYNTHESIS;
  if (normalized === "upload") return TAB_UPLOAD;
  if (normalized === "library") return TAB_LIBRARY;
  if (normalized === "inspect" || normalized === "explore") return TAB_MY_DATASET;
  if (normalized === "my-dataset" || normalized === "my_dataset" || normalized === "dataset") return TAB_MY_DATASET;
  return null;
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
  if (
    fileId != null &&
    dataStore.activeExperimentId === experimentId &&
    dataStore.activeFileId === fileId &&
    dataStore.fileInfo !== null
  ) {
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    return true;
  }

  await dataStore.selectExperiment(experimentId);
  if (fileId == null) {
    await showExperimentContents(experimentId);
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    return true;
  }

  const file = dataStore.experimentFiles.find((entry) => entry.id === fileId);
  if (!file) {
    return false;
  }

  dataStore.clearCatalogExploration();
  await dataStore.inspectFile(file.id, file.file_path, experimentId);
  activeTab.value = TAB_MY_DATASET;
  persistActiveDataTab();
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
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    return true;
  }

  return false;
}

async function applyRouteExploreState() {
  syncGuidedExampleSession();
  const wantsExplore =
    route.query.tab === "inspect" ||
    route.query.tab === "explore" ||
    route.query.tab === "my-dataset" ||
    route.query.tab === "my_dataset" ||
    route.query.tab === "dataset" ||
    route.query.experimentId != null ||
    route.query.experiment != null ||
    route.query.fileId != null ||
    route.query.fromTemplate === "1" ||
    isGuidedExampleSession.value;
  if (!wantsExplore) {
    return;
  }

  const experimentId = queryNumber(route.query.experimentId ?? route.query.experiment);
  const fileId = queryNumber(route.query.fileId);

  try {
    if (experimentId != null && fileId != null) {
      const inspected = await inspectExperimentFile(experimentId, fileId);
      if (inspected) {
        return;
      }
    }

    if (experimentId != null) {
      await dataStore.selectExperiment(experimentId);
      await showExperimentContents(experimentId);
      activeTab.value = TAB_MY_DATASET;
      persistActiveDataTab();
      return;
    }

    if (route.query.focus === "latest-project" || isGuidedExampleSession.value) {
      const inspected = await inspectLatestProjectFile();
      if (inspected) {
        return;
      }
    }
  } catch {
    // Errors are surfaced by the Contents panel.
  }

  activeTab.value = TAB_MY_DATASET;
}

async function applyRouteDataState() {
  const requestedTab = routeTabIndex(route.query.tab);
  if (requestedTab !== null) {
    activeTab.value = requestedTab;
    persistActiveDataTab();
    if (requestedTab === TAB_MY_DATASET) {
      await applyRouteExploreState();
    }
    return;
  }

  await applyRouteExploreState();
}

function goToWorkflow() {
  router.push("/workflow");
}

// --- Lifecycle ---

onMounted(async () => {
  await projectStore.ensureProjectForBrowserTab();
  currentDataDraftStorageKey = dataDraftStorageKey();
  restoreActiveDataTab();
  restoreDataDraft(currentDataDraftStorageKey);
  await Promise.all([
    fetchQuota(),
    dataStore.fetchCatalog(),
    dataStore.fetchExperiments(),
    dataStore.fetchReferenceCatalog(),
  ]);
  await dataStore.restoreActiveExperimentForCurrentProject();
  syncGuidedExampleSession();
  await applyRouteDataState();

  // Restore My Dataset when the Pinia store still has an active contents
  // exploration (i.e. the user left the Data page after inspecting a
  // reference or file). Route-driven state takes precedence.
  if (
    [TAB_IMPORT, TAB_SYNTHESIS].includes(activeTab.value) &&
    (dataStore.catalogDatasetInfo !== null || dataStore.fileInfo !== null)
  ) {
    activeTab.value = TAB_MY_DATASET;
  }

  await ensureInitialContentsSelection();
  if (isHitranLibrarySource(librarySource.value)) {
    void searchHitranLibrary();
  }
});

watch(
  () => dataDraftSnapshot(),
  () => {
    scheduleDataDraftPersist();
  },
  { deep: true },
);

watch(
  () => dataStore.activeExperimentId,
  (experimentId) => {
    void refreshActiveExperimentMetadata(experimentId);
  },
  { immediate: true },
);

watch(activeTab, (tabIndex) => {
  if (isGuidedExampleSession.value && tabIndex !== TAB_MY_DATASET) {
    activeTab.value = TAB_MY_DATASET;
  }
});

watch(
  () => [
    libraryResolutionCm1.value,
    libraryWavenumberMin.value,
    libraryWavenumberMax.value,
    libraryTemperatureK.value,
    libraryPressureAtm.value,
  ],
  () => {
    if (librarySource.value === "hitran") {
      clearHitranLibrarySpectra();
    }
  }
);

watch(
  () => [
    route.query.tab,
    route.query.experimentId,
    route.query.experiment,
    route.query.fileId,
    route.query.focus,
    route.query.fromTemplate,
  ],
  () => {
    void applyRouteDataState();
  }
);

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

async function refreshProjectContext() {
  await projectStore.fetchProjects();
  if (projectStore.currentProjectId != null) {
    await projectStore.fetchProject(projectStore.currentProjectId);
  }
}

async function onSynthesisSaved() {
  await refresh();
  await refreshProjectContext();
}

async function refreshActiveExperimentMetadata(experimentId: number | null): Promise<void> {
  activeExperimentMetadata.value = null;
  if (experimentId == null) return;
  try {
    const response = await api.get(`/experiments/${experimentId}`);
    activeExperimentMetadata.value = objectOrNull(response.data?.metadata) ?? {};
  } catch {
    activeExperimentMetadata.value = null;
  }
}

async function reopenInspectedSynthesisRecipe(): Promise<void> {
  const recipe = inspectedSynthesisRecipe.value;
  if (!recipe) return;
  activeTab.value = TAB_SYNTHESIS;
  persistActiveDataTab();
  await nextTick();
  await synthesisPanelRef.value?.reopenRecipe(recipe, inspectedSynthesisTitle.value);
}

async function reopenSelectedLibraryBasket(): Promise<void> {
  const draft = savedLibraryDraft.value;
  if (!draft) return;
  applyLibraryDraft(draft);
  activeTab.value = TAB_LIBRARY;
  persistActiveDataTab();
  await nextTick();
  if (isHitranLibrarySource(librarySource.value)) {
    await searchHitranLibrary();
  }
  toast.add({
    severity: "success",
    summary: "Library basket reopened",
    detail: `${selectedLibraryKeys.size} reference ${selectedLibraryKeys.size === 1 ? "entry" : "entries"} restored.`,
    life: 4000,
  });
}

async function showExperimentContents(experimentId: number) {
  dataStore.clearCatalogExploration();
  try {
    await dataStore.inspectExperimentRawFiles(experimentId);
  } catch {
    // Error is stored in dataStore.fileInfoError and rendered by Contents.
  }
}

async function ensureInitialContentsSelection() {
  if (dataStore.fileInfo || dataStore.catalogDatasetInfo || !dataStore.activeExperimentId) {
    return;
  }
  const hasSingleDataset = dataStore.experiments.length === 1;
  const hasSingleFile = dataStore.experimentFiles.length === 1;
  if (hasSingleDataset && hasSingleFile) {
    await onInspectFile(dataStore.experimentFiles[0], { updateRoute: false });
    return;
  }
  if (activeTab.value === TAB_MY_DATASET) {
    await showExperimentContents(dataStore.activeExperimentId);
  }
}

// --- Experiment CRUD ---

async function onExperimentSelect(exp: ExperimentSummary | null) {
  if (!exp) return;
  await dataStore.selectExperiment(exp.id);
  activeTab.value = TAB_MY_DATASET;
  persistActiveDataTab();
  await showExperimentContents(exp.id);
  const queryWithoutFile = { ...route.query };
  delete queryWithoutFile.fileId;
  await router.replace({
    path: "/data",
    query: {
      ...queryWithoutFile,
      tab: "my-dataset",
      experiment: String(exp.id),
    },
  });
}

function openEditDatasetDialog(experiment: ExperimentSummary) {
  editExperimentTarget.value = experiment;
  editExpName.value = experiment.name;
  editExpDescription.value = experiment.description ?? "";
  editSubmitted.value = false;
  showEditDatasetDialog.value = true;
}

async function onEditExperiment() {
  editSubmitted.value = true;
  const target = editExperimentTarget.value;
  const name = editExpName.value.trim();
  if (!target || !name) return;

  editingExp.value = true;
  try {
    await dataStore.updateExperiment(target.id, {
      name,
      description: editExpDescription.value.trim() || null,
    });
    showEditDatasetDialog.value = false;
    editExperimentTarget.value = null;
    editExpName.value = "";
    editExpDescription.value = "";
    editSubmitted.value = false;
    await refreshProjectContext();
    toast.add({
      severity: "success",
      summary: "Dataset Updated",
      detail: name,
      life: 2500,
    });
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Update Failed",
      detail: getErrorMessage(err, "Failed to update dataset"),
      life: 5000,
    });
  } finally {
    editingExp.value = false;
  }
}

// --- File operations ---

async function onFileSelect(event: { files?: File[] }) {
  if (dataUploadDisabled.value) {
    clearUploadFileSelection();
    return;
  }
  const file = event.files?.[0] ?? null;
  selectedFile.value = file;
  if (!file) return;
  try {
    const staged = await dataStore.stageUploadFile(file);
    stagedUploadMembers.value.push(staged);
    previewUploadId.value = staged.staging_id;
    uploadOverrides[staged.staging_id] = uploadControlOverrides(staged);
  } catch (err: unknown) {
    clearUploadFileSelection();
    toast.add({
      severity: "error",
      summary: "Stage Failed",
      detail: getErrorMessage(err, "Failed to stage file for preview"),
      life: 5000,
    });
  }
}

async function onUploadFile() {
  if (dataUploadDisabled.value) {
    toast.add({
      severity: "warn",
      summary: "Upload Disabled",
      detail: uploadDisabledMessage.value || "File upload is disabled.",
      life: 4000,
    });
    return;
  }
  if (!stagedUploadMembers.value.length) return;
  uploading.value = true;
  try {
    // Synthesis-style flow: each click creates a new My Dataset with the
    // typed name (or the file name as default), then uploads the file into
    // it. The user no longer has to pre-create a dataset via the dialog.
    const name = uploadDatasetName.value.trim() || defaultUploadDatasetName();
    const created = await dataStore.createExperiment(name, undefined, projectStore.currentProjectId);
    await dataStore.selectExperiment(created.id);
    await dataStore.commitStagedUploads(
      created.id,
      uploadStage.value,
      stagedUploadMembers.value.map((member) => ({
        staging_id: member.staging_id,
        overrides: uploadOverrides[member.staging_id] ?? null,
      })),
    );
    await fetchQuota();
    toast.add({
      severity: "success",
      summary: "Upload Complete",
      detail: `Added ${stagedUploadMembers.value.length} file(s) into "${name}"`,
      life: 3000,
    });
    // Clear form so the next upload starts fresh.
    clearUploadFileSelection();
    stagedUploadMembers.value = [];
    previewUploadId.value = null;
    uploadStage.value = "raw";
    uploadDataRole.value = "auto";
    uploadTargetColumn.value = "";
    uploadTargetType.value = "auto";
    uploadDatasetName.value = "";
    // Refresh experiment list and project counts after auto-saving the upload.
    await Promise.all([dataStore.fetchExperiments(), refreshProjectContext()]);
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    await showExperimentContents(created.id);
  } catch (err) {
    console.error("Upload failed:", err);
    toast.add({
      severity: "error",
      summary: "Upload Failed",
      detail: getErrorMessage(err, "Failed to upload file"),
      life: 5000,
    });
  } finally {
    uploading.value = false;
  }
}

function previewUploadMember(stagingId: string) {
  previewUploadId.value = stagingId;
}

async function removeStagedUpload(stagingId: string) {
  try {
    await dataStore.deleteStagedUpload(stagingId);
  } catch {
    // Best-effort cleanup. Removing from the client list is enough to keep
    // accidental commits out of the user's dataset.
  }
  stagedUploadMembers.value = stagedUploadMembers.value.filter((member) => member.staging_id !== stagingId);
  delete uploadOverrides[stagingId];
  if (previewUploadId.value === stagingId) {
    previewUploadId.value = stagedUploadMembers.value[0]?.staging_id ?? null;
  }
}

function onPreviewUploadOverrides(overrides: PreparedDataOverrides) {
  const member = selectedUploadMember.value;
  if (!member) return;
  uploadOverrides[member.staging_id] = { ...overrides };
  syncUploadControlsFromOverrides(overrides);
}

function confirmDeleteFile(file: ExperimentFile) {
  deleteTarget.value = file;
  showDeleteDialog.value = true;
}

function confirmDeleteExperiment(experiment: ExperimentSummary) {
  deleteExperimentTarget.value = experiment;
  showDeleteExpDialog.value = true;
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
    // Refresh experiment list and project counts after auto-saving the deletion.
    await Promise.all([dataStore.fetchExperiments(), refreshProjectContext()]);
  } catch (err) {
    console.error("Delete failed:", err);
  } finally {
    deleting.value = false;
  }
}

async function onDeleteExperiment() {
  const experimentId = deleteExperimentTarget.value?.id ?? dataStore.activeExperimentId;
  if (!experimentId) return;
  deletingExp.value = true;
  try {
    await dataStore.deleteExperiment(experimentId);
    showDeleteExpDialog.value = false;
    deleteExperimentTarget.value = null;
    await refreshProjectContext();
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Delete Failed",
      detail: getErrorMessage(err, "Failed to delete dataset"),
      life: 5000,
    });
  } finally {
    deletingExp.value = false;
  }
}

async function onInspectFile(file: ExperimentFile, options: { updateRoute?: boolean } = {}) {
  const updateRoute = options.updateRoute ?? true;
  const experimentId = dataStore.activeExperimentId;
  if (!experimentId) return;
  activeTab.value = TAB_MY_DATASET;
  persistActiveDataTab();
  await nextTick();
  dataStore.clearCatalogExploration();
  try {
    await dataStore.inspectFile(file.id, file.file_path, experimentId);
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    if (updateRoute) {
      await router.replace({
        path: "/data",
        query: {
          ...route.query,
          tab: "my-dataset",
          experiment: String(experimentId),
          fileId: String(file.id),
        },
      });
    }
  } catch {
    // Error is stored in dataStore.fileInfoError
  }
}

// --- Helpers ---

function sourcePreviewFilesFromNames(names: Array<string | null | undefined>): SourcePreviewFile[] {
  const seen = new Set<string>();
  const files: SourcePreviewFile[] = [];
  for (const raw of names) {
    if (!raw) continue;
    const name = extractFileName(raw.trim());
    if (!name || seen.has(name)) continue;
    seen.add(name);
    files.push({ name });
  }
  return files;
}

function extractFileName(filePath: string): string {
  return filePath.split(/[\\/]/).pop() || filePath;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDatasetFileShape(file: ExperimentFile): string {
  if (typeof file.n_samples !== "number" || typeof file.n_features !== "number") {
    return "";
  }
  const sampleLabel = file.is_spectra ? "spectra" : "samples";
  const featureLabel = file.is_spectra ? "points" : "features";
  return `${file.n_samples.toLocaleString()} ${sampleLabel} × ${file.n_features.toLocaleString()} ${featureLabel}`;
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
/*
  Page-level chrome restyled to the canonical Project / Dashboard / Models
  Zen vocabulary — hairline dividers, 0.9375rem base, 1.75rem h1 at weight
  500, 1080px max-width, no boxed panels at the page level. The inner tab
  content styles (file groups, ref-catalog cards, plots) are left as-is
  intentionally — that's the "trim, don't restructure" instruction.
*/

.data-content {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 0 1rem;
  color: var(--text-color);
  font-size: 0.9375rem;
  line-height: 1.5;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

/* Context strip: 2-cell — Project on the left (always), active-subtab
   summary on the right (dynamic per current TabView). The right cell
   is a div, not a button — switching subtabs happens via the TabView,
   so the cell is informational, not actionable. */
.data-context-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--surface-border);
}

.data-context-item {
  appearance: none;
  background: transparent;
  border: none;
  border-right: 1px solid var(--surface-border);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  min-width: 0;
  padding: 0.25rem 1rem 0.25rem 0;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: color 0.15s ease;
}

.data-context-item:last-child {
  border-right: none;
  padding-left: 1rem;
  padding-right: 0;
}

.data-context-item.active-context {
  cursor: default;
}

.data-context-item:not(.active-context):hover strong {
  color: var(--primary-color);
}

.data-context-item:focus-visible {
  outline: 1px solid var(--primary-color);
  outline-offset: 2px;
}

.data-context-item strong {
  color: var(--text-color);
  font-size: 1rem;
  font-weight: 500;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  transition: color 0.15s ease;
}

.data-context-item small {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.context-label {
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

/* Zen subtab styling — strip PrimeVue TabView's boxed chrome and render
   the tabs as a flat hairline-underline strip. Active tab gets a primary
   underline; non-active tabs are secondary text; hover lifts to primary
   with a half-strength underline. */
.data-content :deep(.p-tabview) {
  background: transparent;
}

.data-content :deep(.p-tabview-nav-container),
.data-content :deep(.p-tabview-nav-content) {
  background: transparent;
}

.data-content :deep(.p-tabview-nav) {
  display: flex;
  align-items: center;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--surface-border);
  padding: 0;
  margin: 0;
  list-style: none;
}

.data-content :deep(.p-tabview-nav li) {
  margin: 0;
  background: transparent;
}

.data-content :deep(.p-tabview-nav .p-tabview-nav-link) {
  background: transparent !important;
  border: none !important;
  border-radius: 0;
  border-bottom: 2px solid transparent !important;
  color: var(--text-color-secondary);
  font-size: 0.9375rem;
  font-weight: 500;
  padding: 0.6rem 1rem;
  transition: color 0.15s ease, border-color 0.15s ease;
  box-shadow: none !important;
}

.data-content :deep(.p-tabview-nav li:not(.p-disabled):not(.p-highlight) .p-tabview-nav-link:hover) {
  color: var(--primary-color);
  border-bottom-color: color-mix(in srgb, var(--primary-color) 40%, transparent) !important;
}

.data-content :deep(.p-tabview-nav li.p-highlight .p-tabview-nav-link) {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color) !important;
}

/* Two-group tab layout:
     left group  (sources)  = Import · Synthesis · Upload · Library
     right group (store)    = My Dataset
   `My Dataset` (the 5th nav child) gets margin-left:auto, producing the
   visible grouping. A leading hairline marks the split. */
.data-content :deep(.p-tabview-nav > li:nth-child(5)) {
  margin-left: auto;
  border-left: 1px solid var(--surface-border);
}

.data-content :deep(.p-tabview-nav > li:nth-child(5)) .p-tabview-nav-link {
  padding-left: 1.25rem;
}

.data-content :deep(.p-tabview-panels) {
  background: transparent;
  padding: 1.5rem 0 0;
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
  align-items: start;
  margin-bottom: 1rem;
}

.experiment-list-panel,
.files-panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  padding: 0.75rem;
}

.panel-heading {
  align-items: flex-start;
  border-bottom: 1px solid var(--surface-border);
  display: flex;
  justify-content: space-between;
  margin: -0.15rem 0 0.65rem;
  padding-bottom: 0.6rem;
}

.panel-heading div {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.panel-heading strong {
  color: var(--text-color);
  font-size: 0.9rem;
  font-weight: 650;
}

.panel-heading span {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.files-panel {
  max-height: 260px;
  overflow-y: auto;
}

.exp-table :deep(.p-datatable-tbody > tr.p-highlight) {
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
  color: var(--primary-color);
  box-shadow: none;
}

.exp-table :deep(.p-datatable-tbody > tr.p-highlight > td) {
  border-color: color-mix(in srgb, var(--primary-color) 28%, var(--surface-border));
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

/* Zen file row: no fill; hairline-bottom separator; hover lifts to
   primary text + border (no background tint). */
.file-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.45rem 0.5rem;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--surface-border);
  border-radius: 6px;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}

.file-row:last-child {
  border-bottom: none;
}

.file-row:hover {
  background: var(--surface-hover);
  color: var(--primary-color);
  border-bottom-color: color-mix(in srgb, var(--primary-color) 40%, var(--surface-border));
}

.file-row.selected {
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
  color: var(--primary-color);
  box-shadow: none;
}

.dataset-name-button {
  appearance: none;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: 500;
  padding: 0;
  text-align: left;
  cursor: pointer;
}

.dataset-name-button:hover,
.dataset-name-button:focus-visible {
  color: var(--primary-color);
  outline: none;
}

.dataset-row-actions {
  display: flex;
  gap: 0.15rem;
  justify-content: flex-end;
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

/* Library panel — flat. The library is just a list rendered inline,
   no enclosing card. */
.library-panel {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
}

.library-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.library-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 4px;
  color: #1e293b;
  font-size: 1rem;
  font-weight: 600;
}

.library-title i {
  color: #64748b;
}

.library-header p {
  margin: 0;
  color: #64748b;
  font-size: 0.9rem;
  line-height: 1.45;
}

/* Outline pill — same vocabulary as the Active tag on Project. */
.library-count {
  flex: 0 0 auto;
  border: 1px solid var(--surface-border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: lowercase;
  padding: 0.05rem 0.45rem;
}

.library-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 10px;
  margin-bottom: 12px;
}

.compact-field {
  min-width: 150px;
  margin: 0;
}

.compact-field label {
  display: block;
  margin-bottom: 4px;
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 600;
}

.hitran-settings-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  width: 100%;
}

.builder-reopen-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0 0 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
}

/* ---- Contents panel ---- */
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
  color: #64748b;
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
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  width: 100%;
  box-sizing: border-box;
}

.plot-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 8px;
}

/* AI-generated commentary — left-edge accent stripe in primary,
   no enclosing fill. */
.peak-analysis-panel {
  margin-top: 0.75rem;
  padding: 0.25rem 0 0.25rem 1rem;
  background: transparent;
  border: none;
  border-left: 3px solid var(--primary-color);
  border-radius: 0;
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
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
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
/* AI-generated commentary — left-edge accent stripe, no enclosing fill. */
.data-story-panel {
  margin-top: 1rem;
  padding: 0.25rem 0 0.25rem 1rem;
  background: transparent;
  border: none;
  border-left: 3px solid var(--primary-color);
  border-radius: 0;
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
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: lowercase;
  color: #8b5cf6;
  background: transparent;
  border: 1px solid color-mix(in srgb, #8b5cf6 35%, transparent);
  padding: 0.05rem 0.45rem;
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
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  margin-bottom: 1.5rem;
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
  color: #64748b;
}

.source-side-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1.25rem;
  align-items: start;
}

.source-list-pane,
.source-preview-pane {
  min-width: 0;
}

/* Errors get a left-edge red stripe instead of a filled card. */
.ref-catalog-error {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.25rem 0 0.25rem 1rem;
  background: transparent;
  border: none;
  border-left: 3px solid var(--red-500);
  border-radius: 0;
  color: var(--red-500);
  font-size: 0.9375rem;
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
  background: transparent;
  border: none;
  border-radius: 0;
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
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 0.6rem;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--surface-border);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.ref-dataset-item:last-child {
  border-bottom: none;
}

.ref-dataset-item:hover {
  background: color-mix(in srgb, var(--primary-color) 5%, transparent);
  color: var(--primary-color);
  border-bottom-color: color-mix(in srgb, var(--primary-color) 40%, var(--surface-border));
}

.ref-dataset-item.selected {
  background: color-mix(in srgb, var(--primary-color) 14%, var(--surface-ground));
  color: var(--primary-color);
  border-bottom-color: color-mix(in srgb, var(--primary-color) 50%, var(--surface-border));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary-color) 30%, transparent);
}

.ref-dataset-item.previewed,
.selected-member-row.previewed {
  background: color-mix(in srgb, var(--primary-color) 8%, var(--surface-ground));
  color: var(--primary-color);
}

.ref-dataset-item.selected::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0.35rem;
  bottom: 0.35rem;
  width: 3px;
  background: var(--primary-color);
  border-radius: 0 3px 3px 0;
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

/* Sticky-feel action bar — hairline above instead of a tinted card. */
.ref-action-bar {
  display: grid;
  grid-template-columns: auto minmax(12rem, 1fr) auto;
  align-items: end;
  gap: 0.75rem;
  margin-top: 1rem;
  padding: 0.75rem 0;
  background: transparent;
  border: none;
  border-top: 1px solid var(--surface-border);
  border-radius: 0;
}

.ref-action-bar .selected-member-rows {
  grid-column: 1 / -1;
  grid-row: 2;
}

.library-import-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 14rem;
  color: var(--text-color-secondary);
  font-size: 0.82rem;
}

.library-spectrum-action {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  align-items: flex-start;
}

.library-spectrum-tag {
  align-self: flex-start;
}

.library-spectrum-progress {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 140px;
  color: var(--text-color-secondary);
}

.library-spectrum-progress small {
  font-size: 0.75rem;
}

.library-preview-panel {
  margin-top: 1rem;
  border-top: 1px solid var(--surface-border);
  padding-top: 0.875rem;
}

.library-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.5rem;
}

.library-preview-header div {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.library-preview-header span {
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

.ref-selection-count {
  font-size: 0.9375rem;
  font-weight: 500;
  color: var(--primary-color);
}

.ref-action-name {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 1;
  min-width: 12rem;
}

.ref-action-name label {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}

.selected-member-rows {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.selected-member-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  min-width: 0;
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--surface-border);
  cursor: pointer;
}

.selected-member-row > span:not(.p-tag) {
  flex: 1 1 12rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
}

.selected-member-detail {
  flex: 1 1 100%;
  min-width: 0;
  color: var(--text-color-secondary);
  font-size: 0.74rem;
  line-height: 1.25;
}

.selected-member-status {
  margin-left: auto;
  flex: 0 0 auto;
}

/* ---- My Dataset section ---- */
.my-dataset-section {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  margin-bottom: 1rem;
}

/* ---- Upload subtab panel ---- */
.upload-panel {
  gap: 1rem;
  max-width: none;
}

.upload-disabled-notice {
  border: 1px solid #fbbf24;
  background: #fffbeb;
  color: #92400e;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 0.9rem;
}

.upload-hint {
  margin: 0;
  padding: 0.25rem 0 0.25rem 1rem;
  border-left: 3px solid var(--surface-border);
  color: var(--text-color-secondary);
  font-size: 0.9375rem;
}

.source-dataset-cta {
  align-items: center;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  display: flex;
  gap: 1rem;
  justify-content: space-between;
  margin-bottom: 1rem;
  padding: 0.875rem 1rem;
}

.source-dataset-cta div {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.source-dataset-cta strong {
  color: var(--text-color);
  font-size: 0.9375rem;
  font-weight: 600;
}

.source-dataset-cta span {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.upload-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.upload-stage {
  width: 100%;
  max-width: 240px;
}

.upload-shape-grid {
  display: grid;
  gap: 0.85rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.upload-shape-control {
  width: 100%;
}

.upload-action {
  display: flex;
  align-items: flex-end;
  gap: 0.75rem;
  margin-top: 0.25rem;
}

.upload-members {
  margin-top: -0.25rem;
}

.upload-format-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.upload-format-chip {
  border: 1px solid var(--surface-border);
  border-radius: 999px;
  font-size: 0.75rem;
  line-height: 1;
  padding: 0.3rem 0.5rem;
}

.upload-format-chip.disabled {
  color: #94a3b8;
  background: #f8fafc;
}

.upload-name {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 1;
  min-width: 12rem;
}

.upload-name label {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}

.my-dataset-summary {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  margin: 0 0 1rem;
}

@media (max-width: 800px) {
  .source-side-layout,
  .ref-action-bar {
    grid-template-columns: 1fr;
  }

  .upload-shape-grid {
    grid-template-columns: 1fr;
  }
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
  .data-context-strip {
    grid-template-columns: 1fr 1fr;
  }

  .data-context-item:nth-child(2) {
    border-right: 0;
  }

  .data-context-item:nth-child(-n + 2) {
    border-bottom: 1px solid #e2e8f0;
  }

  .load-panels {
    grid-template-columns: 1fr;
  }

  .explore-panels {
    grid-template-columns: 1fr;
  }

}
</style>
