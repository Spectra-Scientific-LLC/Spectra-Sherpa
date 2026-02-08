<template>
  <section class="card">
    <h1>Logs</h1>
    <p>Recent application logs (localhost only).</p>
    <button class="secondary" @click="fetchLogs">Refresh</button>
    <div style="margin-top: 16px">
      <div v-if="error" style="color: #b91c1c">{{ error }}</div>
      <div v-for="entry in logs" :key="entry.timestamp" style="margin-top: 12px">
        <strong>{{ entry.level }}</strong>
        <span style="margin-left: 8px; color: #64748b">{{ entry.timestamp }}</span>
        <div style="white-space: pre-wrap">{{ entry.message }}</div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";

import api from "@/api/client";

const logs = ref<Array<{ timestamp: string; level: string; message: string }>>([]);
const error = ref("");

const fetchLogs = async () => {
  error.value = "";
  try {
    const response = await api.get("/logs");
    logs.value = response.data.logs || [];
  } catch (err) {
    error.value = "Unable to load logs. Check API key and server status.";
  }
};
</script>
