export interface PairedEvaluationRecord {
  schema_version: 'spectrasherpa-paired-evaluation/1';
  protocol: { recipes: Array<{ run_id: number; model_node_id: string }> };
  protocol_digest: string;
  population: { development_count: number; held_out_count: number };
  splits: Array<{ digest: string }>;
  paired_rmsecv_differences: number[];
  results: Array<{ execution: { metrics: { rmse: number } } }>;
  summary: { right_meaningfully_better: number; left_meaningfully_better: number; within_margin: number };
  interpretation: string;
}
