import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: path.resolve(__dirname, "../src/spectra_sherpa/static"),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          if (id.includes("plotly.js-dist-min")) {
            return "plotly";
          }
          if (id.includes("@vue-flow")) {
            return "vue-flow";
          }
          if (id.includes("primevue") || id.includes("primeicons")) {
            return "primevue";
          }
          if (
            id.includes("/vue/") ||
            id.includes("vue-router") ||
            id.includes("pinia")
          ) {
            return "vue-core";
          }
          return "vendor";
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/ws": {
        target: "http://127.0.0.1:8000",
        ws: true,
      },
    },
  },
});
