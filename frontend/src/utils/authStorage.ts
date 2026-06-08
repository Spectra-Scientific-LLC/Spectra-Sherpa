const API_KEY_STORAGE_KEY = "api_key";
const TOKEN_STORAGE_KEY = "token";

export function readStoredApiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE_KEY) || "";
}

export function hasStoredApiKey(): boolean {
  return Boolean(readStoredApiKey());
}

export function writeStoredApiKey(value: string): void {
  // Local/OSS compatibility credential: enterprise browser auth uses JWTs,
  // while local and hybrid deployments may still need an API key fallback.
  // lgtm[js/clear-text-storage-of-sensitive-data]
  localStorage.setItem(API_KEY_STORAGE_KEY, value);
}

export function clearStoredApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE_KEY);
}

export function readStoredToken(): string {
  return localStorage.getItem(TOKEN_STORAGE_KEY) || "";
}

export function hasStoredToken(): boolean {
  return Boolean(readStoredToken());
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}
