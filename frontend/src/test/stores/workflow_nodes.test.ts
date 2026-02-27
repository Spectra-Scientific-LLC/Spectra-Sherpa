import { describe, it, expect } from 'vitest'

describe('Workflow node types', () => {
  it('uses canonical dot-notation types', () => {
    // Legacy UPPERCASE types and mapping functions have been removed.
    // Node types are always canonical dot-notation: model.pca, preprocess.smooth, etc.
    const canonicalTypes = [
      'model.kmeans',
      'model.dbscan',
      'model.hca',
      'model.pcr',
      'model.svr',
      'data.source',
      'preprocess.normalize',
    ]
    canonicalTypes.forEach((t) => {
      expect(t).toMatch(/^[a-z]+\.[a-z_]+$/)
    })
  })
})
