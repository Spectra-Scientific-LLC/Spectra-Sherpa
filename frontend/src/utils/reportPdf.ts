/**
 * Open a self-contained report HTML document in a print window.
 *
 * Browsers do not allow a web app to write an arbitrary PDF file directly
 * without a PDF rendering dependency or server-side renderer. The native
 * print dialog is the most dependable local-first path: users choose
 * "Save as PDF", and the report HTML controls the printed layout.
 */
export function openReportPdfExport(html: string, filename: string): boolean {
  const printWindow = window.open("", "_blank", "width=1100,height=800");
  if (!printWindow) return false;

  const title = filename.replace(/\.pdf$/i, "");
  const printableHtml = html.replace(
    /<title>.*?<\/title>/i,
    `<title>${escapeTitle(title)}</title>`,
  );

  printWindow.document.open();
  printWindow.document.write(printableHtml);
  printWindow.document.close();

  const printWhenReady = () => {
    printWindow.focus();
    printWindow.print();
  };

  if (printWindow.document.readyState === "complete") {
    window.setTimeout(printWhenReady, 100);
  } else {
    printWindow.addEventListener("load", () => window.setTimeout(printWhenReady, 100), {
      once: true,
    });
  }

  return true;
}

function escapeTitle(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
