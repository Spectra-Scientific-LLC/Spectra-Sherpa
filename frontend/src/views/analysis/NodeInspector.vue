<template>
  <div class="node-inspector">
    <div class="inspector-header">
      <h3>Node Inspector</h3>
    </div>

    <div v-if="!selectedNode" class="empty-state">
      <i class="pi pi-info-circle"></i>
      <p>Select a node to view and edit its parameters</p>
    </div>

    <div v-else class="inspector-content">
      <!-- Node Info -->
      <div class="node-info">
        <h4>{{ selectedNode.data.label }}</h4>
        <p class="muted-text">{{ getNodeDescription(selectedNode.type) }}</p>
      </div>

      <!-- Parameters Form -->
      <div class="parameters-section">
        <h5>Parameters</h5>
        <div v-if="currentParameters.length === 0" class="muted-text">
          No parameters for this node type
        </div>
        <div v-else class="parameters-form">
          <div
            v-for="param in currentParameters"
            :key="param.name"
            class="field"
          >
            <label :for="param.name">{{ param.label }}</label>

            <!-- Number input -->
            <InputNumber
              v-if="param.type === 'number'"
              :id="param.name"
              v-model="parameterValues[param.name]"
              :min="param.min"
              :max="param.max"
              :step="param.step"
              @update:model-value="updateParameter(param.name, $event)"
            />

            <!-- Boolean toggle -->
            <InputSwitch
              v-else-if="param.type === 'boolean'"
              :id="param.name"
              v-model="parameterValues[param.name]"
              @update:model-value="updateParameter(param.name, $event)"
            />

            <!-- Dropdown select -->
            <Dropdown
              v-else-if="param.type === 'select'"
              :id="param.name"
              v-model="parameterValues[param.name]"
              :options="param.options"
              :option-label="param.optionLabel || 'label'"
              :option-value="param.optionValue || 'value'"
              @update:model-value="updateParameter(param.name, $event)"
            />

            <!-- Text input -->
            <InputText
              v-else
              :id="param.name"
              v-model="parameterValues[param.name]"
              @update:model-value="updateParameter(param.name, $event)"
            />

            <small v-if="param.description" class="muted-text">{{
              param.description
            }}</small>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="inspector-actions">
        <Button
          label="Execute Node"
          icon="pi pi-play"
          class="w-full"
          @click="executeNode"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import InputNumber from "primevue/inputnumber";
import InputSwitch from "primevue/inputswitch";
import Dropdown from "primevue/dropdown";
import { useWorkflowStore } from "@/stores/workflow";

interface Props {
  selectedNode: any;
}

interface Emits {
  (e: "update-parameters", nodeId: string, parameters: any): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const parameterValues = ref<Record<string, any>>({});
const workflowStore = useWorkflowStore();

const mapMetadataParams = (nodeType: string, parameters: any[]): any[] => {
  const reverseMapping = workflowStore.getReverseParamMapping(nodeType);

  return parameters.map((param) => {
    // If backend name has a frontend equivalent, use the frontend name
    const frontendName = reverseMapping?.[param.name] || param.name;

    return {
      name: frontendName,
      label: param.label,
      type: param.param_type,
      min: param.min_value,
      max: param.max_value,
      step: param.step,
      options: param.options,
      description: param.description,
      default: param.default,
      required: param.required,
    };
  });
};

const currentParameters = computed(() => {
  if (!props.selectedNode) return [];
  const metadata = workflowStore.getNodeMetadata(props.selectedNode.type);
  if (metadata?.parameters?.length) {
    return mapMetadataParams(props.selectedNode.type, metadata.parameters);
  }
  return [];
});

watch(
  [() => props.selectedNode, currentParameters],
  ([newNode]) => {
    if (!newNode) {
      parameterValues.value = {};
      return;
    }

    const nextValues = { ...newNode.data.parameters };
    currentParameters.value.forEach((param) => {
      if (!(param.name in nextValues)) {
        if (param.default !== undefined) {
          nextValues[param.name] = param.default;
        } else if (param.type === "boolean") {
          nextValues[param.name] = false;
        } else if (param.type === "number") {
          nextValues[param.name] = param.min ?? 0;
        } else {
          nextValues[param.name] = "";
        }
      }
    });
    parameterValues.value = nextValues;
  },
  { immediate: true }
);

const updateParameter = (name: string, value: any) => {
  if (props.selectedNode) {
    emit("update-parameters", props.selectedNode.id, {
      ...parameterValues.value,
      [name]: value,
    });
  }
};

const executeNode = () => {
  if (props.selectedNode) {
    // TODO: Execute node computation
    console.log("Executing node:", props.selectedNode.id, parameterValues.value);
  }
};

const getNodeDescription = (nodeType: string) => {
  const metadata = workflowStore.getNodeMetadata(nodeType);
  if (metadata?.description) {
    return metadata.description;
  }
  const descriptions: Record<string, string> = {
    "baseline.als": "Asymmetric Least Squares baseline correction",
    "baseline.rubberband": "Rubberband baseline correction",
    "smooth.savitzky_golay": "Savitzky-Golay smoothing filter",
    "normalize.snv": "Standard Normal Variate normalization",
    "model.pca": "Principal Component Analysis",
    "model.pls": "Partial Least Squares regression",
  };
  return descriptions[nodeType] || "No description available";
};
</script>

<style scoped>
.node-inspector {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  max-height: 50%;
  overflow: hidden;
}

.inspector-header {
  padding: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.inspector-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.empty-state {
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
}

.empty-state i {
  font-size: 2rem;
  margin-bottom: 8px;
}

.inspector-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.node-info h4 {
  margin: 0 0 4px 0;
  font-size: 1rem;
}

.parameters-section h5 {
  margin: 0 0 12px 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: #64748b;
}

.parameters-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.inspector-actions {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
}

.w-full {
  width: 100%;
}
</style>
