<template>
  <RouterView v-if="isPublicRoute" />
  <MainLayout v-else />
</template>

<script setup lang="ts">
import { computed } from "vue";
import { RouterView, useRoute } from "vue-router";

import MainLayout from "@/layouts/MainLayout.vue";

const route = useRoute();
const isPublicRoute = computed(() => Boolean(route.meta.public));
</script>
