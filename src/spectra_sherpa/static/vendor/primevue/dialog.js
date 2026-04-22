// Shim: re-exports the OSS-loaded primevue/dialog instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.dialog;
if (!mod) {
  throw new Error(
    "[vendor/primevue/dialog.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.dialog.",
  );
}
export default mod.default ?? mod;
