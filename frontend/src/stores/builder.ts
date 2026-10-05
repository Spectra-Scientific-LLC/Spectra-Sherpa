import { defineStore } from "pinia";
import api from "@/api/client";
import { blobFromResponseData, downloadBlob } from "@/utils/download";

/** File-transfer actions shared by the workflow builder. */
export const useBuilderStore = defineStore("builder", () => {
  const downloadDataset = async (fileId: number, fileName: string) => {
    try {
      const response = await api.get(`/datasets/download/${fileId}`, {
        responseType: "blob",
      });
      downloadBlob(blobFromResponseData(response.data), fileName);
    } catch (error) {
      console.error("Download failed:", error);
      throw error;
    }
  };

  return { downloadDataset };
});
