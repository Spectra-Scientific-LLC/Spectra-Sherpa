import { describe, it, expect } from 'vitest'
import {
  MULTI_INPUT_NODES,
  NODE_TYPE_MAP,
  getLegacyNodeType,
  normalizeNodeType,
} from '@/stores/workflow'

describe('Workflow node type mappings', () => {
  it('normalizes clustering and regression node types', () => {
    expect(normalizeNodeType('KMEANS')).toBe('model.kmeans')
    expect(normalizeNodeType('DBSCAN')).toBe('model.dbscan')
    expect(normalizeNodeType('HCA')).toBe('model.hca')
    expect(normalizeNodeType('PCR')).toBe('model.pcr')
    expect(normalizeNodeType('SVR')).toBe('model.svr')
  })

  it('provides legacy reverse mappings for new nodes', () => {
    expect(getLegacyNodeType('model.kmeans')).toBe('KMEANS')
    expect(getLegacyNodeType('model.dbscan')).toBe('DBSCAN')
    expect(getLegacyNodeType('model.hca')).toBe('HCA')
    expect(getLegacyNodeType('model.pcr')).toBe('PCR')
    expect(getLegacyNodeType('model.svr')).toBe('SVR')
  })

  it('keeps multi-input port definitions for regression nodes', () => {
    expect(MULTI_INPUT_NODES.PCR).toBeDefined()
    expect(MULTI_INPUT_NODES.SVR).toBeDefined()
  })

  it('includes new node types in the mapping table', () => {
    expect(NODE_TYPE_MAP.KMEANS).toBe('model.kmeans')
    expect(NODE_TYPE_MAP.DBSCAN).toBe('model.dbscan')
    expect(NODE_TYPE_MAP.HCA).toBe('model.hca')
    expect(NODE_TYPE_MAP.PCR).toBe('model.pcr')
    expect(NODE_TYPE_MAP.SVR).toBe('model.svr')
  })
})
