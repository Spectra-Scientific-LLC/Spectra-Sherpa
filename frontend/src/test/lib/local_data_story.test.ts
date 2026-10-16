import { afterEach, describe, expect, it, vi } from "vitest";
import { localStoryMessage, streamLocalDataStory } from "@/lib/localDataStory";

const source = {
  title: "Corn M5",
  data: [[1, 2, 3], [4, 5, 6]],
  shape: [2, 3],
  domain: { technique: "NIR", instrument: "M5" },
  x_axis: { title: "Wavelength", units: "nm", data: [1100, 1200, 1300] },
  target_context: { target_name: "Moisture", target_units: "wt %" },
  metadata: { prop_names: ["Moisture", "Batch"], contents_title: "Corn M5", api_key: "never-send" },
  descriptive: { acquisition_note: "Diffuse reflectance" },
  property_stats: [{ name: "Moisture", min: 8.1, max: 12.2 }],
  source_identity: { sha256: "abc", file_path: "/private/secret.mat", userPassword: "never-send-this" },
};

afterEach(() => vi.unstubAllGlobals());

describe("local BYO Data Story", () => {
  it("uses parsed scientific context while excluding raw rows, paths and credentials", () => {
    const message = localStoryMessage(source, "Can Batch be used as a group?");
    expect(message).toContain("Diffuse reflectance");
    expect(message).toContain("Moisture");
    expect(message).toContain("M5");
    expect(message).toContain("wt %");
    expect(message).toContain("Can Batch be used as a group?");
    expect(message).not.toContain("[[1,2,3],[4,5,6]]");
    expect(message).not.toContain("/private/secret.mat");
    expect(message).not.toContain("never-send");
  });

  it("keeps scientific facts within the local chat limit for large parsed metadata", () => {
    const metadata = Object.fromEntries(Array.from({ length: 60 }, (_, i) =>
      [`field_${i}`, "sample annotation ".repeat(50)]));
    const message = localStoryMessage({ ...source, metadata }, "What does this dataset contain?");
    expect(message.length).toBeLessThan(16_000);
    expect(message).toContain("Corn M5");
    expect(message).toContain("NIR");
    expect(message).toContain("omitted_for_input_limit");
  });

  it("summarizes every parsed sample row without forwarding row-level values", () => {
    const message = localStoryMessage({
      ...source,
      y_axis: { sample_table: {
        block: ["B1", "B1", "B2", "B2"],
        specimen_id: ["S1", "S2", "S3", "S4"],
        acquisition_order: [1, 2, 3, 4],
      } },
    }, "");
    expect(message).toContain('"name":"block"');
    expect(message).toContain('"counts":{"B1":2,"B2":2}');
    expect(message).toContain('"distinct":4');
    expect(message).toContain('"mean":2.5');
    expect(message).not.toContain('"sample_table"');
    expect(message).not.toContain('"S1"');
  });

  it("does not forward user filters or active analysis choices with source metadata", () => {
    const message = localStoryMessage({
      ...source,
      metadata: {
        ...source.metadata,
        acquisition_method: "ATR-IR",
        selected_file_ids: [11, 12],
        sample_inclusion_mask: [true, false],
        data_portfolio_name: "filtered-view",
        nested: { preview_row_ids: [1], user_filter: "only lavender" },
      },
      y_axis: { sample_table: {
        botanical_group: ["lavender", "lavender"],
        include: [true, false],
      } },
      analysis_binding: { selected_target: "botanical_group" },
      scientific_projection: { excluded_samples: ["specimen-2"] },
    }, "");
    expect(message).toContain("ATR-IR");
    expect(message).toContain("botanical_group");
    for (const userChoice of ["selected_file_ids", "sample_inclusion_mask", "filtered-view",
      "preview_row_ids", "only lavender", '"name":"include"', "analysis_binding",
      "scientific_projection", "specimen-2"]) {
      expect(message).not.toContain(userChoice);
    }
  });

  it("computes signal statistics from the full matrix, including late rows and columns", () => {
    const data = Array.from({ length: 301 }, () => Array(3001).fill(1));
    data[300][3000] = -7;
    const message = localStoryMessage({ ...source, data, n_samples: 301, n_features: 3001 }, "");
    expect(message).toContain('"total_rows":301');
    expect(message).toContain('"finite_values":903301');
    expect(message).toContain('"signal_min":-7');
    expect(message).not.toContain("sampled_rows");
  });

  it("streams the BYO reply and propagates a provider error", async () => {
    const encoder = new TextEncoder();
    const response = (parts: string[]) => ({
      ok: true,
      body: new ReadableStream({
        start(controller) {
          for (const part of parts) controller.enqueue(encoder.encode(part));
          controller.close();
        },
      }),
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(response([
      'data: {"type":"chunk","text":"Corn "}\n',
      '\ndata: {"type":"chunk","text":"M5"}\n\ndata: {"type":"done"}\n\n',
    ])).mockResolvedValueOnce(response(['data: {"type":"error","detail":"Chat request failed"}\n\n']));
    vi.stubGlobal("fetch", fetchMock);
    const chunks: string[] = [];
    const result = await streamLocalDataStory(source, "", (text) => chunks.push(text), new AbortController().signal);
    expect(result).toBe("Corn M5");
    expect(chunks).toEqual(["Corn ", "M5"]);
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/chat/stream");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).message).toContain("Corn M5");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).max_tokens).toBe(4096);
    await expect(streamLocalDataStory(source, "", () => {}, new AbortController().signal))
      .rejects.toThrow("Chat request failed");
  });

  it("rejects an interrupted stream rather than presenting an incomplete story", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('data: {"type":"chunk","text":"partial"}\r\n\r\n'));
          controller.close();
        },
      }),
    }));
    await expect(streamLocalDataStory(source, "", () => {}, new AbortController().signal))
      .rejects.toThrow("ended before");
  });
});
