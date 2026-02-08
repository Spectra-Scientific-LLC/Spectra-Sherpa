import { defineStore } from "pinia";

export const useAppStore = defineStore("app", {
  state: () => ({
    apiKey: localStorage.getItem("api_key") || "",
  }),
  actions: {
    setApiKey(value: string) {
      this.apiKey = value;
      localStorage.setItem("api_key", value);
    },
  },
});
