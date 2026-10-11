export type InvestigationStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type InvestigationStage =
  | "queued"
  | "claiming"
  | "retrieving_evidence"
  | "generating_hypotheses"
  | "validating_citations"
  | "evaluating_groundedness"
  | "persisting_results"
  | "persisting"
  | "completed"
  | "failed"
  | "cancelled";

export type HypothesisStatus = "supported" | "contested" | "rejected";
export type HypothesisConfidence = "low" | "medium" | "high";
export type SystemConfidenceLevel = "low" | "medium" | "high" | "unknown";
export type GroundednessStatus =
  | "well_supported"
  | "partially_supported"
  | "weakly_supported"
  | "unsupported"
  | "contested"
  | "rejected"
  | "evaluation_failed";

export interface EvidenceLinkResponse {
  id: string;
  hypothesis_id: string;
  evidence_event_id: string;
  link_type: "supports" | "contradicts";
  excerpt?: string | null;
}

export interface GroundednessAssessmentDetails {
  version?: string;
  groundedness_score?: number;
  system_confidence_score?: number;
  system_confidence?: SystemConfidenceLevel;
  groundedness_status?: GroundednessStatus;
  support_score?: number;
  contradiction_score?: number;
  citation_score?: number;
  temporal_score?: number;
  coverage_score?: number;
  diversity_score?: number;
  retrieval_score?: number;
  unsupported_claim_score?: number;
  assessment_reasons?: string[];
  calibration_status?: string;
  [key: string]: unknown;
}

export interface HypothesisResponse {
  id: string;
  investigation_job_id: string;
  incident_id: string;
  organization_id: string;
  claim: string;
  rationale: string;
  confidence: HypothesisConfidence;
  confidence_score?: number | null;
  confidence_note: string;
  status: HypothesisStatus;
  rejection_reason?: string | null;
  provider?: string | null;
  model?: string | null;
  created_at: string;
  supporting_evidence: EvidenceLinkResponse[];
  contradicting_evidence: EvidenceLinkResponse[];

  // Milestone 4: Groundedness & System-derived confidence
  model_confidence?: HypothesisConfidence | null;
  model_confidence_score?: number | null;
  groundedness_score?: number | null;
  system_confidence?: SystemConfidenceLevel | string | null;
  system_confidence_score?: number | null;
  groundedness_status?: GroundednessStatus | string | null;
  assessment_version?: string | null;
  assessment_details?: GroundednessAssessmentDetails | null;
}

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
