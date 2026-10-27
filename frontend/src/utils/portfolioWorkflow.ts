import type { components } from "@/types/api/v1";

type Portfolio = components["schemas"]["PortfolioOut"];
export type AveragingMode = "step" | "phase_across_cycles" | "cycle_phase";

/** Graph assembly only. All numerical work belongs to registered canonical nodes. */
export function portfolioWorkflow(portfolio: Portfolio, mode: AveragingMode, references: number[], statistic: "mean" | "median" = "median"): components["schemas"]["WorkflowCreate"] {
  if (!references.length || references.some(x => !Number.isFinite(x)) || new Set(references).size !== references.length)
    throw new Error("Enter distinct finite reference peak positions.");
  const pin = { project_id: portfolio.project_id, portfolio_id: portfolio.id, selection_sha256: portfolio.selection_sha256 };
  const nodes = [
    { node_id: "load", node_type: "data.portfolio_load", label: portfolio.name, parameters: pin },
    { node_id: "average", node_type: "preprocess.portfolio_average", parameters: { ...pin, mode, statistic, transition_trim_seconds: 0 } },
    { node_id: "smooth", node_type: "preprocess.smooth", parameters: { method: "savitzky_golay", size: 7, order: 2 } },
    { node_id: "normalize", node_type: "preprocess.normalize", parameters: { method: "snv" } },
    { node_id: "peaks", node_type: "analysis.partitioned_peaks", parameters: { reference_positions: references.map(String), matching_tolerance: 0.5 } },
    { node_id: "wide", node_type: "data.wide_peak_table", parameters: { reference_positions: references.map(String), tolerance: 0.5 } },
    { node_id: "csv", node_type: "output.peak_csv", parameters: { filename: "peak-intensities.csv" } },
  ].map((node, i) => ({ ...node, position_x: 100 + i * 240, position_y: 180 }));
  return {
    name: `${portfolio.name} · peak extraction`, project_id: portfolio.project_id, nodes,
    edges: nodes.slice(1).map((node, i) => ({ from_node_id: nodes[i].node_id, to_node_id: node.node_id,
      from_output: nodes[i].node_id === "peaks" ? "per_spectrum" : "default", to_input: "default" })),
  };
}
