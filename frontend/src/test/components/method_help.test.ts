import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import MethodHelp from "@/components/MethodHelp.vue";

describe("contextual methodology help", () => {
  it("uses a compact, keyboard-accessible secure documentation link", () => {
    const wrapper = mount(MethodHelp, { props: {
      path: "chemometrics/validation-design/#component-selection", label: "Component selection",
    } });
    const link = wrapper.get("a");
    expect(link.text()).toBe("?");
    expect(link.attributes("href")).toBe("https://docs.spectrascientific.ai/chemometrics/validation-design/#component-selection");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("aria-label")).toContain("Component selection");
  });

  it("resolves every static methodology link to an OSS documentation section", () => {
    const source = resolve(process.cwd(), "src");
    const paths = readdirSync(source, { recursive: true }).filter((file) => String(file).endsWith(".vue"));
    let links = 0;
    for (const file of paths) {
      const content = readFileSync(resolve(source, String(file)), "utf8");
      for (const match of content.matchAll(/<MethodHelp\b[^>]*path="([^"]+)"/g)) {
        const [page, anchor] = match[1].split("/#");
        const doc = readFileSync(resolve(process.cwd(), "../docs", page + ".md"), "utf8");
        const headings = [...doc.matchAll(/^#+ (.+)$/gm)].map((heading) =>
          heading[1].toLowerCase().replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "-"));
        expect(headings, match[1]).toContain(anchor);
        links++;
      }
    }
    expect(links).toBeGreaterThan(10);
  });
});
