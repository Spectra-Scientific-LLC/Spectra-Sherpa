<template>
  <Dialog
    v-model:visible="visible"
    modal
    :draggable="false"
    :style="{ width: '480px' }"
    header="About SpectraSherpa"
    class="about-dialog"
  >
    <div class="about-body">
      <p class="about-tagline">Local-first chemometrics platform.</p>

      <div class="about-versions">
        <div class="about-version-row">
          <span class="about-label">Frontend bundle</span>
          <code class="about-value">{{ frontendVersion }}</code>
        </div>
        <div class="about-version-row">
          <span class="about-label">Backend package</span>
          <code class="about-value">{{ backendVersion ?? "—" }}</code>
        </div>
      </div>

      <div v-if="versionDrift" class="about-drift">
        <i class="pi pi-exclamation-triangle"></i>
        <div>
          <strong>Bundle drift detected.</strong>
          The frontend bundle and backend are on different versions.
          Hard-reload your browser (<kbd>Ctrl/Cmd</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>)
          to pick up the latest bundle.
        </div>
      </div>

      <ul class="about-links">
        <li>
          <i class="pi pi-globe"></i>
          <a href="https://spectrascientific.ai" target="_blank" rel="noopener">spectrascientific.ai</a>
        </li>
        <li>
          <i class="pi pi-book"></i>
          <a href="https://docs.spectrascientific.ai" target="_blank" rel="noopener">Documentation</a>
        </li>
        <li>
          <i class="pi pi-github"></i>
          <a href="https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa" target="_blank" rel="noopener">GitHub</a>
        </li>
      </ul>

      <p class="about-license">Released under the GNU AGPL v3.0 or later.</p>
    </div>

    <template #footer>
      <Button
        :label="copied ? 'Copied!' : 'Copy diagnostics'"
        :icon="copied ? 'pi pi-check' : 'pi pi-copy'"
        class="p-button-text"
        @click="copyDiagnostics"
      />
      <Button label="Close" icon="pi pi-times" @click="visible = false" autofocus />
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { ref } from "vue";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import { useAppVersion } from "@/composables/useAppVersion";

const visible = defineModel<boolean>("visible", { default: false });
const { frontendVersion, backendVersion, versionDrift } = useAppVersion();

const copied = ref(false);

const copyDiagnostics = async () => {
  const lines = [
    `SpectraSherpa diagnostics`,
    `Frontend bundle: ${frontendVersion}`,
    `Backend package: ${backendVersion.value ?? "unavailable"}`,
    `Drift: ${versionDrift.value ? "yes" : "no"}`,
    `User agent: ${navigator.userAgent}`,
    `URL: ${window.location.href}`,
    `Generated: ${new Date().toISOString()}`,
  ];
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    copied.value = true;
    setTimeout(() => (copied.value = false), 2000);
  } catch {
    // Clipboard write can fail in insecure contexts or sandboxed iframes.
    // Silently no-op; the user can still read the values off the dialog.
  }
};
</script>

<style scoped>
.about-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.about-tagline {
  margin: 0;
  color: #4b5563;
  font-size: 0.9rem;
}

.about-versions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 10px 12px;
}

.about-version-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
}

.about-label {
  color: #6b7280;
}

.about-value {
  font-family: "SF Mono", "Monaco", "Menlo", "Courier New", monospace;
  background: #ffffff;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid #e5e7eb;
  font-size: 0.8rem;
  color: #111827;
}

.about-drift {
  display: flex;
  gap: 10px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 0.85rem;
  color: #92400e;
}

.about-drift i {
  flex: 0 0 auto;
  margin-top: 2px;
}

.about-drift kbd {
  background: #fef3c7;
  border: 1px solid #fde68a;
  border-radius: 3px;
  padding: 1px 4px;
  font-family: inherit;
  font-size: 0.75rem;
}

.about-links {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.85rem;
}

.about-links li {
  display: flex;
  align-items: center;
  gap: 8px;
}

.about-links a {
  color: #2563eb;
  text-decoration: none;
}

.about-links a:hover {
  text-decoration: underline;
}

.about-license {
  margin: 0;
  color: #9ca3af;
  font-size: 0.75rem;
  border-top: 1px solid #f3f4f6;
  padding-top: 12px;
}
</style>
