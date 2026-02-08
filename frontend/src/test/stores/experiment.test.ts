import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useExperimentStore } from '@/stores/experiment'
import api from '@/services/api'

// Mock the API module
vi.mock('@/services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

describe('Experiment Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('initializes with empty state', () => {
    const store = useExperimentStore()
    expect(store.experiments).toEqual([])
    expect(store.selectedExperiment).toBeNull()
    expect(store.files).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('fetches experiments successfully', async () => {
    const mockExperiments = [
      { id: 1, name: 'Experiment 1', description: 'Test 1' },
      { id: 2, name: 'Experiment 2', description: 'Test 2' },
    ]

    vi.mocked(api.get).mockResolvedValueOnce({ data: mockExperiments })

    const store = useExperimentStore()
    await store.fetchExperiments()

    expect(api.get).toHaveBeenCalledWith('/experiments')
    expect(store.experiments).toEqual(mockExperiments)
    expect(store.loading).toBe(false)
  })

  it('handles fetch experiments error', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(api.get).mockRejectedValueOnce(new Error('Network error'))

    const store = useExperimentStore()
    await store.fetchExperiments()

    expect(store.experiments).toEqual([])
    expect(store.loading).toBe(false)
    expect(consoleSpy).toHaveBeenCalled()

    consoleSpy.mockRestore()
  })

  it('selects an experiment', async () => {
    const mockExperiment = { id: 1, name: 'Test Experiment' }
    const mockFiles = [{ id: 1, file_path: 'test.csv' }]

    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: mockExperiment })
      .mockResolvedValueOnce({ data: mockFiles })

    const store = useExperimentStore()
    await store.selectExperiment(1)

    expect(api.get).toHaveBeenCalledWith('/experiments/1')
    expect(api.get).toHaveBeenCalledWith('/experiments/1/files')
    expect(store.selectedExperiment).toEqual(mockExperiment)
    expect(store.files).toEqual(mockFiles)
  })

  it('creates a new experiment', async () => {
    const newExperiment = {
      name: 'New Experiment',
      description: 'Test description',
      metadata: {},
    }

    const createdExperiment = { id: 1, ...newExperiment }
    vi.mocked(api.post).mockResolvedValueOnce({ data: createdExperiment })

    const store = useExperimentStore()
    const result = await store.createExperiment(newExperiment)

    expect(api.post).toHaveBeenCalledWith('/experiments', newExperiment)
    expect(result).toEqual(createdExperiment)
  })
})
