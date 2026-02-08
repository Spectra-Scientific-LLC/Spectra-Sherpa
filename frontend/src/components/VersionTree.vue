<template>
  <div class="version-tree">
    <div v-if="flatNodes.length === 0" class="version-tree__empty">
      No versions yet.
    </div>
    <div v-for="node in flatNodes" :key="node.id" class="version-tree__row">
      <div class="version-tree__label" :style="{ paddingLeft: `${node.level * 18}px` }">
        <span class="version-tree__dot"></span>
        <div>
          <strong>{{ node.version_name }}</strong>
          <div class="version-tree__meta">
            <span>{{ node.created_at }}</span>
            <span v-if="node.file_count">- {{ node.file_count }} files</span>
          </div>
          <div v-if="node.description" class="version-tree__desc">
            {{ node.description }}
          </div>
        </div>
      </div>
      <button class="version-tree__restore" @click="emitRestore(node.version_name)">
        Restore
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { VersionInfo } from "@/types";

interface FlatNode extends VersionInfo {
  level: number;
  children: FlatNode[];
}

const props = defineProps<{
  versions: VersionInfo[];
}>();

const emit = defineEmits<{
  (event: "restore", versionName: string): void;
}>();

const buildTree = (versions: VersionInfo[]): FlatNode[] => {
  const map = new Map<number, FlatNode>();
  versions.forEach((version) => {
    map.set(version.id, { ...version, level: 0, children: [] });
  });
  const roots: FlatNode[] = [];
  map.forEach((node) => {
    if (node.parent_version_id && map.has(node.parent_version_id)) {
      map.get(node.parent_version_id)?.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
};

const flatten = (nodes: FlatNode[], level = 0, acc: FlatNode[] = []): FlatNode[] => {
  nodes.forEach((node) => {
    const entry: FlatNode = { ...node, level, children: node.children };
    acc.push(entry);
    if (node.children.length > 0) {
      flatten(node.children, level + 1, acc);
    }
  });
  return acc;
};

const flatNodes = computed(() => {
  const roots = buildTree([...props.versions].reverse());
  return flatten(roots);
});

const emitRestore = (versionName: string) => {
  emit("restore", versionName);
};
</script>

<style scoped>
.version-tree {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.version-tree__row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.version-tree__label {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.version-tree__dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 999px;
  background: #2563eb;
  flex-shrink: 0;
}

.version-tree__meta {
  color: #64748b;
  font-size: 0.85rem;
  margin-top: 4px;
}

.version-tree__desc {
  margin-top: 4px;
  font-size: 0.9rem;
}

.version-tree__restore {
  padding: 6px 12px;
  border-radius: 8px;
  border: none;
  background: #f97316;
  color: white;
  cursor: pointer;
}

.version-tree__empty {
  color: #94a3b8;
}
</style>
