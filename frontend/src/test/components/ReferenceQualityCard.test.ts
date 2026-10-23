import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ReferenceQualityCard from "@/components/ReferenceQualityCard.vue";
import type { ReferenceValueEvidence } from "@/types";
import { applicationReferenceEvidence } from "@/utils/referenceQuality";

const evidence: ReferenceValueEvidence = {
  schema_version: "spectrasherpa.reference-value-evidence/1",
  source_file_id: 1,
  sample_table_file_id: 2,
  sample_table_sha256: "a".repeat(64),
  target_name: "moisture",
  target_type: "continuous",
  units: "wt %",
  method: {
    method_id: "oven-dry",
    version: "2",
    response_identity: { names: ["moisture"], units: ["wt %"] },
    measurement_basis: "replicate_mean",
    measurements_per_label: 2,
    precision: null,
  },
  provenance: "Laboratory worksheet",
  precision_study_provenance: null,
  replicate_evidence_digest: null,
  source_included_count: 18,
  missing_included_count: 0,
  missing_excluded_count: 2,
  instrument_repeatability: null,
  qualification_gaps: ["Reference measurement precision is not recorded"],
};

describe("reference-value review", () => {
  it("separates source count, fit count and unknown laboratory precision", () => {
    const wrapper = mount(ReferenceQualityCard, { props: { evidence, calibrationRows: 12 } });
    expect(wrapper.text()).toContain("18 before calibration/test split");
    expect(wrapper.text()).toContain("Calibration rows");
    expect(wrapper.text()).toContain("12");
    expect(wrapper.text()).toContain("Mean of 2 measurements; mapping unverified");
    expect(wrapper.text()).toContain("Reference measurement precision is not recorded");
    expect(wrapper.text()).toContain("Model residuals do not establish laboratory precision");
  });

  it("does not invent a method or precision for an older model", () => {
    const wrapper = mount(ReferenceQualityCard, { props: { evidence: null } });
    expect(wrapper.text()).toContain("Laboratory reference declaration not recorded");
    expect(wrapper.text()).not.toContain("Pooled within-specimen");
  });

  it("shows reported laboratory SD with its unit and replicate-study denominator", () => {
    const reported: ReferenceValueEvidence = {
      ...evidence,
      precision_study_provenance: "study-7",
      method: { ...evidence.method!, precision: {
        estimator: "pooled_within_specimen_sample_sd",
        sd: [0.12],
        degrees_of_freedom: 12,
        specimens: 6,
        replicates_per_specimen: 3,
        evidence_digest: "b".repeat(64),
      } },
    };
    const wrapper = mount(ReferenceQualityCard, { props: { evidence: reported } });
    expect(wrapper.text()).toContain("0.12 wt % pooled within-specimen SD (unverified)");
    expect(wrapper.text()).toContain("6 specimens × 3 replicates; 12 degrees of freedom");
  });

  it("reads the exact application's metadata envelope and keeps training and evaluation separate", () => {
    const output = { artifact_uid: "saved-pls", metadata: {
      training_reference_value_evidence: evidence,
      evaluation_reference_value_evidence: null,
    } };
    expect(applicationReferenceEvidence(output, "training")?.target_name).toBe("moisture");
    expect(applicationReferenceEvidence(output, "evaluation")).toBeNull();
    expect(applicationReferenceEvidence({ ...output, model_metadata: output.metadata, metadata: null }, "training"))
      .toBeNull();
  });
});
