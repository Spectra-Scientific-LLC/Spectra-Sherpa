import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { useAppConfig } from "@/composables/useAppConfig";
import {
  getAdvisorMemoryAdapter,
  type CompactScopeResult,
  type MemoryNode,
  type ScopeArgs,
  type ScopeStateEnvelope,
  type Topic,
} from "@/lib/advisorMemoryAdapter";
import { useProjectStore } from "@/stores/project";
import { useSherpaStore } from "@/stores/sherpa";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import type { AdvisorChannel } from "@/types";
import { getErrorMessage } from "@/utils/errors";

export const useAdvisorStore = defineStore("advisor", () => {
  const { appMode } = useAppConfig();
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

  const activeNodeId = computed(() => activeNode.value?.id ?? null);
  const activeChannel = computed(
    () => channels.value.find((channel) => channel.id === activeChannelId.value) ?? null
  );
  const projectChannel = computed(
    () => channels.value.find((channel) => channel.channel_type === "project" && channel.workflow_id == null) ?? null
  );

  function resetProjectScope(): void {
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

    isLoading.value = true;
    error.value = null;
    try {
      const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
      const envelope = await adapter.switchScope(args);
      _applyScopeEnvelope(envelope);
      projectId.value = args.projectId;

      const sherpaStore = useSherpaStore();
      const activeTopic = envelope.topics.find((t) => t.id === envelope.active_topic_id) ?? null;
      if (activeTopic?.conversation_id) {
        try {
          await sherpaStore.loadConversation(activeTopic.conversation_id);
        } catch (err) {
          console.warn("[advisor] Could not load topic conversation; starting fresh", err);
          sherpaStore.startNewConversation();
        }
      } else {
        sherpaStore.startNewConversation();
      }
      return envelope.active_node;
    } catch (err) {
      error.value = getErrorMessage(err);
      return null;
    } finally {
      isLoading.value = false;
    }
  }

  async function createTopic(
    init: { title?: string | null; conversationId?: string | null } = {},
  ): Promise<Topic | null> {
    if (activeNode.value === null) return null;
    try {
      const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
      const topic = await adapter.createTopic(activeNode.value.id, init);
      topics.value = [topic, ...topics.value];
      return topic;
    } catch (err) {
      error.value = getErrorMessage(err);
      return null;
    }
  }

  async function setActiveTopic(topicId: number | null): Promise<void> {
    if (activeNode.value === null) return;
    try {
      const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
      const envelope = await adapter.setActiveTopic(activeNode.value.id, topicId);
      _applyScopeEnvelope(envelope);
    } catch (err) {
      error.value = getErrorMessage(err);
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
    try {
      const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
      return await adapter.compactScope(activeNode.value.id);
    } catch (err) {
      error.value = getErrorMessage(err);
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
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.get<AdvisorChannel[]>(
        `/projects/${targetProjectId}/advisor-channels`
      );
      projectId.value = targetProjectId;
      channels.value = data;
      return data;
    } catch (err) {
      error.value = getErrorMessage(err);
      return [];
    } finally {
      isLoading.value = false;
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

    error.value = null;
    try {
      const { data } = await api.post<AdvisorChannel>(`/workflows/${workflowId}/advisor-channel`);
      upsertChannel(data);
      projectId.value = targetProjectId ?? data.project_id;
      return data;
    } catch (err) {
      error.value = getErrorMessage(err);
      return null;
    }
  }

  async function updateChannel(
    channelId: number,
    payload: Partial<Pick<AdvisorChannel, "title" | "color" | "conversation_id">>,
  ): Promise<AdvisorChannel | null> {
    const targetProjectId = projectId.value;
    if (targetProjectId === null) return null;

    try {
      const { data } = await api.put<AdvisorChannel>(
        `/projects/${targetProjectId}/advisor-channels/${channelId}`,
        payload,
      );
      upsertChannel(data);
      return data;
    } catch (err) {
      error.value = getErrorMessage(err);
      return null;
    }
  }

  async function switchToChannel(channel: AdvisorChannel | null): Promise<void> {
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
        console.warn("[advisor] Unable to load channel conversation; starting a fresh thread", err);
      }
    }

    sherpaStore.startNewConversation();
  }

  async function switchToWorkflowChannel(
    workflowId: number,
    advisorChannelId?: number | null,
    targetProjectId = projectId.value,
  ): Promise<void> {
    if (targetProjectId !== null && projectId.value !== targetProjectId) {
      await loadAdvisorChannels(targetProjectId);
    }

    const channel =
      (advisorChannelId
        ? channels.value.find((item) => item.id === advisorChannelId)
        : null)
      ?? await ensureWorkflowChannel(workflowId, targetProjectId);
    await switchToChannel(channel);
  }

  async function switchToProjectChannel(targetProjectId = projectId.value): Promise<void> {
    if (targetProjectId !== null && projectId.value !== targetProjectId) {
      await loadAdvisorChannels(targetProjectId);
    }
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
