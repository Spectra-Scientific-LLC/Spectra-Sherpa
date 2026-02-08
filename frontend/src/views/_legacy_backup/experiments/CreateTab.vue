<template>
  <div class="create-tab">
    <div class="form-container">
      <!-- Basic Information Section -->
      <div class="section">
        <h3 class="section-title">
          <i class="pi pi-info-circle"></i>
          Basic Information
        </h3>
        <div class="form-grid">
          <div class="field">
            <label for="exp-name">Name <span class="required">*</span></label>
            <InputText
              id="exp-name"
              v-model="draftExperiment.name"
              placeholder="Enter experiment name"
            />
          </div>
          <div class="field full-width">
            <label for="exp-desc">Description</label>
            <Textarea
              id="exp-desc"
              v-model="draftExperiment.description"
              rows="3"
              placeholder="Describe the purpose and goals of this experiment"
            />
          </div>
        </div>
      </div>

      <!-- File Upload Section -->
      <div class="section">
        <h3 class="section-title">
          <i class="pi pi-upload"></i>
          Import Spectra Files
        </h3>
        <SpectraFileUpload
          :show-header="false"
          :show-upload-button="false"
          @files-selected="onFilesSelected"
        />
      </div>

      <!-- Hardware Configuration Section -->
      <div class="section">
        <h3 class="section-title">
          <i class="pi pi-cog"></i>
          Hardware Configuration
        </h3>
        <div class="form-grid two-column">
          <div class="field">
            <label for="hw-instrument">Instrument</label>
            <InputText
              id="hw-instrument"
              v-model="draftExperiment.hardware.instrument"
              placeholder="e.g., Bruker FTIR"
            />
          </div>
          <div class="field">
            <label for="hw-detector">Detector</label>
            <InputText
              id="hw-detector"
              v-model="draftExperiment.hardware.detector"
              placeholder="e.g., MCT"
            />
          </div>
          <div class="field">
            <label for="hw-location">Location</label>
            <InputText
              id="hw-location"
              v-model="draftExperiment.hardware.location"
              placeholder="e.g., Lab A, Building 5"
            />
          </div>
          <div class="field">
            <label for="hw-operator">Operator</label>
            <InputText
              id="hw-operator"
              v-model="draftExperiment.hardware.operator"
              placeholder="Your name"
            />
          </div>
        </div>
      </div>

      <!-- DOE Setup Section -->
      <div class="section">
        <h3 class="section-title">
          <i class="pi pi-chart-bar"></i>
          Design of Experiments (Optional)
        </h3>
        <div class="form-grid two-column">
          <div class="field">
            <label for="doe-design">Design Type</label>
            <InputText
              id="doe-design"
              v-model="draftExperiment.doe.design"
              placeholder="e.g., Full Factorial, RSM"
            />
          </div>
          <div class="field">
            <label for="doe-objective">Objective</label>
            <InputText
              id="doe-objective"
              v-model="draftExperiment.doe.objective"
              placeholder="What are you investigating?"
            />
          </div>
        </div>

        <div class="subsection">
          <h4>Factors</h4>
          <div class="factors-list">
            <div
              v-for="(factor, idx) in draftExperiment.doe.factors"
              :key="idx"
              class="factor-row"
            >
              <InputText
                v-model="factor.name"
                placeholder="Factor name (e.g., Temperature)"
                class="factor-input"
              />
              <InputText
                v-model="factor.levels"
                placeholder="Levels (e.g., 20, 40, 60)"
                class="factor-input"
              />
              <Button
                icon="pi pi-times"
                class="p-button-rounded p-button-text p-button-danger p-button-sm"
                @click="removeFactor(idx)"
              />
            </div>
          </div>
          <Button
            label="Add Factor"
            icon="pi pi-plus"
            class="p-button-text p-button-sm"
            @click="addFactor"
          />
        </div>
      </div>

      <!-- Mixtures Setup Section -->
      <div class="section">
        <h3 class="section-title">
          <i class="pi pi-box"></i>
          Mixture Components (Optional)
        </h3>
        <p class="section-help">
          Define the composition of mixtures used in this experiment
        </p>
        <div class="mixtures-list">
          <div
            v-for="(mix, idx) in draftExperiment.mixtures"
            :key="idx"
            class="mixture-row"
          >
            <InputText
              v-model="mix.component"
              placeholder="Component name (e.g., Ethanol)"
              class="mixture-input"
            />
            <InputNumber
              v-model="mix.fraction"
              placeholder="Fraction (%)"
              :min="0"
              :max="100"
              suffix="%"
              class="mixture-number"
            />
            <Button
              icon="pi pi-times"
              class="p-button-rounded p-button-text p-button-danger p-button-sm"
              @click="removeMixture(idx)"
            />
          </div>
        </div>
        <Button
          label="Add Component"
          icon="pi pi-plus"
          class="p-button-text p-button-sm"
          @click="addMixture"
        />
      </div>

      <!-- Actions -->
      <div class="form-actions">
        <Button
          label="Reset"
          icon="pi pi-refresh"
          class="p-button-text"
          @click="resetDraft"
        />
        <Button
          label="Create Experiment"
          icon="pi pi-check"
          :disabled="!canCreate"
          @click="createExperiment"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useToast } from 'primevue/usetoast';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import InputText from 'primevue/inputtext';
import Textarea from 'primevue/textarea';

import { useExperimentStore } from '@/stores/experiment';
import SpectraFileUpload from '@/components/data/SpectraFileUpload.vue';

const store = useExperimentStore();
const toast = useToast();

const emit = defineEmits<{
  created: [experimentId: number];
}>();

const selectedFiles = ref<File[]>([]);

const onFilesSelected = (files: File[]) => {
  selectedFiles.value = files;
};

const draftExperiment = ref({
  name: '',
  description: '',
  hardware: {
    instrument: '',
    detector: '',
    location: '',
    operator: '',
  },
  doe: {
    design: '',
    objective: '',
    factors: [{ name: '', levels: '' }],
  },
  mixtures: [{ component: '', fraction: 0 }],
});

const canCreate = computed(() => {
  return draftExperiment.value.name.trim().length > 0;
});

const resetDraft = () => {
  draftExperiment.value = {
    name: '',
    description: '',
    hardware: {
      instrument: '',
      detector: '',
      location: '',
      operator: '',
    },
    doe: {
      design: '',
      objective: '',
      factors: [{ name: '', levels: '' }],
    },
    mixtures: [{ component: '', fraction: 0 }],
  };
};

const addMixture = () => {
  draftExperiment.value.mixtures.push({ component: '', fraction: 0 });
};

const removeMixture = (index: number) => {
  if (draftExperiment.value.mixtures.length > 1) {
    draftExperiment.value.mixtures.splice(index, 1);
  }
};

const addFactor = () => {
  draftExperiment.value.doe.factors.push({ name: '', levels: '' });
};

const removeFactor = (index: number) => {
  if (draftExperiment.value.doe.factors.length > 1) {
    draftExperiment.value.doe.factors.splice(index, 1);
  }
};

const createExperiment = async () => {
  if (!canCreate.value) {
    return;
  }

  try {
    const result = await store.createExperiment({
      name: draftExperiment.value.name,
      description: draftExperiment.value.description,
      metadata: {
        hardware: draftExperiment.value.hardware,
        doe: draftExperiment.value.doe,
        mixtures: draftExperiment.value.mixtures,
      },
    });

    // Upload selected files to the new experiment
    if (result && result.id && selectedFiles.value.length > 0) {
      let uploadedCount = 0;
      const failedFiles: string[] = [];

      for (const file of selectedFiles.value) {
        try {
          await store.uploadFile(result.id, file, 'raw');
          uploadedCount++;
        } catch {
          failedFiles.push(file.name);
        }
      }

      if (uploadedCount > 0) {
        toast.add({
          severity: 'success',
          summary: 'Files Uploaded',
          detail: `${uploadedCount} file(s) uploaded to experiment`,
          life: 3000,
        });
      }

      if (failedFiles.length > 0) {
        toast.add({
          severity: 'warn',
          summary: 'Some Uploads Failed',
          detail: `Failed to upload: ${failedFiles.join(', ')}`,
          life: 4000,
        });
      }
    }

    toast.add({
      severity: 'success',
      summary: 'Created',
      detail: `Experiment "${draftExperiment.value.name}" created successfully`,
      life: 3000,
    });

    // Emit created event with experiment ID
    if (result && result.id) {
      emit('created', result.id);
    }

    // Reset form and clear files
    resetDraft();
    selectedFiles.value = [];
  } catch (error) {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to create experiment',
      life: 3000,
    });
  }
};
</script>

<style scoped>
.create-tab {
  background: #f8fafc;
}

.form-container {
  max-width: 900px;
  margin: 0 auto;
}

.section {
  background: #ffffff;
  border-radius: 8px;
  padding: 24px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.section-title {
  margin: 0 0 16px 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-title i {
  color: #3b82f6;
}

.section-help {
  margin: 0 0 16px 0;
  font-size: 0.875rem;
  color: #64748b;
}

.form-grid {
  display: grid;
  gap: 16px;
}

.form-grid.two-column {
  grid-template-columns: repeat(2, 1fr);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field.full-width {
  grid-column: 1 / -1;
}

.field label {
  font-weight: 500;
  font-size: 0.875rem;
  color: #334155;
}

.required {
  color: #ef4444;
}

.subsection {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid #e2e8f0;
}

.subsection h4 {
  margin: 0 0 12px 0;
  font-size: 0.9375rem;
  font-weight: 500;
  color: #475569;
}

.factors-list,
.mixtures-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.factor-row,
.mixture-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.factor-input,
.mixture-input {
  flex: 1;
}

.mixture-number {
  width: 140px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px 24px;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

@media (max-width: 768px) {
  .form-grid.two-column {
    grid-template-columns: 1fr;
  }

  .factor-row,
  .mixture-row {
    flex-wrap: wrap;
  }
}
</style>
