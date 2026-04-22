// Shim: re-exports the OSS-loaded Vue instance. Populated by OSS
// main.ts via globalThis.__OSS_VENDOR__.vue before any /ui/*.js
// module imports `vue`.
//
// Vite's template compiler emits calls to a large set of Vue runtime
// helpers (openBlock, createBlock, createElementVNode, withCtx, etc.)
// — the server-frontend bundles import them as bare specifiers from
// "vue". This shim must re-export the full public Vue runtime-dom API
// so those imports resolve. If Vue adds a new public export that a
// bundled server module uses, add it here.

const vendor = globalThis.__OSS_VENDOR__?.vue;
if (!vendor) {
  throw new Error(
    "[vendor/vue.js] OSS bundle did not populate globalThis.__OSS_VENDOR__.vue. " +
      "OSS src/main.ts must expose the Vue module before /ui/*.js is imported.",
  );
}

// Reactivity.
export const ref = vendor.ref;
export const reactive = vendor.reactive;
export const readonly = vendor.readonly;
export const computed = vendor.computed;
export const watch = vendor.watch;
export const watchEffect = vendor.watchEffect;
export const watchPostEffect = vendor.watchPostEffect;
export const watchSyncEffect = vendor.watchSyncEffect;
export const toRef = vendor.toRef;
export const toRefs = vendor.toRefs;
export const toValue = vendor.toValue;
export const unref = vendor.unref;
export const isRef = vendor.isRef;
export const isReactive = vendor.isReactive;
export const isReadonly = vendor.isReadonly;
export const isProxy = vendor.isProxy;
export const shallowRef = vendor.shallowRef;
export const shallowReactive = vendor.shallowReactive;
export const shallowReadonly = vendor.shallowReadonly;
export const triggerRef = vendor.triggerRef;
export const customRef = vendor.customRef;
export const markRaw = vendor.markRaw;
export const toRaw = vendor.toRaw;
export const effectScope = vendor.effectScope;
export const getCurrentScope = vendor.getCurrentScope;
export const onScopeDispose = vendor.onScopeDispose;
export const proxyRefs = vendor.proxyRefs;

// Composition API.
export const defineComponent = vendor.defineComponent;
export const defineAsyncComponent = vendor.defineAsyncComponent;
export const defineCustomElement = vendor.defineCustomElement;
export const provide = vendor.provide;
export const inject = vendor.inject;
export const hasInjectionContext = vendor.hasInjectionContext;
export const getCurrentInstance = vendor.getCurrentInstance;
export const useAttrs = vendor.useAttrs;
export const useSlots = vendor.useSlots;
export const useModel = vendor.useModel;
export const useCssModule = vendor.useCssModule;
export const useCssVars = vendor.useCssVars;
export const nextTick = vendor.nextTick;
export const mergeProps = vendor.mergeProps;

// Lifecycle hooks.
export const onBeforeMount = vendor.onBeforeMount;
export const onMounted = vendor.onMounted;
export const onBeforeUpdate = vendor.onBeforeUpdate;
export const onUpdated = vendor.onUpdated;
export const onBeforeUnmount = vendor.onBeforeUnmount;
export const onUnmounted = vendor.onUnmounted;
export const onActivated = vendor.onActivated;
export const onDeactivated = vendor.onDeactivated;
export const onErrorCaptured = vendor.onErrorCaptured;
export const onRenderTracked = vendor.onRenderTracked;
export const onRenderTriggered = vendor.onRenderTriggered;
export const onServerPrefetch = vendor.onServerPrefetch;

// Built-in components.
export const Teleport = vendor.Teleport;
export const Transition = vendor.Transition;
export const TransitionGroup = vendor.TransitionGroup;
export const KeepAlive = vendor.KeepAlive;
export const Suspense = vendor.Suspense;
export const Fragment = vendor.Fragment;
export const Comment = vendor.Comment;
export const Text = vendor.Text;
export const Static = vendor.Static;

// Render / VNode helpers — all compiler-emitted helpers live here.
export const h = vendor.h;
export const createApp = vendor.createApp;
export const createVNode = vendor.createVNode;
export const createTextVNode = vendor.createTextVNode;
export const createCommentVNode = vendor.createCommentVNode;
export const createStaticVNode = vendor.createStaticVNode;
export const createElementVNode = vendor.createElementVNode;
export const createElementBlock = vendor.createElementBlock;
export const createBlock = vendor.createBlock;
export const openBlock = vendor.openBlock;
export const cloneVNode = vendor.cloneVNode;
export const isVNode = vendor.isVNode;
export const withCtx = vendor.withCtx;
export const withDirectives = vendor.withDirectives;
export const withModifiers = vendor.withModifiers;
export const withKeys = vendor.withKeys;
export const withMemo = vendor.withMemo;
export const withScopeId = vendor.withScopeId;
export const normalizeClass = vendor.normalizeClass;
export const normalizeStyle = vendor.normalizeStyle;
export const normalizeProps = vendor.normalizeProps;
export const toDisplayString = vendor.toDisplayString;
export const toHandlers = vendor.toHandlers;
export const resolveComponent = vendor.resolveComponent;
export const resolveDirective = vendor.resolveDirective;
export const resolveDynamicComponent = vendor.resolveDynamicComponent;
export const resolveFilter = vendor.resolveFilter;
export const guardReactiveProps = vendor.guardReactiveProps;
export const setBlockTracking = vendor.setBlockTracking;
export const pushScopeId = vendor.pushScopeId;
export const popScopeId = vendor.popScopeId;
export const renderList = vendor.renderList;
export const renderSlot = vendor.renderSlot;
export const vShow = vendor.vShow;
export const vModelText = vendor.vModelText;
export const vModelCheckbox = vendor.vModelCheckbox;
export const vModelRadio = vendor.vModelRadio;
export const vModelSelect = vendor.vModelSelect;
export const vModelDynamic = vendor.vModelDynamic;

// Version / misc.
export const version = vendor.version;

export default vendor;
