/**
 * Sherpa Advisor memory adapter (R1 + R2 + R9).
 *
 * The frontend's only role for memory is **detect** the active scope and
 * **render** the state the server returns.  This module hides the
 * server/local split behind a single interface so the rest of the app
 * does not need to know which mode it is in.
 *
 * Server-backed mode (hybrid / enterprise) talks to spectra-server's
 * ``/api/v1/memory/*`` endpoints.  Local mode keeps a minimal per-scope
 * topic list in ``localStorage`` — no graph, no facts, no compaction,
 * no Memory Map.
 *
 * R1 surface: scope switching + topic CRUD.
 * R2 surface: compaction (server-backed only; local is a no-op).
 * R9 surface: Memory Map data fetch (server-backed only; local returns
 * ``null`` so the view can render an "upgrade to enable" stub).
 */

import api from "@/api/client";

export interface ScopeArgs {
  projectId: number;
  tabKey: string;
  subscopeKey: string;
  resourceType?: string | null;
  resourceId?: number | null;
  title?: string | null;
}

export interface MemoryNode {
  id: number;
  project_id: number;
  node_type: string;
  tab_key: string;
  subscope_key: string;
  title: string | null;
  resource_type: string | null;
  resource_id: number | null;
  visibility: string;
  owner_user_id: number | null;
}

export interface Topic {
  id: number;
  memory_node_id: number;
  /** Server-internal — present here only because legacy chat-load paths still use it. Removed in R2. */
  conversation_id: string | null;
  title: string | null;
  is_archived: boolean;
  created_at: string;
  last_used_at: string;
}

export interface ScopeStateEnvelope {
  active_node: MemoryNode;
  topics: Topic[];
  active_topic_id: number | null;
}

export interface CompactScopeResult {
  nodeId: number;
  /** ``false`` when the node had nothing to compact (no active topic, < 2 messages, or local mode). */
  compacted: boolean;
  factId: number | null;
  version: number | null;
  messageCount: number | null;
}

// R9 — Memory Map types.  Mirror the server response shape exactly so
// the view can render badge data without an extra normalization layer.
export interface NodeBadges {
  topic_count: number;
  fact_count: number;
  last_compaction_at: string | null;
  stale_descendant_count: number;
}

export interface MemoryMapNode {
  id: number;
  tab_key: string;
  subscope_key: string;
  node_type: string;
  title: string | null;
  badges: NodeBadges;
}

export interface MemoryMapEdge {
  id: number;
  source_node_id: number;
  target_node_id: number;
  edge_type: string;
  weight: number;
}

export interface MemoryMapData {
  project_id: number;
  nodes: MemoryMapNode[];
  edges: MemoryMapEdge[];
}

export interface AdvisorMemoryAdapter {
  switchScope(args: ScopeArgs): Promise<ScopeStateEnvelope>;
  listTopics(nodeId: number): Promise<Topic[]>;
  createTopic(nodeId: number, init?: { title?: string | null; conversationId?: string | null }): Promise<Topic>;
  setActiveTopic(nodeId: number, topicId: number | null): Promise<ScopeStateEnvelope>;
  /** R2: compact the active topic into a summary fact.  Local-mode no-op. */
  compactScope(nodeId: number): Promise<CompactScopeResult>;
  /** R9: Memory Map data fetch.  Returns ``null`` in local mode (no graph). */
  getMemoryMap(projectId: number): Promise<MemoryMapData | null>;
}

// ---------------------------------------------------------------------------
// Server-backed adapter
// ---------------------------------------------------------------------------

class ServerAdvisorMemoryAdapter implements AdvisorMemoryAdapter {
  async switchScope(args: ScopeArgs): Promise<ScopeStateEnvelope> {
    const { data } = await api.post<ScopeStateEnvelope>("/memory/scope/switch", {
      project_id: args.projectId,
      tab_key: args.tabKey,
      subscope_key: args.subscopeKey,
      resource_type: args.resourceType ?? null,
      resource_id: args.resourceId ?? null,
      title: args.title ?? null,
    });
    return data;
  }

  async listTopics(nodeId: number): Promise<Topic[]> {
    const { data } = await api.get<Topic[]>(`/memory/nodes/${nodeId}/topics`);
    return data;
  }

  async createTopic(
    nodeId: number,
    init: { title?: string | null; conversationId?: string | null } = {},
  ): Promise<Topic> {
    const { data } = await api.post<Topic>(`/memory/nodes/${nodeId}/topics`, {
      title: init.title ?? null,
      conversation_id: init.conversationId ?? null,
    });
    return data;
  }

  async setActiveTopic(nodeId: number, topicId: number | null): Promise<ScopeStateEnvelope> {
    const { data } = await api.patch<ScopeStateEnvelope>(
      `/memory/nodes/${nodeId}/active-topic`,
      { topic_id: topicId },
    );
    return data;
  }

  async compactScope(nodeId: number): Promise<CompactScopeResult> {
    const { data } = await api.post<{
      node_id: number;
      compacted: boolean;
      fact_id: number | null;
      version: number | null;
      message_count: number | null;
    }>(`/memory/nodes/${nodeId}/compact`);
    return {
      nodeId: data.node_id,
      compacted: data.compacted,
      factId: data.fact_id,
      version: data.version,
      messageCount: data.message_count,
    };
  }

  async getMemoryMap(projectId: number): Promise<MemoryMapData | null> {
    const { data } = await api.get<MemoryMapData>("/memory/map", {
      params: { project_id: projectId },
    });
    return data;
  }
}

// ---------------------------------------------------------------------------
// Local adapter (degraded mode for OSS local-only deployments)
// ---------------------------------------------------------------------------

const LOCAL_STORAGE_KEY = "spectra_sherpa_local_memory_v1";

interface LocalState {
  nodes: MemoryNode[];
  topics: Topic[];
  /**
   * Per-node active topic. Keyed by node id, value is the topic id (or
   * null when no topic is active). Distinct namespace from node ids —
   * comparing ``topic.id === node.id`` is wrong (R1 review fix).
   */
  nodeActiveTopics: Record<number, number | null>;
  /** Auto-incrementing IDs so the local adapter can mint primary keys. */
  nextNodeId: number;
  nextTopicId: number;
}

function emptyState(): LocalState {
  return { nodes: [], topics: [], nodeActiveTopics: {}, nextNodeId: 1, nextTopicId: 1 };
}

function loadLocalState(): LocalState {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<LocalState>;
      return {
        nodes: parsed.nodes ?? [],
        topics: parsed.topics ?? [],
        // Backfill on read so older clients without the field do not
        // crash when this build first runs against their localStorage.
        nodeActiveTopics: parsed.nodeActiveTopics ?? {},
        nextNodeId: parsed.nextNodeId ?? 1,
        nextTopicId: parsed.nextTopicId ?? 1,
      };
    }
  } catch (error) {
    console.warn("[advisorMemoryAdapter] failed to read localStorage; resetting", error);
  }
  return emptyState();
}

function persistLocalState(state: LocalState): void {
  try {
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    console.warn("[advisorMemoryAdapter] failed to persist localStorage", error);
  }
}

function nowIso(): string {
  return new Date().toISOString();
}

class LocalAdvisorMemoryAdapter implements AdvisorMemoryAdapter {
  async switchScope(args: ScopeArgs): Promise<ScopeStateEnvelope> {
    const state = loadLocalState();
    let node = state.nodes.find(
      (n) =>
        n.project_id === args.projectId &&
        n.tab_key === args.tabKey &&
        n.subscope_key === args.subscopeKey,
    );
    if (!node) {
      node = {
        id: state.nextNodeId++,
        project_id: args.projectId,
        node_type:
          args.tabKey === "workflow" && args.subscopeKey.startsWith("sheet:")
            ? "workflow_sheet"
            : "subtab",
        tab_key: args.tabKey,
        subscope_key: args.subscopeKey,
        title: args.title ?? null,
        resource_type: args.resourceType ?? null,
        resource_id: args.resourceId ?? null,
        visibility: "project",
        owner_user_id: null,
      };
      state.nodes.push(node);
    } else if (args.title && node.title !== args.title) {
      node.title = args.title;
    }
    persistLocalState(state);

    const topics = state.topics.filter((t) => t.memory_node_id === node!.id && !t.is_archived);
    // Active topic is keyed by node id but stored as a topic id, so the
    // lookup is `nodeActiveTopics[node.id]` — never `topic.id === node.id`.
    const storedActiveTopicId = state.nodeActiveTopics[node.id] ?? null;
    const activeTopicStillValid =
      storedActiveTopicId !== null && topics.some((t) => t.id === storedActiveTopicId);
    return {
      active_node: { ...node },
      topics: [...topics],
      active_topic_id: activeTopicStillValid ? storedActiveTopicId : null,
    };
  }

  async listTopics(nodeId: number): Promise<Topic[]> {
    const state = loadLocalState();
    return state.topics.filter((t) => t.memory_node_id === nodeId && !t.is_archived);
  }

  async createTopic(
    nodeId: number,
    init: { title?: string | null; conversationId?: string | null } = {},
  ): Promise<Topic> {
    const state = loadLocalState();
    const topic: Topic = {
      id: state.nextTopicId++,
      memory_node_id: nodeId,
      conversation_id: init.conversationId ?? null,
      title: init.title ?? null,
      is_archived: false,
      created_at: nowIso(),
      last_used_at: nowIso(),
    };
    state.topics.push(topic);
    persistLocalState(state);
    return topic;
  }

  async setActiveTopic(nodeId: number, topicId: number | null): Promise<ScopeStateEnvelope> {
    const state = loadLocalState();
    const node = state.nodes.find((n) => n.id === nodeId);
    if (!node) {
      throw new Error(`Local memory: node ${nodeId} not found`);
    }
    if (topicId !== null) {
      const topic = state.topics.find((t) => t.id === topicId && t.memory_node_id === nodeId);
      if (topic === undefined) {
        throw new Error(`Local memory: topic ${topicId} does not belong to node ${nodeId}`);
      }
      topic.last_used_at = nowIso();
    }
    state.nodeActiveTopics[nodeId] = topicId;
    persistLocalState(state);

    const topics = state.topics.filter((t) => t.memory_node_id === nodeId && !t.is_archived);
    return {
      active_node: { ...node },
      topics: [...topics],
      active_topic_id: topicId,
    };
  }

  async compactScope(nodeId: number): Promise<CompactScopeResult> {
    // Local mode has no facts table — compaction is a no-op.  The
    // ``compacted: false`` result tells the UI to show the
    // "nothing to save" toast instead of "memory saved".
    return { nodeId, compacted: false, factId: null, version: null, messageCount: null };
  }

  async getMemoryMap(_projectId: number): Promise<MemoryMapData | null> {
    // Local mode has no graph — no edges, no badge data, no
    // stale-descendant tracking.  Returning ``null`` lets the
    // Memory Map view render an "upgrade to enable" stub instead of
    // a misleadingly empty graph.
    return null;
  }
}

// ---------------------------------------------------------------------------
// Adapter selection
// ---------------------------------------------------------------------------

const serverAdapter = new ServerAdvisorMemoryAdapter();
const localAdapter = new LocalAdvisorMemoryAdapter();

/**
 * Pick the right adapter for the current app mode.  ``isServerBacked``
 * is a boolean that the caller derives from ``useAppConfig().appMode``;
 * keeping the selector pure makes this module trivial to unit-test.
 */
export function getAdvisorMemoryAdapter(isServerBacked: boolean): AdvisorMemoryAdapter {
  return isServerBacked ? serverAdapter : localAdapter;
}
