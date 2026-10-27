import type { DatasetSelectionSummary } from '@/utils/datasetSelectionSummary';
import type { StepEntry, StepSelection, StepPortfolio } from './useProcessingStepSelection';

/** Format-specific adapter into the shared dataset review sections. No decoding or reduction. */
export function processingStepDatasetSummary(entries: StepEntry[], selections: StepSelection[], saved: StepPortfolio | null): DatasetSelectionSummary {
  const sourceFiles = new Set<string>(), companions = new Set<string>();
  const samples = selections.map(selection => {
    const entry = entries.find(e => e.experimentId === selection.experiment_id && e.file.id === selection.file_id);
    const wafer = entry?.catalog.wafers.find(w => w.asset_id === selection.asset_id);
    const phases = selection.step_id === 'production' ? ['etch','passivation'] : selection.step_id === 'gas1' ? ['gas1_plasma'] : selection.step_id === 'mixed' ? ['mixed_plasma'] : [selection.step_id];
    const intervals = wafer?.steps.filter(s => phases.includes(s.step_id)).flatMap(s => s.intervals) || [];
    const partition = saved?.selection.partitions.find(p => p.experiment_id === selection.experiment_id && p.file_id === selection.file_id && p.asset_id === selection.asset_id && p.step_id === selection.step_id);
    const count = partition ? partition.intervals.reduce((n,i) => n+i.last-i.first+1,0) : intervals.reduce((n,i) => n+i.acquisition_count,0);
    sourceFiles.add(`${selection.experiment_id}/${selection.file_id}`);
    companions.add(`${selection.experiment_id}/${selection.process_file_id}`);
    const starts = intervals.map(i => i.start_time), ends = intervals.map(i => i.end_time);
    return { Date: entry?.catalog.date || '', Wafer: selection.asset_id, Step: selection.step_id === 'production' ? 'BOSCH production' : selection.step_id,
      Acquisitions: count, 'UTC start': starts.length ? new Date(Math.min(...starts)*1000).toISOString() : '', 'UTC end': ends.length ? new Date(Math.max(...ends)*1000).toISOString() : '' };
  });
  return {
    files: entries.filter(e => sourceFiles.has(`${e.experimentId}/${e.file.id}`)).map(e => e.file.file_path.split('/').pop() || e.file.file_path),
    acquisition: [
      {label:'Technique',value:'Optical emission spectroscopy'},
      {label:'Acquisition',value:'Time series · irregular acquisition times'},
      {label:'Sample organization',value:'Day / wafer / processing step'},
      {label:'Phase assignment',value:'Process gas-flow records',detail:'Gas/OES clock alignment is estimated. Uncertain transition edges are excluded from phase selections.'},
    ],
    columns:['Date','Wafer','Step','Acquisitions','UTC start','UTC end'], samples,
    metadata:[
      {label:'Files in selection',value:String(sourceFiles.size)},
      {label:'Process companions',value:String(companions.size)},
      {label:'Groups in selection',value:String(samples.length)},
      {label:'Acquisitions in selection',value:samples.reduce((n,s) => n+s.Acquisitions,0).toLocaleString()},
      {label:'Reduction',value:'None · original time series'},
      {label:'Clock alignment',value:'Estimated from process/OES correlation'},
      {label:'Quality assessment',value:'Not calculated for the full time series'},
      ...(saved ? [{label:'Selection SHA-256',value:saved.selection_sha256}] : []),
    ],
  };
}
