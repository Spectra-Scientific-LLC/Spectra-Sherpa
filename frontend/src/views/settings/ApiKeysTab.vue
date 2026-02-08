<template>
  <div class="api-keys-container">
    <!-- App Authentication Key -->
    <div class="key-section">
      <div class="section-header">
        <h3>App Authentication Key</h3>
        <span class="badge required">Required</span>
      </div>
      <p class="description">
        This key is required for authenticating with the local backend server (WebSocket connections, API requests).
        The default key is <code>default-local-key</code> for local development.
      </p>
      <div class="field">
        <label for="app-key">App API Key</label>
        <InputText
          id="app-key"
          v-model="appApiKey"
          placeholder="default-local-key"
          class="key-input"
          autocomplete="off"
        />
      </div>
      <div class="actions">
        <Button
          label="Save App Key"
          icon="pi pi-save"
          :loading="savingApp"
          :disabled="!appApiKey.trim() || savingApp"
          @click="saveAppKey"
        />
      </div>
      <div v-if="appMessage" class="message success">
        <i class="pi pi-check-circle" />
        {{ appMessage }}
      </div>
      <div v-if="appError" class="message error">
        <i class="pi pi-times-circle" />
        {{ appError }}
      </div>
    </div>

    <!-- LLM Provider Configuration -->
    <div class="key-section">
      <div class="section-header">
        <h3>AI Assistant / LLM Configuration</h3>
        <span class="badge optional">Optional</span>
      </div>
      <p class="description">
        Configure your LLM provider for AI assistant features (workflow suggestions, code generation, peak identification).
        DeepSeek is preconfigured but you can change to another OpenAI-compatible provider.
      </p>

      <!-- LLM Provider Selection -->
      <div class="field">
        <label for="llm-provider">LLM Provider</label>
        <Dropdown
          id="llm-provider"
          v-model="llmProvider"
          :options="llmProviders"
          optionLabel="label"
          optionValue="value"
          placeholder="Select LLM Provider"
          class="provider-dropdown"
        />
      </div>

      <!-- API Base URL -->
      <div class="field">
        <label for="llm-base-url">API Base URL</label>
        <InputText
          id="llm-base-url"
          v-model="llmBaseUrl"
          placeholder="https://api.deepseek.com"
          class="key-input"
          :disabled="llmProvider !== 'custom'"
        />
        <small class="hint">
          Base URL for the LLM API endpoint. Auto-configured for known providers.
        </small>
      </div>

      <!-- Model Name -->
      <div class="field">
        <label for="llm-model">Model Name</label>
        <InputText
          id="llm-model"
          v-model="llmModel"
          placeholder="deepseek-chat"
          class="key-input"
          :disabled="llmProvider !== 'custom'"
        />
        <small class="hint">
          Model identifier. Auto-configured for known providers.
        </small>
      </div>

      <!-- API Key -->
      <div class="field">
        <label for="llm-key">
          {{ llmProviderLabel }} API Key
          <span v-if="isCurrentProviderKeySaved" class="saved-indicator">
            <i class="pi pi-check-circle" /> Saved
          </span>
        </label>
        <div class="password-input-wrapper">
          <InputText
            id="llm-key"
            v-model="llmApiKey"
            :type="showLlmKey ? 'text' : 'password'"
            :placeholder="isCurrentProviderKeySaved ? 'Leave empty to keep existing key' : `Enter your ${llmProviderLabel} API key`"
            class="key-input"
            autocomplete="off"
          />
          <Button
            :icon="showLlmKey ? 'pi pi-eye-slash' : 'pi pi-eye'"
            class="p-button-text p-button-sm toggle-visibility"
            @click="showLlmKey = !showLlmKey"
            v-tooltip.left="showLlmKey ? 'Hide key' : 'Show key'"
          />
        </div>
        <small class="hint">
          <span v-if="isCurrentProviderKeySaved">
            API key already saved. Enter a new key to update it, or leave empty to keep the existing one.
          </span>
          <span v-else>
            Get your API key from
            <a :href="llmProviderUrl" target="_blank" rel="noopener">{{ llmProviderUrl }}</a>
          </span>
        </small>
      </div>

      <!-- Verbose Mode -->
      <div class="field">
        <div class="switch-field">
          <InputSwitch v-model="llmVerbose" inputId="llm-verbose" />
          <label for="llm-verbose">Verbose Responses</label>
        </div>
        <small class="hint">
          When disabled, AI responses will be limited to 2 paragraphs for brevity.
        </small>
      </div>

      <div class="actions">
        <Button
          label="Save LLM Configuration"
          icon="pi pi-save"
          :loading="savingLlm"
          :disabled="(!llmApiKey.trim() && !isCurrentProviderKeySaved) || savingLlm"
          @click="saveLlmKey"
        />
        <Button
          v-if="hasLlmKey"
          label="Test Connection"
          icon="pi pi-bolt"
          class="p-button-outlined"
          :loading="testing"
          :disabled="testing"
          @click="testLlmConnection"
        />
      </div>
      <div v-if="llmMessage" class="message success">
        <i class="pi pi-check-circle" />
        {{ llmMessage }}
      </div>
      <div v-if="llmError" class="message error">
        <i class="pi pi-times-circle" />
        {{ llmError }}
      </div>
    </div>

    <!-- Current Saved Keys -->
    <div class="key-section">
      <h3>Saved API Keys</h3>
      <p class="description">
        API keys currently stored in the database (encrypted).
      </p>
      <div v-if="loading" class="loading-state">
        <i class="pi pi-spin pi-spinner" />
        Loading saved keys...
      </div>
      <div v-else-if="savedKeys.length === 0" class="empty-state">
        <i class="pi pi-info-circle" />
        No API keys configured yet.
      </div>
      <div v-else class="saved-keys-list">
        <div v-for="keyInfo in savedKeys" :key="keyInfo.service_name" class="key-item">
          <div class="key-info">
            <span class="service-name">{{ formatServiceName(keyInfo.service_name) }}</span>
            <span v-if="keyInfo.last_used_at" class="last-used">
              Last used: {{ formatDate(keyInfo.last_used_at) }}
            </span>
            <span v-else class="last-used">Never used</span>
          </div>
          <Button
            icon="pi pi-trash"
            class="p-button-text p-button-sm p-button-danger"
            @click="deleteKey(keyInfo.service_name)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import InputSwitch from "primevue/inputswitch";
import Dropdown from "primevue/dropdown";
import api from "@/api/client";

interface SavedKeyInfo {
  service_name: string;
  last_used_at: string | null;
}

const appApiKey = ref(localStorage.getItem("api_key") || "");
const llmProvider = ref("deepseek");
const llmBaseUrl = ref("https://api.deepseek.com");
const llmModel = ref("deepseek-chat"); // Cost-effective default
const llmApiKey = ref("");
const llmVerbose = ref(localStorage.getItem("llm_verbose") !== "false"); // Default true
const showLlmKey = ref(false);

const appMessage = ref("");
const appError = ref("");
const llmMessage = ref("");
const llmError = ref("");

const savingApp = ref(false);
const savingLlm = ref(false);
const testing = ref(false);
const loading = ref(true);

const savedKeys = ref<SavedKeyInfo[]>([]);
const hasLlmKey = ref(false);

const llmProviders = [
  { label: "DeepSeek", value: "deepseek" },
  { label: "OpenAI", value: "openai" },
  { label: "Google Gemini", value: "gemini" },
  { label: "Custom (OpenAI-compatible)", value: "custom" },
];

const llmProviderLabel = computed(() => {
  const provider = llmProviders.find(p => p.value === llmProvider.value);
  return provider?.label || "LLM";
});

const isCurrentProviderKeySaved = computed(() => {
  const serviceName = llmProvider.value === "custom" ? "custom_llm" : llmProvider.value;
  return savedKeys.value.some(k => k.service_name === serviceName);
});

const llmProviderUrl = computed(() => {
  switch (llmProvider.value) {
    case "deepseek":
      return "https://platform.deepseek.com/api_keys";
    case "openai":
      return "https://platform.openai.com/api-keys";
    case "gemini":
      return "https://aistudio.google.com/apikey";
    default:
      return "#";
  }
});

// Watch provider changes to update defaults
watch(llmProvider, (newProvider) => {
  if (newProvider === "deepseek") {
    llmBaseUrl.value = "https://api.deepseek.com";
    llmModel.value = "deepseek-chat";
  } else if (newProvider === "openai") {
    llmBaseUrl.value = "https://api.openai.com/v1";
    llmModel.value = "gpt-5-mini";
  } else if (newProvider === "gemini") {
    llmBaseUrl.value = "https://generativelanguage.googleapis.com/v1beta/openai/";
    llmModel.value = "gemini-2.5-flash";
  } else {
    // Custom - leave as is
  }

  // Clear API key field when switching providers to prevent confusion
  llmApiKey.value = "";
  llmMessage.value = "";
  llmError.value = "";
});

const formatServiceName = (service: string): string => {
  const names: Record<string, string> = {
    app: "App Authentication",
    deepseek: "DeepSeek LLM",
    openai: "OpenAI LLM",
    gemini: "Google Gemini LLM",
  };
  return names[service] || service;
};

const formatDate = (dateStr: string | null): string => {
  if (!dateStr) return "Never";
  const date = new Date(dateStr);
  return date.toLocaleString();
};

const loadSavedKeys = async () => {
  loading.value = true;
  try {
    const response = await api.get("/api-keys");
    savedKeys.value = response.data;
    hasLlmKey.value = savedKeys.value.some(k =>
      k.service_name === "deepseek" ||
      k.service_name === "openai" ||
      k.service_name === "gemini"
    );

    // Load LLM configuration
    try {
      const configResponse = await api.get("/llm-config");
      if (configResponse.data) {
        llmProvider.value = configResponse.data.provider;
        llmBaseUrl.value = configResponse.data.base_url;
        llmModel.value = configResponse.data.model;
        llmVerbose.value = configResponse.data.verbose;
      }
    } catch (error) {
      console.log("No LLM config found, using defaults");
    }
  } catch (error) {
    console.error("Failed to load saved keys:", error);
  } finally {
    loading.value = false;
  }
};

const saveAppKey = async () => {
  const previousKey = localStorage.getItem("api_key") || "";
  appMessage.value = "";
  appError.value = "";
  savingApp.value = true;

  try {
    if (appApiKey.value.trim()) {
      await api.post(
        "/api-keys",
        { service_name: "app", key: appApiKey.value.trim() },
        { headers: { "X-API-Key": previousKey || appApiKey.value.trim() } }
      );
    }
    localStorage.setItem("api_key", appApiKey.value.trim());
    appMessage.value = "App API key saved successfully!";
    await loadSavedKeys();
  } catch {
    appError.value = "Failed to save app API key. Please try again.";
  } finally {
    savingApp.value = false;
  }
};

const saveLlmKey = async () => {
  llmMessage.value = "";
  llmError.value = "";
  savingLlm.value = true;

  try {
    // Save the LLM API key (service_name will be "deepseek", "openai", "gemini", etc.)
    const serviceName = llmProvider.value === "custom" ? "custom_llm" : llmProvider.value;

    // Only save API key if a new one is provided
    if (llmApiKey.value.trim()) {
      await api.post("/api-keys", {
        service_name: serviceName,
        key: llmApiKey.value.trim(),
      });
    } else if (!isCurrentProviderKeySaved.value) {
      // If no key provided and no existing key, error
      llmError.value = `Please enter an API key for ${llmProviderLabel.value}.`;
      savingLlm.value = false;
      return;
    }

    // Save LLM configuration (provider, base_url, model, verbose) to backend
    await api.post("/llm-config", {
      provider: serviceName,
      base_url: llmBaseUrl.value,
      model: llmModel.value,
      verbose: llmVerbose.value,
    });

    llmMessage.value = `${llmProviderLabel.value} configuration saved successfully!`;
    hasLlmKey.value = true;

    // Clear the API key field after successful save
    llmApiKey.value = "";

    await loadSavedKeys();

    // Notify other components (like AI assistant) that config changed
    console.log('[Settings] Dispatching llm-config-changed event');
    window.dispatchEvent(new CustomEvent("llm-config-changed"));
  } catch (error: any) {
    llmError.value = `Failed to save ${llmProviderLabel.value} configuration. Please check your app authentication key.`;
    console.error("Save error:", error);
  } finally {
    savingLlm.value = false;
  }
};

const testLlmConnection = async () => {
  llmMessage.value = "";
  llmError.value = "";
  testing.value = true;

  try {
    const response = await api.post("/llm/chat", {
      message: "Hello, please respond with 'OK' to confirm connection.",
      conversation_id: null,
    });

    if (response.data.response) {
      llmMessage.value = `✓ LLM connection successful! Response: "${response.data.response.substring(0, 50)}..."`;
    }
  } catch (error: any) {
    if (error.response?.status === 401) {
      llmError.value = "Authentication failed. Please check your App API Key.";
    } else {
      llmError.value = `LLM connection failed: ${error.response?.data?.detail || error.message}`;
    }
  } finally {
    testing.value = false;
  }
};

const deleteKey = async (serviceName: string) => {
  if (!confirm(`Delete API key for ${formatServiceName(serviceName)}?`)) {
    return;
  }

  try {
    await api.delete(`/api-keys/${serviceName}`);
    await loadSavedKeys();

    if (serviceName === "deepseek" || serviceName === "openai" || serviceName === "gemini") {
      hasLlmKey.value = false;
    }
  } catch {
    alert("Failed to delete API key.");
  }
};

onMounted(async () => {
  await loadSavedKeys();
});
</script>

<style scoped>
.api-keys-container {
  display: flex;
  flex-direction: column;
  gap: 32px;
  max-width: 800px;
}

.key-section {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 24px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.section-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: #1f2937;
}

.badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.badge.required {
  background: #fee2e2;
  color: #991b1b;
}

.badge.optional {
  background: #dbeafe;
  color: #1e40af;
}

.description {
  margin: 0 0 20px;
  font-size: 0.9rem;
  color: #6b7280;
  line-height: 1.5;
}

.description code {
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.85rem;
  color: #1f2937;
}

.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  font-weight: 500;
  font-size: 0.9rem;
  color: #374151;
  margin-bottom: 6px;
}

.saved-indicator {
  margin-left: 8px;
  font-size: 0.75rem;
  font-weight: 500;
  color: #059669;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.saved-indicator i {
  font-size: 0.85rem;
}

.switch-field {
  display: flex;
  align-items: center;
  gap: 12px;
}

.switch-field label {
  margin: 0;
  cursor: pointer;
}

.key-input,
.provider-dropdown {
  width: 100%;
}

.password-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
}

.password-input-wrapper .key-input {
  flex: 1;
  padding-right: 48px;
}

.password-input-wrapper .toggle-visibility {
  position: absolute;
  right: 4px;
  color: #6b7280;
}

.password-input-wrapper .toggle-visibility:hover {
  color: #374151;
}

.hint {
  display: block;
  margin-top: 6px;
  font-size: 0.8rem;
  color: #9ca3af;
}

.hint a {
  color: #2563eb;
  text-decoration: none;
}

.hint a:hover {
  text-decoration: underline;
}

.hint code {
  background: #f3f4f6;
  padding: 2px 4px;
  border-radius: 3px;
  font-size: 0.75rem;
}

.actions {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}

.message {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding: 12px 16px;
  border-radius: 6px;
  font-size: 0.9rem;
}

.message.success {
  background: #d1fae5;
  color: #065f46;
  border: 1px solid #6ee7b7;
}

.message.error {
  background: #fee2e2;
  color: #991b1b;
  border: 1px solid #fca5a5;
}

.saved-keys-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.key-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.key-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.service-name {
  font-weight: 600;
  color: #1f2937;
}

.last-used {
  font-size: 0.8rem;
  color: #6b7280;
}

.loading-state,
.empty-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: #6b7280;
  font-size: 0.9rem;
}

.empty-state {
  background: #f9fafb;
  border: 1px dashed #d1d5db;
  border-radius: 6px;
}
</style>
