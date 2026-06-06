import { describe, expect, it, vi, afterEach } from "vitest";

import { openReportPdfExport } from "@/utils/reportPdf";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("openReportPdfExport", () => {
  it("opens a print window with the report title set from the PDF filename", () => {
    vi.useFakeTimers();
    const fakeWindow = {
      document: {
        readyState: "complete",
        open: vi.fn(),
        write: vi.fn(),
        close: vi.fn(),
      },
      focus: vi.fn(),
      print: vi.fn(),
      addEventListener: vi.fn(),
    };
    vi.spyOn(window, "open").mockReturnValue(fakeWindow as unknown as Window);

    const opened = openReportPdfExport(
      "<html><head><title>Old</title></head><body>Report</body></html>",
      "method_validation_report.pdf",
    );

    expect(opened).toBe(true);
    expect(fakeWindow.document.write).toHaveBeenCalledWith(
      expect.stringContaining("<title>method_validation_report</title>"),
    );

    vi.runAllTimers();
    expect(fakeWindow.focus).toHaveBeenCalled();
    expect(fakeWindow.print).toHaveBeenCalled();
  });

  it("reports failure when the browser blocks the print window", () => {
    vi.spyOn(window, "open").mockReturnValue(null);

    expect(openReportPdfExport("<html></html>", "blocked.pdf")).toBe(false);
  });
});
