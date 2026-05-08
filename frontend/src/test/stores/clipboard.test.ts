import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useClipboardStore, type ClipboardPayload } from '../../stores/clipboard';
import type { WorkflowNode, WorkflowEdge } from '../../stores/workflow';

describe('Clipboard Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('initializes with an empty payload', () => {
    const store = useClipboardStore();
    expect(store.payload).toBeNull();
    expect(store.isEmpty()).toBe(true);
  });

  it('stores and retrieves payloads accurately, returning deep copies', () => {
    const store = useClipboardStore();

    const mockPayload: ClipboardPayload = {
      nodes: [
        { id: 'node_1', type: 'DATA', x: 0, y: 0, params: {} } as WorkflowNode
      ],
      edges: [
        { from: 'node_1', to: 'node_2', fromPort: 'default', toPort: 'default' } as WorkflowEdge
      ],
      sourceWorkflowId: 101
    };

    store.set(mockPayload);
    expect(store.isEmpty()).toBe(false);

    const retrieved = store.get();
    expect(retrieved).not.toBeNull();
    expect(retrieved!.nodes.length).toBe(1);
    expect(retrieved!.edges.length).toBe(1);
    expect(retrieved!.sourceWorkflowId).toBe(101);

    // Verify it is a deep copy
    expect(retrieved).not.toBe(store.payload);
    expect(retrieved!.nodes[0]).not.toBe(store.payload!.nodes[0]);

    retrieved!.nodes[0].params.changed = true;
    expect(store.payload!.nodes[0].params.changed).toBeUndefined();
  });
});
