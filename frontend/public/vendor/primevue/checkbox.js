// Shim: re-exports the OSS-loaded primevue/checkbox instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.checkbox;
if (!mod) {
  throw new Error(
    "[vendor/primevue/checkbox.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.checkbox.",
  );
}
export default mod.default ?? mod;
