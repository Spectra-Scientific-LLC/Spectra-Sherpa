import { describe, it, expect, beforeEach, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import WorkflowCanvas from '../../views/workflow-builder/WorkflowCanvas.vue';
import type { WorkflowNode, WorkflowEdge } from '../../stores/workflow';

describe('WorkflowCanvas Selection & Multi-Drag', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  const mockNodes: WorkflowNode[] = [
    { id: 'node_1', type: 'DATA', x: 100, y: 100, params: {} } as WorkflowNode,
    { id: 'node_2', type: 'PREPROCESS', x: 300, y: 100, params: {} } as WorkflowNode,
  ];

  const mockEdges: WorkflowEdge[] = [];

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
});
