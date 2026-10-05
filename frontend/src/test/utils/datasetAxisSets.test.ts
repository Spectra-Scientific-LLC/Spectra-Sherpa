import { describe, expect, it } from "vitest";

import {
  datasetAxisDisplayState,
  PRIMARY_AXIS_SET,
  projectDatasetAxisDisplay,
} from "@/utils/datasetAxisSets";

function axis() {
  return {
    axis_class: "SpectralAxis",
    data: [1000, 900, 800],
    labels: ["v1", "v2", "v3"],
    title: "Wavenumber",
    units: "cm-1",
    primary_scale_name: "Wavenumber",
    primary_label_name: "Variables",
    primary_title_name: "Spectral axis",
    alternate_scales: [
      {
        name: "Wavelength",
        values: [10000, 11111.111, 12500],
        title: "Wavelength",
        units: "nm",
        axis_type: "wavelength",
        source_set_index: 1,
      },
    ],
    alternate_label_sets: [
      { name: "Detector channels", values: ["D1", "D2", "D3"], source_set_index: 1 },
    ],
    alternate_title_sets: [
      { name: "Instrument title", title: "NIR detector", source_set_index: 1 },
    ],
    class_sets: [{ name: "Detector", values: ["A", "A", "B"], source_set_index: 0 }],
  };
}

describe("dataset axis-set presentation authority", () => {
  it("projects alternate scales, labels, and titles without changing alignment", () => {
    const state = datasetAxisDisplayState(axis(), 3);
    expect(state.kind).toBe("valid");
    if (state.kind !== "valid") throw new Error("expected valid axis metadata");
    expect(state.scaleOptions.map((option) => option.value)).toEqual([
      PRIMARY_AXIS_SET,
      "scale:Wavelength",
    ]);
    expect(state.classOptions).toEqual([{ label: "Detector", value: "class:Detector" }]);
    expect(
      projectDatasetAxisDisplay(
        state,
        "scale:Wavelength",
        "labels:Detector channels",
        "title:Instrument title",
      ),
    ).toEqual({
      values: [10000, 11111.111, 12500],
      labels: ["D1", "D2", "D3"],
      title: "NIR detector",
      units: "nm",
      quantity: null,
      axisType: "wavelength",
      scaleName: "Wavelength",
      labelSetName: "Detector channels",
      titleSetName: "Instrument title",
    });
  });

  it("fails closed on misalignment, nonfinite scales, and duplicate set identities", () => {
    expect(datasetAxisDisplayState(axis(), 4)).toMatchObject({ kind: "invalid" });
    const nonfinite = axis();
    nonfinite.alternate_scales[0].values[1] = Number.NaN;
    expect(datasetAxisDisplayState(nonfinite, 3)).toMatchObject({ kind: "invalid" });
    const duplicate = axis();
    duplicate.alternate_label_sets.push({
      name: "Detector channels",
      values: ["X", "Y", "Z"],
      source_set_index: 2,
    });
    expect(datasetAxisDisplayState(duplicate, 3)).toMatchObject({ kind: "invalid" });
  });

  it("keeps ordinary single-axis datasets valid without offering invented alternatives", () => {
    const state = datasetAxisDisplayState({ data: [1, 2], title: "Time", units: "s" }, 2);
    expect(state).toMatchObject({
      kind: "valid",
      scaleOptions: [{ value: PRIMARY_AXIS_SET }],
      labelOptions: [],
      titleOptions: [{ value: PRIMARY_AXIS_SET }],
      classOptions: [],
    });
  });
});
