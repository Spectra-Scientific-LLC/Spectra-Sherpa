// Shim: re-exports the OSS-loaded Vue instance. Populated by OSS
// main.ts via globalThis.__OSS_VENDOR__.vue before any /ui/*.js
// module imports `vue`.
//
// STATUS (Phase 1b commit 4 scaffolding): the named exports below
// cover what the ported views and the server auth/admin modules
// currently use. If a module imports a Vue symbol not listed here,
// extend this shim rather than changing the module — the goal is
// for the server modules to write idiomatic `import { X } from "vue"`.

const vendor = globalThis.__OSS_VENDOR__?.vue;
if (!vendor) {
  throw new Error(
    "[vendor/vue.js] OSS bundle did not populate globalThis.__OSS_VENDOR__.vue. " +
      "OSS src/main.ts must expose the Vue module before /ui/*.js is imported.",
  );
}

export const ref = vendor.ref;
export const reactive = vendor.reactive;
export const readonly = vendor.readonly;
export const computed = vendor.computed;
export const watch = vendor.watch;
export const watchEffect = vendor.watchEffect;
export const defineComponent = vendor.defineComponent;
export const defineAsyncComponent = vendor.defineAsyncComponent;
export const h = vendor.h;
export const onMounted = vendor.onMounted;
export const onUnmounted = vendor.onUnmounted;
export const onBeforeMount = vendor.onBeforeMount;
export const onBeforeUnmount = vendor.onBeforeUnmount;
export const nextTick = vendor.nextTick;
export const toRef = vendor.toRef;
export const toRefs = vendor.toRefs;
export const unref = vendor.unref;
export const isRef = vendor.isRef;
export const markRaw = vendor.markRaw;
export const shallowRef = vendor.shallowRef;
export const provide = vendor.provide;
export const inject = vendor.inject;
export const Teleport = vendor.Teleport;
export const Transition = vendor.Transition;
export const TransitionGroup = vendor.TransitionGroup;
export const KeepAlive = vendor.KeepAlive;

export default vendor;
