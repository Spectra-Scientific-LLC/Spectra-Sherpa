<template>
  <div class="plate-map-96">
    <div class="plate-header">
      <div class="row-label"></div>
      <div v-for="col in 12" :key="col" class="col-label">
        {{ col }}
      </div>
    </div>

    <div v-for="row in rows" :key="row" class="plate-row">
      <div class="row-label">{{ row }}</div>

      <div
        v-for="col in 12"
        :key="`${row}${col}`"
        class="well"
        :class="{
          'well-assigned': getWellValue(`${row}${col}`),
          'well-selected': selectedWell === `${row}${col}`,
        }"
        @click="onWellClick(`${row}${col}`)"
      >
        <div class="well-position">{{ row }}{{ col }}</div>
        <div v-if="getWellValue(`${row}${col}`)" class="well-content">
          {{ getWellValue(`${row}${col}`) }}
        </div>
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

interface PlateWell {
  well_position: string;
  mixture_id?: number | null;
  label?: string;
}

const props = defineProps<{
  wells: PlateWell[];
  selectedWell?: string | null;
  showLegend?: boolean;
}>();

const emit = defineEmits<{
  (e: "well-click", wellPosition: string): void;
}>();

const rows = ["A", "B", "C", "D", "E", "F", "G", "H"];

const wellMap = computed(() => {
  const map: Record<string, string> = {};
  props.wells.forEach((well) => {
    if (well.mixture_id) {
      map[well.well_position] = well.label || `Mix ${well.mixture_id}`;
    }
  });
  return map;
});

const getWellValue = (position: string) => {
  return wellMap.value[position] || null;
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
}

.plate-header {
  display: grid;
  grid-template-columns: 40px repeat(12, 1fr);
  gap: 4px;
  margin-bottom: 4px;
}

.row-label {
  width: 40px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 0.9rem;
  color: #475569;
}

.col-label {
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 0.9rem;
  color: #475569;
}

.plate-row {
  display: grid;
  grid-template-columns: 40px repeat(12, 1fr);
  gap: 4px;
}

.well {
  aspect-ratio: 1;
  border: 2px solid #cbd5e1;
  border-radius: 8px;
  background: #ffffff;
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
  border-color: #3b82f6;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.2);
  transform: scale(1.05);
}

.well-position {
  font-size: 0.65rem;
  color: #94a3b8;
  font-weight: 500;
}

.well-content {
  font-size: 0.7rem;
  color: #1e293b;
  font-weight: 600;
  text-align: center;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  width: 100%;
}

.well-assigned {
  background: #dbeafe;
  border-color: #3b82f6;
}

.well-selected {
  background: #bfdbfe;
  border-color: #1d4ed8;
  box-shadow: 0 0 0 3px rgba(29, 78, 216, 0.2);
}

.plate-legend {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  padding: 12px;
  background: #f8fafc;
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
  border: 2px solid #cbd5e1;
}

.legend-swatch.well-empty {
  background: #ffffff;
}

.legend-swatch.well-assigned {
  background: #dbeafe;
  border-color: #3b82f6;
}

@media (max-width: 1200px) {
  .well {
    padding: 2px;
  }

  .well-position {
    font-size: 0.6rem;
  }

  .well-content {
    font-size: 0.65rem;
  }
}
</style>
