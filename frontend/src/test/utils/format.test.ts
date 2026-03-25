import { describe, expect, it } from "vitest";
import { formatBytes, formatDateTime } from "@/utils/format";

describe("formatBytes", () => {
  it("returns '0 B' for null/undefined/zero", () => {
    expect(formatBytes(null)).toBe("0 B");
    expect(formatBytes(undefined)).toBe("0 B");
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(-1)).toBe("0 B");
  });

  it("formats bytes", () => {
    expect(formatBytes(500)).toBe("500 B");
  });

  it("formats kilobytes", () => {
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
  });

  it("formats megabytes", () => {
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB");
    expect(formatBytes(10 * 1024 * 1024)).toBe("10 MB");
  });

  it("formats gigabytes", () => {
    expect(formatBytes(1024 ** 3)).toBe("1.0 GB");
  });

  it("formats terabytes", () => {
    expect(formatBytes(1024 ** 4)).toBe("1.0 TB");
  });
});

describe("formatDateTime", () => {
  it("formats valid ISO string", () => {
    const result = formatDateTime("2024-06-15T10:30:00Z");
    // Locale-dependent, but should contain date parts
    expect(result).toBeTruthy();
    expect(result).not.toBe("2024-06-15T10:30:00Z");
  });

  it("returns input for invalid date", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});
