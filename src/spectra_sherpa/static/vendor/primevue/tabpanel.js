// Shim: re-exports the OSS-loaded primevue/tabpanel instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.tabpanel;
if (!mod) {
  throw new Error(
    "[vendor/primevue/tabpanel.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.tabpanel.",
  );
}
export default mod.default ?? mod;
