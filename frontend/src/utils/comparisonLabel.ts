/** Stable column order shared by qualified evidence, plots and descriptive tables. */
export const comparisonLabel = (label: string, index: number): string => `${index + 1} · ${label}`;
export const comparisonDeltaLabel = (left = 0, right = 1): string => `Delta (${right + 1} − ${left + 1})`;
