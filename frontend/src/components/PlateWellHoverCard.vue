<template>
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
import { nextTick, ref } from "vue";

interface PlateWellDetail {
  label: string;
  value: string;
}

export interface PlateWell {
  well_position: string;
  mixture_id?: number | null;
  label?: string;
  assigned?: boolean;
  tooltip?: string;
  excluded?: boolean;
  details?: PlateWellDetail[];
}

const hoverCard = ref<HTMLElement | null>(null);
const hoveredWell = ref<PlateWell | null>(null);
const hoverCardStyle = ref<Record<string, string>>({ left: "12px", top: "12px" });
let anchor: HTMLElement | null = null;
let fromFocus = false;
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

async function show(details: PlateWell | null, event: MouseEvent | FocusEvent, pointerMoved = false) {
  const current = event.currentTarget as HTMLElement | null;
  if (!details || !current) return;
  // Scrolling focused cells under a stationary pointer can emit mouseenter.
  // Only deliberate pointer motion may replace keyboard-owned context.
  if (event.type !== "focus" && fromFocus && document.activeElement === anchor && !pointerMoved) return;
  anchor = current;
  fromFocus = event.type === "focus";
  hoveredWell.value = details;
  await nextTick();
  if (anchor === current) positionHoverCard(current);
}
function hide() {
  hoveredWell.value = null;
  anchor = null;
  fromFocus = false;
}
function hidePointer() {
  if (!fromFocus) hide();
}
function viewportScrolled(viewport: HTMLElement | null) {
  if (fromFocus && anchor && viewport && document.activeElement === anchor) {
    const cell = anchor.getBoundingClientRect();
    const bounds = viewport.getBoundingClientRect();
    if (
      cell.bottom > bounds.top &&
      cell.top < bounds.bottom &&
      cell.right > bounds.left &&
      cell.left < bounds.right
    ) {
      positionHoverCard(anchor);
      return;
    }
  }
  hide();
}
defineExpose({ show, hide, hidePointer, viewportScrolled });
</script>

<style scoped>
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
</style>
