import { mount } from "@vue/test-utils";
import { defineComponent, ref } from "vue";
import { describe, expect, it } from "vitest";
import PeakExecutionDetails from "@/components/common/PeakExecutionDetails.vue";
import ScientificNumberInput from "@/components/common/ScientificNumberInput.vue";
import { parseScientificNumber } from "@/utils/scientificNumberInput";
import { validateScientificMetadata } from "@/utils/scientificMetadataValidation";

describe("scientific numeric entry", () => {
  it("preserves the decimal separator and lexical precision across parent echoes and blur", async () => {
    const wrapper = mount(
      defineComponent({
        components: { ScientificNumberInput },
        setup: () => ({ value: ref<number | string | null>(null) }),
        template: '<ScientificNumberInput v-model="value" :step="0.01" :min="0" />',
      }),
    );
    const input = wrapper.get("input");
    for (const text of ["0", "0.", "0.5", "0.50000"]) {
      await input.setValue(text);
      expect(input.element.value).toBe(text);
    }
    await input.trigger("blur");
    expect(input.element.value).toBe("0.50000");
    expect(wrapper.vm.value).toBe(0.5);
  });

  it.each(["1e-12", "0.1234567890123456", "1.2300e+20", "-3.5", ".5", "5."])(
    "admits %s without step-based precision limits",
    async (text) => {
      const wrapper = mount(ScientificNumberInput, { props: { modelValue: null, step: 1 } });
      await wrapper.get("input").setValue(text);
      await wrapper.get("input").trigger("blur");
      expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([Number(text)]);
      expect(wrapper.get("input").element.value).toBe(text);
      expect(wrapper.find(".numeric-error").exists()).toBe(false);
    },
  );

  it("retains out-of-range entries and discloses bounds instead of clamping", async () => {
    const wrapper = mount(ScientificNumberInput, {
      props: { modelValue: 0.5, min: 0, max: 1, id: "prominence" },
    });
    expect(wrapper.text()).toContain("Allowed range: 0 to 1");
    for (const value of [-0.5, 2]) {
      await wrapper.get("input").setValue(String(value));
      await wrapper.get("input").trigger("blur");
      expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([value]);
      expect(wrapper.get("input").element.value).toBe(String(value));
      expect(wrapper.get("input").attributes("aria-invalid")).toBe("true");
      expect(wrapper.text()).toContain("has not been changed");
    }
  });

  it.each([
    "-",
    "1e-",
    "0x10",
    "NaN",
    "Infinity",
    "1e309",
    "1e-400",
    "9007199254740993",
    "0.10000000000000001",
  ])("refuses %s explicitly without emitting a substituted number", async (text) => {
    const wrapper = mount(ScientificNumberInput, { props: { modelValue: 0.5 } });
    await wrapper.get("input").setValue(text);
    await wrapper.get("input").trigger("blur");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([text]);
    expect(wrapper.get("input").element.value).toBe(text);
    expect(wrapper.get("input").attributes("aria-invalid")).toBe("true");
  });

  it("handles optional clear and external value replacement", async () => {
    const wrapper = mount(ScientificNumberInput, { props: { modelValue: 0.5 } });
    await wrapper.get("input").setValue("");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([null]);
    await wrapper.setProps({ modelValue: 0.7 });
    expect(wrapper.get("input").element.value).toBe("0.7");
    expect(parseScientificNumber("-0.000e-400").value).toBe(-0);
  });

  it("validates numeric metadata drafts and bounds for execution", () => {
    expect(validateScientificMetadata({ acquisition: { n_scans: 1.5 } })).toHaveLength(1);
    expect(
      validateScientificMetadata({
        conditions: { pressure_atm: "1e-", ambient_humidity_percent: 101 },
      }),
    ).toHaveLength(2);
    expect(
      validateScientificMetadata({
        acquisition: { n_scans: 0 },
        cell: { pathlength_mm: "9007199254740993" },
      }),
    ).toHaveLength(2);
    expect(
      validateScientificMetadata({
        conditions: { pressure_atm: 0.123456789 },
        cell: { pathlength_mm: 1e-12 },
      }),
    ).toEqual([]);
  });
});

describe("retained peak execution inputs", () => {
  it("shows exact None arguments and decimal spelling from the run without reconstruction", async () => {
    const call =
      "scipy.signal.find_peaks(spectrum, height=None, threshold=None, distance=None, prominence=0.123456789, width=None, wlen=None, rel_height=0.5, plateau_size=None)";
    const wrapper = mount(PeakExecutionDetails, {
      props: { diagnostics: { scipy_version: "1.17.1", scipy_find_peaks_call: call } },
    });
    expect(wrapper.get("pre").text()).toBe(call);
    expect(wrapper.text()).toContain("1.17.1");
    expect(wrapper.text()).toContain("Editing settings does not change this execution record");
    await wrapper.setProps({ diagnostics: {} });
    expect(wrapper.find("pre").exists()).toBe(false);
    expect(wrapper.text()).toContain("current settings cannot establish historical inputs");
  });
});
