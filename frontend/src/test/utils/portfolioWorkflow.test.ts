import { expect, it } from 'vitest';
import { portfolioWorkflow, type AveragingMode } from '@/utils/portfolioWorkflow';
import type { components } from '@/types/api/v1';
const portfolio = { id: 12, project_id: 6, name: 'Etch days', selection_sha256: 'a'.repeat(64) } as components['schemas']['PortfolioOut'];
it.each<AveragingMode>(['step','phase_across_cycles','cycle_phase'])('pins the saved cohort and connects independent peak columns for %s', mode => {
  const graph = portfolioWorkflow(portfolio, mode, [515.14]);
  expect(graph.nodes?.map(n => n.node_type)).toEqual(['data.portfolio_load','preprocess.portfolio_average','preprocess.smooth','preprocess.normalize','analysis.partitioned_peaks','data.wide_peak_table','output.peak_csv']);
  expect(graph.nodes?.[0].parameters).toEqual({project_id:6,portfolio_id:12,selection_sha256:'a'.repeat(64)});
  expect(graph.nodes?.[1].parameters).toMatchObject({portfolio_id:12,selection_sha256:'a'.repeat(64),mode,statistic:'median'});
  expect(graph.edges?.find(e => e.to_node_id === 'wide')).toMatchObject({from_node_id:'peaks',from_output:'per_spectrum'});
});
it('refuses blank, nonfinite or duplicate peak positions', () => {
  for (const refs of [[],[NaN],[515,515]]) expect(() => portfolioWorkflow(portfolio,'step',refs)).toThrow();
});
