// Shim: re-exports the OSS-loaded primevue/card instance.
const mod = globalThis.__OSS_VENDOR__?.primevue?.card;
if (!mod) {
  throw new Error(
    "[vendor/primevue/card.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.primevue.card.",
  );
}
export default mod.default ?? mod;
