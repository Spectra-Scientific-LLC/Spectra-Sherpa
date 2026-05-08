import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { useSherpaStore } from "@/stores/sherpa";
import type { AdvisorChannel } from "@/types";
import { getErrorMessage } from "@/utils/errors";

export const useAdvisorStore = defineStore("advisor", () => {
  const projectId = ref<number | null>(null);
  const channels = ref<AdvisorChannel[]>([]);
  const activeChannelId = ref<number | null>(null);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  const activeChannel = computed(
    () => channels.value.find((channel) => channel.id === activeChannelId.value) ?? null
  );
  const projectChannel = computed(
    () => channels.value.find((channel) => channel.channel_type === "project" && channel.workflow_id == null) ?? null
  );

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
  };
});
