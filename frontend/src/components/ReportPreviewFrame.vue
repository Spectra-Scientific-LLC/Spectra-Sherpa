<template>
  <iframe
    title="Report preview"
    :srcdoc="html"
    sandbox="allow-same-origin allow-popups"
  />
</template>

<script setup lang="ts">
// Documentation links may open a sandboxed tab. Report scripts, top navigation,
// forms, and escaping the sandbox remain forbidden.
defineProps<{ html: string }>();
</script>
