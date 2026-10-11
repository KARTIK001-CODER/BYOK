export type RemediationStatus =
  | "draft"
  | "proposed"
  | "reviewed"
  | "approved"
  | "rejected"
  | "superseded"
  | "cancelled"
  | "expired";

export type RemediationRiskLevel = "low" | "medium" | "high" | "critical";

export type RemediationActionType =
  | "config_change"
  | "service_restart"
  | "rollback"
  | "scale"
  | "dependency_update"
  | "firewall_rule"
  | "manual";

export type ApprovalDecision = "approved" | "rejected";

export interface RemediationActionItem {
  step_number: number;
  action_type: RemediationActionType;
  description: string;
  target_system: string;
  command?: string | null;
  parameters?: Record<string, unknown>;
  risk_level: RemediationRiskLevel;
  reversible: boolean;
  requires_human_approval: boolean;
  is_executable: boolean;
}

export interface RiskAssessmentDetails {
  overall_risk_level: RemediationRiskLevel;
  risk_score: number;
  risk_factors: string[];
  blast_radius: string;
  reversibility_assessment: string;
  groundedness_alignment?: string | null;
  requires_human_approval: boolean;
  execution_restricted: boolean;
  restrictions_note: string;
}

export interface RemediationProposal {
  id: string;
  incident_id: string;
  organization_id: string;
  hypothesis_id?: string | null;
  investigation_job_id?: string | null;
  title: string;
  description: string;
  status: RemediationStatus;
  risk_level: RemediationRiskLevel;
  risk_assessment?: RiskAssessmentDetails | null;
  actions: RemediationActionItem[];
  is_executable: boolean;
  rollback_plan?: string | null;
  estimated_impact?: string | null;
  mitigation_rationale?: string | null;
  review_notes?: string | null;
  rejection_reason?: string | null;
  superseded_by_id?: string | null;
  created_by_user_id?: string | null;
  version: number;
  approved_by_user_id?: string | null;
  approved_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface RemediationProposalListResponse {
  items: RemediationProposal[];
  total: number;
}

export interface RemediationApproval {
  id: string;
  organization_id: string;
  remediation_proposal_id: string;
  proposal_version: number;
  reviewer_user_id: string;
  decision: ApprovalDecision;
  rationale: string;
  risk_level_at_decision: RemediationRiskLevel;
  policy_version: string;
  request_id?: string | null;
  snapshot: Record<string, unknown>;
  created_at: string;
}

export interface RemediationApprovalListResponse {
  items: RemediationApproval[];
  total: number;
}

export interface RemediationAuditEvent {
  id: string;
  organization_id: string;
  remediation_proposal_id: string;
  event_type: string;
  actor_user_id?: string | null;
  actor_role?: string | null;
  proposal_version: number;
  from_status?: string | null;
  to_status?: string | null;
  details?: Record<string, unknown> | null;
  request_id?: string | null;
  created_at: string;
}

export interface RemediationAuditEventListResponse {
  items: RemediationAuditEvent[];
  total: number;
}

export interface RemediationDryRunResponse {
  dry_run_type: string;
  allowed: boolean;
  risk_level: string;
  required_roles: string[];
  separation_of_duties_passed: boolean;
  risk_assessment_valid: boolean;
  lifecycle_eligible: boolean;
  violations: string[];
  policy_version: string;
  disclaimer: string;
}
