/** Describe retained serialization layers without rewriting artifact identities. */
export function modelSerializerDisclosure(port: any): string | null {
  const outer = port?.value?.serializer;
  const inner = port?.value?.metadata?.serializer ?? port?.metadata?.serializer;
  if (typeof outer !== "string" || typeof inner !== "string") return null;
  return `Fitted-state envelope: ${outer}. Component payload: ${inner}.`;
}
