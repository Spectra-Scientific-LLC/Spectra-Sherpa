import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import MethodHelp from "@/components/MethodHelp.vue";
import { METHOD_TOPICS, resolveMethodHelpUrl } from "@/utils/documentation";

describe("contextual methodology help", () => {
  it("offers one collapsed context control with documentation and Escape dismissal", async () => {
    const wrapper = mount(MethodHelp, { props: {
      topic: "displayExports", label: "Plot context", context: "Both panels: 50 of 150 active rows.",
    } });
    const details = wrapper.get("details");
    expect(details.attributes("open")).toBeUndefined();
    expect(wrapper.findAll("summary")).toHaveLength(1);
    expect(wrapper.get("summary").attributes("aria-label")).toBe("Plot context");
    (details.element as HTMLDetailsElement).open = true;
    expect(wrapper.get("p").text()).toBe("Both panels: 50 of 150 active rows.");
    expect(wrapper.get("a").attributes("href")).toContain("#display-and-table-exports");
    await details.trigger("keydown", { key: "Escape" });
    expect((details.element as HTMLDetailsElement).open).toBe(false);
  });
  it("uses a compact, keyboard-accessible secure documentation link", () => {
    const wrapper = mount(MethodHelp, { props: {
      topic: "componentSelection", label: "Component selection",
    } });
    const link = wrapper.get("a");
    expect(link.text()).toBe("?");
    expect(link.attributes("href")).toBe("https://docs.spectrascientific.ai/chemometrics/validation-design/#component-selection");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("aria-label")).toContain("Component selection");
  });

  it("resolves every static methodology link to an OSS documentation section", () => {
    for (const path of Object.values(METHOD_TOPICS)) {
      const [page, anchor] = path.split("/#");
      const doc = readFileSync(resolve(process.cwd(), "../docs", page + ".md"), "utf8");
      const headings = [...doc.matchAll(/^#+ (.+)$/gm)].map((heading) =>
        heading[1].toLowerCase().replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "-"));
      expect(headings, path).toContain(anchor);
    }
    const source = resolve(process.cwd(), "src");
    const paths = readdirSync(source, { recursive: true }).filter((file) => String(file).endsWith(".vue"));
    let links = 0;
    for (const file of paths) {
      const content = readFileSync(resolve(source, String(file)), "utf8");
      for (const match of content.matchAll(/<MethodHelp\b[^>]*\stopic="([^"]+)"/g)) {
        expect(resolveMethodHelpUrl(match[1]), String(file)).not.toBeNull();
        links++;
      }
    }
    expect(links).toBeGreaterThan(10);
  });
  it("refuses unknown topics and arbitrary destinations", () => {
    for (const value of ["../../private", "https://example.com", "toString", null]) {
      expect(resolveMethodHelpUrl(value)).toBeNull();
    }
  });
});
