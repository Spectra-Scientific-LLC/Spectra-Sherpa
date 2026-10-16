import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ValidationLedger from "@/components/ValidationLedger.vue";
import SavedValue from "@/views/models/SavedValue.vue";
import {
  columnDecimals,
  evaluationRoleLabel,
  formatMeasurement,
  isAuditField,
  scientificFieldLabel,
  scientificScalar,
  scientificMetricNotes,
  scientificErrorMetricLabel,
  scientificProtocolLabel,
  scientificMetricContext,
} from "@/utils/scientificDisplay";

describe("scientific display helpers", () => {
  it("keeps undeclared Corn/Shootout error units honest without qualifying dimensionless scores", () => {
    const evidence = { target_units: [null], x_units: "nm", value_units: "absorbance", rmse: 0.2, r2: 0.9 };
    const before = JSON.stringify(evidence);
    expect(scientificErrorMetricLabel("rmse", evidence)).toBe("RMSE (units not declared)");
    expect(scientificErrorMetricLabel("r2", evidence)).not.toContain("units");
    expect(scientificErrorMetricLabel("mae", { target_units: ["%"] })).toBe("MAE (%)");
    expect(scientificErrorMetricLabel("bias", { target_units: ["%", null] })).toContain("units not declared");
    expect(scientificErrorMetricLabel("rmse", { target_units: null, metadata: { target_units: "%" } })).toBe("RMSE (units not declared)");
    expect(scientificErrorMetricLabel("rmse", { target_units: "dimensionless" })).toBe("RMSE (dimensionless)");
    expect(JSON.stringify(evidence)).toBe(before);
  });
  it("uses declared protocols and never derives CV from fold configuration", () => {
    expect(scientificProtocolLabel({ n_folds: 5, method: "PLS" })).toBe("Protocol: not declared");
    expect(scientificProtocolLabel({ metadata: { role: "held_out_test" } })).toBe("Protocol: Held-out test");
    expect(scientificProtocolLabel({ population_authority: { role: "cross_validation" } })).toBe("Protocol: Cross-validation (CV)");
  });
  it("renders units and protocol beside saved scientific error metrics", () => {
    const wrapper = mount(SavedValue, { props: { scientific: true, value: {
      rmse: 0.1234, r2: 0.9, target_units: [null], metadata: { role: "held_out_test" },
    } } });
    expect(wrapper.text()).toContain("RMSE (units not declared)");
    expect(wrapper.text()).toContain("Protocol: Held-out test");
    expect(wrapper.findAll("dt").find(item => item.text().startsWith("R²"))?.text()).not.toContain("units");
  });
  it.each([false, true])("inherits only response context into nested saved metrics; child null override %s", async (override) => {
    const value = { metrics: { rmse: 0.2, r2: 0.9, ...(override ? { target_units: null, role: "cross_validation" } : {}) },
      metadata: { target_units: ["wt %"], role: "held_out_test", value_units: "absorbance", x_units: "nm" } };
    const wrapper = mount(SavedValue, { props: { value, scientific: true } });
    const details = wrapper.find('dd details');
    (details.element as HTMLDetailsElement).open = true;
    await details.trigger('toggle');
    expect(wrapper.text()).toContain(`RMSE (${override ? "units not declared" : "wt %"})`);
    expect(wrapper.text()).toContain(`Protocol: ${override ? "Cross-validation (CV)" : "Held-out test"}`);
    expect(scientificMetricContext(value)).toEqual({ target_units: ["wt %"], role: "held_out_test" });
  });
  it("renders separate units for indexed saved errors and target rows", async () => {
    const wrapper = mount(SavedValue, { props: { scientific: true, value: {
      metadata: { target_units: ["%", "mg/L"], role: "held_out_test" },
      rmse_per_target: [0.2, 3.1],
      per_target: [{ target: "Moisture", rmse: 0.2 }, { target: "Protein", rmse: 3.1 }],
    } } });
    for (const details of wrapper.findAll('dd details')) {
      (details.element as HTMLDetailsElement).open = true;
      await details.trigger('toggle');
    }
    expect(wrapper.text()).toContain("RMSE [1] (%): 0.2");
    expect(wrapper.text()).toContain("RMSE [2] (mg/L): 3.1");
    expect(wrapper.findAll('tbody tr')[0].text()).toContain("(%) · Protocol: Held-out test");
    expect(wrapper.findAll('tbody tr')[1].text()).toContain("(mg/L) · Protocol: Held-out test");
    expect(wrapper.text()).not.toContain("% / mg/L");
  });
  it("gives every row of one quantity the same four-significant-figure precision", () => {
    expect(columnDecimals([99.82868069410324, 2.266546083068735])).toBe(2);
    expect(columnDecimals([0.01234, 0.5])).toBe(4);
    expect(columnDecimals([1450.2, 1200.5], 5)).toBe(1);
    expect(formatMeasurement(99.82868069410324, 2)).toBe("99.83");
    expect(formatMeasurement(-0.0004, 2)).toBe("0.00");
    expect(formatMeasurement("Carbon dioxide", 2)).toBe("Carbon dioxide");
  });

  it("uses chemometric names for evaluation roles and saved fields", () => {
    expect(evaluationRoleLabel("calibration")).toBe("Calibration fit");
    expect(evaluationRoleLabel("cross_validation")).toBe("Cross-validation");
    expect(evaluationRoleLabel("held_out_test")).toBe("Test set");
    expect(scientificFieldLabel("rmsecv")).toBe("RMSECV");
    expect(scientificFieldLabel("accounted_samples")).toBe("Samples evaluated");
    expect(scientificScalar(1.2949488617445029)).toBe("1.2949");
    expect(scientificScalar(1450.2)).toBe("1450.2");
    expect(scientificScalar(231)).toBe("231");
  });

  it("separates provenance bookkeeping from scientific fields", () => {
    for (const key of ["node_id", "worker_execution", "population_authority", "evidence_sha256", "split_plan_digest", "schema_version"]) {
      expect(isAuditField(key)).toBe(true);
    }
    for (const key of ["rmse", "r2", "n_samples", "accuracy"]) expect(isAuditField(key)).toBe(false);
  });
});

describe("sample prediction ledger", () => {
  const rows = [
    { sample: "1", target: "CO2", reference: 99.82868069410324, predicted: 99.48827966932163, residual: 0.3404010247816, role: "calibration" },
    { sample: "2", target: "CO2", reference: 2.266546083068735, predicted: 3.0114476052692893, residual: -0.7449015222005544, role: "calibration" },
  ];

  it("rounds measurements per target, keeps full precision in tooltips, and names the set", () => {
    const wrapper = mount(ValidationLedger, { props: { rows } });
    const text = wrapper.text();
    expect(text).toContain("99.83");
    expect(text).toContain("-0.74");
    expect(text).not.toContain("99.82868069410324");
    expect(wrapper.find('[title="99.82868069410324"]').exists()).toBe(true);
    expect(text).toContain("Calibration fit");
    expect(text).toContain("2 calibration fit");
  });

  it("warns that calibration-only rows are fitted values, not validation", () => {
    expect(mount(ValidationLedger, { props: { rows } }).find('[role="note"]').text()).toContain("not how it predicts new samples");
    const mixed = [...rows, { ...rows[0], sample: "3", role: "held_out_test" }];
    expect(mount(ValidationLedger, { props: { rows: mixed } }).find('[role="note"]').exists()).toBe(false);
  });
});

describe("scientific saved values", () => {
  it("labels metrics, rounds them, and folds provenance into audit details", () => {
    const wrapper = mount(SavedValue, { props: { scientific: true, value: {
      rmsecv: 1.2949488617445029, accounted_samples: 9, node_id: "eval_1", evidence_sha256: "a".repeat(64),
    } } });
    const visible = wrapper.get(".saved-value").text();
    expect(visible).toContain("RMSECV");
    expect(visible).toContain("1.2949");
    expect(visible).toContain("Samples evaluated");
    expect(visible).not.toContain("eval_1");
    expect(wrapper.get(".saved-audit summary").text()).toBe("Audit details (2)");
  });

  it("keeps authored values exactly as recorded without the scientific view", () => {
    const wrapper = mount(SavedValue, { props: { value: { tolerance: 0.000123456789, node_id: "x" } } });
    expect(wrapper.text()).toContain("0.000123456789");
    expect(wrapper.text()).toContain("node id");
    expect(wrapper.find(".saved-audit").exists()).toBe(false);
  });
});

describe("fractions", () => {
  it("shows a fraction such as accuracy to four significant figures", () => {
    expect(scientificScalar(0.8888888888888888)).toBe("0.8889");
  });
});


it("explains only explicitly recorded metric populations", async () => {
  const { scientificMetricNotes } = await import("@/utils/scientificDisplay");
  expect(scientificMetricNotes({ population: "non_noise_samples_only" })[0]).toContain("noise samples are excluded");
  expect(scientificMetricNotes({ population: "all_samples" })).toEqual([]);
  expect(scientificMetricNotes({ schema_version: "spectrasherpa.classification-evaluation/1", predicted_only_labels: ["unassigned"] })[0]).toContain("reference classes only");
  expect(scientificMetricNotes({ predicted_only_labels: ["unassigned"] })).toEqual([]);
});

it("removes nested worker metadata while preserving scientific values", async () => {
  const { scientificMetadata } = await import("@/utils/scientificDisplay");
  const source = { diagnostics: { n_components: 3, worker_execution: { worker_pid: 24, origin_pid: 9, execution_id: 'private' } } };
  expect(scientificMetadata(source)).toEqual({ diagnostics: { n_components: 3 } });
  expect(source.diagnostics.worker_execution.worker_pid).toBe(24);
});


it("explains retained nested SIMCA calibration and DBSCAN populations without inferring missing declarations", () => {
  expect(scientificMetricNotes({ diagnostics: { metrics: {
    schema_version: 1, task_type: "classification", method: "simca",
    evidence_scope: "calibration_fit_diagnostics_not_validation_evidence",
  } } }).join(" ")).toContain("rejection label is not an additional class");
  expect(scientificMetricNotes({ metadata: { quality_summary: { population: "non_noise_samples_only" } } })[0]).toContain("DBSCAN noise samples are excluded");
  expect(scientificMetricNotes({ method: "simca", train_f1_macro: 0.8 })).toEqual([]);
  expect(scientificMetricNotes({ noise_fraction: 0.4, silhouette_score: 0.2 })).toEqual([]);
});
