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
    // Avoid Lightning CSS's platform-specific optional native package in CI.
    // esbuild minification is deterministic for the committed OSS static bundle
    // and removes a flaky post-merge failure mode on Ubuntu runners.
    cssMinify: "esbuild",
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("plotly.js-cartesian-dist-min")) {
            return "plotly";
          }
          // Keep the Vue runtime (incl. @vue/reactivity) in its own leaf
          // vendor chunk. Otherwise the default splitter co-locates Vue
          // inside the entry chunk, and any small module that calls a
          // reactivity primitive at top level (e.g. composables/demoModeState's
          // `ref(...)` state) lands in a sibling chunk that imports `ref`
          // back from the entry — a circular chunk dependency. In the
          // production build that cycle can evaluate the sibling before the
          // entry defines RefImpl, throwing "X is not a constructor" at boot
          // and blanking the SPA. A dedicated, dependency-free Vue chunk
          // always initializes first, so the cycle cannot form.
          if (id.includes("/node_modules/@vue/") || id.includes("/node_modules/vue/")) {
            return "vue";
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
