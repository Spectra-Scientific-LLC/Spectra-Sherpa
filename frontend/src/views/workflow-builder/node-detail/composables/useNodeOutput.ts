import { computed, type Ref } from "vue";
import { buildNodeOutput, resolvePortPayload, type NodeOutput } from "@/utils/nodeOutput";
import type {
  ExecutedPresentationRecord,
  NodeScientificValueDescriptors,
} from "@/stores/workflow-types";

export { resolvePortPayload } from "@/utils/nodeOutput";

export function useNodeOutput(
  nodeOutput: Ref<NodeOutput | null>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  nodeMetadata: Ref<any>,
) {
  const normalizeNodeOutput = (
    result: unknown,
    descriptors?: NodeScientificValueDescriptors | null,
    presentation?: ExecutedPresentationRecord | null,
  ): NodeOutput => {
    const outputPorts = nodeMetadata.value?.output_ports;
    const presentationContract = presentation
      ? { digest: presentation.contract_digest, payload: presentation.contract }
      : null;
    return buildNodeOutput(result, outputPorts, null, descriptors, presentationContract);
  };

  const primaryOutputPayload = computed(() => {
    const primaryPort = nodeOutput.value?.primary_port;
    if (!primaryPort) return null;
    return resolvePortPayload(nodeOutput.value?.ports?.[primaryPort]);
  });

  return { normalizeNodeOutput, resolvePortPayload, primaryOutputPayload };
}
