<template>
  <section class="data-content">
    <WorkspaceHeader title="Data" :actions="headerActionItems">
      <Button v-if="!workflowSelectionContextRequested" label="Workflow" icon="pi pi-arrow-right"
        iconPos="right" class="p-button-sm" :loading="workflowHandoffBusy"
        :disabled="workflowHandoffBusy" :title="workflowHandoffTitle" @click="goToWorkflow()" />
    </WorkspaceHeader>
    <WorkspaceContext label="Data workspace context">
      <WorkspaceContextItem :label="activeSubtabLabel" :value="activeSubtabValue" aria-live="polite">
        {{ activeSubtabDetail }}
      </WorkspaceContextItem>
    </WorkspaceContext>

    <section
      v-if="workflowSelectionContextRequested"
      class="workflow-selection-context"
      aria-label="Workflow sheet data selection"
    >
      <div class="workflow-selection-heading">
        <div>
          <span class="context-label">Editing workflow sheet</span>
          <strong>{{ workflowSelectionContext?.workflow_name || "Loading sheet context…" }}</strong>
          <small>
            {{ workflowSelectionContext?.source_node_label || workflowSourceNodeId }}
            <template v-if="workflowSelectionContext?.current_revision">
              · revision {{ workflowSelectionContext.current_revision.revision_number }} by
              {{ workflowSelectionContext.current_revision.created_by_name }}
            </template>
          </small>
        </div>
        <Tag
          :value="workflowSelectionContext?.saved_selection ? 'Sheet-specific' : 'Pending first binding'"
          :severity="workflowSelectionContext?.saved_selection ? 'info' : 'warn'"
        />
      </div>
      <p>
        <template v-if="workflowSelectionContext && !workflowSelectionContext.saved_selection">
          Choose this source node's dataset, views, target, and groups.
        </template>
        <template v-else>
          File filters, target, and groups apply to this source node only.
        </template>
      </p>
      <details><summary>Details</summary>
        Applying creates an immutable revision that follows the workflow run into its report.
      </details>
      <div v-if="workflowSelectionContextError" class="workflow-selection-error" role="alert">
        {{ workflowSelectionContextError }}
      </div>
      <div class="workflow-selection-actions">
        <InputText
          v-model="workflowSelectionReason"
          placeholder="Reason for this selection change (optional)"
          aria-label="Reason for data selection change"
        />
        <Button
          label="Cancel"
          icon="pi pi-arrow-left"
          class="p-button-text"
          @click="returnToWorkflow"
        />
        <Button
          label="Apply to this sheet"
          icon="pi pi-check"
          :loading="workflowSelectionApplying || workflowSelectionContextLoading"
          :disabled="workflowSelectionContextLoading || !workflowSelectionContext"
          @click="applyWorkflowDataSelection"
        />
      </div>
    </section>

    <WorkspaceState v-if="dataStore.catalogError" kind="error" :message="dataStore.catalogError">
      <Button label="Retry catalog" class="p-button-sm" :loading="dataStore.catalogLoading" @click="dataStore.fetchCatalog()" />
    </WorkspaceState>
    <WorkspaceState v-if="dataStore.experimentsError" kind="error" :message="dataStore.experimentsError">
      <Button label="Retry datasets" class="p-button-sm" :loading="dataStore.experimentsLoading" @click="retryExperiments" />
    </WorkspaceState>

    <WorkspaceTabs v-model="activeTabId" :tab-ids="DATA_TAB_IDS">
      <!-- ======================== IMPORT TAB ======================== -->
      <TabPanel header="Import">
        <p v-if="qualified" role="status">
          Import a local catalog reference or select an exact registered file you have acquired.
          Automatic provider downloads are unavailable.
        </p>
        <div class="source-side-layout">
          <!-- ============ REFERENCE DATASETS (top, prominent) ============ -->
          <div class="ref-catalog-section source-list-pane">
            <h3 class="ref-catalog-title">
              <i class="pi pi-database"></i>
              Reference Datasets
            </h3>

            <WorkspaceState v-if="dataStore.referenceCatalogLoading" kind="loading" message="Loading catalog…" />

            <WorkspaceState v-else-if="dataStore.referenceCatalogError" kind="error" :message="dataStore.referenceCatalogError">
              <Button
                label="Retry"
                icon="pi pi-refresh"
                class="p-button-sm p-button-outlined"
                :loading="dataStore.referenceCatalogLoading"
                @click="dataStore.fetchReferenceCatalog()"
              />
            </WorkspaceState>

            <div v-else-if="dataStore.referenceCatalog" class="ref-catalog-groups">
              <Panel
                v-if="dataStore.referenceCatalog.builtin.length"
                :toggleable="true"
                :collapsed="builtinCollapsed"
                @update:collapsed="builtinCollapsed = $event"
                class="ref-group-panel"
              >
                <template #header>
                  <span class="ref-panel-header">
                    <i class="pi pi-box"></i>
                    Built-in reference data
                    <Tag
                      :value="String(dataStore.referenceCatalog.builtin.length)"
                      severity="info"
                      rounded
                    />
                  </span>
                </template>
                <div
                  v-for="ds in dataStore.referenceCatalog.builtin"
                  :key="ds.name"
                  class="ref-dataset-item"
                  :class="{
                    selected: selectedRefDatasets.has(dsKey(ds)),
                    previewed: previewRefKey === dsKey(ds),
                  }"
                  @click="previewReferenceDataset(ds)"
                >
                  <Checkbox
                    :modelValue="selectedRefDatasets.has(dsKey(ds))"
                    :binary="true"
                    @click.stop
                    @update:model-value="toggleRefDataset(ds)"
                  />
                  <span class="ref-ds-label">{{ ds.label }}</span>
                </div>
              </Panel>

              <!-- Spectra Scientific synthetic benchmarks -->
              <Panel
                v-if="dataStore.referenceCatalog.synthetic.length"
                :toggleable="true"
                :collapsed="syntheticCollapsed"
                @update:collapsed="syntheticCollapsed = $event"
                class="ref-group-panel"
              >
                <template #header>
                  <span class="ref-panel-header">
                    <i class="pi pi-sparkles"></i>
                    Spectra Scientific Synthetic Benchmarks
                    <Tag
                      :value="String(dataStore.referenceCatalog.synthetic.length)"
                      severity="info"
                      rounded
                    />
                  </span>
                </template>
                <div
                  v-for="ds in dataStore.referenceCatalog.synthetic"
                  :key="ds.name"
                  class="ref-dataset-item"
                  :class="{
                    selected: selectedRefDatasets.has(dsKey(ds)),
                    previewed: previewRefKey === dsKey(ds),
                  }"
                  @click="previewReferenceDataset(ds)"
                >
                  <Checkbox
                    :modelValue="selectedRefDatasets.has(dsKey(ds))"
                    :binary="true"
                    @click.stop
                    @update:model-value="toggleRefDataset(ds)"
                  />
                  <span class="ref-ds-label">{{ ds.label }}</span>
                </div>
              </Panel>

              <!-- sklearn -->
              <Panel
                v-if="dataStore.referenceCatalog.sklearn.length"
                :toggleable="true"
                :collapsed="sklearnCollapsed"
                @update:collapsed="sklearnCollapsed = $event"
                class="ref-group-panel"
              >
                <template #header>
                  <span class="ref-panel-header">
                    <i class="pi pi-cog"></i>
                    scikit-learn datasets
                    <Tag
                      :value="String(dataStore.referenceCatalog.sklearn.length)"
                      severity="info"
                      rounded
                    />
                  </span>
                </template>
                <div
                  v-for="ds in dataStore.referenceCatalog.sklearn"
                  :key="ds.name"
                  class="ref-dataset-item"
                  :class="{
                    selected: selectedRefDatasets.has(dsKey(ds)),
                    previewed: previewRefKey === dsKey(ds),
                  }"
                  @click="previewReferenceDataset(ds)"
                >
                  <Checkbox
                    :modelValue="selectedRefDatasets.has(dsKey(ds))"
                    :binary="true"
                    @click.stop
                    @update:model-value="toggleRefDataset(ds)"
                  />
                  <span class="ref-ds-label">{{ ds.label }}</span>
                </div>
              </Panel>

              <Panel
                v-if="visibleRegisteredReferences.length"
                :toggleable="true"
                :collapsed="registeredCollapsed"
                @update:collapsed="registeredCollapsed = $event"
                class="ref-group-panel"
              >
                <template #header>
                  <span class="ref-panel-header">
                    <i class="pi pi-verified"></i>
                    User-acquired Eigenvector datasets
                    <Tag
                      :value="String(userAcquiredReferenceDatasets.length)"
                      severity="info"
                      rounded
                    />
                  </span>
                </template>
                <p class="reference-acquisition-help" role="status">
                  These datasets are not bundled or downloaded automatically by this catalog. Get
                  the original ZIP file from the provider page, then choose “Import downloaded
                  file”. Importing a file you already have works offline.
                </p>
                <article
                  v-for="ds in userAcquiredReferenceDatasets"
                  :key="ds.name"
                  class="registered-reference-card"
                >
                  <div class="registered-reference-card__heading">
                    <div>
                      <strong>{{ ds.label }}</strong>
                      <small>{{ conciseTechnicalSummary(ds) }}</small>
                    </div>
                  </div>
                  <div class="registered-reference-card__actions">
                    <a
                      v-if="ds.provider_page"
                      :href="ds.provider_page"
                      target="_blank"
                      rel="noopener noreferrer"
                      :aria-label="`${ds.label}: provider page (opens in a new tab)`"
                      >Provider page</a
                    >
                    <Button
                      label="Import downloaded file"
                      icon="pi pi-file-import"
                      class="p-button-sm"
                      :loading="registeredImportState[ds.name]?.status === 'importing'"
                      :disabled="registeredImportBusy"
                      @click="selectRegisteredReferenceFile(ds)"
                    />
                  </div>
                  <small
                    v-if="registeredImportState[ds.name]?.message"
                    class="registered-reference-card__status"
                    :class="registeredImportState[ds.name]?.status"
                    role="status"
                  >
                    {{ registeredImportState[ds.name]?.message }}
                  </small>
                </article>
                <input
                  ref="registeredReferenceInputRef"
                  class="visually-hidden-file-input"
                  type="file"
                  accept=".zip,application/zip"
                  multiple
                  aria-hidden="true"
                  tabindex="-1"
                  @change="onRegisteredReferenceSelection"
                />
              </Panel>

              <Panel
                v-if="legacyReferenceDatasets.length"
                :toggleable="true"
                :collapsed="legacyCollapsed"
                @update:collapsed="legacyCollapsed = $event"
                class="ref-group-panel"
              >
                <template #header>
                  <span class="ref-panel-header">
                    <i class="pi pi-folder-open"></i>
                    Additional scientific source catalog
                    <Tag :value="String(legacyReferenceDatasets.length)" severity="info" rounded />
                  </span>
                </template>
                <article
                  v-for="ds in legacyReferenceDatasets"
                  :key="dsKey(ds)"
                  class="registered-reference-card"
                >
                  <div class="registered-reference-card__heading">
                    <div>
                      <strong>{{ ds.label }}</strong>
                      <small>{{ legacySourceRequirement(ds) }}</small>
                    </div>
                  </div>
                  <div class="registered-reference-card__actions">
                    <a
                      v-if="ds.requires_runtime_download && ds.download_page"
                      :href="ds.download_page"
                      target="_blank"
                      rel="noopener noreferrer"
                      :aria-label="`${ds.label}: provider page (opens in a new tab)`"
                      >Provider page</a
                    >
                    <Button
                      v-if="ds.requires_runtime_download"
                      label="Open file upload"
                      icon="pi pi-file-import"
                      class="p-button-sm p-button-outlined"
                      @click="openLegacyReferenceUpload(ds)"
                    />
                    <Button
                      v-else
                      label="Select bundled source"
                      icon="pi pi-check"
                      class="p-button-sm p-button-outlined"
                      @click="toggleRefDataset(ds)"
                    />
                  </div>
                </article>
              </Panel>
            </div>

            <!-- Action bar -->
            <div class="ref-action-bar" v-if="selectedRefDatasets.size > 0">
              <span class="ref-selection-count">{{ selectedRefDatasets.size }} selected</span>
              <div class="selected-member-rows">
                <div
                  v-for="member in selectedReferenceMembers"
                  :key="member.key"
                  class="selected-member-row"
                >
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
          <KeepAlive>
            <DatasetSourcePreview
              v-if="activeTab === TAB_IMPORT"
              class="source-preview-pane"
              :sourceRef="previewRefSource"
              :title="previewRefTitle"
              :files="previewRefFiles"
              :overrides="previewRefOverrides"
              :acquisition-required="previewRefDataset?.source === 'registered'"
              @update:overrides="onPreviewRefOverrides"
            />
          </KeepAlive>
        </div>
      </TabPanel>

      <!-- ======================== SYNTHESIS TAB ======================== -->
      <TabPanel :disabled="qualified">
        <!-- #header slot is required so the open_synthesis click target
             (used by Sherpa Advisor's action ontology) lives on the tab
             header. Add the `p-tabview-title` class explicitly so the
             span picks up the same baseline / line-height PrimeVue
             auto-applies for header="…" tabs — without it, the active
             underline sits a couple pixels lower than the others. -->
        <template #header>
          <span class="p-tabview-title" data-action="open_synthesis">Synthesis</span>
        </template>
        <KeepAlive>
          <SynthesisPanel
            v-if="!qualified && activeTab === TAB_SYNTHESIS"
            ref="synthesisPanelRef"
            @saved="onSynthesisSaved"
          />
        </KeepAlive>
      </TabPanel>

      <!-- ======================== UPLOAD TAB ======================== -->
      <TabPanel header="Upload">
        <section class="upload-panel source-side-layout">
          <div class="source-list-pane">
            <div v-if="dataUploadDisabled" class="upload-disabled-notice" :role="availabilityError ? 'alert' : 'status'">
              <span>{{ uploadDisabledMessage }}</span>
              <Button
                v-if="qualified && availabilityError && !isCapabilityDisabled('data_upload')"
                label="Retry access check"
                icon="pi pi-refresh"
                :disabled="availabilityLoading"
                @click="refreshAvailability"
              />
            </div>
            <div class="upload-form">
              <div class="upload-intro">
                <div>
                  <h3>Add scientific files</h3>
                  <p>
                    Select files, a whole folder, or a ZIP. Every admitted spectrum is previewed
                    before it is added.
                  </p>
                </div>
                <Tag
                  v-if="stagedUploadMembers.length"
                  :value="`${stagedUploadMembers.length} ready`"
                  severity="success"
                />
              </div>
              <div class="upload-source-actions" aria-label="Choose scientific sources">
                <Button
                  label="Choose sources"
                  icon="pi pi-folder-open"
                  :disabled="dataUploadDisabled"
                  aria-haspopup="true"
                  aria-controls="upload-source-menu"
                  @click="toggleUploadSourceMenu"
                />
                <Menu
                  id="upload-source-menu"
                  ref="uploadSourceMenuRef"
                  :model="uploadSourceMenuItems"
                  :popup="true"
                />
                <input
                  ref="uploadFilesInputRef"
                  class="visually-hidden-file-input"
                  type="file"
                  :accept="uploadAcceptList"
                  multiple
                  aria-hidden="true"
                  tabindex="-1"
                  @change="onNativeFileSelection"
                />
                <input
                  ref="uploadFolderInputRef"
                  class="visually-hidden-file-input"
                  type="file"
                  multiple
                  webkitdirectory=""
                  directory=""
                  aria-hidden="true"
                  tabindex="-1"
                  @change="onNativeFileSelection"
                />
              </div>
              <small class="field-hint"
                >Choose files or a folder. ZIPs expand automatically; supported members load and
                refused members are reported below.</small
              >
              <div v-if="stagedUploadMembers.length" class="selected-member-rows upload-members">
                <div
                  v-for="member in stagedUploadMembers"
                  :key="member.staging_id"
                  class="selected-member-row"
                  :class="{ previewed: previewUploadId === member.staging_id }"
                  @click="previewUploadMember(member.staging_id)"
                >
                  <span>
                    <strong>{{ member.filename }}</strong>
                    <small v-if="member.source_name && member.source_name !== member.filename">{{
                      member.source_name
                    }}</small>
                    <small v-if="stagedUploadErrors[member.staging_id]" class="upload-cleanup-error">
                      {{ stagedUploadErrors[member.staging_id] }}
                    </small>
                  </span>
                  <Button
                    icon="pi pi-trash"
                    class="p-button-text p-button-sm p-button-rounded p-button-danger"
                    title="Remove"
                    @click.stop="removeStagedUpload(member.staging_id)"
                  />
                </div>
              </div>
              <details v-if="uploadRefusals.length" class="upload-refusals" open>
                <summary>
                  {{ uploadRefusals.length }} source{{ uploadRefusals.length === 1 ? "" : "s" }}
                  not loaded
                </summary>
                <ul>
                  <li
                    v-for="(refusal, index) in uploadRefusals"
                    :key="`${index}:${refusal.source_name}`"
                  >
                    <strong>{{ refusal.source_name }}</strong>
                    <span>{{ refusal.reason }}</span>
                  </li>
                </ul>
              </details>
              <div
                v-if="selectedUploadAssetWarnings.length"
                class="scientific-asset-warning"
                role="status"
                aria-label="Scientific import warning"
              >
                <i class="pi pi-exclamation-triangle" aria-hidden="true" />
                <div>
                  <div v-for="warning in selectedUploadAssetWarnings" :key="warning">
                    {{ warning }}
                  </div>
                </div>
              </div>
              <Panel
                :toggleable="true"
                :collapsed="uploadOptionsCollapsed"
                @update:collapsed="uploadOptionsCollapsed = $event"
                class="upload-options-panel"
              >
                <template #header>
                  <span class="upload-options-heading">
                    <i class="pi pi-sliders-h"></i>
                    Import options and details
                  </span>
                </template>
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
                <div v-if="selectionHasCsv" class="upload-shape-grid">
                  <div class="field">
                    <label>CSV data shape</label>
                    <Dropdown
                      v-model="uploadDataRole"
                      :options="uploadDataRoleOptions"
                      optionLabel="label"
                      optionValue="value"
                      class="upload-shape-control"
                      :disabled="dataUploadDisabled"
                      placeholder="Choose target type"
                    />
                    <small class="field-help">Required before using a supervised analysis starter.</small>
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
                <div
                  v-if="selectedUploadMember && selectedUploadMember.assets.length > 1"
                  class="field"
                >
                  <label for="upload-scientific-asset">Scientific result to preview</label>
                  <Dropdown
                    inputId="upload-scientific-asset"
                    v-model="uploadAssetIds[selectedUploadMember.staging_id]"
                    :options="selectedUploadMember.assets"
                    optionLabel="title"
                    optionValue="asset_id"
                    placeholder="Select the exact result"
                    class="w-full"
                  >
                    <template #option="{ option }">
                      <span
                        >{{ option.title || option.asset_id }} ·
                        {{ option.shape.join(" × ") }}</span
                      >
                    </template>
                  </Dropdown>
                </div>
                <small class="field-hint">{{ uploadFormatHint }}</small>
              </Panel>
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
          <KeepAlive>
            <DatasetSourcePreview
              v-if="activeTab === TAB_UPLOAD"
              class="source-preview-pane"
              :sourceRef="previewUploadSource"
              :title="previewUploadTitle"
              :files="previewUploadFiles"
              :overrides="previewUploadOverrides"
              :csvPlan="selectedUploadCsvPlan"
              @update:overrides="onPreviewUploadOverrides"
            />
          </KeepAlive>
        </section>
      </TabPanel>

      <!-- ======================== LIBRARY TAB ======================== -->
      <TabPanel :disabled="qualified">
        <template #header>
          <span class="p-tabview-title" data-action="open_library">Library</span>
        </template>
        <section v-if="!qualified" class="library-panel">
          <div class="library-header">
            <div>
              <h3 class="library-title">
                <i class="pi pi-book"></i>
                Reference Library
              </h3>
              <p>
                Search local reference entries and packaged compound records. Use Import for
                datasets you want to copy into My Dataset.
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
                :placeholder="
                  isHitranLibrarySource(librarySource)
                    ? 'Search HITRAN species...'
                    : 'Search compounds...'
                "
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
                <InputNumber
                  inputId="library-resolution"
                  v-model="libraryResolutionCm1"
                  :min="0.001"
                  :maxFractionDigits="4"
                  :useGrouping="false"
                />
              </div>
              <div class="field compact-field">
                <label for="library-wmin">Min cm^-1</label>
                <InputNumber
                  inputId="library-wmin"
                  v-model="libraryWavenumberMin"
                  :min="1"
                  :useGrouping="false"
                />
              </div>
              <div class="field compact-field">
                <label for="library-wmax">Max cm^-1</label>
                <InputNumber
                  inputId="library-wmax"
                  v-model="libraryWavenumberMax"
                  :min="2"
                  :useGrouping="false"
                />
              </div>
              <div class="field compact-field">
                <label for="library-temperature">Temperature (K)</label>
                <InputNumber
                  inputId="library-temperature"
                  v-model="libraryTemperatureK"
                  :min="50"
                  :max="5000"
                  :maxFractionDigits="2"
                  :useGrouping="false"
                />
              </div>
              <div class="field compact-field">
                <label for="library-pressure">Pressure (atm)</label>
                <InputNumber
                  inputId="library-pressure"
                  v-model="libraryPressureAtm"
                  :min="0.000001"
                  :maxFractionDigits="6"
                  :useGrouping="false"
                />
              </div>
            </div>
          </div>
          <div class="synthesis-note warn" v-if="isHitranLibrarySource(librarySource)">
            <i class="pi pi-info-circle" />
            <span
              >HITRAN spectra are fetched live when needed and require your own HITRAN API key in
              Settings > API Keys.</span
            >
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
              <div class="empty-state-sm">{{ dataStore.catalogError ? "Catalog unavailable" : "No library entries" }}</div>
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
                    :disabled="
                      !librarySpectra[data.key] ||
                      selectedLibraryKeys.has(data.key) ||
                      hitranLibraryImportActive
                    "
                    :title="
                      librarySpectra[data.key]
                        ? 'Add to the library basket'
                        : 'Load spectrum before adding to the library basket'
                    "
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
                    <ProgressBar
                      :value="librarySpectrumProgress[data.key].progress"
                      :showValue="false"
                    />
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
            <Column
              v-if="librarySource === 'hitran_xsec'"
              header="Measurement"
              style="min-width: 260px"
            >
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
            <Column
              field="file_path"
              header="File"
              style="width: 160px"
              v-if="librarySource === 'nist'"
            >
              <template #body="{ data }">
                <span class="file-size">{{ data.file_path.split("/").pop() }}</span>
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
                <small v-if="member.detail" class="selected-member-detail">{{
                  member.detail
                }}</small>
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
                :value="
                  activeLibraryImportJob.status === 'pending'
                    ? 'In queue'
                    : activeLibraryImportJob.status
                "
                :severity="libraryJobSeverity"
              />
              <span>{{ activeLibraryImportJob.progress }}%</span>
              <span>{{
                activeLibraryImportJob.progress_message || "Preparing HITRAN import"
              }}</span>
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

      <!-- ======================== MULTI-WELL TAB ======================== -->
      <TabPanel header="Multi-well">
        <MultiWellAcquisitionPanel
          :experiment-id="dataStore.activeExperimentId"
          :experiment-name="selectedExperimentName"
          :experiment-options="dataStore.experiments"
          :source-file-id="dataStore.activeFileId"
          :sync-refresh-revision="measuredSamplesRevision"
          @select-experiment="onAcquisitionExperimentSelect"
        />
      </TabPanel>

      <!-- ======================== MY DATASET TAB ======================== -->
      <!-- Persistent dataset collection; all source tabs feed this view. -->
      <TabPanel header="My Dataset" :headerStyle="{ marginLeft: 'auto' }">
        <div class="my-dataset-section">
          <p class="my-dataset-summary">
            {{ dataStore.experiments.length }} dataset{{
              dataStore.experiments.length === 1 ? "" : "s"
            }}
            containing {{ totalExperimentFiles }} file{{ totalExperimentFiles === 1 ? "" : "s" }}
            from Import, Synthesis, Upload, and Library.
          </p>

          <div class="load-panels">
            <!-- Dataset list (left) -->
            <div class="experiment-list-panel">
              <div class="panel-heading">
                <div>
                  <strong>Packaged Datasets</strong>
                  <span>{{ plotSelectionSummary }}</span>
                </div>
              </div>
              <DataTable
                v-if="!dataStore.experimentsError"
                :value="dataStore.experiments"
                :loading="dataStore.experimentsLoading"
                selectionMode="single"
                :selection="selectedExperiment"
                @update:selection="onExperimentSelect"
                dataKey="id"
                :rows="20"
                scrollable
                scrollHeight="flex"
                size="small"
                stripedRows
                class="exp-table"
              >
                <template #empty>
                  <div class="empty-state-sm">No datasets yet</div>
                </template>
                <Column header="Preview" style="width: 68px">
                  <template #header>
                    <PlotSelectionCheckbox
                      :checked="allExperimentsPlotted"
                      :partial="someExperimentsPlotted"
                      :disabled="dataStore.experiments.length === 0"
                      label="Preview all packaged datasets"
                      title="Preview all packaged datasets"
                      @toggle="onPlotAllExperiments"
                    />
                  </template>
                  <template #body="{ data }">
                    <PlotSelectionCheckbox
                      :checked="isExperimentFullyPlotted(data.id)"
                      :partial="isExperimentPartlyPlotted(data.id)"
                      :label="`Preview ${data.name}`"
                      :title="`Include ${data.name} in the data preview`"
                      @toggle="(checked) => onPlotExperimentToggle(data, checked)"
                    />
                  </template>
                </Column>
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
                <Column field="file_count" header="Views" :sortable="true" style="width: 70px" />
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

            <!-- Scientist-selectable data views (right) -->
            <div class="files-panel">
              <div class="panel-heading">
                <div>
                  <strong>Data Views</strong>
                  <span>{{ selectedExperimentName }}</span>
                </div>
                <PlotSelectionCheckbox
                  v-if="selectedExperiment"
                  :checked="isExperimentFullyPlotted(selectedExperiment.id)"
                  :partial="isExperimentPartlyPlotted(selectedExperiment.id)"
                  :disabled="dataStore.experimentFiles.length === 0"
                  :label="`Preview all files in ${selectedExperimentName}`"
                  :title="`Preview all files in ${selectedExperimentName}`"
                  @toggle="onActiveExperimentPlotToggle"
                />
              </div>
              <div v-if="!dataStore.activeExperimentId" class="empty-state">
                <i class="pi pi-arrow-left"></i>
                <span>Select a dataset to view its files</span>
              </div>

              <div v-else-if="dataStore.experimentFilesLoading" class="empty-state">
                <ProgressSpinner style="width: 28px; height: 28px" />
                <span>Loading files...</span>
              </div>

              <div v-else-if="dataStore.experimentFilesRefusal" class="empty-state">
                <i class="pi pi-exclamation-triangle"></i>
                <span>{{ dataStore.experimentFilesRefusal.message }}</span>
                <small
                  v-if="
                    dataStore.experimentFilesRefusal.code === 'trial_dataset_authority_superseded'
                  "
                >
                  Remove this packaged dataset and import the reviewed provider file again.
                </small>
              </div>

              <div v-else-if="dataStore.experimentFiles.length === 0" class="empty-state">
                <i class="pi pi-inbox"></i>
                <span>No files in this dataset</span>
                <small>Use Import, Synthesis, Upload, or Library to add data to this record.</small>
              </div>

              <div v-else class="file-groups">
                <div v-for="stage in fileStages" :key="stage.key" class="file-stage">
                  <div v-if="filesForStage(stage.key).length > 0" class="stage-section">
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
                        :title="fileRowHoverText(file)"
                        :aria-label="fileRowAccessibleLabel(file)"
                        role="button"
                        tabindex="0"
                        @click="onInspectFile(file)"
                        @keydown.enter.prevent="onInspectFile(file)"
                        @keydown.space.prevent="onInspectFile(file)"
                      >
                        <PlotSelectionCheckbox
                          :checked="isFilePlotted(file)"
                          :label="`Preview ${extractFileName(file.file_path)}`"
                          :title="`Include ${extractFileName(file.file_path)} in the data preview`"
                          @toggle="(checked) => onPlotFileToggle(file, checked)"
                        />
                        <div class="file-info">
                          <span class="file-name">{{ dataViewLabel(file) }}</span>
                          <span v-if="formatDatasetFileShape(file)" class="file-size">
                            {{ formatDatasetFileShape(file) }}
                          </span>
                          <span v-if="file.file_size_bytes" class="file-size">
                            {{ formatFileSize(file.file_size_bytes) }}
                          </span>
                        </div>
                        <div class="file-actions">
                          <Button
                            v-if="registeredPackageView(file.file_path)"
                            label="Use only"
                            class="p-button-text p-button-sm"
                            :title="`Use only ${dataViewLabel(file)} for preview and workflow modeling`"
                            @click.stop="useOnlyDataView(file)"
                          />
                          <Button
                            icon="pi pi-download"
                            class="p-button-text p-button-sm p-button-rounded"
                            title="Download"
                            @click.stop="
                              dataStore.downloadFile(file.id, extractFileName(file.file_path))
                            "
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
              <aside
                v-if="activePackageViewNames.length"
                class="active-view-set"
                aria-live="polite"
              >
                <strong>Workflow view set:</strong>
                <span>{{ activePackageViewSummary }}</span>
                <small v-if="activePackageViewNames.length > 1">
                  These package views have different feature spaces and cannot be combined as one
                  ordinary workflow source. Choose <b>Use only</b> beside one view.
                </small>
                <small v-else>
                  This is the single view used for preview and workflow modeling. Clicking a file
                  name changes inspection focus only.
                </small>
                <small v-if="activeProviderRoleSummary">
                  {{ activeProviderRoleSummary }} These source roles remain descriptive metadata;
                  no calibration, test, normal, or fault role is imposed on a new workflow.
                </small>
              </aside>
            </div>
          </div>
          <SelectedSpectraPlotPanel
            :plot-datasets="plotDatasetSources"
            :plot-dataset-count="plottedExperimentIds.length"
            :plot-file-count="plottedFileCount"
            :plot-datasets-loading="plotDatasetsLoading"
            :plot-datasets-error="plotDatasetsError"
            :active-experiment-id="dataStore.activeExperimentId"
            :active-file-name="
              dataStore.activeFilePath ? extractFileName(dataStore.activeFilePath) : null
            "
            @harmonize="goToWorkflow('preprocess.wavenumber_align')"
          />
          <DataContentsPanel
            :active-dataset-name="selectedExperimentName"
            :selected-file-count="activeSelectedFileCount"
            :selected-file-names="activeSelectedFileNames"
            :initial-analysis-target="requestedAnalysisSelection.target"
            :initial-analysis-group="requestedAnalysisSelection.group"
            :analysis-selection-hydrated="analysisSelectionHydrated"
            :analysis-selection-status="analysisSelectionStatus"
            @analysis-choice="onAnalysisChoice"
            @analysis-selection-commit="onAnalysisSelectionCommit"
            @measured-samples-published="measuredSamplesRevision += 1"
          />
          <CollectionDefinitionPanel
            v-if="dataStore.activeExperimentId"
            :experiment-id="dataStore.activeExperimentId"
            :refresh-key="collectionDefinitionRefreshKey"
            :file-types="activeCollectionFileTypes"
            :allow-definition-import="!activeDatasetIsGoverned"
            :governed-source="activeDatasetIsGoverned"
            @changed="onCollectionDefinitionChanged"
          />
          <section v-if="dataStore.activeExperimentId" class="dataset-view-registry" aria-label="Saved dataset definitions">
            <div class="panel-heading">
              <strong>Saved definitions</strong>
              <span>Exact source, included samples, target and group</span>
            </div>
            <div v-if="datasetViewError" role="alert">{{ datasetViewError }}</div>
            <div class="dataset-view-actions">
              <Button label="Show Default" class="p-button-sm p-button-outlined" :disabled="datasetViewBusy" @click="showDefaultDatasetView" />
              <InputText v-model="newDatasetViewName" aria-label="New dataset definition name" placeholder="New definition name" maxlength="120" />
              <Button label="Save as new" class="p-button-sm" :loading="datasetViewBusy" :disabled="!newDatasetViewName.trim() || !analysisSelectionHydrated || dataStore.fileInfoLoading" @click="saveDatasetView" />
            </div>
            <ul class="dataset-view-list">
              <li v-for="view in datasetViews" :key="view.id">
                <span>{{ view.name }}</span>
                <Button label="Show" class="p-button-sm p-button-text" :disabled="datasetViewBusy" @click="showDatasetView(view)" />
                <Button label="Delete" class="p-button-sm p-button-text p-button-danger" :disabled="datasetViewBusy" @click="deleteDatasetView(view)" />
              </li>
            </ul>
          </section>
          <div
            v-if="canReopenSynthesisRecipe || canReopenLibraryBasket"
            class="builder-reopen-actions"
          >
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
          <div
            v-if="pendingInspection && inspectionAssets.length > 1"
            class="inspection-asset-selector"
          >
            <label for="inspection-scientific-asset">Scientific result</label>
            <Dropdown
              inputId="inspection-scientific-asset"
              v-model="inspectionAssetId"
              :options="inspectionAssets"
              optionLabel="title"
              optionValue="asset_id"
              placeholder="Select the exact result to inspect"
              class="w-full"
              @change="onInspectionAssetChange"
            >
              <template #option="{ option }">
                <span
                  >{{ option.title || option.asset_id }} · {{ option.asset_id }} ·
                  {{ option.shape.join(" × ") }}</span
                >
              </template>
            </Dropdown>
            <small
              >The same exact result identity is used by preview, workflows, and model
              application.</small
            >
          </div>
          <div
            v-if="inspectionWarnings.length"
            class="scientific-asset-warning"
            role="status"
            aria-label="Scientific import warning"
          >
            <i class="pi pi-exclamation-triangle" aria-hidden="true" />
            <div>
              <div v-for="warning in inspectionWarnings" :key="warning">{{ warning }}</div>
            </div>
          </div>
        </div>
      </TabPanel>
    </WorkspaceTabs>

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
        <Button label="Cancel" class="p-button-text" @click="showEditDatasetDialog = false" />
        <Button label="Save" icon="pi pi-check" :loading="editingExp" @click="onEditExperiment" />
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
        <strong>{{ deleteTarget ? extractFileName(deleteTarget.file_path) : "" }}</strong
        >?
      </p>
      <template #footer>
        <Button label="Cancel" class="p-button-text" @click="showDeleteDialog = false" />
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
        <Button label="Cancel" class="p-button-text" @click="showDeleteExpDialog = false" />
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
import Menu from "primevue/menu";
import Panel from "primevue/panel";
import ProgressSpinner from "primevue/progressspinner";
import ProgressBar from "primevue/progressbar";
import Tag from "primevue/tag";
import api from "@/api/client";
import { useAppConfig } from "@/composables/useAppConfig";
import { useProjectAvailability } from "@/composables/useProjectAvailability";
import { useDemoMode } from "@/composables/useDemoMode";
import {
  useDataStore,
  type CsvImportPlan,
  type DataMatrixRef,
  type PreparedDataOverrides,
  type StagedUpload,
  type StagedUploadRefusal,
} from "@/stores/data";
import { useAdvisorStore } from "@/stores/advisor";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { useProjectProvenanceStore } from "@/stores/projectProvenance";
import { useWorkflowStore } from "@/stores/workflow";
import { getErrorCode, getErrorMessage } from "@/utils/errors";
import { useToast } from "primevue/usetoast";
import type {
  DatasetAnalysisReadiness,
  DatasetPlotSource,
  ExperimentFile,
  ExperimentFileAssets,
  ExperimentSummary,
  JobInfo,
  ScientificAsset,
  SherpaDatasetDict,
} from "@/types";
import type { ReferenceDatasetOption } from "@/stores/workflow";
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import WorkspaceContext from "@/components/workspace/WorkspaceContext.vue";
import WorkspaceContextItem from "@/components/workspace/WorkspaceContextItem.vue";
import WorkspaceTabs from "@/components/workspace/WorkspaceTabs.vue";
import WorkspaceState from "@/components/workspace/WorkspaceState.vue";
import PlotSelectionCheckbox from "@/components/data/PlotSelectionCheckbox.vue";
import DataContentsPanel from "./DataContentsPanel.vue";
import SelectedSpectraPlotPanel from "./SelectedSpectraPlotPanel.vue";
import CollectionDefinitionPanel, {
  type CollectionDefinitionReceipt,
} from "./CollectionDefinitionPanel.vue";
import DatasetSourcePreview from "./DatasetSourcePreview.vue";
import SynthesisPanel from "./SynthesisPanel.vue";
import MultiWellAcquisitionPanel from "./MultiWellAcquisitionPanel.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import type { SpectrumPayload } from "@/stores/synthesis";
import { alignedSpectrumIdentities, selectedDatasetRows } from "@/utils/multiDatasetOverlay";
import {
  captureDatasetSelection,
  captureLoadedDatasetSelection,
} from "@/utils/myDatasetAdvisorContext";
import {
  createDataSelectionReceiptId,
  storeDataSelectionReceipt,
  type DataSelectionReceipt,
} from "@/utils/workflowDataSelection";
import {
  clearRetainedInspection,
  retainedInspection,
  retainedDatasetWorkspace,
} from "@/utils/retainedInspection";

const DATA_ENTRY_MODE_KEY = "sherpa:data-entry-mode";
const DATA_ENTRY_PROJECT_KEY = "sherpa:data-entry-project-id";
const DATA_ENTRY_DATASET_KEY = "sherpa:data-entry-dataset-intent";
const DATA_ACTIVE_TAB_PREFIX = "spectra_sherpa_data_active_tab_v3";
const DATA_DRAFT_PREFIX = "spectra_sherpa_data_draft_v1";
const MAX_PLOTTED_DATASETS = 12;
const TAB_IMPORT = 0;
const TAB_SYNTHESIS = 1;
const TAB_UPLOAD = 2;
const TAB_LIBRARY = 3;
const TAB_MULTI_WELL = 4;
const TAB_MY_DATASET = 5;

interface AnalysisStarterDatasetIntent {
  schema_version: "spectra-analysis-starter-dataset-intent/1";
  project_id: number;
  dataset_id: string;
  source: string;
  name: string;
  label: string;
  template_slug?: string | null;
  /** Set after the selected reference has been admitted into My Dataset. */
  imported_experiment_id?: number | null;
}

interface WorkflowSourceSelection {
  experiment_id: number;
  dataset_name: string;
  stage: "raw" | "preprocessed" | "synthetic";
  selected_file_ids: number[] | null;
  asset_id: string | null;
  source_manifest_sha256: string;
  collection_definition_sha256: string | null;
  scientific_collection_sha256: string;
  target_authority: {
    schema_version: "spectrasherpa-target-authority/1";
    column: string;
    target_type: "categorical" | "continuous";
    units: string | null;
    source_digest: string;
  } | null;
  group_column: string | null;
  dataset_view_id?: number | null;
  dataset_view_sha256?: string | null;
}

interface WorkflowDataSelectionRevision {
  id: number;
  revision_number: number;
  created_by_name: string;
  created_at: string;
  reason: string | null;
  selection: WorkflowSourceSelection;
}

interface WorkflowDataSelectionContext {
  workflow_id: number;
  workflow_name: string;
  source_node_id: string;
  source_node_label: string;
  project_id: number | null;
  current_revision: WorkflowDataSelectionRevision | null;
  saved_selection: WorkflowSourceSelection | null;
}

const appConfigApi = useAppConfig();
const {
  qualified, availability, error: availabilityError,
  loading: availabilityLoading, refresh: refreshAvailability,
} = useProjectAvailability();
const appConfig = computed(
  () => appConfigApi.config?.value ?? appConfigApi.appConfig?.value ?? null,
);
const { isCapabilityDisabled } = appConfigApi;
const { isDemoMode, uploadsLastWeek, uploadsLimitWeek, uploadsResetWeekAt, fetchQuota } =
  useDemoMode();
const dataStore = useDataStore();
const authStore = useAuthStore();
const projectStore = useProjectStore();
const provenanceStore = useProjectProvenanceStore();
const workflowStore = useWorkflowStore();
const advisorStore = useAdvisorStore();
const toast = useToast();
const route = useRoute();
const router = useRouter();
const workflowContextId = computed(() => queryNumber(route.query.workflow));
const workflowSourceNodeId = computed(() =>
  typeof route.query.source_node === "string" ? route.query.source_node : "",
);
const workflowSelectionContextRequested = computed(
  () => workflowContextId.value !== null && Boolean(workflowSourceNodeId.value),
);
const workflowSelectionContext = ref<WorkflowDataSelectionContext | null>(null);
const workflowSelectionContextLoading = ref(false);
const workflowSelectionContextError = ref<string | null>(null);
const workflowSelectionApplying = ref(false);
const workflowSelectionReason = ref("");
const synthesisPanelRef = ref<InstanceType<typeof SynthesisPanel> | null>(null);
const uploadSourceMenuRef = ref<InstanceType<typeof Menu> | null>(null);
const uploadFilesInputRef = ref<HTMLInputElement | null>(null);
const uploadFolderInputRef = ref<HTMLInputElement | null>(null);
const registeredReferenceInputRef = ref<HTMLInputElement | null>(null);

const activeExperimentMetadata = ref<Record<string, unknown> | null>(null);
type PlotFileRef = Pick<ExperimentFile, "id" | "file_path" | "stage">;
type PlotFileSelection = PlotFileRef[] | null;
const plotFileSelections = ref<Record<number, PlotFileSelection>>({});
type AnalysisChoice = {
  target: string;
  targetType: "categorical" | "continuous" | null;
  targetUnits: string | null;
  sourceDigest: string | null;
  group: string;
  readiness: DatasetAnalysisReadiness | null;
};

type DatasetView = {
  id: number;
  name: string;
  selection_sha256: string;
  selection: {
    selected_file_ids: number[] | null;
    stage: "raw" | "preprocessed" | "synthetic";
    asset_id: string | null;
    target_authority: {
      column: string;
      target_type: "categorical" | "continuous";
      units: string | null;
      source_digest: string;
    } | null;
    group_column: string | null;
    source_manifest_sha256: string;
    collection_definition_sha256: string | null;
    scientific_collection_sha256: string | null;
  };
};
const datasetViews = ref<DatasetView[]>([]);
const selectedDatasetView = ref<DatasetView | null>(null);
const datasetViewError = ref<string | null>(null);
const datasetViewBusy = ref(false);
const newDatasetViewName = ref("");
const exactInspectionSelection = ref(false);
let datasetViewLoadRequest = 0;

async function refreshDatasetViews(experimentId: number | null): Promise<void> {
  const request = ++datasetViewLoadRequest;
  datasetViews.value = [];
  datasetViewError.value = null;
  if (experimentId == null) return;
  try {
    const response = await api.get<DatasetView[]>(`/experiments/${experimentId}/dataset-views`);
    if (request === datasetViewLoadRequest) datasetViews.value = response.data;
  } catch (error) {
    if (request === datasetViewLoadRequest) datasetViewError.value = getErrorMessage(error, "Saved definitions are unavailable.");
  }
}

watch(() => dataStore.activeExperimentId, (id) => {
  selectedDatasetView.value = null;
  void refreshDatasetViews(id);
}, { immediate: true });

async function saveDatasetView(): Promise<void> {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null) return;
  datasetViewBusy.value = true;
  datasetViewError.value = null;
  try {
    const selection = plotFileSelections.value[experimentId];
    const fileIds = Array.isArray(selection) ? selection.map((file) => file.id) : null;
    const defaultStage = dataStore.experimentFiles.some((file) => file.stage === "raw") ? "raw" : "synthetic";
    const sourceFiles = fileIds == null
      ? dataStore.experimentFiles.filter((file) => file.stage === defaultStage)
      : dataStore.experimentFiles.filter((file) => fileIds.includes(file.id));
    const stage = sourceFiles[0]?.stage;
    if (stage !== "raw" && stage !== "preprocessed" && stage !== "synthetic") {
      throw new Error("Select an available dataset source first.");
    }
    if (sourceFiles.some((file) => file.stage !== stage)) throw new Error("Save one data stage at a time.");
    const choice = analysisChoice.value;
    const targetAuthority = choice.target && choice.targetType && choice.sourceDigest
      ? { schema_version: "spectrasherpa-target-authority/1", column: choice.target,
          target_type: choice.targetType, units: choice.targetUnits, source_digest: choice.sourceDigest }
      : null;
    const created = await api.post<DatasetView>(`/experiments/${experimentId}/dataset-views`, {
      name: newDatasetViewName.value.trim(), stage,
      selected_file_ids: fileIds, asset_id: inspectionAssetId.value,
      target_authority: targetAuthority, group_column: choice.group || null,
    });
    newDatasetViewName.value = "";
    await refreshDatasetViews(experimentId);
    if (projectStore.currentProjectId != null) {
      await api.post(`/projects/${projectStore.currentProjectId}/choices`, {
        kind: "dataset", experiment_id: experimentId, dataset_view_id: created.data.id,
      });
      selectedDatasetView.value = created.data;
      await provenanceStore.refresh(projectStore.currentProjectId);
    }
  } catch (error) {
    datasetViewError.value = getErrorMessage(error, "Could not save the exact dataset definition.");
  } finally {
    datasetViewBusy.value = false;
  }
}

async function showDatasetView(view: DatasetView): Promise<void> {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null) return;
  datasetViewBusy.value = true;
  datasetViewError.value = null;
  try {
    const response = await api.get<DatasetView>(`/experiments/${experimentId}/dataset-views/${view.id}`);
    const saved = response.data.selection;
    const fileIds = saved.selected_file_ids;
    const selected = fileIds == null ? null : fileIds.map((id) => {
      const file = dataStore.experimentFiles.find((candidate) => candidate.id === id);
      if (!file) throw new Error("A saved source file is no longer available.");
      return { id: file.id, file_path: file.file_path, stage: file.stage };
    });
    setExperimentPlotSelection(experimentId, selected);
    ++analysisSelectionRequest;
    const authority = saved.target_authority;
    analysisChoice.value = {
      target: authority?.column ?? "", targetType: authority?.target_type ?? null,
      targetUnits: authority?.units ?? null, sourceDigest: authority?.source_digest ?? null,
      group: saved.group_column ?? "", readiness: null,
    };
    requestedAnalysisSelection.value = { target: analysisChoice.value.target, group: analysisChoice.value.group };
    analysisSelectionHydrated.value = true;
    analysisSelectionStatus.value = "idle";
    await showExperimentContents(experimentId, null, saved.asset_id, true);
    await loadPlottedDatasets();
    if (projectStore.currentProjectId != null) {
      await api.post(`/projects/${projectStore.currentProjectId}/choices`, {
        kind: "dataset", experiment_id: experimentId, dataset_view_id: view.id,
      });
      await provenanceStore.refresh(projectStore.currentProjectId);
    }
    selectedDatasetView.value = response.data;
  } catch (error) {
    datasetViewError.value = getErrorMessage(error, "This saved definition cannot be shown.");
  } finally {
    datasetViewBusy.value = false;
  }
}

async function showDefaultDatasetView(): Promise<void> {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null) return;
  datasetViewError.value = null;
  selectedDatasetView.value = null;
  const registered = dataStore.experimentFiles.filter((file) => registeredPackageView(file.file_path));
  const first = registered.length > 1 ? registered[0] : null;
  setExperimentPlotSelection(experimentId, first
    ? [{ id: first.id, file_path: first.file_path, stage: first.stage }] : null);
  await refreshActiveExperimentMetadata(experimentId);
  await showExperimentContents(experimentId);
  await loadPlottedDatasets();
  if (projectStore.currentProjectId != null) {
    try {
      await api.post(`/projects/${projectStore.currentProjectId}/choices`, {
        kind: "dataset", experiment_id: experimentId,
        stage: first?.stage ?? (dataStore.experimentFiles.some((file) => file.stage === "raw") ? "raw" : "synthetic"),
        selected_file_ids: first ? [first.id] : null,
        asset_id: inspectionAssetId.value,
      });
      await provenanceStore.refresh(projectStore.currentProjectId);
    } catch (error) {
      datasetViewError.value = getErrorMessage(error, "Default is displayed, but its active choice could not be recorded.");
    }
  }
}

async function deleteDatasetView(view: DatasetView): Promise<void> {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null || !window.confirm(`Delete saved definition "${view.name}"? Its source data will remain.`)) return;
  datasetViewBusy.value = true;
  datasetViewError.value = null;
  try {
    await api.delete(`/experiments/${experimentId}/dataset-views/${view.id}`);
    if (selectedDatasetView.value?.id === view.id) selectedDatasetView.value = null;
    await refreshDatasetViews(experimentId);
  } catch (error) {
    datasetViewError.value = getErrorMessage(error, "Could not delete this definition.");
  } finally {
    datasetViewBusy.value = false;
  }
}

const analysisChoice = ref<AnalysisChoice>({
  target: "",
  targetType: null,
  targetUnits: null,
  sourceDigest: null,
  group: "",
  readiness: null,
});
const analysisSelectionHydrated = ref(false);
// Saved/user intent must survive temporary empty projections during hydration.
const requestedAnalysisSelection = ref({ target: "", group: "" });
const analysisSelectionStatus = ref<"loading" | "idle" | "saving" | "saved" | "error">("loading");
let analysisSelectionRequest = 0;
const workflowHandoffBusy = computed(
  () =>
    activeTab.value === TAB_MY_DATASET &&
    dataStore.activeExperimentId != null &&
    (dataStore.fileInfoLoading || analysisChoice.value.readiness === null),
);
const workflowHandoffTitle = computed(() =>
  workflowHandoffBusy.value
    ? dataStore.fileInfoError ||
      "Inspecting the active dataset before choosing an analysis starter."
    : "Choose an analysis starter for the current data.",
);
const plottedExperimentIds = computed(() =>
  dataStore.experiments
    .filter((experiment) =>
      Object.prototype.hasOwnProperty.call(plotFileSelections.value, experiment.id),
    )
    .map((experiment) => experiment.id),
);
const plotDatasetSources = ref<DatasetPlotSource[]>([]);
const plotDatasetsLoading = ref(false);
const plotDatasetsError = ref<string | null>(null);
const fileSampleLabelsByExperiment = ref<Record<number, Record<string, string[]>>>({});
const fileSampleLabelRequests = new Map<number, Promise<void>>();
let plotDatasetRequest = 0;
let contentsInspectionRequest = 0;
let experimentFocusRequest = 0;
const fileAssetInventoryCache = new Map<string, Promise<ExperimentFileAssets>>();
let residentDatasets = retainedDatasetWorkspace(
  dataStore,
  `${authStore.user?.id}:${projectStore.currentProjectId}`,
);
const DATA_TAB_IDS = ["import", "synthesis", "upload", "library", "multi-well", "my-dataset"] as const;
const activeTab = ref(0);
const activeTabId = computed({
  get: () => DATA_TAB_IDS[activeTab.value] ?? "import",
  set: (id: string) => {
    const index = DATA_TAB_IDS.indexOf(id as typeof DATA_TAB_IDS[number]);
    if (index < 0) return;
    activeTab.value = index;
    onDataTabSelected(index);
  },
});
const measuredSamplesRevision = ref(0);
const isGuidedExampleSession = ref(false);
const headerActionItems = computed(() => [
  ...(workflowSelectionContextRequested.value
    ? []
    : [
        {
          label: "Workflow",
          icon: "pi pi-arrow-right",
          disabled: workflowHandoffBusy.value,
          command: () => goToWorkflow(),
        },
      ]),
]);
const uploadSourceMenuItems = [
  {
    label: "Files or ZIP",
    icon: "pi pi-file-import",
    command: () => openUploadFilesPicker(),
  },
  {
    label: "Folder",
    icon: "pi pi-folder-open",
    command: () => openUploadFolderPicker(),
  },
];

// R3 — Sherpa Advisor scope routing for the Data tab.  The UI now has
// clearer Data workspace tabs, while the server still owns the stable
// memory vocabulary (`load`, `explore`, `synthesis`).
const DATA_SUBSCOPE_KEYS = ["load", "synthesis", "load", "load", "explore", "explore"] as const;
const DATA_SUBSCOPE_TITLES = [
  "Import",
  "Synthesis",
  "Upload",
  "Library",
  "Multi-well",
  "Contents",
] as const;

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
      builtin?: boolean;
      registered?: boolean;
      synthetic: boolean;
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
  my_dataset?: {
    plot_file_selections: Record<number, PlotFileSelection>;
  };
}

function dataActiveTabStorageKey(): string {
  return `${DATA_ACTIVE_TAB_PREFIX}_${authStore.user?.id ?? "local"}_${
    projectStore.currentProjectId ?? "no-project"
  }`;
}

function dataDraftStorageKey(): string {
  const workflowScope = workflowSelectionContextRequested.value
    ? `:workflow-${workflowContextId.value}:source-${workflowSourceNodeId.value}`
    : "";
  return `${DATA_DRAFT_PREFIX}:${authStore.user?.id ?? "local"}:${
    projectStore.currentProjectId ?? "no-project"
  }${workflowScope}`;
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
    residentDatasets = retainedDatasetWorkspace(dataStore, `${authStore.user?.id}:${next}`);
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
    plotFileSelections.value = {};
    analysisChoice.value = {
      target: "",
      targetType: null,
      targetUnits: null,
      sourceDigest: null,
      group: "",
      readiness: null,
    };
    restoreDataDraft(currentDataDraftStorageKey);
    plotDatasetSources.value = [];
    plotDatasetsError.value = null;
    plotDatasetRequest += 1;
    contentsInspectionRequest += 1;
    fileAssetInventoryCache.clear();
    residentDatasets.clear();
    dataStore.clearActiveExperimentSelection();
    await Promise.all([dataStore.fetchCatalog(), dataStore.fetchExperiments()]);
    await dataStore.restoreActiveExperimentForCurrentProject();
    if (activeTab.value === TAB_MY_DATASET) await ensureInitialContentsSelection();
    await loadPlottedDatasets();
    if (next != null) void syncAdvisorForDataSubtab();
  },
);
onMounted(() => {
  void syncAdvisorForDataSubtab();
});

onBeforeUnmount(() => {
  releaseAdvisorDatasetContext?.();
  persistDataDraftNow();
  stopLibraryImportPolling();
  clearLibrarySpectrumLoadQueue();
});

let releaseAdvisorDatasetContext: (() => void) | undefined;
function registerAdvisorDatasetContext(): void {
  releaseAdvisorDatasetContext?.();
  releaseAdvisorDatasetContext = dataStore.registerAdvisorDatasetContext?.(() => ({
    schema: "spectra-my-dataset-advisor/1",
    authority:
      "Current My Dataset selection; prior workflow result shapes are not current selection counts.",
    captured_at: new Date().toISOString(),
    project_id: projectStore.currentProjectId,
    active_experiment_id: dataStore.activeExperimentId,
    loading: plotDatasetsLoading.value || dataStore.fileInfoLoading,
    selection_error: plotDatasetsError.value,
    analysis_choice: { ...analysisChoice.value, hydrated: analysisSelectionHydrated.value },
    datasets: dataStore.experiments.map((experiment) => ({
      experiment_id: experiment.id,
      name: experiment.name,
      selected: hasExperimentPlotSelection(experiment.id),
      total_files: experiment.file_count,
      plot_members:
        plotDatasetSources.value
          .find((source) => source.experimentId === experiment.id)
          ?.members.map((member) => ({
            file_id: member.fileId,
            file_name: member.fileName,
            ...captureDatasetSelection(
              member.dataset,
              plotDatasetSources.value.find((source) => source.experimentId === experiment.id)
                ?.selectedFileNames ?? null,
            ),
          })) ?? [],
      ...captureLoadedDatasetSelection(
        residentDatasets.get(experiment.id) ??
          (experiment.id === dataStore.activeExperimentId ? dataStore.fileInfo : null),
        plotFileSelections.value[experiment.id]?.map((file) => file.file_path) ??
          (plotFileSelections.value[experiment.id] === null ? null : undefined),
        plotDatasetSources.value.find((source) => source.experimentId === experiment.id),
      ),
    })),
  }));
}
onMounted(registerAdvisorDatasetContext);
watch(() => projectStore.currentProjectId, registerAdvisorDatasetContext);

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
const librarySpectrumProgress = reactive<
  Record<string, { progress: number; message: string | null }>
>({});
const librarySpectrumLoadQueue = ref<LibrarySpectrumQueueItem[]>([]);
const activeLibrarySpectrumLoadKey = ref<string | null>(null);
const activeLibraryPreviewKey = ref<string | null>(null);
let libraryImportPollTimer: ReturnType<typeof window.setInterval> | null = null;
const selectedRefDatasets = reactive(new Set<string>());
const previewRefKey = ref<string | null>(null);
const refOverrides = reactive<Record<string, PreparedDataOverrides>>({});
const builtinCollapsed = ref(true);
const registeredCollapsed = ref(true);
const syntheticCollapsed = ref(true);
const sklearnCollapsed = ref(true);
const legacyCollapsed = ref(true);
const importing = ref(false);
const pendingRegisteredReference = ref<ReferenceDatasetOption | null>(null);
const registeredImportState = reactive<
  Record<string, { status: "importing" | "ready" | "error"; message: string }>
>({});
const registeredImportBusy = computed(() =>
  Object.values(registeredImportState).some((state) => state.status === "importing"),
);
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
const uploadQuotaExhausted = computed(
  () =>
    isDemoMode.value &&
    uploadsLastWeek.value !== null &&
    uploadsLimitWeek.value > 0 &&
    uploadsLimitWeek.value < 999999 &&
    uploadsLastWeek.value >= uploadsLimitWeek.value,
);
const uploadDisabledMessage = computed(() => {
  if (isCapabilityDisabled("data_upload")) return "File upload is disabled for this deployment.";
  if (uploadQuotaExhausted.value) {
    const reset = uploadsResetWeekAt.value
      ? new Date(uploadsResetWeekAt.value).toLocaleString()
      : "later";
    return `Demo upload limit reached. Your next upload is available ${reset}.`;
  }
  if (qualified.value) {
    if (projectStore.currentProjectId == null) return "Select or create a project to upload data.";
    if (availabilityLoading.value) return "Checking project access…";
    if (availabilityError.value) return availabilityError.value;
    if (!availability.value?.write) {
      return "This project is read-only. Upload to a project where you have write access.";
    }
  }
  return "";
});
const dataUploadDisabled = computed(
  () => (qualified.value && !availability.value?.write) || isCapabilityDisabled("data_upload") || uploadQuotaExhausted.value,
);
const uploadDataFormats = computed(() => appConfig.value?.dataFormats ?? null);
const uploadAcceptList = computed(() => {
  if (uploadDataFormats.value?.acceptedFilenamePatterns?.length) return "";
  const accepted = uploadDataFormats.value?.acceptedExtensions;
  return accepted?.join(",") ?? "";
});
const availableUploadFormats = computed(() => {
  const formats = uploadDataFormats.value?.formats;
  if (!formats?.length) return [];
  return formats.filter((format) => format.available).map((format) => format.name);
});
const disabledUploadFormats = computed(() => {
  const formats = uploadDataFormats.value?.formats ?? [];
  return formats.filter((format) => !format.available);
});
const uploadFormatHint = computed(() => {
  const supported = availableUploadFormats.value.join(", ");
  const disabled = disabledUploadFormats.value;
  const resourceHint =
    "50 MB upload limit. Dense CSV/JCAMP text has a decoded-data safety limit; use NPY/NPZ for large numeric matrices";
  if (!disabled.length) return `Supported: ${supported} (${resourceHint})`;
  const hints: string[] = [];
  if (disabled.some((format) => format.unsupportedReason && !format.requiresExport)) {
    hints.push("additional vendor readers are pending native qualification");
  }
  if (disabled.some((format) => format.requiresExport))
    hints.push("OMNICxi/Paradigm containers require spectrum export first");
  return `Supported: ${supported} (${resourceHint}). ${hints.join("; ")}.`;
});
const deleting = ref(false);
const uploadStage = ref("raw");
const uploadDataRole = ref("auto");
const uploadTargetColumn = ref("");
const uploadTargetType = ref("");
const uploadOptionsCollapsed = ref(true);
const selectedFile = ref<File | null>(null);
const stagedUploadMembers = ref<StagedUpload[]>([]);
const stagedUploadErrors = reactive<Record<string, string>>({});
const uploadRefusals = ref<StagedUploadRefusal[]>([]);
const selectionHasCsv = computed(() =>
  stagedUploadMembers.value.some((member) => member.format_id === "csv"),
);
const previewUploadId = ref<string | null>(null);
const uploadOverrides = reactive<Record<string, PreparedDataOverrides>>({});
const uploadAssetIds = reactive<Record<string, string | null>>({});
const deleteTarget = ref<ExperimentFile | null>(null);
const inspectionAssets = ref<ScientificAsset[]>([]);
const inspectionAssetId = ref<string | null>(null);
const inspectionWarnings = ref<string[]>([]);
const pendingInspection = ref<
  | { kind: "file"; experimentId: number; file: ExperimentFile }
  | { kind: "experiment"; experimentId: number }
  | null
>(null);

// Inline "Dataset name" inputs on Import + Upload subtabs. Mirror the
// Synthesis pattern: name the new My Dataset before clicking "Add to
// My Dataset"; the click creates the Experiment and ingests in one step.
const importDatasetName = ref("");
const libraryDatasetName = ref("");
const uploadDatasetName = ref("");

function clearUploadFileSelection() {
  selectedFile.value = null;
  if (uploadFilesInputRef.value) uploadFilesInputRef.value.value = "";
  if (uploadFolderInputRef.value) uploadFolderInputRef.value.value = "";
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

function replaceReactiveRecord<T>(
  target: Record<string, T>,
  source: Record<string, T> | undefined,
): void {
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
  libraryRangeMode.value = isLibraryRangeMode(libraryDraft.range_mode)
    ? libraryDraft.range_mode
    : "widest";
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
        builtin: builtinCollapsed.value,
        registered: registeredCollapsed.value,
        synthetic: syntheticCollapsed.value,
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
    my_dataset: {
      plot_file_selections: cloneJson(plotFileSelections.value),
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
      const selectedKey = Array.isArray(importDraft.selected_keys)
        ? importDraft.selected_keys.find((value) => typeof value === "string" && value.trim())
        : null;
      replaceReactiveSet(selectedRefDatasets, selectedKey ? [selectedKey] : []);
      previewRefKey.value =
        typeof importDraft.preview_key === "string" ? importDraft.preview_key : null;
      replaceReactiveRecord(refOverrides, importDraft.overrides);
      importDatasetName.value = stringOrEmpty(importDraft.dataset_name);
      builtinCollapsed.value = importDraft.collapsed?.builtin ?? true;
      registeredCollapsed.value = importDraft.collapsed?.registered ?? true;
      syntheticCollapsed.value = importDraft.collapsed?.synthetic ?? true;
      sklearnCollapsed.value = importDraft.collapsed?.sklearn ?? true;
    }

    applyLibraryDraft(draft.library);
    if (draft.my_dataset) {
      const restoredSelections: Record<number, PlotFileSelection> = {};
      for (const [rawExperimentId, rawSelection] of Object.entries(
        draft.my_dataset.plot_file_selections ?? {},
      )) {
        const experimentId = Number(rawExperimentId);
        if (!Number.isInteger(experimentId) || experimentId < 1) continue;
        if (rawSelection === null) {
          restoredSelections[experimentId] = null;
          continue;
        }
        if (!Array.isArray(rawSelection)) continue;
        const files = rawSelection.filter(
          (file): file is PlotFileRef =>
            Boolean(file) &&
            Number.isInteger(Number(file.id)) &&
            Number(file.id) > 0 &&
            typeof file.file_path === "string" &&
            Boolean(file.file_path),
        );
        if (files.length) restoredSelections[experimentId] = files;
      }
      plotFileSelections.value = restoredSelections;
    }
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
  const first = Array.from(selectedRefDatasets)[0];
  const [, ...rest] = first.split("::");
  return referenceByKey(first)?.label ?? rest.join("::");
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
  { label: "Categorical", value: "categorical" },
  { label: "Continuous", value: "continuous" },
];

const selectedUploadMember = computed(
  () =>
    stagedUploadMembers.value.find((member) => member.staging_id === previewUploadId.value) ??
    stagedUploadMembers.value[0] ??
    null,
);
function uniqueAssetWarnings(assets: ScientificAsset[]): string[] {
  return [
    ...new Set(assets.flatMap((asset) => asset.warnings ?? []).filter((warning) => warning.trim())),
  ];
}
const selectedUploadAssetWarnings = computed(() => {
  const member = selectedUploadMember.value;
  if (!member) return [];
  const selectedId = uploadAssetIds[member.staging_id] ?? null;
  if (selectedId) {
    const selected = member.assets.find((asset) => asset.asset_id === selectedId);
    return selected ? uniqueAssetWarnings([selected]) : [];
  }
  return uniqueAssetWarnings(member.assets);
});
const previewUploadSource = computed<DataMatrixRef | null>(() => {
  const member = selectedUploadMember.value;
  if (!member) return null;
  const assetId = uploadAssetIds[member.staging_id] ?? null;
  if (member.assets.length > 1 && !assetId) return null;
  return {
    kind: "staged",
    staging_id: member.staging_id,
    asset_id: assetId,
    overrides: uploadOverrides[member.staging_id] ?? null,
  };
});
const previewUploadTitle = computed(() => selectedUploadMember.value?.filename ?? "Upload preview");
const previewUploadFiles = computed<SourcePreviewFile[]>(() =>
  selectedUploadMember.value
    ? sourcePreviewFilesFromNames([selectedUploadMember.value.filename])
    : [],
);
const previewUploadOverrides = computed(() =>
  selectedUploadMember.value ? (uploadOverrides[selectedUploadMember.value.staging_id] ?? {}) : {},
);
const selectedUploadCsvPlan = computed<CsvImportPlan | null>(
  () => selectedUploadMember.value?.csv_import_plan ?? null,
);

let uploadControlsHydrating = false;
let uploadControlsHydrationRun = 0;

function uploadControlOverrides(
  member: StagedUpload,
  existing: PreparedDataOverrides = {},
): PreparedDataOverrides {
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
  uploadTargetType.value = overrides?.target_type || "";
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

watch([uploadDataRole, uploadTargetColumn, uploadTargetType], () => {
  if (uploadControlsHydrating) return;
  const member = selectedUploadMember.value;
  if (!member) return;
  uploadOverrides[member.staging_id] = uploadControlOverrides(
    member,
    uploadOverrides[member.staging_id] ?? {},
  );
});

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
  return dataStore.experiments.find((e) => e.id === dataStore.activeExperimentId) ?? null;
});

const allExperimentsPlotted = computed(
  () =>
    dataStore.experiments.length > 0 &&
    dataStore.experiments
      .slice(0, MAX_PLOTTED_DATASETS)
      .every((experiment) => plotFileSelections.value[experiment.id] === null),
);
const someExperimentsPlotted = computed(
  () => plottedExperimentIds.value.length > 0 && !allExperimentsPlotted.value,
);
const plottedFileCount = computed(() =>
  dataStore.experiments.reduce((total, experiment) => {
    if (!Object.prototype.hasOwnProperty.call(plotFileSelections.value, experiment.id)) {
      return total;
    }
    const selection = plotFileSelections.value[experiment.id];
    return total + (selection === null ? experiment.file_count : selection.length);
  }, 0),
);
const activeSelectedFileCount = computed(() => {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null || !hasExperimentPlotSelection(experimentId)) return 0;
  const selection = plotFileSelections.value[experimentId];
  return selection === null ? (selectedExperiment.value?.file_count ?? 0) : selection.length;
});
const activeSelectedFiles = computed(() => {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null || !hasExperimentPlotSelection(experimentId)) return [];
  const selection = plotFileSelections.value[experimentId];
  if (selection === null) return dataStore.experimentFiles;
  const selectedIds = new Set(selection.map((file) => file.id));
  return dataStore.experimentFiles.filter((file) => selectedIds.has(file.id));
});
const activeSelectedFileNames = computed(() =>
  activeSelectedFiles.value.map((file) => extractFileName(file.file_path)),
);
function restoreResidentInspection(dataset: SherpaDatasetDict): void {
  dataStore.clearInspection();
  dataStore.fileInfo = dataset;
  const files = activeSelectedFiles.value.length
    ? activeSelectedFiles.value
    : dataStore.experimentFiles.filter((file) =>
        file.stage === (dataset.metadata?.contents_stage ?? "raw"),
      );
  if (files.length === 1) dataStore.activateFile(files[0].id, files[0].file_path);
}
const activePackageViewNames = computed(() =>
  activeSelectedFiles.value
    .map((file) => registeredPackageView(file.file_path))
    .filter((value): value is string => value !== null),
);
const activePackageViewSummary = computed(() => {
  const views = activeSelectedFiles.value.flatMap((file) => {
    const label = registeredPackageView(file.file_path);
    if (!label) return [];
    if (typeof file.n_samples !== "number") return [label];
    return [
      `${label} (${file.n_samples.toLocaleString()} row${file.n_samples === 1 ? "" : "s"})`,
    ];
  });
  return views.length ? views.join(", ") : "No package view selected";
});
const activeProviderRoleSummary = computed(() => {
  const roleValues = dataStore.fileInfo?.sample_axis?.sample_table?.analysis_role;
  if (!Array.isArray(roleValues)) return null;
  const counts = new Map<string, number>();
  for (const value of roleValues) {
    const role = String(value).trim();
    if (role) counts.set(role, (counts.get(role) ?? 0) + 1);
  }
  if (!counts.size) return null;
  return `Provider row roles: ${[...counts].map(([role, count]) => `${role} (${count})`).join(", ")}.`;
});

const plotSelectionSummary = computed(() => {
  if (plottedFileCount.value === 0) return "Choose datasets or files.";
  return `${plottedFileCount.value} file${plottedFileCount.value === 1 ? "" : "s"} selected.`;
});

const selectedExperimentName = computed(
  () => selectedExperiment.value?.name ?? "No dataset selected",
);

const selectedExperimentFileCount = computed(
  () => selectedExperiment.value?.file_count ?? dataStore.experimentFiles.length,
);

const collectionDefinitionRefreshKey = computed(() =>
  dataStore.experimentFiles
    .map((file) => `${file.id}:${file.stage}:${file.file_size_bytes ?? 0}`)
    .join("|"),
);

const activeCollectionFileTypes = computed(() => [
  ...new Set(
    dataStore.experimentFiles
      .map((file) => file.file_type?.trim().toUpperCase())
      .filter((value): value is string => Boolean(value)),
  ),
]);

const activeDatasetIsGoverned = computed(() => {
  const datasetId = dataStore.fileInfo?.dataset_id;
  const sourceCollection = objectOrNull(dataStore.fileInfo?.metadata?.source_collection);
  const sourceIdentity = objectOrNull(dataStore.fileInfo?.source_identity);
  const sourceKind = stringOrEmpty(activeExperimentMetadata.value?.source_kind);
  return (
    (typeof datasetId === "string" && datasetId.startsWith("builtin:")) ||
    sourceCollection?.source === "builtin" ||
    (typeof sourceCollection?.dataset_id === "string" &&
      sourceCollection.dataset_id.startsWith("builtin:")) ||
    sourceKind === "user_acquired_registered_reference" ||
    sourceKind === "builtin_reference" ||
    sourceIdentity?.source_kind === "user_acquired_registered_reference" ||
    typeof activeExperimentMetadata.value?.reference_projection_id === "string" ||
    typeof activeExperimentMetadata.value?.reference_package_id === "string"
  );
});

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
  dataStore.experiments.reduce((total, experiment) => total + (experiment.file_count ?? 0), 0),
);

const inspectedDatasetShape = computed(() => {
  if (dataStore.fileInfo) {
    const selected = activeSelectedFileNames.value;
    const rows = selected.length ? selectedDatasetRows(dataStore.fileInfo, selected) : null;
    return `${rows?.length ?? dataStore.fileInfo.n_samples} samples × ${dataStore.fileInfo.n_features} features`;
  }
  if (dataStore.catalogDatasetInfo?.n_samples || dataStore.catalogDatasetInfo?.n_features) {
    return `${dataStore.catalogDatasetInfo.n_samples ?? "?"} samples × ${dataStore.catalogDatasetInfo.n_features ?? "?"} features`;
  }
  return `${selectedExperimentFileCount.value} file${selectedExperimentFileCount.value === 1 ? "" : "s"}`;
});

const syntheticFileCount = computed(() => filesForStage("synthetic").length);

const synthesisStateLabel = computed(() =>
  syntheticFileCount.value > 0
    ? `${syntheticFileCount.value} synthetic file${syntheticFileCount.value === 1 ? "" : "s"}`
    : "Ready to generate",
);

const synthesisStateDetail = computed(() =>
  selectedExperiment.value
    ? "Create time-series mixtures for downstream models"
    : "Select or create a dataset record first",
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
    case TAB_IMPORT:
      return "Import";
    case TAB_SYNTHESIS:
      return "Synthesis";
    case TAB_UPLOAD:
      return "Upload";
    case TAB_LIBRARY:
      return "Library";
    case TAB_MULTI_WELL:
      return "Multi-well";
    case TAB_MY_DATASET:
      return "My Dataset";
    default:
      return "—";
  }
});

const activeSubtabValue = computed(() => {
  switch (activeTab.value) {
    case TAB_IMPORT:
      return "Reference catalog";
    case TAB_SYNTHESIS:
      return synthesisStateLabel.value;
    case TAB_UPLOAD:
      return dataStore.activeExperimentId
        ? `Add to ${selectedExperimentName.value}`
        : "Pick a dataset first";
    case TAB_LIBRARY:
      return selectedLibraryKeys.size
        ? `${selectedLibraryKeys.size} in basket`
        : "Pure compound library";
    case TAB_MULTI_WELL:
      return dataStore.activeExperimentId ? selectedExperimentName.value : "Pick a dataset first";
    case TAB_MY_DATASET:
      return selectedExperimentName.value;
    default:
      return "—";
  }
});

const activeSubtabDetail = computed(() => {
  switch (activeTab.value) {
    case TAB_IMPORT:
      return qualified.value
        ? "Local catalog references and exact registered uploads"
        : "Browse reference datasets — Add to My Dataset";
    case TAB_SYNTHESIS:
      return synthesisStateDetail.value;
    case TAB_UPLOAD:
      return selectedFile.value
        ? `Ready to add ${selectedFile.value.name}`
        : stagedUploadMembers.value.length
          ? `${stagedUploadMembers.value.length} staged file${stagedUploadMembers.value.length === 1 ? "" : "s"}`
          : "Stage + file → Add to My Dataset";
    case TAB_LIBRARY:
      return selectedLibraryKeys.size
        ? "Review basket — Add to My Dataset"
        : "Browse pure-compound reference spectra";
    case TAB_MULTI_WELL:
      return "Multi-well experiment acquisition plan";
    case TAB_MY_DATASET:
      return (
        inspectedDatasetShape.value ||
        `${selectedExperimentFileCount.value} file${selectedExperimentFileCount.value === 1 ? "" : "s"}`
      );
    default:
      return "";
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
  })),
);

function isHitranLibrarySource(source: LibrarySource): boolean {
  return source === "hitran" || source === "hitran_xsec";
}

const activeLibraryRows = computed<LibraryRow[]>(() =>
  librarySource.value === "hitran"
    ? hitranLibraryRows.value
    : librarySource.value === "hitran_xsec"
      ? hitranXsecLibraryRows.value
      : nistLibraryRows.value,
);

const filteredLibrary = computed<LibraryRow[]>(() => {
  const q = librarySearch.value.toLowerCase().trim();
  if (isHitranLibrarySource(librarySource.value)) return activeLibraryRows.value;
  if (!q) return activeLibraryRows.value;
  return activeLibraryRows.value.filter(
    (d) =>
      d.compound_name.toLowerCase().includes(q) ||
      d.cas_number.toLowerCase().includes(q) ||
      (d.formula || "").toLowerCase().includes(q),
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
  return [`${n} pts`, `${min.toFixed(2)}-${max.toFixed(2)} cm^-1`, spectrum.y_quantity]
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
  const body =
    Math.abs(low - high) < 1e-9 ? formatNumber(low) : `${formatNumber(low)}-${formatNumber(high)}`;
  return suffix ? `${body} ${suffix}` : body;
}

function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "blank";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 4, useGrouping: false });
}

function hitranXsecOptionLabel(option: HitranXsecOption, index: number): string {
  const temp = formatRange(option.temperature_k, "K");
  const pressure = formatRange(option.pressure_torr, "Torr");
  const resolution = option.resolution_cm1
    ? `${formatNumber(option.resolution_cm1)} cm^-1`
    : "blank res.";
  const broadener = option.broadener || "blank broadener";
  return `${index + 1}. T ${temp} · p ${pressure} · ${resolution} · ${broadener}`;
}

function hitranXsecOptionChoices(entry: LibraryRow): Array<{ label: string; value: number }> {
  const options = entry.xsec_options?.length ? entry.xsec_options : [{}];
  return options.map((option, index) => ({
    label: hitranXsecOptionLabel(option, index),
    value: index,
  }));
}

const selectedLibraryMembers = computed(() =>
  Object.values(selectedLibraryRows)
    .filter((entry) => selectedLibraryKeys.has(entry.key))
    .map((entry) => ({
      key: entry.key,
      label: libraryLabel(entry),
      detail: libraryBasketDetail(entry),
    })),
);

const hitranLibraryImportActive = computed(
  () =>
    activeLibraryImportJob.value !== null &&
    ["pending", "running"].includes(activeLibraryImportJob.value.status),
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
    xsec_option: entry.source === "hitran_xsec" ? (entry.selected_xsec_option ?? 0) : null,
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
      ? (option.pressure_torr[0] + option.pressure_torr[1]) / 2 / 760
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
  if (
    entry.source === "hitran_xsec" &&
    settings.xsec_option !== null &&
    settings.xsec_option !== undefined
  ) {
    parts.push(`measurement ${settings.xsec_option + 1}`);
  }
  if (settings.points) parts.push(`${settings.points} pts`);
  if (settings.y_quantity) parts.push(settings.y_quantity);
  return parts.join(" · ");
}

function nistSpectrumToPayload(
  entry: LibraryRow,
  spectrum: NistLibrarySpectrumResponse,
): SpectrumPayload {
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
      throw new Error(
        response.data.error_message || response.data.progress_message || "Spectrum load failed",
      );
    }
  }
}

async function fetchLibrarySpectrum(entry: LibraryRow): Promise<SpectrumPayload> {
  if (entry.source === "nist") {
    if (entry.id == null) throw new Error("NIST library row is missing an id");
    const response = await api.get<NistLibrarySpectrumResponse>(
      `/datasets/library/${entry.id}/spectrum`,
    );
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
    throw new Error(
      loadResponse.data.message || "Spectrum load did not return a spectrum or job id.",
    );
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
  if (
    isHitranLibrarySource(entry.source) &&
    activeLibrarySpectrumLoadKey.value &&
    activeLibrarySpectrumLoadKey.value !== entry.key
  ) {
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
            ? firstOption.resolution_cm1
              ? `${formatNumber(firstOption.resolution_cm1)} cm^-1`
              : "measured"
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

const visibleRegisteredReferences = computed<ReferenceDatasetOption[]>(() => {
  const registered = dataStore.referenceCatalog?.registered ?? [];
  const packages = new Set<string>();
  return registered.flatMap((dataset) => {
    const packaged = dataset.dataset_package;
    if (!packaged) return [dataset];
    if (packages.has(packaged.package_id)) return [];
    packages.add(packaged.package_id);
    return [
      {
        ...dataset,
        name: packaged.package_id,
        label: packaged.package_title,
        description: packaged.package_description,
        technical_summary:
          packaged.package_id === "eigenvector-cgl-nir-v1"
            ? "One 231-sample NIR view retains Casein, Glucose, Lactate, and Moisture measurements; the provider calibration/test assignment is visible as metadata and is not imposed on new models."
            : packaged.package_id === "eigenvector-corn-v1"
              ? "Three aligned NIR instrument views (M5, MP5, and MP6) share 80 specimens and Moisture, Oil, Protein, and Starch annotations; M5 starts selected."
              : packaged.package_id === "eigenvector-diesel-d4052-v1"
                ? "Three NIR cohorts contain 122 low-level A, 121 low-level B, and 20 high-level measurements with paired D4052 density results; low-level A starts selected and cross-set specimen alignment is not assumed."
                : packaged.package_id === "eigenvector-nir-shootout-v1"
                  ? "Six NIR data views span calibration, test, and validation cohorts on two instruments, with Weight, Hardness, and Assay annotations; calibration instrument 1 starts selected."
                  : packaged.package_id === "eigenvector-metal-etch-v1"
                    ? "Three complementary process views contain 21 machine-sensor variables, 129 OES wavelengths, and 71 RF-monitor variables; OES starts selected and cross-view row alignment is not assumed."
                    : dataset.technical_summary,
      },
    ];
  });
});

const userAcquiredReferenceDatasets = computed<ReferenceDatasetOption[]>(() => {
  return visibleRegisteredReferences.value;
});

const legacyReferenceDatasets = computed<ReferenceDatasetOption[]>(() => {
  const catalog = dataStore.referenceCatalog;
  if (!catalog) return [];
  return [...catalog.eigenvector, ...catalog.oes];
});

const allReferenceDatasets = computed<ReferenceDatasetOption[]>(() => {
  const catalog = dataStore.referenceCatalog;
  if (!catalog) return [];
  return [
    ...catalog.builtin,
    ...catalog.synthetic,
    ...catalog.sklearn,
    ...userAcquiredReferenceDatasets.value,
    ...legacyReferenceDatasets.value,
  ];
});

function legacySourceRequirement(dataset: ReferenceDatasetOption): string {
  if (dataset.requires_runtime_download) {
    return "Provider file required. Download it outside Sherpa, upload the exact local file, then choose its dataset view. This catalog card does not select a view for you.";
  }
  return "Bundled with this deployment and available without network egress.";
}

function openLegacyReferenceUpload(dataset: ReferenceDatasetOption) {
  previewRefKey.value = dsKey(dataset);
  activeTab.value = TAB_UPLOAD;
  persistActiveDataTab();
}

function conciseTechnicalSummary(dataset: ReferenceDatasetOption): string {
  if (dataset.source === "builtin" && dataset.name === "lavender-essential-oil-v1") {
    return "33 FTIR spectra with specimen, botanical group, and authenticity labels.";
  }
  if (dataset.technical_summary?.trim()) return dataset.technical_summary.trim();
  return "Qualified reference data for native Sherpa analysis.";
}

function dsKey(ds: { source?: string; name: string }): string {
  return `${ds.source || "unknown"}::${ds.name}`;
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
  }),
);

const previewRefDataset = computed(() =>
  previewRefKey.value ? referenceByKey(previewRefKey.value) : null,
);
const previewRefSource = computed<DataMatrixRef | null>(() => {
  const dataset = previewRefDataset.value;
  if (!dataset || dataset.source === "registered") return null;
  return {
    kind: "reference",
    project_id: projectStore.currentProjectId,
    source: dataset.source || "unknown",
    name: dataset.name,
    overrides: refOverrides[dsKey(dataset)] ?? null,
  };
});
const previewRefTitle = computed(() => {
  const dataset = previewRefDataset.value;
  const intent = pendingAnalysisStarterIntent();
  if (dataset?.source === "registered" && intent) return intent.label;
  return dataset?.label ?? "Reference preview";
});
const previewRefFiles = computed<SourcePreviewFile[]>(() => {
  const dataset = previewRefDataset.value;
  if (!dataset) return [];
  if (dataset.files?.length) return sourcePreviewFilesFromNames(dataset.files);
  if (dataset.file_path) return sourcePreviewFilesFromNames([dataset.file_path]);
  return [];
});
const previewRefOverrides = computed(() =>
  previewRefKey.value ? (refOverrides[previewRefKey.value] ?? {}) : {},
);

function toggleRefDataset(ds: ReferenceDatasetOption) {
  const key = dsKey(ds);
  if (selectedRefDatasets.has(key)) {
    selectedRefDatasets.delete(key);
    if (previewRefKey.value === key) previewRefKey.value = null;
  } else {
    selectedRefDatasets.clear();
    selectedRefDatasets.add(key);
    previewRefKey.value = key;
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

function isDefiniteImportRefusal(error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  return status !== undefined && [400, 403, 404, 409, 413, 422].includes(status);
}

async function onImportSelectedDatasets(): Promise<boolean> {
  if (selectedRefDatasets.size === 0) return false;
  importing.value = true;
  let createdExperimentId: number | null = null;
  const starterIntent = pendingAnalysisStarterIntent();
  try {
    // Synthesis-style flow: each click creates a new My Dataset with the
    // typed name (or a sensible default if blank), then ingests the
    // selected references into it. The user no longer has to pre-create a
    // dataset via the dialog.
    const name = importDatasetName.value.trim() || defaultImportDatasetName();
    const created = await dataStore.createExperiment(
      name,
      undefined,
      projectStore.currentProjectId,
    );
    createdExperimentId = created.id;
    await dataStore.selectExperiment(created.id);

    const datasets = Array.from(selectedRefDatasets).map((key) => {
      const [source, ...rest] = key.split("::");
      return { source, name: rest.join("::"), overrides: refOverrides[key] ?? null };
    });
    const result = await dataStore.importReferenceDatasets(created.id, datasets);
    const admittedExperimentId = result.experiment_id ?? created.id;
    if (admittedExperimentId !== created.id) {
      await dataStore.deleteExperiment(created.id);
    }
    createdExperimentId = null;
    if (starterIntent) {
      // Persist completion as soon as the server returns the admitted
      // experiment. Preview refreshes are UI work and must not make a
      // committed import look retryable on the next route visit.
      try {
        window.sessionStorage.setItem(
          DATA_ENTRY_DATASET_KEY,
          JSON.stringify({ ...starterIntent, imported_experiment_id: admittedExperimentId }),
        );
      } catch {
        // Session storage is an enhancement; the dataset remains durable.
      }
    }
    await dataStore.selectExperiment(admittedExperimentId);
    toast.add({
      severity: "success",
      summary: "Import Complete",
      detail: result.reused_existing
        ? `This reference is already in My Dataset. The existing dataset is open.`
        : `Imported ${result.imported} file(s) into "${name}"`,
      life: 3000,
    });
    selectedRefDatasets.clear();
    importDatasetName.value = "";
    await refreshProjectContext();
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    await showExperimentContents(admittedExperimentId);
    return true;
  } catch (err: unknown) {
    if (createdExperimentId !== null && isDefiniteImportRefusal(err)) {
      try {
        await dataStore.deleteExperiment(createdExperimentId);
      } catch {
        // Preserve the original failure.
      }
    }
    toast.add({
      severity: "error",
      summary: "Import Failed",
      detail: getErrorMessage(err, "Failed to import datasets"),
      life: 5000,
    });
    return false;
  } finally {
    importing.value = false;
  }
}

function selectRegisteredReferenceFile(dataset: ReferenceDatasetOption): void {
  pendingRegisteredReference.value = dataset;
  if (registeredReferenceInputRef.value) {
    registeredReferenceInputRef.value.value = "";
    registeredReferenceInputRef.value.click();
  }
}

async function onRegisteredReferenceSelection(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  const dataset = pendingRegisteredReference.value;
  input.value = "";
  pendingRegisteredReference.value = null;
  if (!files.length || !dataset) return;

  const requiredFiles = dataset.dataset_package?.artifact_ids.length ?? 1;
  if (files.length !== requiredFiles) {
    const message = `${dataset.label} requires exactly ${requiredFiles} downloaded provider file${requiredFiles === 1 ? "" : "s"}; select them together.`;
    registeredImportState[dataset.name] = { status: "error", message };
    toast.add({
      severity: "warn",
      summary: "Select Complete Package",
      detail: message,
      life: 6000,
    });
    return;
  }

  registeredImportState[dataset.name] = {
    status: "importing",
    message: `Verifying ${files.length} provider file${files.length === 1 ? "" : "s"} — importing ${dataset.label}`,
  };
  let createdExperimentId: number | null = null;
  try {
    const packaged = dataset.dataset_package;
    const created = await dataStore.createExperiment(
      dataset.label,
      dataset.description || undefined,
      projectStore.currentProjectId,
      {
        source_kind: "user_acquired_registered_reference",
        ...(packaged
          ? { reference_package_id: packaged.package_id }
          : { reference_projection_id: dataset.name }),
        provider: dataset.provider,
      },
    );
    createdExperimentId = created.id;
    const result = await dataStore.importRegisteredReference(
      created.id,
      packaged ? { packageId: packaged.package_id } : { projectionId: dataset.name },
      files,
    );
    const admittedExperimentId = result.experiment_id ?? created.id;
    if (admittedExperimentId !== created.id) {
      await dataStore.deleteExperiment(created.id);
    }
    createdExperimentId = null;
    await dataStore.selectExperiment(admittedExperimentId);
    await refreshProjectContext();
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    const initialFileIds = result.initial_file_ids ?? [];
    await showExperimentContents(admittedExperimentId, initialFileIds[0] ?? null);
    if (initialFileIds.length) {
      const initialIds = new Set(initialFileIds);
      const initialViews = result.files
        .filter((entry) => initialIds.has(entry.id))
        .map(({ id, file_path, stage }) => ({ id, file_path, stage }));
      setExperimentPlotSelection(admittedExperimentId, initialViews);
      await loadPlottedDatasets();
    }
    registeredImportState[dataset.name] = {
      status: "ready",
      message: result.reused_existing
        ? `Ready — opened the existing ${dataset.label} in My Dataset`
        : `Ready — ${dataset.label} is available in My Dataset`,
    };
    toast.add({
      severity: "success",
      summary: "Reference Verified",
      detail: result.reused_existing
        ? `${dataset.label} was already verified. The existing dataset is open in My Dataset.`
        : `${dataset.label} is ready in My Dataset.`,
      life: 4000,
    });
  } catch (error: unknown) {
    if (createdExperimentId !== null && isDefiniteImportRefusal(error)) {
      try {
        await dataStore.deleteExperiment(createdExperimentId);
      } catch {
        // The server owns cleanup truth; never obscure the admission refusal.
      }
    }
    const message = getErrorMessage(
      error,
      `This file does not match the registered ${dataset.label} reference file. ` +
        "Download it again from the Eigenvector dataset catalog. No data from the refused file was retained.",
    );
    registeredImportState[dataset.name] = { status: "error", message };
    toast.add({ severity: "error", summary: "Reference Refused", detail: message, life: 7000 });
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
      detail:
        response.data.error_message ||
        response.data.progress_message ||
        "Failed to import HITRAN spectra",
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
    const created = await dataStore.createExperiment(
      name,
      undefined,
      projectStore.currentProjectId,
      {
        builder_state: {
          kind: "library_basket",
          version: 1,
          title: name,
          library: libraryDraft,
        },
      },
    );
    await dataStore.selectExperiment(created.id);

    const hitranRows = selectedRows.filter(
      (entry) => isHitranLibrarySource(entry.source) && entry.component_id,
    );
    const componentSpecs = hitranRows.map((entry) => {
      const frozen = entry.frozen_settings ?? freezeLibrarySettings(entry);
      return {
        component_id:
          entry.source === "hitran_xsec"
            ? frozen.component_id ||
              `${String(entry.component_id)}#${entry.selected_xsec_option ?? 0}`
            : String(entry.component_id),
        resolution_cm1:
          frozen.resolution_cm1 ?? (entry.source === "hitran" ? libraryResolutionCm1.value : null),
        wavenumber_min:
          frozen.wavenumber_min ?? (entry.source === "hitran" ? libraryWavenumberMin.value : null),
        wavenumber_max:
          frozen.wavenumber_max ?? (entry.source === "hitran" ? libraryWavenumberMax.value : null),
        temperature_k:
          frozen.temperature_k ?? (entry.source === "hitran" ? libraryTemperatureK.value : null),
        pressure_atm:
          frozen.pressure_atm ?? (entry.source === "hitran" ? libraryPressureAtm.value : null),
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
      component_ids: hitranRows.map((entry) =>
        entry.source === "hitran_xsec"
          ? `${String(entry.component_id)}#${entry.selected_xsec_option ?? 0}`
          : String(entry.component_id),
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
  await importLibraryRows(
    Object.values(selectedLibraryRows).filter((entry) => selectedLibraryKeys.has(entry.key)),
  );
}

function onAddAllVisibleNistToBasket() {
  if (librarySource.value !== "nist") return;
  for (const entry of dedupeNistRowsByCompound(
    filteredLibrary.value.filter((entry) => entry.source === "nist"),
  )) {
    selectedLibraryKeys.add(entry.key);
    selectedLibraryRows[entry.key] = { ...entry, frozen_settings: freezeLibrarySettings(entry) };
  }
  if (selectedLibraryKeys.size > 0 && !libraryDatasetName.value.trim()) {
    libraryDatasetName.value = defaultLibraryDatasetName();
  }
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
  if (normalized === "multi-well" || normalized === "multi_well") return TAB_MULTI_WELL;
  if (normalized === "inspect" || normalized === "explore") return TAB_MY_DATASET;
  if (normalized === "my-dataset" || normalized === "my_dataset" || normalized === "dataset")
    return TAB_MY_DATASET;
  return null;
}

function syncGuidedExampleSession() {
  const mode = window.sessionStorage.getItem(DATA_ENTRY_MODE_KEY);
  const projectId = window.sessionStorage.getItem(DATA_ENTRY_PROJECT_KEY);
  isGuidedExampleSession.value =
    mode === "template-example" && projectId === String(projectStore.currentProjectId ?? "");
}

function pendingAnalysisStarterIntent(): AnalysisStarterDatasetIntent | null {
  const mode = window.sessionStorage.getItem(DATA_ENTRY_MODE_KEY);
  const projectId = window.sessionStorage.getItem(DATA_ENTRY_PROJECT_KEY);
  if (mode !== "analysis-starter" || projectId !== String(projectStore.currentProjectId ?? "")) {
    return null;
  }
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(DATA_ENTRY_DATASET_KEY) || "null");
    if (
      parsed?.schema_version !== "spectra-analysis-starter-dataset-intent/1" ||
      parsed.project_id !== projectStore.currentProjectId ||
      typeof parsed.dataset_id !== "string" ||
      typeof parsed.source !== "string" ||
      typeof parsed.name !== "string" ||
      typeof parsed.label !== "string" ||
      (parsed.imported_experiment_id != null &&
        (!Number.isInteger(parsed.imported_experiment_id) || parsed.imported_experiment_id <= 0))
    ) {
      return null;
    }
    return parsed as AnalysisStarterDatasetIntent;
  } catch {
    return null;
  }
}

function clearImportedAnalysisStarterMarker(intent: AnalysisStarterDatasetIntent): void {
  try {
    window.sessionStorage.setItem(
      DATA_ENTRY_DATASET_KEY,
      JSON.stringify({ ...intent, imported_experiment_id: null }),
    );
  } catch {
    // Session storage is an enhancement; a later route can still retry.
  }
}

function applyAnalysisStarterIntent(): boolean {
  const intent = pendingAnalysisStarterIntent();
  if (!intent) return false;

  const intentKey = `${intent.source}::${intent.name}`;
  const registeredSource = (dataStore.referenceCatalog?.registered ?? []).find(
    (dataset) => dsKey(dataset) === intentKey,
  );
  const packageId = registeredSource?.dataset_package?.package_id;
  const dataset =
    referenceByKey(intentKey) ??
    (packageId
      ? (userAcquiredReferenceDatasets.value.find((candidate) => candidate.name === packageId) ??
        null)
      : null);

  selectedRefDatasets.clear();
  if (!dataset) {
    previewRefKey.value = null;
    return true;
  }

  const key = dsKey(dataset);
  previewRefKey.value = key;
  if (registeredSource || dataset.source === "registered" || dataset.source === "eigenvector") {
    // Provider packages require the exact downloaded archive, so reveal the
    // verified-file action without sending them through the server catalog import.
    registeredCollapsed.value = false;
  } else {
    selectedRefDatasets.add(key);
    importDatasetName.value = intent.label;
  }
  return true;
}

function sortFilesNewestFirst(items: ExperimentFile[]): ExperimentFile[] {
  return [...items].sort(
    (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
  );
}

async function inspectExperimentFile(
  experimentId: number,
  fileId: number | null,
): Promise<boolean> {
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

  await showExperimentContents(experimentId);
  dataStore.activateFile(file.id, file.file_path);
  activeTab.value = TAB_MY_DATASET;
  persistActiveDataTab();
  return true;
}

async function inspectLatestProjectFile(): Promise<boolean> {
  if (
    projectStore.currentProjectId != null &&
    (!projectStore.currentProject ||
      projectStore.currentProject.id !== projectStore.currentProjectId)
  ) {
    await projectStore.fetchProject(projectStore.currentProjectId);
  }

  const experiments = [...(projectStore.currentProject?.experiments || [])].sort(
    (left, right) => right.id - left.id,
  );
  for (const experiment of experiments) {
    await dataStore.selectExperiment(experiment.id);
    const latestFile = sortFilesNewestFirst(dataStore.experimentFiles)[0];
    if (!latestFile) {
      continue;
    }

    await showExperimentContents(experiment.id);
    await onInspectFile(latestFile, { updateRoute: false });
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
  const requestedExperimentBelongsToProject =
    experimentId == null ||
    dataStore.experiments.some((experiment) => experiment.id === experimentId);

  if (!requestedExperimentBelongsToProject) {
    // A saved or copied deep link can outlive its project context. Keep the
    // project-scoped selection restored above instead of replacing it with an
    // experiment that the current project cannot admit.
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    return;
  }

  try {
    if (experimentId != null && fileId != null) {
      const inspected = await inspectExperimentFile(experimentId, fileId);
      if (inspected) {
        return;
      }
    }

    if (experimentId != null) {
      if (dataStore.activeExperimentId !== experimentId || !dataStore.fileInfo) {
        await dataStore.selectExperiment(experimentId);
        await showExperimentContents(experimentId);
      }
      const requestedViewId = queryNumber(route.query.viewId);
      if (requestedViewId != null) {
        await refreshDatasetViews(experimentId);
        const requestedView = datasetViews.value.find((view) => view.id === requestedViewId);
        if (requestedView) await showDatasetView(requestedView);
        else datasetViewError.value = "The requested named definition is unavailable in this dataset.";
      } else if (route.query.viewId === "default") {
        await showDefaultDatasetView();
      }
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
  const starterIntent = pendingAnalysisStarterIntent();
  if (starterIntent?.imported_experiment_id != null) {
    const importedExperiment = dataStore.experiments.find(
      (experiment) => experiment.id === starterIntent.imported_experiment_id,
    );
    if (importedExperiment) {
      activeTab.value = TAB_MY_DATASET;
      persistActiveDataTab();
      if (dataStore.activeExperimentId !== importedExperiment.id || !dataStore.fileInfo) {
        await dataStore.selectExperiment(importedExperiment.id);
        await showExperimentContents(importedExperiment.id);
      }
      return;
    }
    // A deleted dataset must not permanently suppress the starter import.
    clearImportedAnalysisStarterMarker(starterIntent);
  }
  if ((requestedTab === null || requestedTab === TAB_IMPORT) && applyAnalysisStarterIntent()) {
    activeTab.value = TAB_IMPORT;
    persistActiveDataTab();
    return;
  }
  if (requestedTab !== null) {
    activeTab.value = requestedTab;
    persistActiveDataTab();
    if (requestedTab === TAB_MY_DATASET) {
      await applyRouteExploreState();
    } else if (requestedTab === TAB_MULTI_WELL) {
      const experimentId = queryNumber(route.query.experimentId ?? route.query.experiment);
      if (
        experimentId != null &&
        dataStore.experiments.some((experiment) => experiment.id === experimentId)
      ) {
        await dataStore.selectExperiment(experimentId);
      }
    }
    return;
  }

  await applyRouteExploreState();
}

function onAnalysisChoice(choice: AnalysisChoice): void {
  analysisChoice.value = choice;
}

async function loadWorkflowDataSelectionContext(): Promise<void> {
  const workflowId = workflowContextId.value;
  const sourceNodeId = workflowSourceNodeId.value;
  if (workflowId === null || !sourceNodeId) return;
  workflowSelectionContextLoading.value = true;
  workflowSelectionContextError.value = null;
  try {
    const response = await api.get<WorkflowDataSelectionContext>(
      `/workflows/${workflowId}/data-selections/${encodeURIComponent(sourceNodeId)}`,
    );
    const context = response.data;
    workflowSelectionContext.value = context;
    const saved = context.saved_selection;
    activeTab.value = TAB_MY_DATASET;
    persistActiveDataTab();
    if (!saved) {
      workflowSelectionContextError.value = null;
      return;
    }
    if (!dataStore.experiments.some((experiment) => experiment.id === saved.experiment_id)) {
      throw new Error("The dataset saved on this sheet is no longer available in this project.");
    }
    if (dataStore.activeExperimentId !== saved.experiment_id) {
      await dataStore.selectExperiment(saved.experiment_id);
    }
    const selectedIds = saved.selected_file_ids;
    if (selectedIds === null) {
      setExperimentPlotSelection(saved.experiment_id, null);
    } else {
      const selectedIdSet = new Set(selectedIds);
      const selectedFiles = dataStore.experimentFiles
        .filter((file) => selectedIdSet.has(file.id))
        .map((file) => ({ id: file.id, file_path: file.file_path, stage: file.stage }));
      if (selectedFiles.length !== selectedIds.length) {
        throw new Error("One or more files saved on this sheet are no longer available.");
      }
      setExperimentPlotSelection(saved.experiment_id, selectedFiles);
    }
    inspectionAssetId.value = saved.asset_id;
    selectedDatasetView.value = null;
    if (saved.dataset_view_id != null) {
      try {
        selectedDatasetView.value = (await api.get<DatasetView>(
          `/experiments/${saved.experiment_id}/dataset-views/${saved.dataset_view_id}`,
        )).data;
      } catch (error) {
        if ((error as { response?: { status?: number } })?.response?.status !== 404) throw error;
        datasetViewError.value = "This sheet's saved definition was deleted. Its recorded source remains available; save a new definition to rebind it.";
      }
    }
    requestedAnalysisSelection.value = {
      target: saved.target_authority?.column ?? "",
      group: saved.group_column ?? "",
    };
    analysisChoice.value = {
      target: saved.target_authority?.column ?? "",
      targetType: saved.target_authority?.target_type ?? null,
      targetUnits: saved.target_authority?.units ?? null,
      sourceDigest: saved.target_authority?.source_digest ?? null,
      group: saved.group_column ?? "",
      readiness: null,
    };
    analysisSelectionHydrated.value = true;
    analysisSelectionStatus.value = "idle";
    await showExperimentContents(saved.experiment_id, null, saved.asset_id, true);
    await loadPlottedDatasets();
  } catch (error: unknown) {
    workflowSelectionContextError.value = getErrorMessage(
      error,
      "The workflow sheet data selection could not be loaded.",
    );
  } finally {
    workflowSelectionContextLoading.value = false;
  }
}

function returnToWorkflow(): void {
  const workflowId = workflowContextId.value;
  void router.push({
    path: "/workflow",
    query: {
      ...(projectStore.currentProjectId
        ? { project_id: String(projectStore.currentProjectId) }
        : {}),
      ...(workflowId ? { workflow_id: String(workflowId) } : {}),
    },
  });
}

async function applyWorkflowDataSelection(): Promise<void> {
  const context = workflowSelectionContext.value;
  const experimentId = dataStore.activeExperimentId;
  if (!context || experimentId === null) return;
  const experiment = dataStore.experiments.find((item) => item.id === experimentId);
  const selection = workflowSelectionForExperiment(experimentId);
  if (!experiment || selection === undefined) {
    workflowSelectionContextError.value = "Choose the files this workflow source should use.";
    return;
  }
  if (Array.isArray(selection) && new Set(selection.map((file) => file.stage)).size > 1) {
    workflowSelectionContextError.value = "Choose files from one processing stage.";
    return;
  }
  try {
    workflowSelectionApplying.value = true;
    workflowSelectionContextError.value = null;
    await showExperimentContents(experimentId, null, inspectionAssetId.value, selectedDatasetView.value !== null);
    const source = objectOrNull(dataStore.fileInfo?.metadata?.source_collection);
    const sourceManifest = stringOrEmpty(source?.source_manifest_sha256);
    const scientificCollection = stringOrEmpty(source?.scientific_collection_sha256);
    if (!sourceManifest || !scientificCollection) {
      throw new Error(
        "The selected data does not expose the governed scientific identity required for a workflow revision.",
      );
    }
    if (
      analysisChoice.value.target &&
      (!analysisChoice.value.targetType || !analysisChoice.value.sourceDigest)
    ) {
      throw new Error("The selected target authority is incomplete. Select the target again.");
    }
    const stage =
      Array.isArray(selection) && selection.length
        ? selection[0].stage
        : context.saved_selection?.experiment_id === experimentId
          ? context.saved_selection.stage
          : dataStore.experimentFiles.some((file) => file.stage === "raw")
            ? "raw"
            : "synthetic";
    const payloadSelection: WorkflowSourceSelection = {
      experiment_id: experimentId,
      dataset_name: experiment.name,
      stage,
      selected_file_ids: selection === null ? null : selection.map((file) => file.id),
      asset_id: inspectionAssetId.value,
      source_manifest_sha256: sourceManifest,
      collection_definition_sha256: stringOrEmpty(source?.collection_definition_sha256) || null,
      scientific_collection_sha256: scientificCollection,
      target_authority:
        analysisChoice.value.target &&
        analysisChoice.value.targetType &&
        analysisChoice.value.sourceDigest
          ? {
              schema_version: "spectrasherpa-target-authority/1",
              column: analysisChoice.value.target,
              target_type: analysisChoice.value.targetType,
              units: analysisChoice.value.targetUnits,
              source_digest: analysisChoice.value.sourceDigest,
            }
          : null,
      group_column: analysisChoice.value.group || null,
    };
    const exactView = selectedDatasetView.value;
    if (exactView &&
      exactView.selection.selected_file_ids?.join(",") === payloadSelection.selected_file_ids?.join(",") &&
      exactView.selection.stage === payloadSelection.stage &&
      exactView.selection.asset_id === payloadSelection.asset_id &&
      exactView.selection.source_manifest_sha256 === payloadSelection.source_manifest_sha256 &&
      exactView.selection.collection_definition_sha256 === payloadSelection.collection_definition_sha256 &&
      exactView.selection.scientific_collection_sha256 === payloadSelection.scientific_collection_sha256 &&
      JSON.stringify(exactView.selection.target_authority) === JSON.stringify(payloadSelection.target_authority) &&
      exactView.selection.group_column === payloadSelection.group_column) {
      payloadSelection.dataset_view_id = exactView.id;
      payloadSelection.dataset_view_sha256 = exactView.selection_sha256;
    }
    const idempotencyKey =
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `data-page-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const response = await api.put<WorkflowDataSelectionRevision>(
      `/workflows/${context.workflow_id}/data-selections/${encodeURIComponent(context.source_node_id)}`,
      {
        expected_revision: context.current_revision?.revision_number ?? null,
        idempotency_key: idempotencyKey,
        origin: "data_page",
        reason: workflowSelectionReason.value.trim() || null,
        selection: payloadSelection,
      },
    );
    workflowSelectionContext.value = {
      ...context,
      current_revision: response.data,
      saved_selection: response.data.selection,
    };
    toast.add({
      severity: "success",
      summary: "Sheet data selection applied",
      detail: `Revision ${response.data.revision_number} is now bound to ${context.source_node_label}.`,
      life: 3500,
    });
    returnToWorkflow();
  } catch (error: unknown) {
    workflowSelectionContextError.value = getErrorMessage(
      error,
      "The data selection could not be applied to this sheet.",
    );
    if ((error as { response?: { status?: number } })?.response?.status === 409) {
      await loadWorkflowDataSelectionContext();
    }
  } finally {
    workflowSelectionApplying.value = false;
  }
}

async function onAnalysisSelectionCommit(choice: AnalysisChoice): Promise<void> {
  analysisChoice.value = choice;
  requestedAnalysisSelection.value = { target: choice.target, group: choice.group };
  if (workflowSelectionContextRequested.value) {
    analysisSelectionStatus.value = "idle";
    return;
  }
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null || !analysisSelectionHydrated.value) return;
  const request = ++analysisSelectionRequest;
  analysisSelectionStatus.value = "saving";
  try {
    const response = await api.put(`/experiments/${experimentId}/analysis-selection`, {
      selected_target: choice.target || null,
      target_type: choice.target ? choice.targetType : null,
      group_column: choice.target && choice.group ? choice.group : null,
      source_digest: choice.sourceDigest,
    });
    if (request !== analysisSelectionRequest || dataStore.activeExperimentId !== experimentId)
      return;
    activeExperimentMetadata.value = {
      ...(activeExperimentMetadata.value ?? {}),
      analysis_selection: response.data,
    };
    analysisSelectionStatus.value = "saved";
  } catch (error: unknown) {
    if (request !== analysisSelectionRequest || dataStore.activeExperimentId !== experimentId)
      return;
    analysisSelectionStatus.value = "error";
    toast.add({
      severity: "error",
      summary: "Selection not saved",
      detail: getErrorMessage(error, "Target and groups could not be saved with this dataset."),
      life: 6000,
    });
  }
}

function workflowExperimentIds(): number[] {
  return dataStore.activeExperimentId == null ? [] : [dataStore.activeExperimentId];
}

function workflowSelectionForExperiment(experimentId: number): PlotFileSelection {
  if (Object.prototype.hasOwnProperty.call(plotFileSelections.value, experimentId)) {
    return plotFileSelections.value[experimentId];
  }
  if (experimentId !== dataStore.activeExperimentId || dataStore.experimentFiles.length === 0) {
    return null;
  }
  const preferredStage =
    ["raw", "preprocessed", "synthetic"].find((stage) =>
      dataStore.experimentFiles.some((file) => file.stage === stage),
    ) ?? "raw";
  const stageFiles = dataStore.experimentFiles.filter((file) => file.stage === preferredStage);
  if (stageFiles.length === 0) return null;
  if (
    preferredStage === "raw" &&
    selectedExperiment.value &&
    stageFiles.length === selectedExperiment.value.file_count &&
    new Set(stageFiles.map((file) => file.stage)).size === 1
  ) {
    return null;
  }
  return stageFiles.map(({ id, file_path, stage }) => ({ id, file_path, stage }));
}

async function goToWorkflow(addNode?: string) {
  const experimentId = dataStore.activeExperimentId;
  const selection = experimentId == null ? null : plotFileSelections.value[experimentId];
  let handoffReadiness = analysisChoice.value.readiness;
  // Local row filters are display state, never a substitute for a server-issued
  // scientific binding. Resolve that binding once, at the Workflow boundary.
  if (
    experimentId != null &&
    (analysisChoice.value.target ||
      (residentDatasets.has(experimentId) && Array.isArray(selection)))
  ) {
    const workflowSelection = workflowSelectionForExperiment(experimentId);
    const requestedTarget = analysisChoice.value.target;
    const requestedAsset = inspectionAssetId.value;
    try {
      await dataStore.inspectExperimentRawFiles(
        experimentId,
        inspectionAssetId.value,
        workflowSelection?.map((file) => file.id),
      );
      await nextTick();
      if (
        dataStore.activeExperimentId !== experimentId ||
        plotFileSelections.value[experimentId] !== selection ||
        analysisChoice.value.target !== requestedTarget ||
        inspectionAssetId.value !== requestedAsset
      ) {
        toast.add({
          severity: "info",
          summary: "Selection changed",
          detail: "Review the current selection before opening Workflow.",
          life: 4000,
        });
        return;
      }
      const inspected = dataStore.fileInfo;
      const choice = { ...analysisChoice.value };
      const base = inspected?.analysis_readiness;
      if (choice.target && !base?.profile) {
        throw new Error("The selected dataset has no current analysis readiness.");
      }
      if (inspected && base?.profile) {
        const profile = {
          ...base.profile,
          target_type: choice.target ? choice.targetType : null,
          target_fields: choice.target ? [choice.target] : [],
        };
        // Reinspection starts the panel's asynchronous compatibility preview.
        // Share that read and await it before snapshotting the workflow receipt.
        handoffReadiness = await retainedInspection(
          inspected,
          `readiness:${JSON.stringify(profile)}`,
          async () =>
            (
              await api.post<DatasetAnalysisReadiness>(
                "/workflow-templates/compatibility-preview",
                {
                  analysis_profile: profile,
                },
              )
            ).data,
        );
        await nextTick();
        if (
          dataStore.activeExperimentId !== experimentId ||
          dataStore.fileInfo !== inspected ||
          plotFileSelections.value[experimentId] !== selection ||
          inspectionAssetId.value !== requestedAsset ||
          analysisChoice.value.target !== choice.target ||
          analysisChoice.value.targetType !== choice.targetType ||
          analysisChoice.value.group !== choice.group
        ) {
          throw new Error(
            "Selection changed. Review the current selection before opening Workflow.",
          );
        }
      }
    } catch (error) {
      toast.add({
        severity: "error",
        summary: "Selection could not be prepared",
        detail: getErrorMessage(error, "Could not bind the selected data."),
        life: 6000,
      });
      return;
    }
  }
  if (
    analysisChoice.value.target &&
    (!analysisChoice.value.targetType || !analysisChoice.value.sourceDigest)
  ) {
    toast.add({
      severity: "error",
      summary: "Target authority is incomplete",
      detail:
        "Re-open Analysis readiness and select the response again after the dataset identity finishes loading.",
      life: 6000,
    });
    return;
  }
  const workflowIds = workflowExperimentIds();
  const mixedStageDataset = workflowIds.find((experimentId) => {
    const selection = workflowSelectionForExperiment(experimentId);
    return Array.isArray(selection) && new Set(selection.map((file) => file.stage)).size > 1;
  });
  if (mixedStageDataset != null) {
    const name =
      dataStore.experiments.find((item) => item.id === mixedStageDataset)?.name ??
      `Dataset ${mixedStageDataset}`;
    toast.add({
      severity: "warn",
      summary: "Choose one processing stage",
      detail: `${name} contains selected files from more than one stage. Select raw, preprocessed, or synthetic files for one workflow source.`,
      life: 6000,
    });
    return;
  }
  const datasets: DataSelectionReceipt["datasets"] = workflowIds.map((experimentId) => {
    const experiment = dataStore.experiments.find((item) => item.id === experimentId);
    const selection = workflowSelectionForExperiment(experimentId);
    return {
      experiment_id: experimentId,
      dataset_name: experiment?.name ?? `Dataset ${experimentId}`,
      selection: selection === null ? "all" : "subset",
      selected_file_count: selection === null ? (experiment?.file_count ?? 0) : selection.length,
      file_ids: selection === null ? null : selection.map((file) => file.id),
      file_paths: selection === null ? null : selection.map((file) => file.file_path),
      asset_id: experimentId === dataStore.activeExperimentId ? inspectionAssetId.value : null,
      stage: selection === null ? "raw" : selection[0].stage,
    };
  });
  const receiptId = createDataSelectionReceiptId();
  try {
    persistDataDraftNow();
    if (datasets.length) {
      storeDataSelectionReceipt(
        {
          schema_version: "spectra-my-dataset-workflow-selection/3",
          receipt_id: receiptId,
          project_id: projectStore.currentProjectId,
          datasets,
          target_authority:
            analysisChoice.value.target &&
            analysisChoice.value.targetType &&
            analysisChoice.value.sourceDigest
              ? {
                  schema_version: "spectrasherpa-target-authority/1",
                  column: analysisChoice.value.target,
                  target_type: analysisChoice.value.targetType,
                  units: analysisChoice.value.targetUnits,
                  source_digest: analysisChoice.value.sourceDigest,
                }
              : null,
          group: analysisChoice.value.group || null,
          analysis_readiness: handoffReadiness,
          analysis_readiness_experiment_id: dataStore.activeExperimentId,
        },
      );
    }
  } catch {
    toast.add({
      severity: "error",
      summary: "Selection could not be carried to Workflow",
      detail:
        "Browser storage is unavailable. Keep this page open and try again after allowing site storage.",
      life: 6000,
    });
    return;
  }
  router.push({
    path: "/workflow",
    query: datasets.length
      ? {
          fromDataSelection: "1",
          selection: receiptId,
          ...(projectStore.currentProjectId ? { project_id: projectStore.currentProjectId } : {}),
          ...(addNode ? { addNode } : {}),
        }
      : addNode
        ? {
            addNode,
            ...(projectStore.currentProjectId ? { project_id: projectStore.currentProjectId } : {}),
          }
        : projectStore.currentProjectId
          ? { project_id: projectStore.currentProjectId }
          : {},
  });
}

// --- Lifecycle ---

onMounted(async () => {
  await projectStore.ensureProjectForBrowserTab();
  currentDataDraftStorageKey = dataDraftStorageKey();
  restoreActiveDataTab();
  restoreDataDraft(currentDataDraftStorageKey);
  const catalogsReady = Promise.allSettled([
    fetchQuota(),
    dataStore.fetchReferenceCatalog(),
    ...(qualified.value ? [] : [dataStore.fetchCatalog()]),
    workflowStore.fetchCompatibilityMatrix(),
  ]);
  await dataStore.fetchExperiments();
  if (pendingAnalysisStarterIntent()) await catalogsReady;
  await dataStore.restoreActiveExperimentForCurrentProject();
  syncGuidedExampleSession();
  await applyRouteDataState();
  // New Analysis carries a reference choice, rather than merely suggesting
  // one. Admit bundled/catalog sources automatically. Provider packages stay
  // manual because they require the exact user-acquired archive.
  if (pendingAnalysisStarterIntent() && selectedRefDatasets.size > 0) {
    await onImportSelectedDatasets();
  }
  if (workflowSelectionContextRequested.value) {
    await loadWorkflowDataSelectionContext();
  }

  const requestedTab = routeTabIndex(route.query.tab);
  const sourceTabRequested =
    (requestedTab != null && requestedTab !== TAB_MY_DATASET) ||
    pendingAnalysisStarterIntent() != null;

  // Restore My Dataset when the Pinia store still has an active contents
  // exploration (i.e. the user left the Data page after inspecting a
  // reference or file). Route-driven state takes precedence.
  if (
    !sourceTabRequested &&
    [TAB_IMPORT, TAB_SYNTHESIS].includes(activeTab.value) &&
    (dataStore.catalogDatasetInfo !== null || dataStore.fileInfo !== null)
  ) {
    activeTab.value = TAB_MY_DATASET;
  }

  if (!sourceTabRequested) {
    const resident =
      dataStore.activeExperimentId == null
        ? null
        : residentDatasets.get(dataStore.activeExperimentId);
    if (resident && dataStore.fileInfo !== resident) {
      restoreResidentInspection(resident);
    }
    await ensureInitialContentsSelection();
  }
  if (plottedExperimentIds.value.length) {
    await loadPlottedDatasets();
  }
  if (!qualified.value && isHitranLibrarySource(librarySource.value)) {
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
  if (qualified.value && [TAB_SYNTHESIS, TAB_LIBRARY].includes(tabIndex)) {
    activeTab.value = TAB_MY_DATASET;
    return;
  }
  if (isGuidedExampleSession.value && tabIndex !== TAB_MY_DATASET) {
    activeTab.value = TAB_MY_DATASET;
  }
});

let dataTabSelectionGeneration = 0;
function onDataTabSelected(tabIndex: number) {
  dataTabSelectionGeneration += 1;
  if (tabIndex === TAB_MY_DATASET) void ensureInitialContentsSelection();
}

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
  },
);

watch(
  () => [
    route.query.tab,
    route.query.experimentId,
    route.query.experiment,
    route.query.fileId,
    route.query.viewId,
    route.query.focus,
    route.query.fromTemplate,
  ],
  () => {
    void applyRouteDataState();
  },
);

async function retryExperiments() {
  await dataStore.fetchExperiments();
  if (!dataStore.experimentsError) await ensureInitialContentsSelection();
}

async function refresh() {
  residentDatasets.clear();
  fileAssetInventoryCache.clear();
  clearRetainedInspection(dataStore.fileInfo);
  await Promise.all([
    dataStore.fetchCatalog(),
    dataStore.fetchExperiments(),
    dataStore.fetchReferenceCatalog(),
  ]);
  if (dataStore.activeExperimentId) {
    await dataStore.selectExperiment(dataStore.activeExperimentId);
  }
  await loadPlottedDatasets();
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
  const request = ++analysisSelectionRequest;
  activeExperimentMetadata.value = null;
  analysisSelectionHydrated.value = false;
  requestedAnalysisSelection.value = { target: "", group: "" };
  analysisSelectionStatus.value = "loading";
  analysisChoice.value = {
    target: "",
    targetType: null,
    targetUnits: null,
    sourceDigest: null,
    group: "",
    readiness: null,
  };
  if (experimentId == null) {
    analysisSelectionHydrated.value = true;
    analysisSelectionStatus.value = "idle";
    return;
  }
  const sheetSelection = workflowSelectionContext.value?.saved_selection;
  if (sheetSelection?.experiment_id === experimentId) {
    analysisChoice.value = {
      target: sheetSelection.target_authority?.column ?? "",
      targetType: sheetSelection.target_authority?.target_type ?? null,
      targetUnits: sheetSelection.target_authority?.units ?? null,
      sourceDigest: sheetSelection.target_authority?.source_digest ?? null,
      group: sheetSelection.group_column ?? "",
      readiness: null,
    };
    requestedAnalysisSelection.value = {
      target: analysisChoice.value.target,
      group: analysisChoice.value.group,
    };
    analysisSelectionHydrated.value = true;
    analysisSelectionStatus.value = "idle";
    return;
  }
  try {
    const response = await api.get(`/experiments/${experimentId}`);
    if (request !== analysisSelectionRequest || dataStore.activeExperimentId !== experimentId)
      return;
    activeExperimentMetadata.value = objectOrNull(response.data?.metadata) ?? {};
    const saved = objectOrNull(activeExperimentMetadata.value.analysis_selection);
    const target = stringOrEmpty(saved?.selected_target);
    const targetType =
      saved?.target_type === "categorical" || saved?.target_type === "continuous"
        ? saved.target_type
        : null;
    analysisChoice.value = {
      target: target && targetType ? target : "",
      targetType: target && targetType ? targetType : null,
      targetUnits: null,
      sourceDigest: stringOrEmpty(saved?.source_digest) || null,
      group: target && targetType ? stringOrEmpty(saved?.group_column) : "",
      readiness: null,
    };
    requestedAnalysisSelection.value = {
      target: analysisChoice.value.target,
      group: analysisChoice.value.group,
    };
    analysisSelectionStatus.value = saved ? "saved" : "idle";
  } catch {
    if (request !== analysisSelectionRequest || dataStore.activeExperimentId !== experimentId)
      return;
    activeExperimentMetadata.value = null;
    analysisSelectionStatus.value = "error";
  } finally {
    if (request === analysisSelectionRequest && dataStore.activeExperimentId === experimentId) {
      analysisSelectionHydrated.value = true;
    }
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

function hasExperimentPlotSelection(experimentId: number): boolean {
  return Object.prototype.hasOwnProperty.call(plotFileSelections.value, experimentId);
}

function isExperimentFullyPlotted(experimentId: number): boolean {
  return (
    hasExperimentPlotSelection(experimentId) && plotFileSelections.value[experimentId] === null
  );
}

function isExperimentPartlyPlotted(experimentId: number): boolean {
  const selection = plotFileSelections.value[experimentId];
  return Array.isArray(selection) && selection.length > 0;
}

function isFilePlotted(file: ExperimentFile): boolean {
  if (dataStore.activeExperimentId == null) return false;
  const selection = plotFileSelections.value[dataStore.activeExperimentId];
  return selection === null || Boolean(selection?.some((candidate) => candidate.id === file.id));
}

function setExperimentPlotSelection(
  experimentId: number,
  selection: PlotFileSelection | undefined,
): void {
  const next = { ...plotFileSelections.value };
  if (selection === undefined || (Array.isArray(selection) && selection.length === 0)) {
    delete next[experimentId];
  } else {
    next[experimentId] = selection;
  }
  plotFileSelections.value = next;
}

async function loadPlottedDatasets(
  prefetched = new Map<number, SherpaDatasetDict>(),
): Promise<void> {
  const request = ++plotDatasetRequest;
  plotDatasetsError.value = null;
  if (plottedExperimentIds.value.length === 0) {
    plotDatasetSources.value = [];
    plotDatasetsLoading.value = false;
    return;
  }
  const selected = plottedExperimentIds.value
    .map((id) => dataStore.experiments.find((experiment) => experiment.id === id))
    .filter((experiment): experiment is ExperimentSummary => Boolean(experiment));
  if (selected.length !== plottedExperimentIds.value.length) {
    plotFileSelections.value = Object.fromEntries(
      selected.map((experiment) => [experiment.id, plotFileSelections.value[experiment.id]]),
    );
  }
  plotDatasetsLoading.value = true;
  const retainedDataset = dataStore.fileInfo;
  const readProjection = (experiment: ExperimentSummary, fileIds?: number[]) => {
    const resident = residentDatasets.get(experiment.id);
    const selection = plotFileSelections.value[experiment.id];
    const assetId = experiment.id === dataStore.activeExperimentId ? inspectionAssetId.value : null;
    if (
      !assetId &&
      resident &&
      (selection === null ||
        (Array.isArray(selection) &&
          selectedDatasetRows(
            resident,
            selection.map((file) => file.file_path),
          ) !== null))
    ) {
      return Promise.resolve(resident);
    }
    const read = async () =>
      prefetched.get(experiment.id) ??
      (
        await api.post<SherpaDatasetDict>("/builder/file-info", {
          experiment_id: experiment.id,
          ...(fileIds ? { file_ids: fileIds } : {}),
          ...(assetId ? { asset_id: assetId } : {}),
        })
      ).data;
    const key = JSON.stringify([
      "plot",
      authStore.user?.id,
      projectStore.currentProjectId,
      experiment,
      fileIds ?? null,
      assetId,
    ]);
    return retainedDataset ? retainedInspection(retainedDataset, key, read) : read();
  };
  const settled = await Promise.allSettled(
    selected.map(async (experiment): Promise<DatasetPlotSource> => {
      const selection = plotFileSelections.value[experiment.id];
      if (selection === null) {
        const dataset = await readProjection(experiment);
        cacheFileSampleLabels(experiment.id, dataset);
        return {
          experimentId: experiment.id,
          name: experiment.name,
          members: [
            {
              fileId: null,
              fileName: `All ${experiment.file_count} files`,
              dataset,
            },
          ],
          selectedFileCount: experiment.file_count,
          totalFileCount: experiment.file_count,
        };
      }
      const dataset = await readProjection(
        experiment,
        selection.map((file) => file.id),
      );
      cacheFileSampleLabels(experiment.id, dataset);
      return {
        experimentId: experiment.id,
        name: experiment.name,
        ...(residentDatasets.get(experiment.id) === dataset
          ? { selectedFileNames: selection.map((file) => file.file_path) }
          : {}),
        members: [
          {
            fileId: selection.length === 1 ? selection[0].id : null,
            fileName:
              selection.length === 1
                ? extractFileName(selection[0].file_path)
                : `${selection.length} selected files`,
            dataset,
          },
        ],
        selectedFileCount: selection.length,
        totalFileCount: experiment.file_count,
      };
    }),
  );
  if (request !== plotDatasetRequest) return;
  const admitted: DatasetPlotSource[] = [];
  const refusals: string[] = [];
  const supersededExperimentIds: number[] = [];
  settled.forEach((result, index) => {
    if (result.status === "fulfilled") {
      admitted.push(result.value);
    } else {
      if (getErrorCode(result.reason) === "trial_dataset_authority_superseded") {
        supersededExperimentIds.push(selected[index].id);
      }
      refusals.push(
        `${selected[index].name}: ${getErrorMessage(
          result.reason,
          "the packaged dataset could not be inspected",
        )}`,
      );
    }
  });
  if (supersededExperimentIds.length) {
    const next = { ...plotFileSelections.value };
    for (const experimentId of supersededExperimentIds) delete next[experimentId];
    plotFileSelections.value = next;
    toast.add({
      severity: "warn",
      summary: "Outdated dataset removed from plot",
      detail:
        "Its registered scientific authority changed. Remove that packaged dataset and import the reviewed provider file again.",
      life: 6000,
    });
  }
  plotDatasetSources.value = admitted;
  plotDatasetsError.value = refusals.length ? `Plot refused: ${refusals.join("; ")}` : null;
  plotDatasetsLoading.value = false;
}

async function onPlotExperimentToggle(
  experiment: ExperimentSummary,
  checked: boolean,
): Promise<void> {
  if (checked) {
    if (
      !hasExperimentPlotSelection(experiment.id) &&
      plottedExperimentIds.value.length >= MAX_PLOTTED_DATASETS
    ) {
      toast.add({
        severity: "warn",
        summary: "Dataset overlay limit reached",
        detail: `Plot at most ${MAX_PLOTTED_DATASETS} packaged datasets at once.`,
        life: 4500,
      });
      return;
    }
    setExperimentPlotSelection(experiment.id, null);
    if (dataStore.activeExperimentId == null) {
      // The first explicit preview also establishes inspection focus. Subsequent
      // comparison previews must not replace the active dataset or its metadata.
      await onExperimentSelect(experiment, { preserveComparisons: true });
      return;
    }
    const resident = residentDatasets.get(experiment.id);
    if (
      resident &&
      dataStore.activeExperimentId === experiment.id &&
      dataStore.fileInfo !== resident
    ) {
      restoreResidentInspection(resident);
    }
  } else {
    setExperimentPlotSelection(experiment.id, undefined);
  }
  await loadPlottedDatasets();
}

async function onActiveExperimentPlotToggle(checked: boolean): Promise<void> {
  if (!selectedExperiment.value) return;
  await onPlotExperimentToggle(selectedExperiment.value, checked);
}

async function onPlotFileToggle(file: ExperimentFile, checked: boolean): Promise<void> {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null) return;
  if (
    !hasExperimentPlotSelection(experimentId) &&
    plottedExperimentIds.value.length >= MAX_PLOTTED_DATASETS
  ) {
    toast.add({
      severity: "warn",
      summary: "Dataset overlay limit reached",
      detail: `Plot at most ${MAX_PLOTTED_DATASETS} packaged datasets at once.`,
      life: 4500,
    });
    return;
  }
  const allFiles = dataStore.experimentFiles.map(({ id, file_path, stage }) => ({
    id,
    file_path,
    stage,
  }));
  const current = plotFileSelections.value[experimentId];
  const activeFocus =
    dataStore.activeFileId != null && dataStore.activeFilePath
      ? { id: dataStore.activeFileId, file_path: dataStore.activeFilePath }
      : null;
  let selected = current === null ? allFiles : [...(current ?? [])];
  if (checked && !selected.some((candidate) => candidate.id === file.id)) {
    selected.push({ id: file.id, file_path: file.file_path, stage: file.stage });
  } else if (!checked) {
    selected = selected.filter((candidate) => candidate.id !== file.id);
  }
  setExperimentPlotSelection(
    experimentId,
    selected.length === allFiles.length && new Set(allFiles.map((item) => item.stage)).size === 1
      ? null
      : selected.length
        ? selected
        : undefined,
  );
  if (selected.length === 0) {
    contentsInspectionRequest += 1;
    inspectionWarnings.value = [];
    inspectionAssets.value = [];
    inspectionAssetId.value = null;
    pendingInspection.value = null;
    dataStore.clearInspection();
    await loadPlottedDatasets();
    return;
  }
  const selectedPackageViews = selected
    .map((candidate) => registeredPackageView(candidate.file_path))
    .filter((value): value is string => value !== null);
  if (checked && new Set(selectedPackageViews).size > 1) {
    const heterogeneousMetalViews = selectedPackageViews.some((label) =>
      ["Machine sensors", "Optical emission spectra", "RF-monitor variables"].includes(label),
    );
    toast.add({
      severity: "warn",
      summary: "Multiple reference views selected",
      detail: heterogeneousMetalViews
        ? "Metal Etch views use different feature spaces. Inspect them together as one package, but select one compatible view for an ordinary workflow; cross-view fusion is not inferred."
        : "These views may represent different instruments or scientific cohorts. Confirm their roles before modeling; use one view for ordinary calibration or an explicit transfer/application workflow across views.",
      life: 6500,
    });
  }
  const resident = residentDatasets.get(experimentId);
  if (
    resident &&
    selectedDatasetRows(
      resident,
      selected.map((file) => file.file_path),
    ) !== null
  ) {
    if (dataStore.fileInfo !== resident) {
      restoreResidentInspection(resident);
    }
    await loadPlottedDatasets();
  } else {
    await showExperimentContents(experimentId);
  }
  if (activeFocus && selected.some((candidate) => candidate.id === activeFocus.id)) {
    dataStore.activateFile(activeFocus.id, activeFocus.file_path);
  }
}

async function useOnlyDataView(file: ExperimentFile): Promise<void> {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null) return;
  setExperimentPlotSelection(experimentId, [
    { id: file.id, file_path: file.file_path, stage: file.stage },
  ]);
  await showExperimentContents(experimentId);
  dataStore.activateFile(file.id, file.file_path);
}

async function onPlotAllExperiments(checked: boolean): Promise<void> {
  if (!checked) {
    plotFileSelections.value = {};
    await loadPlottedDatasets();
    return;
  }
  plotFileSelections.value = Object.fromEntries(
    dataStore.experiments.slice(0, MAX_PLOTTED_DATASETS).map((experiment) => [experiment.id, null]),
  );
  if (dataStore.experiments.length > MAX_PLOTTED_DATASETS) {
    toast.add({
      severity: "warn",
      summary: "Dataset overlay bounded",
      detail: `Selected the first ${MAX_PLOTTED_DATASETS} packaged datasets.`,
      life: 4500,
    });
  }
  if (dataStore.activeExperimentId == null && dataStore.experiments.length) {
    await onExperimentSelect(dataStore.experiments[0], { preserveComparisons: true });
    // Inspection can be refused before it reaches the shared plot loader. That
    // must not suppress other valid datasets in the explicit comparison.
    if (dataStore.experimentFilesRefusal) {
      setExperimentPlotSelection(dataStore.experiments[0].id, undefined);
      await loadPlottedDatasets();
    } else if (!dataStore.fileInfo) {
      await loadPlottedDatasets();
    }
    return;
  }
  await loadPlottedDatasets();
}

async function showExperimentContents(experimentId: number, preferredFileId: number | null = null, preferredAssetId: string | null = null, exactSelection = false) {
  exactInspectionSelection.value = exactSelection;
  const request = ++contentsInspectionRequest;
  dataStore.clearCatalogExploration();
  inspectionWarnings.value = [];
  try {
    const plottedSelection = plotFileSelections.value[experimentId];
    const selectedStage = preferredFileId != null
      ? dataStore.experimentFiles.find((file) => file.id === preferredFileId)?.stage
      : Array.isArray(plottedSelection) && plottedSelection.length
        ? plottedSelection[0].stage
        : dataStore.experimentFiles.some((file) => file.stage === "raw") ? "raw" : "synthetic";
    const sourceFiles = dataStore.experimentFiles.filter((file) => file.stage === selectedStage);
    const explicitViewSelection =
      preferredFileId != null || (Array.isArray(plottedSelection) && plottedSelection.length > 0);
    const selectedViewIds =
      preferredFileId != null
        ? [preferredFileId]
        : Array.isArray(plottedSelection) && plottedSelection.length
          ? plottedSelection.map((selection) => selection.id)
          : sourceFiles.map((file) => file.id);
    const selectedViewId =
      explicitViewSelection && selectedViewIds.length === 1 ? selectedViewIds[0] : null;
    const selectedViewIdSet = new Set(selectedViewIds);
    const inspectionFiles = sourceFiles.filter((file) => selectedViewIdSet.has(file.id));
    const registeredPackageSelection = inspectionFiles.some(
      (file) => registeredPackageView(file.file_path) !== null,
    );
    const loadWholeCollection =
      preferredFileId == null && !exactSelection && !registeredPackageSelection && sourceFiles.length > 1;
    const inventories = await Promise.all(
      (loadWholeCollection ? sourceFiles : inspectionFiles).map((file) => {
        const cacheKey = `${experimentId}:${file.id}`;
        const cached = fileAssetInventoryCache.get(cacheKey);
        if (cached) return cached;
        const pending = dataStore.fetchFileAssets(experimentId, file.id).catch((error) => {
          fileAssetInventoryCache.delete(cacheKey);
          throw error;
        });
        fileAssetInventoryCache.set(cacheKey, pending);
        return pending;
      }),
    );
    if (request !== contentsInspectionRequest) return;
    inspectionWarnings.value = uniqueAssetWarnings(
      inventories.flatMap((inventory) => inventory.assets),
    );
    if (inventories.some((inventory) => inventory.assets.length > 1)) {
      const commonIds = inventories.reduce<Set<string>>((common, inventory, index) => {
        const ids = new Set(inventory.assets.map((asset) => asset.asset_id));
        return index === 0 ? ids : new Set([...common].filter((assetId) => ids.has(assetId)));
      }, new Set<string>());
      inspectionAssets.value = (inventories[0]?.assets ?? []).filter((asset) =>
        commonIds.has(asset.asset_id),
      );
      inspectionAssetId.value = preferredAssetId;
      pendingInspection.value = { kind: "experiment", experimentId };
      dataStore.clearInspection();
      if (!inspectionAssets.value.length) {
        throw new Error(
          "Files in this dataset do not share a selectable scientific result identity.",
        );
      }
      if (preferredAssetId) {
        await onInspectionAssetChange();
        if (dataStore.fileInfo) await loadPlottedDatasets(new Map([[experimentId, dataStore.fileInfo]]));
      }
      return;
    }
    inspectionAssets.value = inventories[0]?.assets ?? [];
    inspectionAssetId.value = preferredAssetId;
    pendingInspection.value = null;
    let inspectedDataset: SherpaDatasetDict;
    if (
      !loadWholeCollection &&
      !registeredPackageSelection &&
      (selectedViewId != null || inspectionFiles.length === 1)
    ) {
      const preferred = inspectionFiles[0];
      if (!preferred) throw new Error("The initial data view is outside this dataset.");
      inspectedDataset = await dataStore.inspectFile(
        preferred.id,
        preferred.file_path,
        experimentId,
        ...(preferredAssetId ? [preferredAssetId] : []),
      );
    } else {
      inspectedDataset = await dataStore.inspectExperimentRawFiles(
        experimentId,
        preferredAssetId,
        !loadWholeCollection && (explicitViewSelection || registeredPackageSelection)
          ? selectedViewIds
          : null,
      );
    }
    if (request !== contentsInspectionRequest) return;
    if (
      loadWholeCollection &&
      explicitViewSelection &&
      inspectedDataset &&
      selectedDatasetRows(
        inspectedDataset,
        inspectionFiles.map((file) => file.file_path),
      ) === null
    ) {
      // Incomplete previews and ambiguous row provenance cannot be filtered
      // locally. Keep the exact server projection for these exceptional views.
      inspectedDataset = await dataStore.inspectExperimentRawFiles(
        experimentId,
        preferredAssetId,
        selectedViewIds,
      );
      if (request !== contentsInspectionRequest) return;
    }
    if (
      (loadWholeCollection || !explicitViewSelection) &&
      !registeredPackageSelection &&
      inspectedDataset?.data?.length === inspectedDataset?.n_samples &&
      inspectedDataset &&
      (!explicitViewSelection ||
        selectedDatasetRows(
          inspectedDataset,
          sourceFiles.map((file) => file.file_path),
        ) !== null)
    ) {
      residentDatasets.set(experimentId, inspectedDataset);
      if (residentDatasets.size > MAX_PLOTTED_DATASETS) {
        residentDatasets.delete(residentDatasets.keys().next().value!);
      }
    }
    cacheFileSampleLabels(experimentId, inspectedDataset);
    await loadPlottedDatasets(new Map([[experimentId, inspectedDataset]]));
  } catch {
    if (request !== contentsInspectionRequest) return;
    inspectionWarnings.value = [];
    toast.add({
      severity: "error",
      summary: "Scientific results unavailable",
      detail:
        dataStore.fileInfoError || "Could not inspect the scientific results in this dataset.",
      life: 6000,
    });
  }
}

async function onCollectionDefinitionChanged(receipt: CollectionDefinitionReceipt): Promise<void> {
  residentDatasets.delete(receipt.experiment_id);
  if (dataStore.activeExperimentId !== receipt.experiment_id) return;
  const attached = receipt.status === "attached";
  const refused = receipt.status === "stale" || receipt.status === "invalid";
  toast.add({
    severity: attached ? "success" : refused ? "error" : "info",
    summary: attached
      ? "Collection definition attached"
      : refused
        ? "Collection definition needs attention"
        : "Collection definition removed",
    detail: receipt.message,
    life: 4500,
  });
  dataStore.clearInspection();
  await showExperimentContents(receipt.experiment_id);
}

let initialContentsSelectionPending: number | null = null;
async function ensureInitialContentsSelection() {
  if (
    initialContentsSelectionPending === dataStore.activeExperimentId ||
    dataStore.fileInfo ||
    dataStore.catalogDatasetInfo ||
    dataStore.experimentFilesLoading ||
    dataStore.experimentFilesRefusal ||
    !dataStore.activeExperimentId
  ) {
    return;
  }
  const hasSingleDataset = dataStore.experiments.length === 1;
  const hasSingleFile = dataStore.experimentFiles.length === 1;
  if (activeTab.value !== TAB_MY_DATASET && !(hasSingleDataset && hasSingleFile)) return;

  const experimentId = dataStore.activeExperimentId;
  const initialTab = activeTab.value;
  const tabGeneration = dataTabSelectionGeneration;
  initialContentsSelectionPending = experimentId;
  try {
    await showExperimentContents(experimentId);
    if (dataStore.activeExperimentId !== experimentId) return;
    if (
      hasSingleDataset && hasSingleFile &&
      activeTab.value === initialTab && dataTabSelectionGeneration === tabGeneration
    ) {
      const file = dataStore.experimentFiles[0];
      dataStore.activateFile(file.id, file.file_path);
      activeTab.value = TAB_MY_DATASET;
      persistActiveDataTab();
    }
  } finally {
    if (initialContentsSelectionPending === experimentId) initialContentsSelectionPending = null;
  }
}

// --- Experiment CRUD ---

async function onExperimentSelect(
  exp: ExperimentSummary | null,
  options: { preserveComparisons?: boolean } = {},
) {
  if (!exp) return;
  if (dataStore.activeExperimentId !== exp.id) selectedDatasetView.value = null;
  const request = ++experimentFocusRequest;
  // Dataset focus is one scientific context.  Comparison checkboxes may add
  // other datasets while that context is stable, but choosing another dataset
  // starts a new context and must not retain a receipt from the prior one.
  if (!options.preserveComparisons) {
    const retainedSelection = plotFileSelections.value[exp.id];
    plotFileSelections.value = {};
    plotDatasetSources.value = [];
    plotDatasetsError.value = null;
    plotDatasetRequest += 1;
    contentsInspectionRequest += 1;
    inspectionWarnings.value = [];
    inspectionAssets.value = [];
    inspectionAssetId.value = null;
    pendingInspection.value = null;
    if (retainedSelection !== undefined) {
      setExperimentPlotSelection(exp.id, retainedSelection);
    }
  }
  await dataStore.selectExperiment(exp.id);
  if (request !== experimentFocusRequest || dataStore.activeExperimentId !== exp.id) return;
  if (dataStore.experimentFilesRefusal) return;
  if (!hasExperimentPlotSelection(exp.id) && dataStore.experimentFiles.length > 0) {
    const registeredViews = dataStore.experimentFiles.filter((file) =>
      Boolean(registeredPackageView(file.file_path)),
    );
    if (registeredViews.length > 1) {
      const preferred = registeredViews[0];
      setExperimentPlotSelection(exp.id, [
        { id: preferred.id, file_path: preferred.file_path, stage: preferred.stage },
      ]);
    } else {
      setExperimentPlotSelection(exp.id, null);
    }
  }
  activeTab.value = TAB_MY_DATASET;
  persistActiveDataTab();
  await showExperimentContents(exp.id);
  if (request !== experimentFocusRequest || dataStore.activeExperimentId !== exp.id) return;
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

async function onAcquisitionExperimentSelect(experimentId: number) {
  const experiment = dataStore.experiments.find((candidate) => candidate.id === experimentId);
  if (!experiment) return;
  await dataStore.selectExperiment(experiment.id);
  activeTab.value = TAB_MULTI_WELL;
  persistActiveDataTab();
  await router.replace({
    path: "/data",
    query: { tab: "multi-well", experiment: String(experiment.id) },
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
    await loadPlottedDatasets();
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
  const files = Array.from(event.files ?? []);
  selectedFile.value = files[0] ?? null;
  if (!files.length) return;
  try {
    const staged = await dataStore.stageUploadBatch(files);
    uploadRefusals.value.push(...staged.refusals);
    for (const member of staged.files) {
      stagedUploadMembers.value.push(member);
      uploadAssetIds[member.staging_id] =
        member.assets.length === 1 ? member.assets[0].asset_id : null;
      uploadOverrides[member.staging_id] = uploadControlOverrides(
        member,
        member.suggested_overrides ?? {},
      );
    }
    previewUploadId.value = staged.files[0]?.staging_id ?? previewUploadId.value;
    clearUploadFileSelection();
    if (staged.file_count && staged.refused_count) {
      toast.add({
        severity: "warn",
        summary: "Sources Partly Ready",
        detail: `${staged.file_count} loaded; ${staged.refused_count} not loaded. Review the receipt below.`,
        life: 5000,
      });
    } else if (staged.file_count) {
      toast.add({
        severity: "success",
        summary: "Sources Ready",
        detail: `${staged.file_count} scientific file${staged.file_count === 1 ? "" : "s"} passed native parsing`,
        life: 2500,
      });
    } else {
      toast.add({
        severity: "error",
        summary: "No Sources Loaded",
        detail: `${staged.refused_count} selected source${staged.refused_count === 1 ? " was" : "s were"} refused. Review the receipt below.`,
        life: 6000,
      });
    }
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

function toggleUploadSourceMenu(event: Event) {
  uploadSourceMenuRef.value?.toggle(event);
}

function openUploadFilesPicker() {
  uploadFilesInputRef.value?.click();
}

function openUploadFolderPicker() {
  uploadFolderInputRef.value?.click();
}

async function onNativeFileSelection(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  await onFileSelect({ files });
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
    const created = await dataStore.createExperiment(
      name,
      undefined,
      projectStore.currentProjectId,
    );
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
    for (const member of stagedUploadMembers.value) delete uploadAssetIds[member.staging_id];
    stagedUploadMembers.value = [];
    uploadRefusals.value = [];
    previewUploadId.value = null;
    uploadStage.value = "raw";
    uploadDataRole.value = "auto";
    uploadTargetColumn.value = "";
    uploadTargetType.value = "";
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
  } catch (err) {
    stagedUploadErrors[stagingId] = getErrorMessage(
      err,
      "The staged file could not be removed. Retry before leaving this page.",
    );
    return;
  }
  stagedUploadMembers.value = stagedUploadMembers.value.filter(
    (member) => member.staging_id !== stagingId,
  );
  delete stagedUploadErrors[stagingId];
  delete uploadOverrides[stagingId];
  delete uploadAssetIds[stagingId];
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
  const deletingFile = deleteTarget.value;
  const deletingExperimentId = dataStore.activeExperimentId;
  residentDatasets.delete(deletingExperimentId);
  deleting.value = true;
  try {
    await dataStore.deleteFile(deletingExperimentId, deletingFile.id);
    fileAssetInventoryCache.delete(`${deletingExperimentId}:${deletingFile.id}`);
    const selection = plotFileSelections.value[deletingExperimentId];
    if (Array.isArray(selection)) {
      setExperimentPlotSelection(
        deletingExperimentId,
        selection.filter((file) => file.id !== deletingFile.id),
      );
    }
    await loadPlottedDatasets();
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
    for (const cacheKey of fileAssetInventoryCache.keys()) {
      if (cacheKey.startsWith(`${experimentId}:`)) fileAssetInventoryCache.delete(cacheKey);
    }
    setExperimentPlotSelection(experimentId, undefined);
    await loadPlottedDatasets();
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
  inspectionWarnings.value = [];
  try {
    // Active-row focus only controls curve emphasis. It must not replace the
    // admitted dataset collection with a single-file preview.
    const inventory = await dataStore.fetchFileAssets(experimentId, file.id);
    inspectionAssets.value = inventory.assets;
    inspectionWarnings.value = uniqueAssetWarnings(inventory.assets);
    inspectionAssetId.value = null;
    pendingInspection.value =
      inventory.assets.length > 1 ? { kind: "file", experimentId, file } : null;
    dataStore.activateFile(file.id, file.file_path);
    if (inventory.assets.length > 1) {
      dataStore.clearInspection();
    }
    void ensureFileSampleLabels(experimentId);
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
    inspectionWarnings.value = [];
    toast.add({
      severity: "error",
      summary: "Scientific results unavailable",
      detail: dataStore.fileInfoError || "Could not inspect the scientific results in this file.",
      life: 6000,
    });
  }
}

async function onInspectionAssetChange() {
  const selection = pendingInspection.value;
  const assetId = inspectionAssetId.value;
  if (!selection || !assetId) return;
  try {
    if (selection.kind === "file") {
      await dataStore.inspectFile(
        selection.file.id,
        selection.file.file_path,
        selection.experimentId,
        assetId,
      );
      cacheFileSampleLabels(
        selection.experimentId,
        dataStore.fileInfo,
        extractFileName(selection.file.file_path),
      );
      void ensureFileSampleLabels(selection.experimentId);
    } else {
      const selected = plotFileSelections.value[selection.experimentId];
      if (exactInspectionSelection.value && Array.isArray(selected)) {
        await dataStore.inspectExperimentRawFiles(selection.experimentId, assetId, selected.map((file) => file.id));
      } else {
        await dataStore.inspectExperimentRawFiles(selection.experimentId, assetId);
      }
      cacheFileSampleLabels(selection.experimentId, dataStore.fileInfo);
    }
  } catch {
    // The store exposes the exact preview error in the Contents panel.
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

function registeredPackageView(filePath: string): string | null {
  const stem = extractFileName(filePath)
    .replace(/\.[^.]+$/, "")
    .toLowerCase();
  const labels: Record<string, string> = {
    "cgl-spectra": "Complete spectra",
    "corn-m5": "M5",
    "corn-mp5": "MP5",
    "corn-mp6": "MP6",
    "diesel-high-level": "High-level set",
    "diesel-low-level-a": "Low-level set A",
    "diesel-low-level-b": "Low-level set B",
    "nir-calibration-1": "Calibration — instrument 1",
    "nir-calibration-2": "Calibration — instrument 2",
    "nir-test-1": "Test — instrument 1",
    "nir-test-2": "Test — instrument 2",
    "nir-validation-1": "Validation — instrument 1",
    "nir-validation-2": "Validation — instrument 2",
    "metal-etch-machine": "Machine sensors",
    "metal-etch-oes": "Optical emission spectra",
    "metal-etch-rfm": "RF-monitor variables",
  };
  if (stem in labels) return labels[stem];
  return null;
}

function dataViewLabel(file: ExperimentFile): string {
  return registeredPackageView(file.file_path) ?? extractFileName(file.file_path);
}

function cacheFileSampleLabels(
  experimentId: number,
  dataset: SherpaDatasetDict | null,
  fallbackFileName = "",
): void {
  if (!dataset || !Array.isArray(dataset.data) || dataset.data.length === 0) return;
  const labelsByFile: Record<string, string[]> = {};
  for (const { fileName, sampleLabel } of alignedSpectrumIdentities(
    dataset,
    dataset.data.length,
    fallbackFileName,
  )) {
    if (!fileName) continue;
    const labels = labelsByFile[fileName] ?? [];
    if (!labels.includes(sampleLabel)) labels.push(sampleLabel);
    labelsByFile[fileName] = labels;
  }
  if (!Object.keys(labelsByFile).length) return;
  fileSampleLabelsByExperiment.value = {
    ...fileSampleLabelsByExperiment.value,
    [experimentId]: {
      ...(fileSampleLabelsByExperiment.value[experimentId] ?? {}),
      ...labelsByFile,
    },
  };
}

function sampleLabelsForFile(file: ExperimentFile): string[] {
  const experimentId = dataStore.activeExperimentId;
  if (experimentId == null) return [];
  return fileSampleLabelsByExperiment.value[experimentId]?.[extractFileName(file.file_path)] ?? [];
}

async function ensureFileSampleLabels(experimentId: number): Promise<void> {
  const files = dataStore.activeExperimentId === experimentId ? dataStore.experimentFiles : [];
  const cached = fileSampleLabelsByExperiment.value[experimentId] ?? {};
  if (
    files.length > 0 &&
    files.every((file) => Boolean(cached[extractFileName(file.file_path)]?.length))
  ) {
    return;
  }
  const pending = fileSampleLabelRequests.get(experimentId);
  if (pending) return pending;
  const request = Promise.resolve(
    api.post<SherpaDatasetDict>("/builder/file-info", { experiment_id: experimentId }),
  )
    .then((response) => {
      if (response?.data) cacheFileSampleLabels(experimentId, response.data);
    })
    .catch(() => undefined)
    .finally(() => fileSampleLabelRequests.delete(experimentId));
  fileSampleLabelRequests.set(experimentId, request);
  return request;
}

function summarizedSampleLabels(labels: string[]): string {
  if (labels.length <= 5) return labels.join(", ");
  return `${labels.slice(0, 5).join(", ")} (+${labels.length - 5} more)`;
}

function fileRowHoverText(file: ExperimentFile): string | undefined {
  const labels = sampleLabelsForFile(file);
  if (!labels.length) return undefined;
  const heading = labels.length === 1 ? "Sample label" : "Sample labels";
  return `${heading}: ${summarizedSampleLabels(labels)}`;
}

function fileRowAccessibleLabel(file: ExperimentFile): string {
  const labels = sampleLabelsForFile(file);
  const fileName = extractFileName(file.file_path);
  return labels.length
    ? `${fileName}. Sample ${labels.length === 1 ? "label" : "labels"}: ${summarizedSampleLabels(labels)}`
    : fileName;
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
.dataset-view-registry {
  margin-top: 1rem;
  padding: 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 0.5rem;
}

.dataset-view-actions,
.dataset-view-list li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.dataset-view-actions {
  margin: 0.75rem 0;
}

.dataset-view-list {
  padding: 0;
  margin: 0;
  list-style: none;
}

.dataset-view-list li {
  padding: 0.25rem 0;
  border-top: 1px solid var(--surface-border);
}

.dataset-view-list li span {
  flex: 1;
  min-width: 10rem;
}
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
  padding: 0 1rem;
  color: var(--text-color);
  font-size: 0.9375rem;
  line-height: 1.5;
}

:global(.content:has(.data-content)) {
  background: #e4e0fa;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.workflow-selection-context {
  margin: 0.85rem 0 0;
  padding: 0.9rem 1rem;
  border: 1px solid color-mix(in srgb, var(--primary-color) 35%, var(--surface-border));
  border-radius: 0.75rem;
  background: color-mix(in srgb, var(--primary-color) 6%, var(--surface-card));
}

.workflow-selection-heading,
.workflow-selection-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.workflow-selection-heading {
  justify-content: space-between;
}

.workflow-selection-heading > div {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.workflow-selection-heading small,
.workflow-selection-context p {
  color: var(--text-color-secondary);
}

.workflow-selection-context p {
  margin: 0.65rem 0;
  font-size: 0.875rem;
}

.workflow-selection-actions .p-inputtext {
  flex: 1 1 18rem;
}

.workflow-selection-error {
  margin-bottom: 0.65rem;
  color: var(--red-600);
  font-size: 0.875rem;
}

.context-label {
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
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
  display: flex;
  flex-direction: column;
  height: 520px;
  overflow: hidden;
  padding: 0.75rem;
}

.panel-heading {
  align-items: flex-start;
  border-bottom: 1px solid var(--surface-border);
  display: flex;
  flex: 0 0 auto;
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

.exp-table {
  flex: 1 1 auto;
  min-height: 0;
}

.exp-table :deep(.p-datatable-wrapper) {
  scrollbar-gutter: stable;
}

.files-panel > .empty-state {
  flex: 1 1 auto;
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
  flex: 1 1 auto;
  gap: 12px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 0.2rem;
  scrollbar-gutter: stable;
}

.active-view-set {
  background: color-mix(in srgb, var(--primary-color) 7%, var(--surface-card));
  border: 1px solid color-mix(in srgb, var(--primary-color) 25%, var(--surface-border));
  border-radius: 6px;
  display: grid;
  flex: 0 0 auto;
  gap: 0.2rem;
  margin-top: 0.65rem;
  padding: 0.55rem 0.65rem;
}

.active-view-set strong,
.active-view-set span {
  font-size: 0.8rem;
}

.active-view-set small {
  color: var(--text-color-secondary);
  line-height: 1.35;
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
  gap: 0.55rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.45rem 0.5rem;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--surface-border);
  border-radius: 6px;
  transition:
    color 0.15s,
    border-color 0.15s,
    background 0.15s;
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
  flex: 1 1 auto;
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

.registered-reference-catalog-link {
  align-items: center;
  background: var(--surface-50);
  border-radius: 8px;
  display: flex;
  gap: 0.75rem;
  justify-content: space-between;
  margin-bottom: 0.75rem;
  padding: 0.75rem;
}

.registered-reference-catalog-link p {
  color: var(--text-color-secondary);
  font-size: 0.82rem;
  line-height: 1.4;
  margin: 0;
}

.registered-reference-catalog-link a {
  flex: 0 0 auto;
}

.registered-reference-card {
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  display: grid;
  gap: 0.65rem;
  padding: 0.85rem;
}

.registered-reference-card__heading {
  align-items: flex-start;
  display: flex;
  gap: 0.75rem;
  justify-content: space-between;
}

.registered-reference-card__heading div {
  display: grid;
  gap: 0.25rem;
}

.registered-reference-card__heading small {
  color: var(--text-color-secondary);
  line-height: 1.4;
  margin: 0;
}

.registered-reference-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.registered-reference-card__status {
  font-weight: 600;
}

.registered-reference-card__status.ready {
  color: var(--green-600);
}

.registered-reference-card__status.error {
  color: var(--red-600);
}

@media (max-width: 48rem) {
  .registered-reference-catalog-link {
    align-items: stretch;
    flex-direction: column;
  }
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
  transition:
    background 0.15s,
    color 0.15s,
    border-color 0.15s;
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
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
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

.upload-intro {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.upload-intro h3,
.upload-intro p {
  margin: 0;
}

.upload-intro p {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  line-height: 1.45;
  margin-top: 0.25rem;
  max-width: 38rem;
}

.upload-source-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.625rem;
}

.visually-hidden-file-input {
  height: 1px;
  left: -10000px;
  overflow: hidden;
  position: absolute;
  top: auto;
  width: 1px;
}

.upload-options-panel {
  border: 1px solid var(--surface-border);
  box-shadow: none;
}

.upload-options-heading {
  align-items: center;
  color: var(--text-color-secondary);
  display: inline-flex;
  font-size: 0.875rem;
  gap: 0.5rem;
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

.upload-members .selected-member-row > span {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.upload-members .selected-member-row small {
  color: var(--text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-members .selected-member-row .upload-cleanup-error {
  color: #b42318;
  white-space: normal;
}

.upload-refusals {
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-radius: 8px;
  color: #9a3412;
  padding: 0.75rem 0.9rem;
}

.upload-refusals summary {
  cursor: pointer;
  font-weight: 700;
}

.upload-refusals ul {
  display: grid;
  gap: 0.55rem;
  margin: 0.75rem 0 0;
  max-height: 14rem;
  overflow: auto;
  padding-left: 1.15rem;
}

.upload-refusals li strong,
.upload-refusals li span {
  display: block;
  overflow-wrap: anywhere;
}

.upload-refusals li span {
  color: #7c2d12;
  font-size: 0.8125rem;
  margin-top: 0.1rem;
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

.field-help {
  font-size: 0.78rem;
  color: #64748b;
}

.inspection-asset-selector {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  max-width: 680px;
  margin: 1rem 0;
  padding: 0.85rem;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
}

.inspection-asset-selector label {
  font-weight: 600;
}

.inspection-asset-selector small {
  color: var(--text-color-secondary);
}

.scientific-asset-warning {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  max-width: 680px;
  margin: 0.75rem 0;
  padding: 0.75rem 0.85rem;
  border: 1px solid #f59e0b;
  border-radius: 8px;
  background: #fffbeb;
  color: #92400e;
  font-size: 0.86rem;
  line-height: 1.4;
}

.scientific-asset-warning i {
  margin-top: 0.15rem;
}

/* ---- Responsive ---- */
@media (max-width: 900px) {



  .workflow-selection-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .load-panels {
    grid-template-columns: 1fr;
  }

  .explore-panels {
    grid-template-columns: 1fr;
  }
}
</style>
