<script lang="ts">
import { cloneVNode, defineComponent, Fragment, h, onBeforeUnmount, onMounted, onUpdated, useId, watch, type PropType, type VNode } from "vue";
import { useRoute } from "vue-router";
import TabView from "primevue/tabview";
import { useWorkspaceNavigation, type WorkspaceNavigationItem } from "@/composables/useWorkspaceNavigation";

function panels(nodes: VNode[]): VNode[] {
  return nodes.flatMap((node) => {
    if (node.type === Fragment && Array.isArray(node.children)) return panels(node.children as VNode[]);
    return typeof node.type === "object" && (node.type as { name?: string }).name === "TabPanel" ? [node] : [];
  });
}

export default defineComponent({
  props: {
    modelValue: { type: String, required: true },
    tabIds: { type: Array as PropType<readonly string[]>, required: true },
    // Custom visual headers can supply a plain-text navigation label.
    labels: { type: Object as PropType<Record<string, string>>, default: () => ({}) },
  },
  emits: { "update:modelValue": (_id: string) => true },
  setup(props, { slots, emit }) {
    const navigation = useWorkspaceNavigation();
    const route = navigation ? useRoute() : undefined;
    const owner = Symbol("workspace-tabs");
    const panelPrefix = useId();
    let items: WorkspaceNavigationItem[] = [];
    const select = (id: string) => {
      if (items.some((item) => item.id === id && !item.disabled)) emit("update:modelValue", id);
    };
    const publish = () => {
      if (navigation && route) navigation.publish(owner, {
        path: route.path, selected: props.modelValue, items, select,
      });
    };
    onMounted(publish);
    onUpdated(publish);
    // Router reuse can change the path without redrawing compiled stable slots.
    if (route) watch(() => route.path, publish, { flush: "post" });
    onBeforeUnmount(() => navigation?.release(owner));
    return () => {
      const content = slots.default?.() ?? [];
      const tabPanels = panels(content);
      items = tabPanels.map((panel, index) => ({
        id: props.tabIds[index],
        panelId: panelPrefix + "-" + props.tabIds[index],
        label: props.labels[props.tabIds[index]] ?? String(panel.props?.header ?? props.tabIds[index]),
        disabled: panel.props?.disabled === true || panel.props?.disabled === "",
      })).filter((item) => !!item.id);
      return h(TabView, {
        class: ["workspace-tabs", { "workspace-tabs--sidebar": !!navigation }],
        pt: navigation ? { root: { role: null }, navContainer: { hidden: true } } : undefined,
        activeIndex: Math.max(0, props.tabIds.indexOf(props.modelValue)),
        "onUpdate:activeIndex": (index: number) => select(props.tabIds[index]),
      }, { default: () => navigation ? tabPanels.map((panel, index) => cloneVNode(panel, {
        contentProps: {
          ...panel.props?.contentProps,
          id: items[index]?.panelId,
          role: "region",
          "aria-label": items[index]?.label,
          "aria-labelledby": undefined,
        },
      })) : content });
    };
  },
});
</script>
<style scoped>
.workspace-tabs,
.workspace-tabs :deep(.p-tabview-nav-container),
.workspace-tabs :deep(.p-tabview-nav-content),
.workspace-tabs :deep(.p-tabview-panels) {
  background: transparent;
}
.workspace-tabs :deep(.p-tabview-nav) {
  display: flex;
  justify-content: flex-start;
  gap: 0.375rem;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  background: transparent;
  margin: 0;
  padding: 0;
}
.workspace-tabs :deep(.p-tabview-nav li) {
  margin: 0;
  background: transparent;
}
.workspace-tabs :deep(.p-tabview-nav-link) {
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--text-color-secondary) 55%, var(--surface-border));
  border-radius: 6px 6px 0 0;
  margin-bottom: 0;
  color: var(--text-color-secondary);
  padding: 0.6rem 1rem;
  font-size: 0.9375rem;
  font-weight: 500;
}
.workspace-tabs :deep(.p-highlight .p-tabview-nav-link) {
  color: var(--primary-color);
  border-color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 8%, transparent);
}
.workspace-tabs :deep(.p-tabview-nav-link:focus-visible) {
  outline: 2px solid var(--primary-color);
  outline-offset: -2px;
}
.workspace-tabs :deep(.p-tabview-panels) {
  padding: 1.5rem 0 0;
}
.workspace-tabs--sidebar :deep(.p-tabview-nav-container) {
  display: none;
}
.workspace-tabs--sidebar :deep(.p-tabview-panels) {
  padding-top: 0;
}
</style>
