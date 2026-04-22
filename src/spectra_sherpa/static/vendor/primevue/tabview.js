// Shim: re-exports the OSS-loaded primevue/tabview instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.tabview;
if (!mod) {
  throw new Error(
    "[vendor/primevue/tabview.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.tabview.",
  );
}
export default mod.default ?? mod;
