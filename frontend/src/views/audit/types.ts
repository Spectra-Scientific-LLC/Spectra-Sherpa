export type ExportFormat = "csv" | "jsonl";

export interface AuditEventRecord {
  id: number;
  tenant_id: string;
  actor_id: number | null;
  actor_kind: string;
  action: string;
  target_type: string;
  target_id: string;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  context: Record<string, unknown> | null;
  request_id: string;
  ts_app_utc: string;
  ts_db_utc: string;
}

export interface AuditEventResponse {
  events: AuditEventRecord[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface ChainStatus {
  ok: boolean;
  rows_checked: number;
  unchained_event_count: number;
  orphan_chain_row_count: number;
}

export interface LastPack {
  packId: string;
  rowCount: number;
  fileCount: number;
  sha256: string;
  verificationOk: boolean;
}

export interface AuditFilterForm {
  scopeType: string;
  scopeId: string;
  action: string;
  targetType: string;
  targetId: string;
  requestId: string;
  since: string;
  until: string;
  format: ExportFormat;
  includePdf: boolean;
}

export interface AuditCapabilities {
  localQuery?: boolean;
  fullPipeline?: boolean;
  reportPack?: boolean;
  exportAudited?: boolean;
}
