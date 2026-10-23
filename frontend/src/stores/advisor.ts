import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { useAppConfig } from "@/composables/useAppConfig";
import { useScopedRequest } from "@/composables/useScopedRequest";
import {
  getAdvisorMemoryAdapter,
  type CompactScopeResult,
  type MemoryNode,
  type ScopeArgs,
  type ScopeStateEnvelope,
  type Topic,
} from "@/lib/advisorMemoryAdapter";
import { useProjectStore } from "@/stores/project";
import { useAuthStore } from "@/stores/auth";
import { useSherpaStore } from "@/stores/sherpa";
import { activeProjectScope, registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import type { AdvisorChannel } from "@/types";
import { getErrorMessage } from "@/utils/errors";

export const useAdvisorStore = defineStore("advisor", () => {
  const { appMode, siteProfile } = useAppConfig();
  const memoryUnavailable = computed(() => appMode.value === "enterprise" && siteProfile?.value === "pro");
  const isServerBacked = computed(() => appMode.value !== "local");

  // R1 canonical state — drives all future routing.  ``advisor_node_id``
  // is the only routing key the WS chat payload carries.
  const activeNode = ref<MemoryNode | null>(null);
  const topics = ref<Topic[]>([]);
  const activeTopicId = ref<number | null>(null);

  // Legacy state — still populated for any UI that has not been
  // migrated to the scope-based model.  Retired in R2.
  const projectId = ref<number | null>(null);
  const channels = ref<AdvisorChannel[]>([]);
  const activeChannelId = ref<number | null>(null);
  const isLoading = ref(false);
  const error = ref<string | null>(null);
  const auth = useAuthStore();
  const workspaceIdentity = () => [auth.user?.id, auth.sessionRevision, activeProjectScope.value];
  const scopeRequests = useScopedRequest(workspaceIdentity, () => { isLoading.value = false; });
  const channelRequests = useScopedRequest(workspaceIdentity, () => { isLoading.value = false; });
  const navigationRequests = useScopedRequest(workspaceIdentity);
  const topicWrites = useScopedRequest(
    () => [...workspaceIdentity(), activeNode.value?.id], undefined, { abortOnInvalidate: false },
  );
  const channelWrites = useScopedRequest(
    () => [...workspaceIdentity(), projectId.value], undefined, { abortOnInvalidate: false },
  );

  const activeNodeId = computed(() => activeNode.value?.id ?? null);
  const activeChannel = computed(
    () => channels.value.find((channel) => channel.id === activeChannelId.value) ?? null
  );
  const projectChannel = computed(
    () => channels.value.find((channel) => channel.channel_type === "project" && channel.workflow_id == null) ?? null
  );

  function resetProjectScope(): void {
    scopeRequests.invalidate();
    channelRequests.invalidate();
    navigationRequests.invalidate();
    topicWrites.invalidate();
    channelWrites.invalidate();
    activeNode.value = null;
    topics.value = [];
    activeTopicId.value = null;
    projectId.value = null;
    channels.value = [];
    activeChannelId.value = null;
    isLoading.value = false;
    error.value = null;
  }
  registerProjectScopeReset(resetProjectScope);

  function _applyScopeEnvelope(envelope: ScopeStateEnvelope): void {
    activeNode.value = envelope.active_node;
    topics.value = envelope.topics;
    activeTopicId.value = envelope.active_topic_id;
  }

  /**
   * Canonical entry point for tab/subtab/sheet navigation.  Sends the
   * scope triple to the server, applies the returned state envelope,
   * and tells the sherpa store to load the bound conversation.
   *
   * Frontend's only job: detect the route, send it, render what comes
   * back.  All graph traversal is server-side.
   */
  async function switchScope(args: ScopeArgs): Promise<MemoryNode | null> {
    if (memoryUnavailable.value) {
      // Pro chat uses its retained, project-authorized conversation directly.
      // Memory scopes have separate custody and are not an admitted capability.
      resetProjectScope();
      return null;
    }
    // Pre-check: the requested scope must belong to the project the user
    // currently has loaded. The backend still authoritatively rejects
    // cross-project scopes (the memory adapter is project-scoped on the
    // server) — this fail-fast guard turns what would be a noisy 403 into
    // a clean local refusal and prevents the advisor UI from briefly
    // showing a foreign project's channel while the request is in flight.
    const activeProjectId = useProjectStore().currentProjectId;
    if (activeProjectId !== null && args.projectId !== activeProjectId) {
      console.warn(
        "[advisor] switchScope refused: requested projectId=%s but active is %s",
        args.projectId,
        activeProjectId,
      );
      return null;
    }

    if (activeNode.value?.project_id === args.projectId && activeNode.value.tab_key === args.tabKey
      && activeNode.value.subscope_key === args.subscopeKey) return activeNode.value;
    const request = scopeRequests.begin();
    activeNode.value = null;
    topics.value = [];
    activeTopicId.value = null;
    useSherpaStore().startNewConversation();
    isLoading.value = true;
    error.value = null;
    try {
      const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
      const envelope = await adapter.switchScope(args);
      if (!request.isCurrent()) return null;
      _applyScopeEnvelope(envelope);
      projectId.value = args.projectId;

      const sherpaStore = useSherpaStore();
      const activeTopic = envelope.topics.find((t) => t.id === envelope.active_topic_id) ?? null;
      if (activeTopic?.conversation_id) {
        try {
          await sherpaStore.loadConversation(activeTopic.conversation_id);
        } catch (err) {
          if (!request.isCurrent()) return null;
          console.warn("[advisor] Could not load topic conversation; starting fresh", err);
          sherpaStore.startNewConversation();
        }
      } else {
        sherpaStore.startNewConversation();
      }
      return request.isCurrent() ? envelope.active_node : null;
    } catch (err) {
      if (!request.isCurrent()) return null;
      error.value = getErrorMessage(err);
      return null;
    } finally {
      if (request.isCurrent()) isLoading.value = false;
    }
  }

  async function createTopic(
    init: { title?: string | null; conversationId?: string | null } = {},
  ): Promise<Topic | null> {
    if (activeNode.value === null) return null;
    const request = topicWrites.capture();
    try {
      const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
      const topic = await adapter.createTopic(activeNode.value.id, init);
      if (!request.isCurrent()) return null;
      topics.value = [topic, ...topics.value];
      return topic;
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
      return null;
    }
  }

  async function setActiveTopic(topicId: number | null): Promise<void> {
    if (activeNode.value === null) return;
    const request = topicWrites.begin();
    try {
      const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
      const envelope = await adapter.setActiveTopic(activeNode.value.id, topicId);
      if (!request.isCurrent()) return;
      _applyScopeEnvelope(envelope);
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
    }
  }

  /**
   * R2 — compact the active scope's conversation into a summary fact.
   * Returns ``null`` when there is no active node.  In server-backed
   * modes this hits ``POST /memory/nodes/{id}/compact``; in local mode
   * the adapter no-ops with ``{compacted: false}`` so the UI can show
   * a clean "nothing to save yet" toast.
   */
  async function compactScope(): Promise<CompactScopeResult | null> {
    if (activeNode.value === null) return null;
    const request = topicWrites.capture();
    try {
      const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
      const result = await adapter.compactScope(activeNode.value.id);
      return request.isCurrent() ? result : null;
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
      return null;
    }
  }

  function upsertChannel(channel: AdvisorChannel): void {
    const index = channels.value.findIndex((item) => item.id === channel.id);
    if (index >= 0) {
      channels.value[index] = channel;
    } else {
      channels.value.push(channel);
    }
  }

  async function loadAdvisorChannels(targetProjectId: number): Promise<AdvisorChannel[]> {
    const request = channelRequests.begin();
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.get<AdvisorChannel[]>(
        `/projects/${targetProjectId}/advisor-channels`, { signal: request.signal },
      );
      if (!request.isCurrent()) return [];
      projectId.value = targetProjectId;
      channels.value = data;
      return data;
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
      return [];
    } finally {
      if (request.isCurrent()) isLoading.value = false;
    }
  }

  async function ensureWorkflowChannel(
    workflowId: number,
    targetProjectId = projectId.value,
  ): Promise<AdvisorChannel | null> {
    const channel =
      channels.value.find((item) => item.workflow_id === workflowId && item.channel_type === "sheet")
      ?? null;
    if (channel) {
      return channel;
    }

    const request = channelWrites.capture();
    error.value = null;
    try {
      const { data } = await api.post<AdvisorChannel>(`/workflows/${workflowId}/advisor-channel`);
      if (!request.isCurrent()) return null;
      upsertChannel(data);
      projectId.value = targetProjectId ?? data.project_id;
      return data;
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
      return null;
    }
  }

  async function updateChannel(
    channelId: number,
    payload: Partial<Pick<AdvisorChannel, "title" | "color" | "conversation_id">>,
  ): Promise<AdvisorChannel | null> {
    const targetProjectId = projectId.value;
    if (targetProjectId === null) return null;
    const request = channelWrites.capture();

    try {
      const { data } = await api.put<AdvisorChannel>(
        `/projects/${targetProjectId}/advisor-channels/${channelId}`,
        payload,
      );
      if (!request.isCurrent()) return null;
      upsertChannel(data);
      return data;
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
      return null;
    }
  }

  async function switchToChannel(channel: AdvisorChannel | null): Promise<void> {
    const request = navigationRequests.begin();
    const sherpaStore = useSherpaStore();
    activeChannelId.value = channel?.id ?? null;

    if (!channel) {
      sherpaStore.startNewConversation();
      return;
    }

    if (channel.conversation_id) {
      try {
        await sherpaStore.loadConversation(channel.conversation_id);
        return;
      } catch (err) {
        if (!request.isCurrent()) return;
        console.warn("[advisor] Unable to load channel conversation; starting a fresh thread", err);
      }
    }

    if (request.isCurrent()) sherpaStore.startNewConversation();
  }

  async function switchToWorkflowChannel(
    workflowId: number,
    advisorChannelId?: number | null,
    targetProjectId = projectId.value,
  ): Promise<void> {
    const request = navigationRequests.begin();
    if (targetProjectId !== null && projectId.value !== targetProjectId) {
      await loadAdvisorChannels(targetProjectId);
    }
    if (!request.isCurrent()) return;

    const channel =
      (advisorChannelId
        ? channels.value.find((item) => item.id === advisorChannelId)
        : null)
      ?? await ensureWorkflowChannel(workflowId, targetProjectId);
    if (!request.isCurrent()) return;
    await switchToChannel(channel);
  }

  async function switchToProjectChannel(targetProjectId = projectId.value): Promise<void> {
    const request = navigationRequests.begin();
    if (targetProjectId !== null && projectId.value !== targetProjectId) {
      await loadAdvisorChannels(targetProjectId);
    }
    if (!request.isCurrent()) return;
    await switchToChannel(projectChannel.value);
  }

  function setFromProjectDetail(targetProjectId: number, items: AdvisorChannel[] = []): void {
    projectId.value = targetProjectId;
    channels.value = [...items];
  }

  return {
    // R1 canonical scope-based state
    activeNode,
    activeNodeId,
    topics,
    activeTopicId,
    switchScope,
    createTopic,
    setActiveTopic,
    compactScope,

    // Legacy channel-based state (kept for parallel operation in R1)
    projectId,
    channels,
    activeChannelId,
    activeChannel,
    projectChannel,
    isLoading,
    error,
    loadAdvisorChannels,
    ensureWorkflowChannel,
    updateChannel,
    switchToChannel,
    switchToWorkflowChannel,
    switchToProjectChannel,
    setFromProjectDetail,
    resetProjectScope,
  };
});
