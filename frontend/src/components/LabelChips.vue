<template>
  <div class="label-chips">
    <Tag
      v-for="label in modelValue"
      :key="label"
      :value="label"
      severity="info"
      class="label-tag"
      :icon="!readonly ? 'pi pi-times' : undefined"
      @click="!readonly && removeLabel(label)"
    />
    <div v-if="!readonly && !adding" class="add-label">
      <Button
        icon="pi pi-plus"
        class="p-button-text p-button-sm p-button-rounded"
        title="Add label"
        @click="adding = true"
      />
    </div>
    <div v-if="adding" class="add-label-input">
      <InputText
        ref="inputRef"
        v-model="newLabel"
        placeholder="Label..."
        class="p-inputtext-sm"
        style="width: 100px"
        @keyup.enter="addLabel"
        @keyup.escape="cancelAdd"
        @blur="addLabel"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch } from "vue";
import Tag from "primevue/tag";
import Button from "primevue/button";
import InputText from "primevue/inputtext";

const props = withDefaults(
  defineProps<{
    modelValue: string[];
    readonly?: boolean;
  }>(),
  { readonly: false }
);

const emit = defineEmits<{
  "update:modelValue": [labels: string[]];
}>();

const adding = ref(false);
const newLabel = ref("");
const inputRef = ref<InstanceType<typeof InputText> | null>(null);

watch(adding, async (val) => {
  if (val) {
    await nextTick();
    const el = (inputRef.value as any)?.$el as HTMLElement | undefined;
    if (el) el.focus();
  }
});

function addLabel() {
  const trimmed = newLabel.value.trim();
  if (trimmed && !props.modelValue.includes(trimmed)) {
    emit("update:modelValue", [...props.modelValue, trimmed]);
  }
  newLabel.value = "";
  adding.value = false;
}

function removeLabel(label: string) {
  emit(
    "update:modelValue",
    props.modelValue.filter((l) => l !== label)
  );
}

function cancelAdd() {
  newLabel.value = "";
  adding.value = false;
}
</script>

<style scoped>
.label-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.label-tag {
  font-size: 0.7rem;
  cursor: pointer;
}

.add-label-input {
  display: inline-flex;
}
</style>
