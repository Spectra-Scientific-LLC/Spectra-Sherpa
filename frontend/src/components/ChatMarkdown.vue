<template>
  <VueMarkdown
    class="chat-markdown"
    :source="normalizedSource"
    :options="markdownOptions"
    :plugins="markdownPlugins"
  />
</template>

<script setup lang="ts">
import { computed } from "vue";
import katex from "katex";
import texmath from "markdown-it-texmath";
import VueMarkdown from "vue-markdown-render";
import { normalizeMathMarkdown } from "@/utils/mathMarkdown";

import "katex/dist/katex.min.css";

const props = defineProps<{
  source: string;
}>();

const normalizedSource = computed(() => normalizeMathMarkdown(props.source));

const markdownOptions = {
  breaks: true,
  linkify: true,
};

const katexOptions = {
  throwOnError: false,
  strict: "ignore" as const,
};

const markdownPlugins = [
  (md: { use: (plugin: unknown, options?: Record<string, unknown>) => void }) => {
    md.use(texmath, {
      engine: katex,
      delimiters: "dollars",
      katexOptions,
    });
    md.use(texmath, {
      engine: katex,
      delimiters: "brackets",
      katexOptions,
    });
  },
];
</script>
