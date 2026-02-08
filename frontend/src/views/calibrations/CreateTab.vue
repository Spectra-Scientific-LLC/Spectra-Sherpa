<template>
  <div class="create-tab">
    <div class="tab-section">
      <div class="section-header">
        <h3>
          <i class="pi pi-plus-circle"></i>
          Create New Calibration
        </h3>
      </div>

      <div class="form-content">
        <div class="form-grid">
          <div class="field">
            <label for="compound-name">Compound Name <span class="required">*</span></label>
            <InputText
              id="compound-name"
              v-model="draftCalibration.compound_name"
              placeholder="e.g., Ethanol"
            />
          </div>

          <div class="field">
            <label for="concentration-mode">Concentration Mode <span class="required">*</span></label>
            <Dropdown
              id="concentration-mode"
              v-model="draftCalibration.concentration_mode"
              :options="modeOptions"
              placeholder="Select mode"
            />
            <small class="field-hint">
              Product: concentration × pathlength; Concentration: direct concentration
            </small>
          </div>

          <div class="field">
            <label for="x-unit">X Unit <span class="required">*</span></label>
            <InputText
              id="x-unit"
              v-model="draftCalibration.x_unit"
              placeholder="e.g., ppm*m"
            />
            <small class="field-hint">
              Unit for concentration (e.g., ppm*m, mol/L, etc.)
            </small>
          </div>

          <div class="field">
            <label for="pathlength">Pathlength (m)</label>
            <InputNumber
              id="pathlength"
              v-model="draftCalibration.pathlength_m"
              :min="0"
              :step="0.1"
              :minFractionDigits="1"
              :maxFractionDigits="4"
              placeholder="Optional"
            />
            <small class="field-hint">
              Optical pathlength in meters (optional)
            </small>
          </div>
        </div>

        <div class="form-actions">
          <Button
            label="Reset"
            icon="pi pi-refresh"
            class="p-button-text"
            @click="resetDraft"
          />
          <Button
            label="Create Calibration"
            icon="pi pi-check"
            :loading="store.loading"
            @click="createCalibration"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import { useToast } from "primevue/usetoast";
import { useCalibrationStore } from "@/stores/calibration";

const store = useCalibrationStore();
const toast = useToast();

const emit = defineEmits<{
  created: [];
}>();

const modeOptions = ["product", "concentration"];

const draftCalibration = ref({
  compound_name: "",
  concentration_mode: "product",
  x_unit: "ppm*m",
  pathlength_m: null as number | null,
});

const resetDraft = () => {
  draftCalibration.value = {
    compound_name: "",
    concentration_mode: "product",
    x_unit: "ppm*m",
    pathlength_m: null,
  };
};

const createCalibration = async () => {
  if (!draftCalibration.value.compound_name.trim()) {
    toast.add({
      severity: "warn",
      summary: "Validation Error",
      detail: "Compound name is required",
      life: 3000,
    });
    return;
  }

  try {
    await store.createCalibration(draftCalibration.value);
    toast.add({
      severity: "success",
      summary: "Created",
      detail: `Calibration for ${draftCalibration.value.compound_name} created successfully`,
      life: 3000,
    });
    resetDraft();
    emit("created");
  } catch (error) {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to create calibration",
      life: 3000,
    });
  }
};
</script>

<style scoped>
.create-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tab-section {
  background: #ffffff;
  border-radius: 8px;
  padding: 20px;
}

.section-header {
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.section-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.form-content {
  max-width: 600px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
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
  color: #dc2626;
}

.field-hint {
  color: #64748b;
  font-size: 0.85rem;
  margin-top: 4px;
}

.form-actions {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid #e2e8f0;
}
</style>
