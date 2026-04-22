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
          if (id.includes("plotly.js-cartesian-dist-min")) {
            return "plotly";
          }
          return undefined;
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
      // REST API — used when VITE_API_BASE_URL is set to a relative path (e.g. /api/v1)
      // instead of the default absolute http://127.0.0.1:8000/api/v1 in client.ts.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "http://127.0.0.1:8000",
        ws: true,
      },
      // Server-provided frontend modules (/ui/auth.js, /ui/admin.js) —
      // served by spectrasherpa-server's StaticFiles mount. Without
      // this the OSS SPA dev server would 404 the dynamic imports
      // because its SPA catch-all consumes them.
      "/ui": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
