// Shim: re-exports the OSS-loaded primevue/message instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.message;
if (!mod) {
  throw new Error(
    "[vendor/primevue/message.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.message.",
  );
}
export default mod.default ?? mod;
