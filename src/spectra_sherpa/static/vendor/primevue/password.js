// Shim: re-exports the OSS-loaded primevue/password instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.password;
if (!mod) {
  throw new Error(
    "[vendor/primevue/password.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.password.",
  );
}
export default mod.default ?? mod;
