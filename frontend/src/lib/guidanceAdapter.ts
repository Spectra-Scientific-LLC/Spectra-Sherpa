import api from "@/api/client";

export interface GuidanceSettings {
  guidance_enabled: boolean;
  toast_enabled: boolean;
  glow_enabled: boolean;
  first_guidance_seen_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface GuidanceNotification {
  id: number;
  project_id: number | null;
  advisor_node_id: number | null;
  rule_id: string;
  kind: string;
  title: string;
  body?: string | null;
  action_id?: string | null;
  action_version?: number | null;
  confidence: number;
  source: string;
  created_at: string;
  expires_at: string;
  shown_at?: string | null;
  dismissed_at?: string | null;
  clicked_at?: string | null;
}

export type GuidanceAckKind = "shown" | "clicked" | "dismissed" | "dont_show_again";

export interface GuidanceSettingsPatch {
  guidance_enabled?: boolean;
  toast_enabled?: boolean;
  glow_enabled?: boolean;
}

export async function fetchGuidanceSettings(): Promise<GuidanceSettings> {
  const { data } = await api.get<GuidanceSettings>("/guidance/settings");
  return data;
}

export async function patchGuidanceSettings(
  patch: GuidanceSettingsPatch
): Promise<GuidanceSettings> {
  const { data } = await api.patch<GuidanceSettings>("/guidance/settings", patch);
  return data;
}

export async function listGuidanceNotifications(options?: {
  includeDismissed?: boolean;
  limit?: number;
}): Promise<GuidanceNotification[]> {
  const { data } = await api.get<GuidanceNotification[]>("/guidance/notifications", {
    params: {
      include_dismissed: options?.includeDismissed ?? false,
      limit: options?.limit ?? 50,
    },
  });
  return data;
}

export async function acknowledgeGuidanceNotification(
  notificationId: number,
  ackKind: GuidanceAckKind
): Promise<GuidanceNotification> {
  const { data } = await api.patch<GuidanceNotification>(
    `/guidance/notifications/${notificationId}`,
    { ack_kind: ackKind }
  );
  return data;
}
