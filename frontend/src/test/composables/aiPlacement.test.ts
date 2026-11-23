import { describe, expect, it, vi, beforeEach } from 'vitest'

const get = vi.fn()
vi.mock('@/api', () => ({ api: { get } }))

describe('AI placement light', () => {
  beforeEach(() => { vi.resetModules(); get.mockReset() })

  async function placement(config: Record<string, unknown>) {
    get.mockResolvedValue({ data: config })
    const { useAppConfig } = await import('@/composables/useAppConfig')
    const app = useAppConfig()
    await app.reloadConfig()
    return app.aiPlacement.value
  }

  const base = { mode: 'local', features: {}, capabilities: {}, llms: {} }

  it('is Local only when every configured AI endpoint runs on this computer', async () => {
    expect(await placement({ ...base, llms: { ollama: { provider: 'ollama', model: 'm', enabled: true, local: true } } })).toBe('local')
    expect(await placement({ ...base, llms: {
      a: { provider: 'ollama', model: 'm', enabled: true, local: true },
      b: { provider: 'openai', model: 'm', enabled: true, local: false },
    } })).toBe('hosted')
  })

  it('is Hosted for a deployment-managed AI and Off when nothing is configured', async () => {
    expect(await placement({ ...base, mode: 'enterprise', capabilities: { managedLlm: true } })).toBe('hosted')
    expect(await placement(base)).toBe('off')
  })
})
