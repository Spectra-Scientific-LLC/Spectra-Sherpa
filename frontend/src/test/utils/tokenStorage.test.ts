import { beforeEach, describe, expect, it } from "vitest";
import {
  saveToken,
  loadToken,
  clearToken,
  hasToken,
  getAllTokens,
  clearAllTokens,
} from "@/utils/tokenStorage";

describe("tokenStorage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe("saveToken / loadToken", () => {
    it("round-trips a token through base64 encoding", () => {
      saveToken("openai", "sk-test-key-123");
      expect(loadToken("openai")).toBe("sk-test-key-123");
    });

    it("returns null for missing provider", () => {
      expect(loadToken("anthropic")).toBeNull();
    });

    it("returns null for corrupted storage", () => {
      localStorage.setItem("llm_token_openai", "not-json");
      expect(loadToken("openai")).toBeNull();
    });

    it("overwrites previous token for same provider", () => {
      saveToken("openai", "key-1");
      saveToken("openai", "key-2");
      expect(loadToken("openai")).toBe("key-2");
    });
  });

  describe("clearToken", () => {
    it("removes token for a provider", () => {
      saveToken("openai", "key");
      clearToken("openai");
      expect(loadToken("openai")).toBeNull();
    });
  });

  describe("hasToken", () => {
    it("returns false when no token", () => {
      expect(hasToken("openai")).toBe(false);
    });

    it("returns true when token exists", () => {
      saveToken("deepseek", "key");
      expect(hasToken("deepseek")).toBe(true);
    });
  });

  describe("getAllTokens", () => {
    it("returns all providers with presence flags", () => {
      saveToken("openai", "k1");
      saveToken("gemini", "k2");
      const tokens = getAllTokens();
      expect(tokens).toEqual({
        openai: true,
        anthropic: false,
        deepseek: false,
        gemini: true,
      });
    });
  });

  describe("clearAllTokens", () => {
    it("removes all provider tokens", () => {
      saveToken("openai", "k1");
      saveToken("anthropic", "k2");
      clearAllTokens();
      expect(getAllTokens()).toEqual({
        openai: false,
        anthropic: false,
        deepseek: false,
        gemini: false,
      });
    });
  });
});
