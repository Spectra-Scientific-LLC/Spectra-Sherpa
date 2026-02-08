import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import type {
  BlendResponse,
  CurvePoint,
  CurveSegment,
  FileInfoResponse,
  PreprocessResponse,
  PreprocessSettings,
  SpectrumPayload,
  NistLibraryEntry,
} from "@/types";

export interface PlotTrace {
  x: number[];
  y: number[];
  type: string;
  mode: string;
  name?: string;
}

export const useBuilderStore = defineStore("builder", () => {
  const loading = ref(false);
  const spectra = ref<SpectrumPayload[]>([]);
  const plotTraces = ref<PlotTrace[]>([]);
  const blendTraces = ref<PlotTrace[]>([]);
  const blendResult = ref<BlendResponse | null>(null);
  const blendConcentrations = ref<Record<string, number[]> | null>(null);
  const blendSettings = ref<any>(null);
  const blendMetadata = ref<any>(null);
  const curvePoints = ref<CurvePoint[]>([]);
  const curveSegments = ref<CurveSegment[]>([]);
  const curveSamplesPerSegment = ref(30);
  const libraryEntries = ref<NistLibraryEntry[]>([]);
  const fileInfo = ref<FileInfoResponse | null>(null);
  const fileInfoLoading = ref(false);

  const settings = ref<PreprocessSettings>({
    align_wavenumbers: false,
    wavenumber_alignment_method: "none",
    wavenumber_alignment_tolerance: 1e-6,
    wavenumber_merge_tolerance: 0.05,
    filter_direction: "wavenumber",
    apply_cosmic_ray_removal: false,
    cosmic_ray_window: 11,
    cosmic_ray_zscore: 6,
    apply_savgol: false,
    savgol_window: 15,
    savgol_polyorder: 3,
    apply_range_limit: false,
    min_wavenumber: 400,
    max_wavenumber: 4000,
    apply_clip_floor: false,
    clip_floor: 0,
    apply_scale: false,
    scale_max_to: 1,
  });

  const fetchCurveDefaults = async () => {
    const response = await api.get("/builder/curves/default");
    curvePoints.value = response.data.curvePoints || [];
    curveSegments.value = response.data.curveSegments || [];
    curveSamplesPerSegment.value = response.data.curveSamplesPerSegment || 30;
  };

  const preprocessSpectra = async (
    payloads: SpectrumPayload[],
    overrideSettings?: PreprocessSettings
  ) => {
    loading.value = true;
    try {
      const response = await api.post<PreprocessResponse>("/builder/preprocess", {
        spectra: payloads,
        settings: overrideSettings || settings.value,
      });
      spectra.value = response.data.data;
      plotTraces.value = spectra.value.map((record) => ({
        x: record.wavenumber || [],
        y: record.absorbance || [],
        type: "scattergl",
        mode: "lines",
        name: record.label,
      }));
      return response.data;
    } finally {
      loading.value = false;
    }
  };

  const blendSpectra = async (
    species: SpectrumPayload[],
    concentrationTimeseries: Record<string, number[]>,
    settings: any = {},
    pathlength?: number,
    metadata?: any
  ) => {
    loading.value = true;
    try {
      const response = await api.post<BlendResponse>("/builder/blend", {
        species,
        concentration_timeseries: concentrationTimeseries,
        settings,
        pathlength_m: pathlength ?? null,
      });
      blendResult.value = response.data;
      blendConcentrations.value = concentrationTimeseries;
      blendSettings.value = settings;
      blendMetadata.value = metadata;
      const firstIndex = 0;
      const absorbance = response.data.absorbance_matrix.map(
        (row) => row[firstIndex] ?? 0
      );
      blendTraces.value = [
        {
          x: response.data.wavenumbers,
          y: absorbance,
          type: "scattergl",
          mode: "lines",
          name: `Blend t=${response.data.times[firstIndex] ?? 0}`,
        },
      ];
      return response.data;
    } finally {
      loading.value = false;
    }
  };

  const addLibraryEntry = (entry: NistLibraryEntry) => {
    if (!libraryEntries.value.find((item) => item.id === entry.id)) {
      libraryEntries.value.push(entry);
    }
  };

  const removeLibraryEntry = (entryId: number) => {
    libraryEntries.value = libraryEntries.value.filter((item) => item.id !== entryId);
  };

  const clearLibraryEntries = () => {
    libraryEntries.value = [];
  };

  const fetchFileInfo = async (filePath: string) => {
    fileInfoLoading.value = true;
    fileInfo.value = null;
    try {
      const response = await api.post<FileInfoResponse>("/builder/file-info", {
        file_path: filePath,
      });
      fileInfo.value = response.data;
      return response.data;
    } catch (error) {
      fileInfo.value = null;
      throw error;
    } finally {
      fileInfoLoading.value = false;
    }
  };

  const clearFileInfo = () => {
    fileInfo.value = null;
  };

  const downloadDataset = async (fileId: number, fileName: string) => {
    try {
      const response = await api.get(`/datasets/download/${fileId}`, {
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", fileName);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error("Download failed:", error);
      throw error;
    }
  };

  return {
    loading,
    spectra,
    plotTraces,
    blendTraces,
    blendResult,
    blendConcentrations,
    blendSettings,
    blendMetadata,
    curvePoints,
    curveSegments,
    curveSamplesPerSegment,
    libraryEntries,
    fileInfo,
    fileInfoLoading,
    settings,
    fetchCurveDefaults,
    preprocessSpectra,
    blendSpectra,
    addLibraryEntry,
    removeLibraryEntry,
    clearLibraryEntries,
    fetchFileInfo,
    clearFileInfo,
    downloadDataset,
  };
});
