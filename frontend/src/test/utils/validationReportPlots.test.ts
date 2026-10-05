import { describe, expect, it } from "vitest";
import { validationFigureSvg, validationFigureCaption } from "@/utils/validationReportPlots";
const figure = {
  state: "available",
  node_id: "cv",
  source_port: "oof_evidence",
  repeat_id: 2,
  total_rows: 2,
  visible_rows: 2,
  observed: [1, 2],
  predicted: [1.1, 1.9],
  residual: [0.1, -0.1],
  units: "mg/L<script>",
  scope: "cross_validation",
};
describe("retained validation plots", () => {
  it("renders every point in two plots with units escaped and scoped denominator", () => {
    expect(validationFigureSvg(figure).match(/<circle/g)).toHaveLength(4);
    expect(validationFigureSvg(figure)).toContain("mg/L&lt;script&gt;");
    expect(validationFigureCaption(figure)).toContain("repeat 2; 2/2 rows");
  });
  it("never silently drops nonfinite points or a missing row", () => {
    expect(validationFigureSvg({ ...figure, predicted: [NaN, 2] })).toBe("");
    expect(validationFigureSvg({ ...figure, total_rows: 3 })).toBe("");
    expect(validationFigureCaption({ ...figure, total_rows: 3 })).toContain("Figure unavailable");
  });
});
