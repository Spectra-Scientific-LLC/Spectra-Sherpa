import { describe, expect, it } from 'vitest';
import { scientificRecordColumnKeys, scientificRecordColumnLabel, scientificStructuredCell } from '@/utils/scientificDisplay';
import { buildNodeOutput } from '@/utils/nodeOutput';
import { projectScientificPresentation, resolveScientificPresentation, scientificEvidenceShape } from '@/utils/scientificPresentation';
import { retainedPeakFixture } from '@/test/fixtures/retainedPeakTable';

describe('retained record presentation', () => {
  it('uses declared per-column units, with only an explicit historical coordinate-unit fallback', () => {
    const metadata = { type: 'PeakFinding', x_units: 'cm-1', column_units: { median_pos: 'nm', median_height: 'absorbance' } };
    expect(scientificRecordColumnLabel('median_pos', metadata, 'peak_table')).toBe('Median position (nm)');
    expect(scientificRecordColumnLabel('median_height', metadata, 'peak_table')).toBe('Median height (absorbance)');
    expect(scientificRecordColumnLabel('median_half_prominence_width', metadata)).toBe('Half-prominence width (cm-1)');
    expect(scientificRecordColumnLabel('median_pos', { type: 'PeakFinding' })).toBe('Median position');
    expect(scientificRecordColumnLabel('median_pos', { ...metadata, column_units: { median_pos: '' } }, 'peak_table')).toBe('Median position');
    expect(scientificRecordColumnLabel('median_pos', { x_units: 'cm-1' })).toBe('median_pos');
    expect(scientificRecordColumnLabel('median_pos', { type: 'PeakFinding', scientific_presentation: { kind: 'numeric_matrix' } }, 'numeric_matrix')).toBe('median_pos');
  });

  it('presents nested records without altering retained values', () => {
    const nested = [{ sample_label: 'A, "quoted"', position: 123.123456789 }];
    const before = structuredClone(nested);
    expect(scientificStructuredCell(nested)).toBe('1 record (hover for details)');
    expect(scientificStructuredCell(nested[0])).toBe(JSON.stringify(nested[0]));
    expect(scientificStructuredCell([1, 2])).toBe('[1,2]');
    expect(scientificStructuredCell(1)).toBeNull();
    expect(scientificStructuredCell(null)).toBeNull();
    expect(nested).toEqual(before);
  });

  it('counts the exact union of record columns only for declared peak tables, without borrowing source dimensions', () => {
    const saved = retainedPeakFixture();
    const output = buildNodeOutput({ peaks: saved.peaks }, undefined, null, { peaks: saved.descriptor } as never,
      { digest: 'synthetic-contract', payload: saved.contract } as never);
    const projected = projectScientificPresentation(output, resolveScientificPresentation(undefined, output, 'peak_table'))!;
    expect(scientificEvidenceShape(projected)).toEqual({ rows: 1, cols: 23, rowLabel: 'consensus group', colLabel: 'columns' });
    projected.data.push({ ...saved.peaks.data[0], extra_retained_field: 1 });
    expect(scientificRecordColumnKeys(projected.data)).toEqual([...Object.keys(saved.peaks.data[0]), 'extra_retained_field']);
    expect(scientificEvidenceShape(projected)).toEqual({ rows: 2, cols: 24, rowLabel: 'consensus groups', colLabel: 'columns' });
    projected.metadata.scientific_presentation.kind = 'numeric_matrix';
    expect(scientificEvidenceShape(projected)).toBeNull();
  });
});
