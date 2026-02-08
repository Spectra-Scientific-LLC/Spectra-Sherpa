import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import type {
  CalModelInfo,
  CalibrationDetail,
  CalibrationFileOut,
  CalibrationSummary,
} from "@/types";

export const useCalibrationStore = defineStore("calibration", () => {
  const calibrations = ref<CalibrationSummary[]>([]);
  const currentCalibration = ref<CalibrationDetail | null>(null);
  const measurements = ref<CalibrationFileOut[]>([]);
  const models = ref<CalModelInfo[]>([]);
  const loading = ref(false);

  const activeModel = computed(
    () => models.value.find((model) => model.is_active) || null
  );

  const fetchCalibrations = async () => {
    loading.value = true;
    try {
      const response = await api.get<CalibrationSummary[]>("/calibrations");
      calibrations.value = response.data;
    } finally {
      loading.value = false;
    }
  };

  const createCalibration = async (payload: {
    compound_name: string;
    concentration_mode: string;
    x_unit: string;
    pathlength_m?: number | null;
    metadata?: Record<string, unknown>;
  }) => {
    loading.value = true;
    try {
      const response = await api.post<CalibrationDetail>("/calibrations", {
        ...payload,
        metadata: payload.metadata || {},
      });
      calibrations.value = [response.data, ...calibrations.value];
      return response.data;
    } finally {
      loading.value = false;
    }
  };

  const fetchCalibration = async (calibrationId: number) => {
    loading.value = true;
    try {
      const response = await api.get<CalibrationDetail>(
        `/calibrations/${calibrationId}`
      );
      currentCalibration.value = response.data;
      return response.data;
    } finally {
      loading.value = false;
    }
  };

  const fetchMeasurements = async (calibrationId: number) => {
    const response = await api.get<CalibrationFileOut[]>(
      `/calibrations/${calibrationId}/measurements`
    );
    measurements.value = response.data;
    return response.data;
  };

  const fetchModels = async (calibrationId: number) => {
    const response = await api.get<CalModelInfo[]>(
      `/calibrations/${calibrationId}/models`
    );
    models.value = response.data;
    return response.data;
  };

  const selectCalibration = async (calibrationId: number) => {
    loading.value = true;
    try {
      await Promise.all([
        fetchCalibration(calibrationId),
        fetchMeasurements(calibrationId),
        fetchModels(calibrationId),
      ]);
    } finally {
      loading.value = false;
    }
  };

  const uploadMeasurement = async (
    calibrationId: number,
    file: File,
    concentration: number
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("concentration", String(concentration));
    await api.post(`/calibrations/${calibrationId}/measurements`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    await fetchMeasurements(calibrationId);
  };

  const fitModel = async (
    calibrationId: number,
    modelType: string,
    settings: Record<string, unknown> = {},
    versionName?: string
  ) => {
    const response = await api.post(`/calibrations/${calibrationId}/fit`, {
      model_type: modelType,
      settings,
      version_name: versionName || null,
    });
    return response.data as { status: string; job_id: number };
  };

  const activateModel = async (calibrationId: number, modelId: number) => {
    const response = await api.put<CalModelInfo>(
      `/calibrations/${calibrationId}/models/${modelId}/activate`
    );
    models.value = models.value.map((model) => ({
      ...model,
      is_active: model.id === response.data.id,
    }));
    return response.data;
  };

  return {
    calibrations,
    currentCalibration,
    measurements,
    models,
    activeModel,
    loading,
    fetchCalibrations,
    createCalibration,
    selectCalibration,
    fetchCalibration,
    fetchMeasurements,
    fetchModels,
    uploadMeasurement,
    fitModel,
    activateModel,
  };
});
