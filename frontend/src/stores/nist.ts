import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import type { NistLibraryEntry, NistSearchResult } from "@/types";

export interface DownloadRequest {
  jobId: number;
  compoundName: string;
}

export const useNistStore = defineStore("nist", () => {
  const searchResults = ref<NistSearchResult[]>([]);
  const library = ref<NistLibraryEntry[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const downloads = ref<DownloadRequest[]>([]);

  const search = async (query: string) => {
    if (!query) {
      searchResults.value = [];
      return;
    }
    loading.value = true;
    try {
      const response = await api.get<NistSearchResult[]>(
        `/nist/search?query=${encodeURIComponent(query)}`
      );
      searchResults.value = response.data;
    } catch (err: any) {
      error.value = err?.message || "Search failed";
      throw err;
    } finally {
      loading.value = false;
    }
  };

  const download = async (payload: {
    cas_number: string;
    compound_name: string;
    resolution?: string | null;
    index?: number | null;
  }) => {
    const response = await api.post<{ status: string; job_id: number }>(
      "/nist/download",
      payload
    );
    downloads.value.push({
      jobId: response.data.job_id,
      compoundName: payload.compound_name,
    });
    return response.data;
  };

  const fetchLibrary = async () => {
    loading.value = true;
    try {
      const response = await api.get<NistLibraryEntry[]>("/nist/library");
      library.value = response.data;
    } finally {
      loading.value = false;
    }
  };

  const clearDownload = (jobId: number) => {
    downloads.value = downloads.value.filter((item) => item.jobId !== jobId);
  };

  return {
    searchResults,
    library,
    loading,
    error,
    downloads,
    search,
    download,
    fetchLibrary,
    clearDownload,
  };
});
