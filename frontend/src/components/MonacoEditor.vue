<script setup lang="ts">
/**
 * Reusable Monaco Editor wrapper with Python syntax highlighting.
 *
 * Usage:
 *   <MonacoEditor v-model="code" language="python" :height="400" />
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

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

interface MonacoEditorInstance {
  getValue: () => string;
  setValue: (value: string) => void;
  onDidChangeModelContent: (listener: () => void) => void;
  updateOptions: (options: { readOnly: boolean }) => void;
  dispose: () => void;
}

interface MonacoNamespace {
  editor: {
    create: (
      element: HTMLElement,
      options: Record<string, unknown>,
    ) => MonacoEditorInstance;
  };
}

const containerRef = ref<HTMLDivElement | null>(null);
const fallbackValue = ref(props.modelValue);
const loadError = ref<string | null>(null);
let editor: MonacoEditorInstance | null = null;
let monaco: MonacoNamespace | null = null;

onMounted(async () => {
  try {
    // Lazy-load monaco via the loader when available.
    const moduleName = "@monaco-editor/loader";
    const loader = await import(/* @vite-ignore */ moduleName);
    monaco = await loader.default.init();
  } catch (error) {
    console.warn("[MonacoEditor] Falling back to textarea editor:", error);
    loadError.value = "Monaco editor is unavailable in this build. Using plain text fallback.";
    return;
  }

  if (!containerRef.value) return;
  if (!monaco) return;

  const monacoEditor = monaco.editor.create(containerRef.value, {
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
  editor = monacoEditor;

  // Emit changes
  monacoEditor.onDidChangeModelContent(() => {
    const value = monacoEditor.getValue();
    if (value !== props.modelValue) {
      emit("update:modelValue", value);
    }
  });
});

// Sync external changes into editor
watch(
  () => props.modelValue,
  (newVal) => {
    fallbackValue.value = newVal;
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

  const onFallbackInput = (event: Event) => {
    const target = event.target as HTMLTextAreaElement;
    fallbackValue.value = target.value;
    emit("update:modelValue", target.value);
  };
  </script>
  
  <template>
    <div v-if="loadError" class="monaco-fallback">
      <small class="fallback-message">{{ loadError }}</small>
      <textarea
        class="fallback-textarea"
        :style="{ height: heightStyle }"
        :value="fallbackValue"
        :readonly="readOnly"
        @input="onFallbackInput"
      />
    </div>
    <div
      v-else
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

.monaco-fallback {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.fallback-message {
  color: var(--text-color-secondary, #94a3b8);
}

.fallback-textarea {
  width: 100%;
  border: 1px solid var(--surface-border, #333);
  border-radius: 6px;
  padding: 0.75rem;
  background: var(--surface-ground, #0f172a);
  color: var(--text-color, #f8fafc);
  resize: vertical;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 0.9rem;
  line-height: 1.5;
}
</style>
