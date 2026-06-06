import { describe, it, expect, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import WorkflowCanvas from '../../views/workflow-builder/WorkflowCanvas.vue';
import { useWorkflowStore } from '../../stores/workflow';
import type { WorkflowNode, WorkflowEdge } from '../../stores/workflow';
import type { NodeTypeMetadata } from '../../types';

describe('WorkflowCanvas Selection & Multi-Drag', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  const mockNodes: WorkflowNode[] = [
    { id: 'node_1', type: 'DATA', x: 100, y: 100, params: {} } as WorkflowNode,
    { id: 'node_2', type: 'PREPROCESS', x: 300, y: 100, params: {} } as WorkflowNode,
  ];

  const mockEdges: WorkflowEdge[] = [];

  const makeNodeMetadata = (
    node_type: string,
    category: string,
    label: string,
  ): NodeTypeMetadata => ({
    node_type,
    category,
    label,
    description: "",
    parameters: [],
    input_types: [],
    output_type: "",
  });

  const seedNodeLibrary = () => {
    const store = useWorkflowStore();
    store.nodeLibrary = new Map<string, NodeTypeMetadata>([
      ["data.synthetic_curve", makeNodeMetadata("data.synthetic_curve", "synthesis", "Synthetic Curve")],
      ["model.pca", makeNodeMetadata("model.pca", "exploratory", "PCA")],
      ["model.pls", makeNodeMetadata("model.pls", "regression", "PLS Regression")],
      ["classification.plsda", makeNodeMetadata("classification.plsda", "classification", "PLS-DA")],
      ["model.kmeans", makeNodeMetadata("model.kmeans", "clustering", "K-Means")],
      ["diagnostics.cross_validation", makeNodeMetadata("diagnostics.cross_validation", "validation", "Cross Validation")],
      ["output.plot", makeNodeMetadata("output.plot", "output", "Plot")],
      ["output.export", makeNodeMetadata("output.export", "output", "Export")],
    ]);
  };

  it('selects a single node without modifiers', async () => {
    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: mockNodes, edges: mockEdges, nodeOutputs: new Map() }
    });

    const nodes = wrapper.findAll('.workflow-node');
    expect(nodes.length).toBe(2);

    // Click first node
    await nodes[0].trigger('mousedown', { clientX: 100, clientY: 100 });
    expect(wrapper.vm.selectedNodeIds.has('node_1')).toBe(true);
    expect(wrapper.vm.selectedNodeIds.has('node_2')).toBe(false);

    // Emitted node-select
    expect(wrapper.emitted('node-select')).toBeTruthy();
    expect(wrapper.emitted('node-select')![0][0]).toEqual(mockNodes[0]);
  });

  it('multi-selects nodes with Shift/Cmd modifiers', async () => {
    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: mockNodes, edges: mockEdges, nodeOutputs: new Map() }
    });

    const nodes = wrapper.findAll('.workflow-node');

    // Click first node
    await nodes[0].trigger('mousedown', { clientX: 100, clientY: 100 });
    
    // Shift-click second node
    await nodes[1].trigger('mousedown', { clientX: 300, clientY: 100, shiftKey: true });
    
    expect(wrapper.vm.selectedNodeIds.size).toBe(2);
    expect(wrapper.vm.selectedNodeIds.has('node_1')).toBe(true);
    expect(wrapper.vm.selectedNodeIds.has('node_2')).toBe(true);
  });

  it('toggles nodes with Ctrl/Cmd click', async () => {
    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: mockNodes, edges: mockEdges, nodeOutputs: new Map() }
    });

    const nodes = wrapper.findAll('.workflow-node');

    await nodes[0].trigger('mousedown', { clientX: 100, clientY: 100 });
    await nodes[1].trigger('mousedown', { clientX: 300, clientY: 100, ctrlKey: true });
    expect(wrapper.vm.selectedNodeIds.size).toBe(2);

    await nodes[0].trigger('mousedown', { clientX: 100, clientY: 100, ctrlKey: true });
    expect(wrapper.vm.selectedNodeIds.has('node_1')).toBe(false);
    expect(wrapper.vm.selectedNodeIds.has('node_2')).toBe(true);
  });

  it('clears selection when clicking empty canvas', async () => {
    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: mockNodes, edges: mockEdges, nodeOutputs: new Map() }
    });

    // Select all first
    wrapper.vm.selectAll();
    expect(wrapper.vm.selectedNodeIds.size).toBe(2);

    // Click canvas background
    const canvas = wrapper.find('.workflow-canvas');
    await canvas.trigger('mousedown', { clientX: 10, clientY: 10 });
    await canvas.trigger('mouseup');

    expect(wrapper.vm.selectedNodeIds.size).toBe(0);
    expect(wrapper.emitted('node-select')).toBeTruthy();
    expect(wrapper.emitted('node-select')![wrapper.emitted('node-select')!.length - 1][0]).toBeNull();
  });

  it('initiates rubber-band selection', async () => {
    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: mockNodes, edges: mockEdges, nodeOutputs: new Map() }
    });

    const canvas = wrapper.find('.workflow-canvas');
    
    // Mouse down on empty space
    await canvas.trigger('mousedown', { clientX: 0, clientY: 0 });
    expect(wrapper.find('.rubber-band').exists()).toBe(true);

    // Move over nodes (0,0) to (500,500)
    await wrapper.trigger('mousemove', { clientX: 500, clientY: 500 });
    
    // Finish drag
    await wrapper.trigger('mouseup');
    
    // Rubber band box should disappear
    expect(wrapper.find('.rubber-band').exists()).toBe(false);
    
    // Both nodes should be selected
    expect(wrapper.vm.selectedNodeIds.size).toBe(2);
  });

  it('drags all selected nodes together', async () => {
    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: mockNodes, edges: mockEdges, nodeOutputs: new Map() }
    });

    const nodes = wrapper.findAll('.workflow-node');
    await nodes[0].trigger('mousedown', { clientX: 100, clientY: 100 });
    await nodes[1].trigger('mousedown', { clientX: 300, clientY: 100, shiftKey: true });

    await nodes[0].trigger('mousedown', { clientX: 100, clientY: 100 });
    await wrapper.trigger('mousemove', { clientX: 140, clientY: 130 });

    const emitted = wrapper.emitted('update:nodes');
    expect(emitted).toBeTruthy();
    const updatedNodes = emitted![emitted!.length - 1][0] as WorkflowNode[];
    expect(updatedNodes.find((node) => node.id === 'node_1')).toMatchObject({ x: 140, y: 130 });
    expect(updatedNodes.find((node) => node.id === 'node_2')).toMatchObject({ x: 340, y: 130 });
  });

  it('shows Paste in the canvas context menu and emits paste-selection', async () => {
    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: mockNodes, edges: mockEdges, nodeOutputs: new Map() }
    });

    await wrapper.find('.workflow-canvas').trigger('contextmenu', {
      clientX: 20,
      clientY: 20,
    });

    const pasteItem = wrapper
      .findAll('.context-menu-item')
      .find((item) => item.text().includes('Paste'));
    expect(pasteItem).toBeTruthy();

    await pasteItem!.trigger('click');
    expect(wrapper.emitted('paste-selection')).toBeTruthy();
  });

  it('does not clear selection on right-click before opening the context menu', async () => {
    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: mockNodes, edges: mockEdges, nodeOutputs: new Map() }
    });

    wrapper.vm.selectAll();
    await wrapper.find('.workflow-canvas').trigger('mousedown', {
      button: 2,
      clientX: 20,
      clientY: 20,
    });

    expect(wrapper.vm.selectedNodeIds.size).toBe(2);
  });

  it('uses the same category color classes for loaded nodes as the add-node palette', () => {
    seedNodeLibrary();
    const loadedNodes: WorkflowNode[] = [
      { id: 'synthetic', type: 'data.synthetic_curve', x: 0, y: 0, params: {} } as WorkflowNode,
      { id: 'pca', type: 'model.pca', x: 180, y: 0, params: {} } as WorkflowNode,
      { id: 'pls', type: 'model.pls', x: 360, y: 0, params: {} } as WorkflowNode,
      { id: 'plsda', type: 'classification.plsda', x: 540, y: 0, params: {} } as WorkflowNode,
      { id: 'kmeans', type: 'model.kmeans', x: 720, y: 0, params: {} } as WorkflowNode,
      { id: 'cv', type: 'diagnostics.cross_validation', x: 900, y: 0, params: {} } as WorkflowNode,
      { id: 'plot', type: 'output.plot', x: 1080, y: 0, params: {} } as WorkflowNode,
      { id: 'export', type: 'output.export', x: 1260, y: 0, params: {} } as WorkflowNode,
    ];

    const wrapper = mount(WorkflowCanvas, {
      props: { nodes: loadedNodes, edges: mockEdges, nodeOutputs: new Map() },
    });

    const headers = wrapper.findAll('.node-header').map((header) => header.classes());
    expect(headers[0]).toContain('header-synthesis');
    expect(headers[1]).toContain('header-exploratory');
    expect(headers[2]).toContain('header-regression');
    expect(headers[3]).toContain('header-classify');
    expect(headers[4]).toContain('header-clustering');
    expect(headers[5]).toContain('header-validation');
    expect(headers[6]).toContain('header-visualize');
    expect(headers[7]).toContain('header-export');
  });
});
