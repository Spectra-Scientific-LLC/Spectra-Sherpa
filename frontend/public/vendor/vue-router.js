// Shim: re-exports the OSS-loaded vue-router instance.
const vendor = globalThis.__OSS_VENDOR__?.vueRouter;
if (!vendor) {
  throw new Error(
    "[vendor/vue-router.js] OSS bundle did not populate " +
      "globalThis.__OSS_VENDOR__.vueRouter.",
  );
}

export const useRouter = vendor.useRouter;
export const useRoute = vendor.useRoute;
export const createRouter = vendor.createRouter;
export const createWebHistory = vendor.createWebHistory;
export const createWebHashHistory = vendor.createWebHashHistory;
export const RouterView = vendor.RouterView;
export const RouterLink = vendor.RouterLink;

export default vendor;
