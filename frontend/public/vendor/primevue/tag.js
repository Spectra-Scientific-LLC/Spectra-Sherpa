// Shim: re-exports the OSS-loaded primevue/tag instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.tag;
if (!mod) {
  throw new Error(
    "[vendor/primevue/tag.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.tag.",
  );
}
export default mod.default ?? mod;
