<template>
  <div class="plate-map-96">
    <div
      ref="viewport"
      class="plate-viewport"
      role="region"
      :aria-label="`${plateFormat.label} map`"
      tabindex="0"
      @scroll="detailsCard?.viewportScrolled(viewport)"
      @keydown="navigateWells"
    >
      <div
        class="plate-grid"
        :style="{
          gridTemplateColumns: `40px repeat(${plateFormat.columns}, 64px)`,
          gridTemplateRows: `32px repeat(${plateFormat.rows.length}, 64px)`,
        }"
      >
        <div class="plate-corner" aria-hidden="true"></div>
        <div
          v-for="col in plateFormat.columns"
          :key="`column-${col}`"
          class="col-label"
          :style="{ gridRow: 1, gridColumn: col + 1 }"
          aria-hidden="true"
        >
          {{ col }}
        </div>
        <template v-for="row in plateRows" :key="row.label">
          <div
            class="row-label"
            :style="{ gridRow: row.gridRow, gridColumn: 1 }"
            aria-hidden="true"
          >
            {{ row.label }}
          </div>
          <div
            v-for="cell in row.cells"
            :key="cell.position"
            class="well"
            :style="{ gridRow: row.gridRow, gridColumn: cell.gridColumn }"
            :aria-label="cell.title"
            tabindex="-1"
            :data-well-position="cell.position"
            role="button"
            :class="{
              'well-assigned': cell.label,
              'well-excluded': cell.excluded,
              'well-collision': cell.collision,
              'well-selected': selectedWell === cell.position,
            }"
            @mouseenter="detailsCard?.show(cell.details, $event)"
            @mousemove="detailsCard?.show(cell.details, $event, true)"
            @mouseleave="detailsCard?.hidePointer()"
            @focus="focusWell($event); detailsCard?.show(cell.details, $event)"
            @blur="detailsCard?.hide()"
            @click="emit('well-click', cell.position)"
            @keydown.enter.prevent="emit('well-click', cell.position)"
            @keydown.space.prevent="emit('well-click', cell.position)"
          >
            <div class="well-position">{{ cell.position }}</div>
            <div v-if="cell.label" class="well-content">{{ cell.label }}</div>
          </div>
        </template>
      </div>
    </div>
    <div v-if="showLegend" class="plate-legend">
      <div class="legend-item">
        <div class="legend-swatch well-empty"></div>
        <span>Empty</span>
      </div>
      <div class="legend-item">
        <div class="legend-swatch well-assigned"></div>
        <span>Assigned</span>
      </div>
      <div class="legend-item">
        <div class="legend-swatch well-excluded"></div>
        <span>Excluded</span>
      </div>
      <div v-if="collisionCount" class="legend-item">
        <div class="legend-swatch well-collision"></div>
        <span>{{ collisionCount }} collision{{ collisionCount === 1 ? "" : "s" }}</span>
      </div>
    </div>
  </div>
  <PlateWellHoverCard ref="detailsCard" />
</template>

<script setup lang="ts">
import { computed, onMounted, onUpdated, ref, watch } from "vue";
import { defaultPlateFormatId, formatWell, getPlateFormat } from "@/utils/plateFormats";
import PlateWellHoverCard, { type PlateWell } from "./PlateWellHoverCard.vue";

const props = defineProps<{
  wells: PlateWell[];
  selectedWell?: string | null;
  showLegend?: boolean;
  interactive?: boolean;
  plateFormatId?: string;
}>();

const emit = defineEmits<{
  (e: "well-click", wellPosition: string): void;
}>();

const plateFormat = computed(() => getPlateFormat(props.plateFormatId ?? defaultPlateFormatId));
const viewport = ref<HTMLElement | null>(null);
const detailsCard = ref<InstanceType<typeof PlateWellHoverCard> | null>(null);
watch(
  () => props.wells,
  () => detailsCard.value?.hide(),
);
watch(
  () => props.plateFormatId,
  () => {
    detailsCard.value?.hide();
    if (viewport.value) {
      viewport.value.scrollTop = 0;
      viewport.value.scrollLeft = 0;
    }
  },
);
const wellsByPosition = computed(() => {
  const map = new Map<string, PlateWell[]>();
  for (const well of props.wells) {
    const position = well.well_position.toUpperCase();
    const entries = map.get(position) ?? [];
    entries.push(well);
    map.set(position, entries);
  }
  return map;
});
const collisionCount = computed(
  () => [...wellsByPosition.value.values()].filter((entries) => entries.length > 1).length,
);
// Hover state is owned by the child; descriptors rebuild only for plate data/geometry.
const plateRows = computed(() =>
  plateFormat.value.rows.map((row, rowIndex) => ({
    label: row,
    gridRow: rowIndex + 2,
    cells: Array.from({ length: plateFormat.value.columns }, (_, colIndex) => {
      const position = formatWell(plateFormat.value, rowIndex, colIndex);
      const entries = wellsByPosition.value.get(position) ?? [];
      const well = entries[0];
      const collision = entries.length > 1;
      const label = collision
        ? `${entries.length} samples`
        : well && (well.assigned || well.mixture_id || well.label)
          ? well.label || `Mix ${well.mixture_id}`
          : null;
      const details: PlateWell | null = collision
        ? {
            well_position: position,
            assigned: true,
            label: `${entries.length} conflicting samples`,
            tooltip: "Resolve the duplicate physical assignment before saving.",
            details: entries.map((entry, index) => ({
              label: `Sample ${index + 1}`,
              value: entry.label || entry.tooltip || "Unnamed sample",
            })),
          }
        : (well ?? null);
      return {
        position,
        gridColumn: colIndex + 2,
        label,
        details,
        collision,
        excluded: entries.some((entry) => entry.excluded),
        title: collision
          ? `${position}: ${entries.length} conflicting sample assignments`
          : well?.tooltip || label || position,
      };
    }),
  })),
);
let focusedWellPosition: string | undefined;
function syncTabStops(): void {
  if (!viewport.value) return;
  const cells = [...viewport.value.querySelectorAll<HTMLElement>(".well")];
  const eligible = cells.filter(cell => props.interactive || wellsByPosition.value.has(cell.dataset.wellPosition!));
  const current = eligible.find(cell => cell === document.activeElement)
    ?? eligible.find(cell => cell.dataset.wellPosition === props.selectedWell)
    ?? eligible.find(cell => cell.dataset.wellPosition === focusedWellPosition)
    ?? eligible[0];
  cells.forEach(cell => { cell.tabIndex = cell === current ? 0 : -1; });
  viewport.value.tabIndex = current ? -1 : 0;
  focusedWellPosition = current?.dataset.wellPosition;
}
onMounted(syncTabStops);
onUpdated(syncTabStops);

// Rove DOM focus without rerendering the complete plate on every keypress.
function focusWell(event: FocusEvent): void {
  const target = event.currentTarget as HTMLElement;
  if (!props.interactive && !wellsByPosition.value.has(target.dataset.wellPosition!)) {
    syncTabStops();
    return;
  }
  viewport.value?.querySelectorAll<HTMLElement>('.well[tabindex="0"]').forEach(cell => {
    if (cell !== target) cell.tabIndex = -1;
  });
  target.tabIndex = 0;
  focusedWellPosition = target.dataset.wellPosition;
}

function navigateWells(event: KeyboardEvent): void {
  const target = event.target as HTMLElement;
  if (!target.classList.contains("well") || !viewport.value) return;
  const cells = [...viewport.value.querySelectorAll<HTMLElement>(".well")];
  const index = cells.indexOf(target), columns = plateFormat.value.columns;
  const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns, ArrowUp: -columns }[event.key];
  let next = index;
  if (step !== undefined) next += step;
  else if (event.key === "Home") next = event.ctrlKey ? 0 : Math.floor(index / columns) * columns;
  else if (event.key === "End") next = event.ctrlKey ? cells.length - 1 : Math.floor(index / columns) * columns + columns - 1;
  else return;
  event.preventDefault();
  // Read-only plates expose assigned wells only; empty cells remain available
  // to mouse users, and interactive authors can navigate every coordinate.
  const direction = event.key === "End" ? -1 : event.key === "Home" ? 1 : next >= index ? 1 : -1;
  while (next >= 0 && next < cells.length) {
    if (props.interactive || wellsByPosition.value.has(cells[next].dataset.wellPosition!)) {
      cells[next].focus();
      cells[next].scrollIntoView?.({ block: "nearest", inline: "nearest" });
      return;
    }
    next += step ?? direction;
  }
}
</script>

<style scoped>
.plate-map-96 {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
}

.plate-viewport {
  max-width: 100%;
  max-height: clamp(12rem, calc(100vh - 12rem), 34rem);
  overflow: auto;
  position: relative;
  isolation: isolate;
  border: 1px solid var(--ss-border);
  border-radius: 6px;
  scroll-padding: 36px 0 0 44px;
}

.plate-viewport:focus-visible {
  outline: 2px solid var(--ss-action);
  outline-offset: 2px;
}

.plate-grid {
  display: grid;
  width: max-content;
  gap: 4px;
}

.plate-corner {
  grid-area: 1 / 1;
  position: sticky;
  top: 0;
  left: 0;
  z-index: 3;
  background: var(--ss-surface);
}

.row-label {
  width: 40px;
  height: 64px;
  position: sticky;
  left: 0;
  z-index: 2;
  background: var(--ss-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--ss-text-secondary);
}

.col-label {
  height: 32px;
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--ss-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--ss-text-secondary);
}

.well {
  aspect-ratio: 1;
  border: 2px solid var(--ss-border-strong);
  border-radius: 8px;
  background: var(--ss-surface);
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4px;
  position: relative;
  overflow: hidden;
}

.well:hover {
  border-color: var(--ss-action);
  box-shadow: 0 2px 8px color-mix(in srgb, var(--ss-action) 20%, transparent);
}

.well-position {
  font-size: 0.65rem;
  color: var(--ss-text-muted);
  font-weight: 500;
}

.well-content {
  font-size: 0.7rem;
  color: var(--ss-text-strong);
  font-weight: 600;
  text-align: center;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  width: 100%;
}

.well-assigned {
  background: var(--ss-action-tint);
  border-color: var(--ss-action);
}

.well-excluded {
  background: var(--ss-surface-subtle);
  border-color: var(--ss-border-strong);
  opacity: 0.7;
}

.well-collision {
  background: var(--ss-danger-surface);
  border-color: var(--ss-danger);
  opacity: 1;
}

.well-selected {
  background: var(--ss-action-tint);
  border-color: var(--ss-action);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ss-action) 20%, transparent);
}

.plate-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
  padding: 12px;
  background: var(--ss-surface-subtle);
  border-radius: 6px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.legend-swatch {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 2px solid var(--ss-border-strong);
}

.legend-swatch.well-empty {
  background: var(--ss-surface);
}

.legend-swatch.well-assigned {
  background: var(--ss-action-tint);
  border-color: var(--ss-action);
}

.legend-swatch.well-excluded {
  background: var(--ss-surface-subtle);
  border-color: var(--ss-border-strong);
}

.legend-swatch.well-collision {
  background: var(--ss-danger-surface);
  border-color: var(--ss-danger);
}
</style>
