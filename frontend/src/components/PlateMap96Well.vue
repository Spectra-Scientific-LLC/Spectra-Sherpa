<template>
  <div class="plate-map-96">
    <div
      ref="viewport"
      class="plate-viewport"
      role="region"
      :aria-label="`${plateFormat.label} map`"
      tabindex="0"
      @scroll="hideWellDetails"
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
        <template v-for="(row, rowIndex) in plateFormat.rows" :key="row">
          <div
            class="row-label"
            :style="{ gridRow: rowIndex + 2, gridColumn: 1 }"
            aria-hidden="true"
          >
            {{ row }}
          </div>

          <div
            v-for="col in plateFormat.columns"
            :key="plateWellPosition(row, col)"
            class="well"
            :style="{ gridRow: rowIndex + 2, gridColumn: col + 1 }"
            :aria-label="getWellTitle(plateWellPosition(row, col))"
            :tabindex="interactive || getWellDetails(plateWellPosition(row, col)) ? 0 : -1"
            role="button"
            :class="{
              'well-assigned': getWellValue(plateWellPosition(row, col)),
              'well-excluded': isWellExcluded(plateWellPosition(row, col)),
              'well-collision': hasWellCollision(plateWellPosition(row, col)),
              'well-selected': selectedWell === plateWellPosition(row, col),
            }"
            @mouseenter="showWellDetails(plateWellPosition(row, col), $event)"
            @mouseleave="hideWellDetails"
            @focus="showWellDetails(plateWellPosition(row, col), $event)"
            @blur="hideWellDetails"
            @click="onWellClick(plateWellPosition(row, col))"
            @keydown.enter.prevent="onWellClick(plateWellPosition(row, col))"
            @keydown.space.prevent="onWellClick(plateWellPosition(row, col))"
          >
            <div class="well-position">{{ plateWellPosition(row, col) }}</div>
            <div v-if="getWellValue(plateWellPosition(row, col))" class="well-content">
              {{ getWellValue(plateWellPosition(row, col)) }}
            </div>
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

  <Teleport to="body">
    <aside
      v-if="hoveredWell"
      ref="hoverCard"
      class="plate-well-hover-card"
      :style="hoverCardStyle"
      role="tooltip"
    >
      <div class="hover-card-heading">
        <span class="hover-card-well">{{ hoveredWell.well_position }}</span>
        <strong>{{ hoveredWell.label || "Assigned sample" }}</strong>
      </div>
      <dl v-if="hoveredWell.details?.length" class="hover-card-details">
        <template v-for="detail in hoveredWell.details" :key="detail.label">
          <dt>{{ detail.label }}</dt>
          <dd>{{ detail.value || "—" }}</dd>
        </template>
      </dl>
      <p v-else class="hover-card-summary">
        {{ hoveredWell.tooltip || hoveredWell.label || hoveredWell.well_position }}
      </p>
    </aside>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { defaultPlateFormatId, formatWell, getPlateFormat } from "@/utils/plateFormats";

interface PlateWellDetail {
  label: string;
  value: string;
}

interface PlateWell {
  well_position: string;
  mixture_id?: number | null;
  label?: string;
  assigned?: boolean;
  tooltip?: string;
  excluded?: boolean;
  details?: PlateWellDetail[];
}

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
const hoverCard = ref<HTMLElement | null>(null);
const hoveredWell = ref<PlateWell | null>(null);
const hoverCardStyle = ref<Record<string, string>>({ left: "12px", top: "12px" });

const plateWellPosition = (row: string, column: number) =>
  formatWell(plateFormat.value, plateFormat.value.rows.indexOf(row), column - 1);

watch(
  () => props.plateFormatId,
  () => {
    hoveredWell.value = null;
    if (viewport.value) {
      viewport.value.scrollTop = 0;
      viewport.value.scrollLeft = 0;
    }
  },
);

const wellsByPosition = computed(() => {
  const map = new Map<string, PlateWell[]>();
  props.wells.forEach((well) => {
    const position = well.well_position.toUpperCase();
    const entries = map.get(position) ?? [];
    entries.push(well);
    map.set(position, entries);
  });
  return map;
});

const collisionCount = computed(
  () => Array.from(wellsByPosition.value.values()).filter((entries) => entries.length > 1).length,
);

const getWellValue = (position: string) => {
  const entries = wellsByPosition.value.get(position.toUpperCase()) ?? [];
  if (entries.length > 1) return `${entries.length} samples`;
  const well = entries[0];
  if (!well || (!well.assigned && !well.mixture_id && !well.label)) return null;
  return well.label || `Mix ${well.mixture_id}`;
};

const getWellTitle = (position: string) => {
  const entries = wellsByPosition.value.get(position.toUpperCase()) ?? [];
  if (entries.length > 1) return `${position}: ${entries.length} conflicting sample assignments`;
  return entries[0]?.tooltip || getWellValue(position) || position;
};

const getWellDetails = (position: string): PlateWell | null => {
  const entries = wellsByPosition.value.get(position.toUpperCase()) ?? [];
  if (entries.length === 0) return null;
  if (entries.length === 1) return entries[0];
  return {
    well_position: position,
    assigned: true,
    label: `${entries.length} conflicting samples`,
    tooltip: "Resolve the duplicate physical assignment before saving.",
    details: entries.map((entry, index) => ({
      label: `Sample ${index + 1}`,
      value: entry.label || entry.tooltip || "Unnamed sample",
    })),
  };
};

const isWellExcluded = (position: string) =>
  (wellsByPosition.value.get(position.toUpperCase()) ?? []).some((well) => well.excluded);

const hasWellCollision = (position: string) =>
  (wellsByPosition.value.get(position.toUpperCase())?.length ?? 0) > 1;

const positionHoverCard = (anchor: HTMLElement) => {
  const card = hoverCard.value;
  if (!card) return;
  const anchorRect = anchor.getBoundingClientRect();
  const gap = 10;
  const viewportPadding = 12;
  const cardWidth = card.offsetWidth || 300;
  const cardHeight = card.offsetHeight || 240;

  let left = anchorRect.right + gap;
  if (left + cardWidth > window.innerWidth - viewportPadding) {
    left = anchorRect.left - cardWidth - gap;
  }
  left = Math.max(viewportPadding, Math.min(left, window.innerWidth - cardWidth - viewportPadding));

  let top = anchorRect.top;
  if (top + cardHeight > window.innerHeight - viewportPadding) {
    top = anchorRect.bottom - cardHeight;
  }
  top = Math.max(viewportPadding, Math.min(top, window.innerHeight - cardHeight - viewportPadding));

  hoverCardStyle.value = { left: `${Math.round(left)}px`, top: `${Math.round(top)}px` };
};

const showWellDetails = async (position: string, event: MouseEvent | FocusEvent) => {
  const details = getWellDetails(position);
  const anchor = event.currentTarget as HTMLElement | null;
  if (!details || !anchor) return;
  hoveredWell.value = details;
  await nextTick();
  positionHoverCard(anchor);
};

const hideWellDetails = () => {
  hoveredWell.value = null;
};

const onWellClick = (position: string) => {
  emit("well-click", position);
};
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

.plate-well-hover-card {
  position: fixed;
  z-index: 12000;
  width: min(20rem, calc(100vw - 24px));
  max-height: calc(100vh - 24px);
  overflow: hidden;
  padding: 0.85rem;
  border: 1px solid var(--ss-action-tint);
  border-radius: 0.75rem;
  background: color-mix(in srgb, var(--ss-surface) 98%, transparent);
  box-shadow: 0 14px 34px color-mix(in srgb, var(--ss-shadow-color) 22%, transparent);
  color: var(--ss-text-strong);
  font-size: 0.82rem;
  pointer-events: none;
}

.hover-card-heading {
  display: flex;
  align-items: baseline;
  gap: 0.55rem;
  padding-bottom: 0.55rem;
  border-bottom: 1px solid var(--ss-border);
}

.hover-card-well {
  padding: 0.15rem 0.4rem;
  border-radius: 0.35rem;
  background: var(--ss-action-tint);
  color: var(--ss-action);
  font-size: 0.78rem;
  font-weight: 700;
}

.hover-card-details {
  display: grid;
  grid-template-columns: minmax(5.5rem, auto) minmax(0, 1fr);
  gap: 0.35rem 0.75rem;
  margin: 0.65rem 0 0;
  font-size: 0.82rem;
}

.hover-card-details dt {
  color: var(--ss-text-muted);
}

.hover-card-details dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}

.hover-card-summary {
  margin: 0.65rem 0 0;
  font-size: 0.82rem;
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
