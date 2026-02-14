/**
 * API token storage utilities
 *
 * Stores LLM API tokens in localStorage with base64 encoding.
 * Client-side encryption would not add real security here — any JS
 * running on the page could read the decryption key too. The actual
 * security boundary is HTTPS transport + server-side validation.
 * Base64 encoding prevents casual shoulder-surfing in DevTools.
 */

import type { LLMProvider, StoredToken } from '@/types/config'

const TOKEN_PREFIX = 'llm_token_'

/**
 * Simple base64 encoding (not encryption!)
 */
function encodeToken(token: string): string {
  return btoa(token)
}

/**
 * Decode base64
 */
function decodeToken(encoded: string): string {
  return atob(encoded)
}

/**
 * Save API token to localStorage
 */
export function saveToken(provider: LLMProvider, token: string): void {
  const stored: StoredToken = {
    provider,
    token: encodeToken(token),
    savedAt: new Date().toISOString(),
  }

  localStorage.setItem(`${TOKEN_PREFIX}${provider}`, JSON.stringify(stored))
}

/**
 * Load API token from localStorage
 */
export function loadToken(provider: LLMProvider): string | null {
  const item = localStorage.getItem(`${TOKEN_PREFIX}${provider}`)
  if (!item) return null

  try {
    const stored: StoredToken = JSON.parse(item)
    return decodeToken(stored.token)
  } catch (error) {
    console.error(`Failed to load token for ${provider}:`, error)
    return null
  }
}

/**
 * Remove API token from localStorage
 */
export function clearToken(provider: LLMProvider): void {
  localStorage.removeItem(`${TOKEN_PREFIX}${provider}`)
}

/**
 * Check if token exists for provider
 */
export function hasToken(provider: LLMProvider): boolean {
  return localStorage.getItem(`${TOKEN_PREFIX}${provider}`) !== null
}

/**
 * Get all saved tokens (without decoding)
 */
export function getAllTokens(): Record<string, boolean> {
  const tokens: Record<string, boolean> = {}
  const providers: LLMProvider[] = ['openai', 'anthropic', 'deepseek', 'gemini']

  for (const provider of providers) {
    tokens[provider] = hasToken(provider)
  }

  return tokens
}

/**
 * Clear all tokens
 */
export function clearAllTokens(): void {
  const providers: LLMProvider[] = ['openai', 'anthropic', 'deepseek', 'gemini']
  providers.forEach(clearToken)
}
