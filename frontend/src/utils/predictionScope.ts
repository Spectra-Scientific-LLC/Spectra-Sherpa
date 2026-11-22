/**
 * Retained scope of a prediction-only model application. Results and both
 * report exports render the same statements so an offline reader keeps the
 * applicability limit shown in the app.
 */
export interface PredictionContext {
  role: 'prediction_only';
  instrument_relation: 'different' | 'same' | 'unknown';
  calibration_instrument: string | null;
  prediction_instrument: string | null;
  transfer_correction: 'none';
  held_out_accuracy_applies: false;
}

export const PREDICTION_SCOPE_STATEMENT =
  'Prediction only. No instrument-transfer correction was applied. Held-out accuracy does not apply to this dataset.';

export function crossInstrumentStatement(context: PredictionContext): string | null {
  if (context.instrument_relation !== 'different') return null;
  return `Uncorrected cross-instrument predictions: ${context.calibration_instrument} → ${context.prediction_instrument}.`;
}

export function predictionScopeLines(context: PredictionContext | null | undefined): string[] {
  if (!context) return [];
  const crossInstrument = crossInstrumentStatement(context);
  return crossInstrument ? [crossInstrument, PREDICTION_SCOPE_STATEMENT] : [PREDICTION_SCOPE_STATEMENT];
}
