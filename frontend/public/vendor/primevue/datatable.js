// Shim: re-exports the OSS-loaded primevue/datatable instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.datatable;
if (!mod) {
  throw new Error(
    "[vendor/primevue/datatable.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.datatable.",
  );
}
export default mod.default ?? mod;
