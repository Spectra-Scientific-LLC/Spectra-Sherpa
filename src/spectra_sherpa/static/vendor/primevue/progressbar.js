// Shim: re-exports the OSS-loaded primevue/progressbar instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.progressbar;
if (!mod) {
  throw new Error(
    "[vendor/primevue/progressbar.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.progressbar.",
  );
}
export default mod.default ?? mod;
