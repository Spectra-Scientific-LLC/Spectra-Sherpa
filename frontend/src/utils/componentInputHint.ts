import authority from "./scientific-presentation-renderers.json";
import type { NodePresentationContract } from "@/types";

/** Local wiring hints are presentation policy, never execution admission. */
export function componentInputHint(contract: NodePresentationContract | null | undefined, connections: Array<{nodeType?: string; port?: string; toPort?: string}>) {
  const ruleKey = "validation_result:component_selection:component_curve";
  const present = contract?.payload.presentations.some(p => `${p.kind}:${p.presentation_id}:${p.source_ports[0]}` === ruleKey);
  if (!present) return null;
  const policy = authority.record_views[ruleKey];
  const rule = policy.training_input_rule;
  const split = connections.filter(c => c.nodeType === rule.source_operation);
  const training = split.every(c => rule.allowed_pairs.some(([from, to]) => c.port === from && c.toPort === to))
    && split.some(c => c.port === rule.feature_output);
  return { splitRole: split.length === 0 ? "none" : training ? "train" : "other" };
}
