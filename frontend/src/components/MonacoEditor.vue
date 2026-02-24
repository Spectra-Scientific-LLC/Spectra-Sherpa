<script setup lang="ts">
/**
 * Reusable Monaco Editor wrapper with Python syntax highlighting.
 *
 * Usage:
 *   <MonacoEditor v-model="code" language="python" :height="400" />
 */
import { ref, watch, onMounted, onBeforeUnmount, nextTick, computed } from "vue";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    language?: string;
    height?: number | string;
    readOnly?: boolean;
    theme?: string;
  }>(),
  {
    language: "python",
    height: 400,
    readOnly: false,
    theme: "vs-dark",
  }
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const containerRef = ref<HTMLDivElement>();
let editor: any = null;
let monaco: any = null;

onMounted(async () => {
  // Lazy-load monaco via the loader
  const loader = await import("@monaco-editor/loader");
  monaco = await loader.default.init();

  if (!containerRef.value) return;

  editor = monaco.editor.create(containerRef.value, {
    value: props.modelValue,
    language: props.language,
    theme: props.theme,
    readOnly: props.readOnly,
    minimap: { enabled: false },
    fontSize: 14,
    lineNumbers: "on",
    scrollBeyondLastLine: false,
    automaticLayout: true,
    tabSize: 4,
    insertSpaces: true,
    wordWrap: "on",
    padding: { top: 8, bottom: 8 },
  });

  // Emit changes
  editor.onDidChangeModelContent(() => {
    const value = editor.getValue();
    if (value !== props.modelValue) {
      emit("update:modelValue", value);
    }
  });
});

// Sync external changes into editor
watch(
  () => props.modelValue,
  (newVal) => {
    if (editor && editor.getValue() !== newVal) {
      editor.setValue(newVal);
    }
  }
);

watch(
  () => props.readOnly,
  (newVal) => {
    if (editor) {
      editor.updateOptions({ readOnly: newVal });
    }
  }
);

  onBeforeUnmount(() => {
    if (editor) {
      editor.dispose();
      editor = null;
    }
  });
  
  const heightStyle = computed(() => {
    return typeof props.height === "number" ? `${props.height}px` : props.height;
  });
  </script>
  
  <template>
    <div
      ref="containerRef"
      class="monaco-editor-container"
      :style="{ height: heightStyle }"
    />
</template>

<style scoped>
.monaco-editor-container {
  width: 100%;
  border: 1px solid var(--surface-border, #333);
  border-radius: 6px;
  overflow: hidden;
}
</style>
