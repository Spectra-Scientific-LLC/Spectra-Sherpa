// Shim: re-exports the OSS-loaded primevue/column instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.column;
if (!mod) {
  throw new Error(
    "[vendor/primevue/column.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.column.",
  );
}
export default mod.default ?? mod;
