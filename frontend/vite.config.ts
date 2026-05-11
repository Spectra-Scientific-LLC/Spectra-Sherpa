import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";
import { readFileSync } from "node:fs";

// Read the frontend bundle's version from package.json at build time and
// inject it as a global compile-time constant.  The footer + About dialog
// surface this alongside the backend version so users can spot bundle drift
// after an upgrade ("FE 0.4.2 vs BE 0.4.3 — hard-reload your browser").
const frontendPkg = JSON.parse(
  readFileSync(path.resolve(__dirname, "package.json"), "utf-8"),
);

export default defineConfig({
  plugins: [vue()],
  define: {
    __SHERPA_FRONTEND_VERSION__: JSON.stringify(frontendPkg.version),
  },
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
