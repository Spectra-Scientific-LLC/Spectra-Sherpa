import { defineStore } from "pinia";
import { readStoredApiKey, writeStoredApiKey } from "@/utils/authStorage";

export const useAppStore = defineStore("app", {
  state: () => ({
    apiKey: readStoredApiKey(),
  }),
  actions: {
    setApiKey(value: string) {
      this.apiKey = value;
      writeStoredApiKey(value);
    },
  },
});
