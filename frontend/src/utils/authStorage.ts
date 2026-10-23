import { readBrowserToken, endBrowserSession } from '@/extension-contract/session-v1';
const API_KEY_STORAGE_KEY = "api_key";

let runtimeApiKey = "";

if (typeof import.meta !== "undefined") {
  runtimeApiKey = (import.meta.env.VITE_DEFAULT_API_KEY as string | undefined) || "";
}

export function readStoredApiKey(): string {
  if (localStorage.getItem(API_KEY_STORAGE_KEY)) {
    localStorage.removeItem(API_KEY_STORAGE_KEY);
  }
  return runtimeApiKey;
}

export function hasStoredApiKey(): boolean {
  return Boolean(readStoredApiKey());
}

export function writeStoredApiKey(value: string): void {
  runtimeApiKey = value;
}

export function clearStoredApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE_KEY);
  runtimeApiKey = "";
}

export function readStoredToken(): string {
  return readBrowserToken() || "";
}

export function hasStoredToken(): boolean {
  return Boolean(readStoredToken());
}

export async function clearStoredToken(): Promise<void> {
  await endBrowserSession();
}
