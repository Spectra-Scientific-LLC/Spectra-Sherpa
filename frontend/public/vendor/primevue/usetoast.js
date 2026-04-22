// Shim: re-exports the OSS-loaded primevue/usetoast composable.
const mod = globalThis.__OSS_VENDOR__?.primevue?.usetoast;
if (!mod) {
  throw new Error(
    "[vendor/primevue/usetoast.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.usetoast.",
  );
}
export const useToast = mod.useToast;
export default mod.default ?? mod;
