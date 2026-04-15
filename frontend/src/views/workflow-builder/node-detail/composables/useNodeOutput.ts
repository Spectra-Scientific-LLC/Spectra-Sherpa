import { computed, type Ref } from "vue";
import { buildNodeOutput, type NodeOutput } from "@/utils/nodeOutput";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function resolvePortPayload(port: any): any {
  if (!port || typeof port !== "object") return port;
  return "value" in port ? port.value : port;
}

export function useNodeOutput(
  nodeOutput: Ref<NodeOutput | null>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  nodeMetadata: Ref<any>,
) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const normalizeNodeOutput = (result: any): NodeOutput => {
    const outputPorts = nodeMetadata.value?.output_ports;
    return buildNodeOutput(result, outputPorts);
  };

  const primaryOutputPayload = computed(() => {
    const primaryPort = nodeOutput.value?.primary_port;
    if (!primaryPort) return null;
    return resolvePortPayload(nodeOutput.value?.ports?.[primaryPort]);
  });

  return { normalizeNodeOutput, resolvePortPayload, primaryOutputPayload };
}
