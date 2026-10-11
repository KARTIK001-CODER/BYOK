export type IncidentSeverity = "info" | "low" | "medium" | "high" | "critical";
export type IncidentStatus = "open" | "investigating" | "mitigated" | "resolved" | "closed";

export interface IncidentCreatePayload {
  title: string;
  description?: string | null;
  severity?: IncidentSeverity;
  status?: IncidentStatus;
  service_name?: string | null;
  environment?: string;
  organization_id?: string | null;
  incident_metadata?: Record<string, unknown> | null;
}

export interface Incident {
  id: string;
  organization_id: string;
  title: string;
  description?: string | null;
  severity: IncidentSeverity;
  status: IncidentStatus;
  service_name?: string | null;
  environment: string;
  created_by_user_id?: string | null;
  resolved_at?: string | null;
  incident_metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  evidence_count?: number;
}

export type EvidenceSourceType =
  | "alert"
  | "log"
  | "metric"
  | "deployment"
  | "git"
  | "trace"
  | "manual";

export interface EvidenceEventCreatePayload {
  source_type: EvidenceSourceType;
  event_type: string;
  event_timestamp: string;
  summary: string;
  normalized_payload?: Record<string, unknown>;
  source_reference?: string | null;
  deduplication_key?: string | null;
}

export type BatchItemStatus = "accepted" | "duplicate" | "rejected" | "failed";

export interface BatchEvidenceItemResult {
  index: number;
  status: BatchItemStatus;
  evidence_id?: string | null;
  deduplication_key?: string | null;
  event_type?: string | null;
  summary?: string | null;
  error_message?: string | null;
}

export interface EvidenceBatchResponse {
  incident_id: string;
  total_submitted: number;
  accepted_count: number;
  duplicate_count: number;
  rejected_count: number;
  failed_count: number;
  results: BatchEvidenceItemResult[];
}

export interface EvidenceEvent {
  id: string;
  incident_id: string;
  organization_id: string;
  source_type: EvidenceSourceType | string;
  event_type: string;
  event_timestamp: string;
  ingestion_timestamp?: string;
  summary: string;
  service_name?: string | null;
  normalized_payload?: Record<string, unknown>;
  source_reference?: string | null;
  deduplication_key?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface TimelineEvent {
  id: string;
  incident_id?: string;
  source_type: EvidenceSourceType | string;
  event_type: string;
  event_timestamp: string;
  summary: string;
  source_reference?: string | null;
  normalized_payload?: Record<string, unknown>;
  deduplication_key?: string | null;
  related_evidence_id?: string | null;
}

export interface TimelineResponse {
  incident_id: string;
  total_events: number;
  events: TimelineEvent[];
  limit: number;
  offset: number;
}
