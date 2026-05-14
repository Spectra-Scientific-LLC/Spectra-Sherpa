import axios from "axios";

import type { AuditEventRecord } from "./types";

export function shortId(value: string | null | undefined, length = 8): string {
  if (!value) return "n/a";
  return value.length > length ? value.slice(0, length) : value;
}

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}

export function hasEventState(event: AuditEventRecord): boolean {
  return Boolean(event.before_state || event.after_state || event.context);
}

export function renderEventState(event: AuditEventRecord): string {
  return JSON.stringify(
    {
      before_state: event.before_state,
      after_state: event.after_state,
      context: event.context,
    },
    null,
    2,
  );
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function extractFilename(disposition: string | undefined, fallback: string): string {
  const match = disposition?.match(/filename="([^"]+)"/);
  return match?.[1] ?? fallback;
}

function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    return typeof message === "string" ? message : null;
  }
  if (detail) return JSON.stringify(detail);
  return null;
}

export async function extractApiErrorMessage(err: unknown, fallback: string): Promise<string> {
  if (!axios.isAxiosError(err)) return fallback;

  const data = err.response?.data;
  if (data instanceof Blob) {
    const text = await data.text();
    if (!text) return err.message || fallback;
    try {
      const parsed = JSON.parse(text);
      return formatDetail(parsed.detail) ?? err.message ?? fallback;
    } catch {
      return text;
    }
  }

  return formatDetail(data?.detail) ?? err.message ?? fallback;
}
