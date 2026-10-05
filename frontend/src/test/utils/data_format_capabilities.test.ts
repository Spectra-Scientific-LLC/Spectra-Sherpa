import { describe, expect, it } from "vitest";

import { filenameAcceptedByCapabilities } from "@/utils/dataFormatCapabilities";

const capability = {
  acceptedExtensions: [".csv", ".opus", ".spc", ".0"],
  acceptedFilenamePatterns: ["numeric-extension"],
};

describe("filenameAcceptedByCapabilities", () => {
  it("uses generated extensions and numeric OPUS patterns", () => {
    expect(filenameAcceptedByCapabilities("sample.csv", capability)).toBe(true);
    expect(filenameAcceptedByCapabilities("sample.opus", capability)).toBe(true);
    expect(filenameAcceptedByCapabilities("sample.0000", capability)).toBe(true);
    expect(filenameAcceptedByCapabilities("sample.42", capability)).toBe(true);
    expect(filenameAcceptedByCapabilities("sample.spc", capability)).toBe(true);
  });
});
