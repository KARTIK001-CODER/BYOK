export type InvestigationStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type InvestigationStage =
  | "queued"
  | "claiming"
  | "retrieving_evidence"
  | "generating_hypotheses"
  | "validating_citations"
  | "persisting_results"
  | "completed"
  | "failed"
  | "cancelled";

export interface InvestigationJob {
  id: string;
  incident_id: string;
  organization_id: string;
  status: InvestigationStatus;
  stage: InvestigationStage | string;
  progress: number;
  error_category?: string | null;
  error_summary?: string | null;
  result_summary?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export type InvestigationEventType =
  | "investigation.connected"
  | "investigation.snapshot"
  | "investigation.progress"
  | "investigation.completed"
  | "investigation.failed"
  | "investigation.cancelled";

export interface InvestigationStreamEventPayload {
  job_id: string;
  incident_id: string;
  status: InvestigationStatus;
  stage: InvestigationStage | string;
  progress: number;
  result_summary?: Record<string, unknown> | null;
  error_summary?: string | null;
  error_category?: string | null;
  updated_at?: string | null;
  timestamp: string;
}

export interface UseInvestigationStreamOptions {
  autoConnect?: boolean;
  maxReconnectAttempts?: number;
  reconnectBaseDelayMs?: number;
  pollingFallbackIntervalMs?: number;
  onEvent?: (eventType: InvestigationEventType, data: InvestigationStreamEventPayload) => void;
  onTerminal?: (data: InvestigationStreamEventPayload) => void;
  onError?: (error: Error) => void;
}

export interface UseInvestigationStreamResult {
  jobId: string | null;
  status: InvestigationStatus | null;
  stage: string | null;
  progress: number;
  resultSummary: Record<string, unknown> | null;
  errorSummary: string | null;
  errorCategory: string | null;
  connected: boolean;
  isTerminal: boolean;
  isPollingFallback: boolean;
  reconnectAttempts: number;
  error: string | null;
  refresh: () => Promise<InvestigationJob | null>;
  cancel: () => Promise<void>;
}
