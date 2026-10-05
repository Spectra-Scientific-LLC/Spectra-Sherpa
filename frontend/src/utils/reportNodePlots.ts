import type { RunReportEntry } from "./reportGenerator";
import { reportMarkdownText } from "./reportValues";
import { validationFigureSvg, validationFigureCaption } from "./validationReportPlots";

export interface ReportNodePlotSection {
  node_id: string;
  label: string;
  node_type: string;
  notices: string[];
  plots: { title: string; image?: string; notice?: string }[];
}

const escape = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const safeImage = (image?: string) => image && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(image) ? image : null;

/** Render run-scoped figures, never images from today's canvas. */
export function reportNodePlotsHtml(run: RunReportEntry): string {
  const sections = run.node_plots ?? [];
  const figures = run.validation_summary?.schema_version === "spectrasherpa-readable-validation/1" && run.validation_summary.run_id === run.id ? run.validation_summary.figures ?? [] : [];
  if (!sections.length && !figures.length) return "";
  let html = `<section class="report-plot-sections"><h2>Plots by node — ${escape(run.name)}</h2>`;
  for (const node of sections) {
    html += `<section class="report-node-plots"><h3>${escape(node.label)} <small>(${escape(node.node_id)} · ${escape(node.node_type)})</small></h3>`;
    for (const notice of node.notices) html += `<p>${escape(notice)}</p>`;
    for (const plot of node.plots) {
      const image = safeImage(plot.image);
      html += `<figure class="report-figure"><h4>${escape(plot.title)}</h4>${image ? `<img src="${image}" alt="${escape(plot.title)}" />` : ""}${plot.notice ? `<figcaption>${escape(plot.notice)}</figcaption>` : ""}</figure>`;
    }
    if (!node.plots.some(plot => safeImage(plot.image))) {
      for (const figure of figures.filter(value => value.node_id === node.node_id)) html += `<figure class="report-figure">${validationFigureSvg(figure)}<figcaption>${escape(validationFigureCaption(figure))}</figcaption></figure>`;
    }
    html += "</section>";
  }
  // Validation figures remain available even when a node presentation cannot be captured.
  for (const nodeId of [...new Set(figures.map(figure => figure.node_id))]) {
    if (sections.some(node => node.node_id === nodeId)) continue;
    html += `<section class="report-node-plots"><h3>Validation — ${escape(nodeId)}</h3>`;
    for (const figure of figures.filter(value => value.node_id === nodeId)) {
      html += `<figure class="report-figure">${validationFigureSvg(figure)}<figcaption>${escape(validationFigureCaption(figure))}</figcaption></figure>`;
    }
    html += "</section>";
  }
  return html + "</section>";
}

export function reportNodePlotsMarkdown(run: RunReportEntry): string {
  const sections = run.node_plots ?? [];
  const figures = run.validation_summary?.schema_version === "spectrasherpa-readable-validation/1" && run.validation_summary.run_id === run.id ? run.validation_summary.figures ?? [] : [];
  if (!sections.length && !figures.length) return "";
  const lines = [`## Plots by node — ${reportMarkdownText(run.name)}`, ""];
  for (const node of sections) {
    lines.push(`### ${reportMarkdownText(node.label)} (${reportMarkdownText(node.node_id)} · ${reportMarkdownText(node.node_type)})`, "", ...node.notices.map(reportMarkdownText), "");
    for (const plot of node.plots) {
      lines.push(`#### ${reportMarkdownText(plot.title)}`, "");
      const image = safeImage(plot.image);
      if (image) lines.push(`![${reportMarkdownText(plot.title)}](${image})`, "");
      if (plot.notice) lines.push(reportMarkdownText(plot.notice), "");
    }
    if (!node.plots.some(plot => safeImage(plot.image))) {
      for (const figure of figures.filter(value => value.node_id === node.node_id)) lines.push(validationFigureSvg(figure), "", reportMarkdownText(validationFigureCaption(figure)), "");
    }
  }
  for (const nodeId of [...new Set(figures.map(figure => figure.node_id))]) {
    if (sections.some(node => node.node_id === nodeId)) continue;
    lines.push(`### Validation — ${reportMarkdownText(nodeId)}`, "");
    for (const figure of figures.filter(value => value.node_id === nodeId)) lines.push(validationFigureSvg(figure), "", reportMarkdownText(validationFigureCaption(figure)), "");
  }
  return lines.join("\n");
}
