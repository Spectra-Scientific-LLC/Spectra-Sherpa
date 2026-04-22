// Shim: re-exports the OSS-loaded primevue/button instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.button;
if (!mod) {
  throw new Error(
    "[vendor/primevue/button.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.button.",
  );
}
export default mod.default ?? mod;
