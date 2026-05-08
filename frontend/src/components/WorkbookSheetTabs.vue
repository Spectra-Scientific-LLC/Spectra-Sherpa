<template>
  <div class="sheet-tabs-shell">
    <button
      v-if="showScrollButtons"
      type="button"
      class="sheet-scroll-btn"
      aria-label="Scroll sheets left"
      @click="scrollByAmount(-180)"
    >
      <i class="pi pi-chevron-left"></i>
    </button>
    <button
      v-if="showScrollButtons"
      type="button"
      class="sheet-scroll-btn"
      aria-label="Scroll sheets right"
      @click="scrollByAmount(180)"
    >
      <i class="pi pi-chevron-right"></i>
    </button>

    <div ref="tabsScroller" class="sheet-tabs-scroller" @wheel.prevent="onWheel">
      <div class="sheet-tabs" @dragover.prevent>
        <template v-for="(sheet, index) in sheets" :key="sheet.workflowId">
          <div
            v-if="dropIndex === index"
            class="sheet-drop-line"
          ></div>
          <button
            type="button"
            class="sheet-tab"
            :class="{ active: index === activeIndex, trial: sheet.kind === 'trial' }"
            :title="sheet.name"
            :style="tabStyle(sheet, index === activeIndex)"
            :draggable="sheet.kind !== 'trial' && !hasTrialSheets"
            @click="emit('switch', index)"
            @dblclick="startRename(index)"
            @contextmenu.prevent="openMenu($event, index)"
            @dragstart="onDragStart(index)"
            @dragenter.prevent="dropIndex = index"
            @dragover.prevent
            @drop.prevent="onDrop(index)"
          >
            <i v-if="sheet.executionStatus === 'running'" class="pi pi-spin pi-spinner status-icon"></i>
            <i v-else-if="sheet.executionStatus === 'success'" class="pi pi-check status-icon success"></i>
            <i v-else-if="sheet.executionStatus === 'error'" class="pi pi-times status-icon error"></i>
            <span v-else-if="hasUnsavedChanges && index === activeIndex" class="dirty-dot"></span>
            <input
              v-if="editingIndex === index"
              ref="renameInput"
              v-model="draftName"
              class="sheet-rename-input"
              maxlength="40"
              @click.stop
              @keydown.enter.prevent="commitRename"
              @keydown.esc.prevent="cancelRename"
              @blur="commitRename"
            />
            <span v-else class="sheet-tab-label">
              <i v-if="sheet.colorSource === 'ai'" class="pi pi-sparkles" style="color: #a855f7; font-size: 0.7rem; margin-right: 4px;" aria-hidden="true"></i>
              {{ sheet.name }}
            </span>
          </button>
        </template>
        <div v-if="dropIndex === sheets.length" class="sheet-drop-line"></div>
      </div>
    </div>

    <button
      type="button"
      class="sheet-add-btn"
      aria-label="Add sheet"
      title="Add sheet"
      @click="toggleAddMenu"
    >
      <i class="pi pi-plus"></i>
    </button>
    <Menu ref="addMenuRef" :model="addMenuItems" :popup="true" />

    <div
      v-if="menu.visible && menu.index !== null"
      class="sheet-context-menu"
      :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
      @click.stop
    >
      <button v-if="!isTrialSheet(menu.index)" type="button" @click="duplicate(menu.index)">
        <i class="pi pi-copy"></i>
        Duplicate
      </button>
      <button v-if="!isTrialSheet(menu.index)" type="button" @click="renameFromMenu(menu.index)">
        <i class="pi pi-pencil"></i>
        Rename
      </button>
      <div v-if="!isTrialSheet(menu.index)" class="sheet-menu-label">Tab Color</div>
      <div v-if="!isTrialSheet(menu.index)" class="sheet-swatches">
        <button
          v-for="color in COLORS"
          :key="color"
          type="button"
          class="sheet-swatch"
          :style="{ backgroundColor: color }"
          :aria-label="`Set tab color ${color}`"
          @click="setColor(menu.index, color)"
        ></button>
      </div>
      <div class="sheet-menu-separator"></div>
      <button
        type="button"
        :disabled="!isTrialSheet(menu.index) && workflowSheetCount <= 1"
        class="danger"
        @click="requestDelete(menu.index)"
      >
        <i :class="isTrialSheet(menu.index) ? 'pi pi-times' : 'pi pi-trash'"></i>
        {{ isTrialSheet(menu.index) ? "Close Trial" : "Delete" }}
      </button>
    </div>

    <Dialog v-model:visible="deleteDialogVisible" modal header="Delete Sheet" :style="{ width: '28rem' }">
      <p class="delete-message">
        Delete "{{ pendingDeleteSheet?.name }}"? This workflow and its execution history will be permanently deleted.
      </p>
      <template #footer>
        <Button label="Cancel" text @click="deleteDialogVisible = false" />
        <Button label="Delete" icon="pi pi-trash" severity="danger" @click="confirmDelete" />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import Menu from "primevue/menu";
import type { WorkbookSheet } from "@/stores/workbook";

const COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b4513", "#64748b"];
const CANVAS_BACKGROUND = "#1e293b";

const props = defineProps<{
  sheets: WorkbookSheet[];
  activeIndex: number;
  hasUnsavedChanges?: boolean;
}>();

const emit = defineEmits<{
  switch: [index: number];
  add: [];
  duplicate: [workflowId: number];
  rename: [workflowId: number, name: string];
  color: [workflowId: number, color: string | null];
  reorder: [orderedIds: number[]];
  delete: [workflowId: number];
}>();

const tabsScroller = ref<HTMLElement | null>(null);
const renameInput = ref<HTMLInputElement | null>(null);
const showScrollButtons = ref(false);
const editingIndex = ref<number | null>(null);
const draftName = ref("");
const previousName = ref("");
const draggedIndex = ref<number | null>(null);
const dropIndex = ref<number | null>(null);
const renameAfterAdd = ref(false);
const deleteDialogVisible = ref(false);
const pendingDeleteIndex = ref<number | null>(null);

const menu = reactive({
  visible: false,
  index: null as number | null,
  x: 0,
  y: 0,
});

const pendingDeleteSheet = computed(() =>
  pendingDeleteIndex.value === null ? null : props.sheets[pendingDeleteIndex.value] ?? null
);
const hasTrialSheets = computed(() => props.sheets.some((sheet) => sheet.kind === "trial"));
const workflowSheetCount = computed(() => props.sheets.filter((sheet) => sheet.kind !== "trial").length);

function isTrialSheet(index: number | null): boolean {
  return index !== null && props.sheets[index]?.kind === "trial";
}

function updateOverflow(): void {
  const el = tabsScroller.value;
  showScrollButtons.value = !!el && el.scrollWidth > el.clientWidth + 4;
}

function scrollByAmount(amount: number): void {
  tabsScroller.value?.scrollBy({ left: amount, behavior: "smooth" });
}

function onWheel(event: WheelEvent): void {
  tabsScroller.value?.scrollBy({ left: event.deltaY || event.deltaX });
}

function tabStyle(sheet: WorkbookSheet, active: boolean): Record<string, string> {
  const style: Record<string, string> = {
    backgroundColor: CANVAS_BACKGROUND,
  };
  if (!sheet.tabColor) return style;
  return {
    ...style,
    boxShadow: `inset 0 3px 0 ${sheet.tabColor}`,
    borderColor: active ? "#334155" : "#475569",
  };
}

function focusRenameInput(): void {
  nextTick(() => {
    const input = Array.isArray(renameInput.value) ? renameInput.value[0] : renameInput.value;
    input?.focus();
    input?.select();
  });
}

function startRename(index: number): void {
  const sheet = props.sheets[index];
  if (!sheet || sheet.kind === "trial") return;
  closeMenu();
  editingIndex.value = index;
  draftName.value = sheet.name;
  previousName.value = sheet.name;
  focusRenameInput();
}

function commitRename(): void {
  if (editingIndex.value === null) return;
  const sheet = props.sheets[editingIndex.value];
  const nextName = draftName.value.trim().slice(0, 40);
  if (sheet && nextName && nextName !== previousName.value) {
    emit("rename", sheet.workflowId, nextName);
  }
  editingIndex.value = null;
}

function cancelRename(): void {
  draftName.value = previousName.value;
  editingIndex.value = null;
}

function addSheet(): void {
  if (editingIndex.value !== null) {
    commitRename();
  }
  renameAfterAdd.value = true;
  emit("add");
}

const addMenuRef = ref<any>(null);

const addMenuItems = computed(() => {
  return [
    {
      label: "Blank Sheet",
      icon: "pi pi-file",
      command: () => {
        addSheet();
      }
    },
    {
      label: "Duplicate Current",
      icon: "pi pi-copy",
      command: () => {
        const active = props.sheets[props.activeIndex];
        if (active && active.kind !== "trial") {
          emit("duplicate", active.workflowId);
        }
      }
    }
  ];
});

function toggleAddMenu(event: Event): void {
  const active = props.sheets[props.activeIndex];
  if (active?.kind === 'trial') {
    addSheet();
  } else {
    addMenuRef.value?.toggle(event);
  }
}

function openMenu(event: MouseEvent, index: number): void {
  menu.visible = true;
  menu.index = index;
  menu.x = event.clientX;
  menu.y = event.clientY;
}

function closeMenu(): void {
  menu.visible = false;
  menu.index = null;
}

function duplicate(index: number | null): void {
  if (index === null) return;
  const sheet = props.sheets[index];
  closeMenu();
  if (sheet) emit("duplicate", sheet.workflowId);
}

function renameFromMenu(index: number | null): void {
  if (index === null) return;
  startRename(index);
}

function setColor(index: number | null, color: string): void {
  if (index === null) return;
  const sheet = props.sheets[index];
  closeMenu();
  if (sheet) emit("color", sheet.workflowId, color);
}

function requestDelete(index: number | null): void {
  if (index === null) return;
  if (!isTrialSheet(index) && workflowSheetCount.value <= 1) return;
  pendingDeleteIndex.value = index;
  if (isTrialSheet(index)) {
    closeMenu();
    confirmDelete();
    return;
  }
  deleteDialogVisible.value = true;
  closeMenu();
}

function confirmDelete(): void {
  const sheet = pendingDeleteSheet.value;
  deleteDialogVisible.value = false;
  pendingDeleteIndex.value = null;
  if (sheet) emit("delete", sheet.workflowId);
}

function onDragStart(index: number): void {
  if (props.sheets[index]?.kind === "trial" || hasTrialSheets.value) return;
  draggedIndex.value = index;
}

function onDrop(index: number): void {
  if (hasTrialSheets.value || draggedIndex.value === null || draggedIndex.value === index) {
    draggedIndex.value = null;
    dropIndex.value = null;
    return;
  }
  const ordered = [...props.sheets];
  const [moved] = ordered.splice(draggedIndex.value, 1);
  ordered.splice(index, 0, moved);
  emit("reorder", ordered.map((sheet) => sheet.workflowId));
  draggedIndex.value = null;
  dropIndex.value = null;
}

function onDocumentClick(): void {
  closeMenu();
}

onMounted(() => {
  updateOverflow();
  window.addEventListener("resize", updateOverflow);
  document.addEventListener("click", onDocumentClick);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", updateOverflow);
  document.removeEventListener("click", onDocumentClick);
});

watch(
  () => props.sheets.length,
  (newLength, oldLength) => {
    nextTick(updateOverflow);
    if (renameAfterAdd.value && newLength > oldLength) {
      renameAfterAdd.value = false;
      startRename(props.activeIndex);
    }
  },
);

watch(() => props.activeIndex, () => nextTick(updateOverflow));
</script>

<style scoped>
.sheet-tabs-shell {
  align-items: flex-end;
  background: #1e293b;
  border: 1px solid #334155;
  border-bottom: 0;
  border-radius: 8px 8px 0 0;
  display: flex;
  gap: 0.25rem;
  min-height: 40px;
  padding: 0.35rem 0.5rem 0;
  position: relative;
}

.sheet-tabs-scroller {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}

.sheet-tabs-scroller::-webkit-scrollbar {
  display: none;
}

.sheet-tabs {
  align-items: flex-end;
  display: flex;
  min-width: max-content;
}

.sheet-tab,
.sheet-add-btn,
.sheet-scroll-btn {
  align-items: center;
  background: #1e293b;
  border: 1px solid #475569;
  color: #dbeafe;
  cursor: pointer;
  display: inline-flex;
  height: 30px;
  justify-content: center;
}

.sheet-tab {
  border-bottom: 0;
  border-radius: 6px 6px 0 0;
  font-size: 0.82rem;
  gap: 0.35rem;
  margin-right: 0.15rem;
  max-width: 9.5rem;
  min-width: 6.25rem;
  padding: 0 0.65rem;
  position: relative;
}

.sheet-tab.active {
  background: #1e293b;
  border-color: #334155;
  border-bottom: 1px solid #1e293b;
  color: #f8fafc;
  font-weight: 700;
  height: 36px;
  margin-bottom: -1px;
  z-index: 1;
}

.sheet-tab-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dirty-dot {
  background: #f8fafc;
  border-radius: 999px;
  height: 6px;
  flex: 0 0 auto;
  width: 6px;
}

.status-icon {
  font-size: 0.75rem;
  margin-right: 0.15rem;
}

.status-icon.success {
  color: #22c55e;
}

.status-icon.error {
  color: #ef4444;
}

.sheet-rename-input {
  background: #0f172a;
  border: 1px solid #60a5fa;
  border-radius: 4px;
  color: #f8fafc;
  font: inherit;
  max-width: 7.5rem;
  min-width: 5rem;
  padding: 0.1rem 0.25rem;
}

.sheet-add-btn,
.sheet-scroll-btn {
  border-radius: 4px;
  flex: 0 0 auto;
  height: 28px;
  margin-bottom: 4px;
  width: 28px;
}

.sheet-add-btn:hover,
.sheet-scroll-btn:hover,
.sheet-tab:hover {
  background: #334155;
  border-color: #64748b;
  color: #f8fafc;
}

.sheet-tab.active:hover {
  background: #1e293b;
  border-color: #334155;
}

.sheet-drop-line {
  background: #60a5fa;
  height: 32px;
  margin: 0 0.1rem;
  width: 2px;
}

.sheet-context-menu {
  background: #1e293b;
  border: 1px solid #475569;
  border-radius: 6px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.3);
  display: grid;
  gap: 0.15rem;
  min-width: 11rem;
  padding: 0.35rem;
  position: fixed;
  z-index: 50;
}

.sheet-context-menu button {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 4px;
  color: #cbd5e1;
  cursor: pointer;
  display: flex;
  gap: 0.5rem;
  padding: 0.45rem 0.55rem;
  text-align: left;
}

.sheet-context-menu button:hover:not(:disabled) {
  background: #3b82f6;
  color: #ffffff;
}

.sheet-context-menu button:disabled {
  color: #64748b;
  cursor: not-allowed;
}

.sheet-context-menu .danger {
  color: #ef4444;
}

.sheet-context-menu .danger:hover:not(:disabled) {
  background: #ef4444;
  color: #ffffff;
}

.sheet-menu-label {
  color: #94a3b8;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.35rem 0.55rem 0.1rem;
  text-transform: uppercase;
}

.sheet-swatches {
  display: flex;
  gap: 0.35rem;
  padding: 0.25rem 0.55rem 0.45rem;
}

.sheet-swatch {
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 999px !important;
  height: 18px;
  padding: 0 !important;
  width: 18px;
}

.sheet-menu-separator {
  border-top: 1px solid #334155;
  margin: 0.2rem 0;
}

.delete-message {
  color: #334155;
  line-height: 1.45;
  margin: 0;
}
</style>
