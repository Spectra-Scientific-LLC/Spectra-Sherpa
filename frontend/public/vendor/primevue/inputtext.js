// Shim: re-exports the OSS-loaded primevue/inputtext instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.inputtext;
if (!mod) {
  throw new Error(
    "[vendor/primevue/inputtext.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.inputtext.",
  );
}
export default mod.default ?? mod;
