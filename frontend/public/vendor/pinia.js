// Shim: re-exports the OSS-loaded Pinia instance.
const vendor = globalThis.__OSS_VENDOR__?.pinia;
if (!vendor) {
  throw new Error(
    "[vendor/pinia.js] OSS bundle did not populate globalThis.__OSS_VENDOR__.pinia.",
  );
}

export const defineStore = vendor.defineStore;
export const storeToRefs = vendor.storeToRefs;
export const createPinia = vendor.createPinia;

export default vendor;
