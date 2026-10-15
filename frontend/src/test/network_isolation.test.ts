import { describe, expect, it, vi } from 'vitest'

describe('unit-test network isolation', () => {
  it('refuses an unmocked fetch before it reaches the local backend', async () => {
    await expect(fetch('http://127.0.0.1:8000/api/v1/health')).rejects.toThrow(
      'Unmocked unit-test fetch request',
    )
  })

  it('allows an explicitly mocked fetch', async () => {
    const mock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', mock)
    try {
      expect((await fetch('/api/v1/health')).ok).toBe(true)
      expect(mock).toHaveBeenCalledOnce()
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
