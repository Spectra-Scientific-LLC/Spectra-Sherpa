export type EvaluationRole = 'calibration' | 'training_cv' | 'held_out' | 'outlier_challenge';
export interface EvidenceReference {
  schema_version?: 'spectrasherpa-evidence-reference/1';
  kind: 'run' | 'evaluation' | 'external'; id: string; provider: string; revision: string;
  selected_output?: { node_id: string; presentation_id: string } | null;
}
export interface PopulationSummary {
  source_count?: number | null; admitted_count?: number | null; excluded_count?: number | null;
  development_count?: number | null; held_out_count?: number | null; evaluation_count?: number | null;
  group_count?: number | null; grouped?: boolean | null; response?: string | null; units?: string | null;
  fold_count?: number | null; partition_digest?: string | null; source_receipt?: string | null;
  verification: 'verified' | 'partial' | 'unknown'; limitations: string[];
}
export interface ScientificSection {
  role: EvaluationRole; state: 'verified' | 'descriptive_only' | 'unavailable'; population: PopulationSummary;
  metrics: Record<string, number>; sample_ids: string[]; observations: number[]; predictions: number[]; reason: string;
}
export interface EvidenceComparison {
  schema_version: 'spectrasherpa-scientific-comparison/1';
  items: Array<{ reference: EvidenceReference; label: string; population: PopulationSummary; dataset_use?: { notice: string; populations: Array<{results_revealed: boolean | null; influenced_development: boolean | null; basis: string}> } | null; sections: Record<EvaluationRole, ScientificSection> }>;
  pairs: Array<{ left_index: number; right_index: number; sections: Array<{
    role: EvaluationRole; state: 'comparable' | 'descriptive_only' | 'reevaluation_needed' | 'unavailable';
    reason: string; next_action: string; metric_values: Record<string, {left: number; right: number}>;
  }> }>;
}
