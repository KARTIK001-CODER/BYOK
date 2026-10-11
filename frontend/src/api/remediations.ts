import { ApiClient } from "./client";
import {
  RemediationApproval,
  RemediationApprovalListResponse,
  RemediationAuditEventListResponse,
  RemediationDryRunResponse,
  RemediationProposal,
  RemediationProposalListResponse,
  RemediationStatus,
  RiskAssessmentDetails,
} from "../types/remediation";

export interface ListRemediationsFilter {
  incident_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export const RemediationsApi = {
  /**
   * List all remediation proposals for the caller's organization with optional filters.
   */
  async listAll(
    filters?: ListRemediationsFilter,
    orgId?: string
  ): Promise<RemediationProposalListResponse> {
    const params = new URLSearchParams();
    if (orgId) params.set("organization_id", orgId);
    if (filters?.incident_id) params.set("incident_id", filters.incident_id);
    if (filters?.status) params.set("status", filters.status);
    if (filters?.limit) params.set("limit", filters.limit.toString());
    if (filters?.offset) params.set("offset", filters.offset.toString());

    const qs = params.toString() ? `?${params.toString()}` : "";
    return ApiClient.request<RemediationProposalListResponse>(`/remediations${qs}`);
  },

  /**
   * List remediation proposals for a specific incident.
   */
  async listForIncident(
    incidentId: string,
    status?: string,
    orgId?: string
  ): Promise<RemediationProposalListResponse> {
    const params = new URLSearchParams();
    if (orgId) params.set("organization_id", orgId);
    if (status) params.set("status", status);

    const qs = params.toString() ? `?${params.toString()}` : "";
    return ApiClient.request<RemediationProposalListResponse>(
      `/incidents/${incidentId}/remediations${qs}`
    );
  },

  /**
   * Retrieve a single remediation proposal by ID.
   */
  async get(remediationId: string): Promise<RemediationProposal> {
    return ApiClient.request<RemediationProposal>(`/remediations/${remediationId}`);
  },

  /**
   * Manually create a remediation proposal for an incident.
   */
  async create(
    incidentId: string,
    payload: Record<string, unknown>
  ): Promise<RemediationProposal> {
    return ApiClient.request<RemediationProposal>(`/incidents/${incidentId}/remediations`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * Generate a remediation proposal from an investigation hypothesis.
   */
  async generate(
    incidentId: string,
    payload: { hypothesis_id?: string; focus?: string }
  ): Promise<RemediationProposal> {
    return ApiClient.request<RemediationProposal>(
      `/incidents/${incidentId}/remediations/generate`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  },

  /**
   * Transition proposal lifecycle status.
   */
  async transitionStatus(
    remediationId: string,
    targetStatus: RemediationStatus,
    notes?: { review_notes?: string; rejection_reason?: string; superseded_by_id?: string }
  ): Promise<RemediationProposal> {
    return ApiClient.request<RemediationProposal>(`/remediations/${remediationId}/status`, {
      method: "PATCH",
      body: JSON.stringify({
        target_status: targetStatus,
        ...notes,
      }),
    });
  },

  /**
   * Recalculate deterministic risk assessment breakdown for a proposal.
   */
  async recalculateRisk(remediationId: string): Promise<RiskAssessmentDetails> {
    return ApiClient.request<RiskAssessmentDetails>(
      `/remediations/${remediationId}/risk-assessment`,
      {
        method: "POST",
      }
    );
  },

  /**
   * Approve a remediation proposal with mandatory rationale.
   */
  async approve(remediationId: string, rationale: string): Promise<RemediationApproval> {
    return ApiClient.request<RemediationApproval>(`/remediations/${remediationId}/approve`, {
      method: "POST",
      body: JSON.stringify({ rationale }),
    });
  },

  /**
   * Reject a remediation proposal with mandatory rationale.
   */
  async reject(remediationId: string, rationale: string): Promise<RemediationApproval> {
    return ApiClient.request<RemediationApproval>(`/remediations/${remediationId}/reject`, {
      method: "POST",
      body: JSON.stringify({ rationale }),
    });
  },

  /**
   * List durable approval and rejection decision records.
   */
  async listApprovals(remediationId: string): Promise<RemediationApprovalListResponse> {
    return ApiClient.request<RemediationApprovalListResponse>(
      `/remediations/${remediationId}/approvals`
    );
  },

  /**
   * List append-only audit events for this remediation proposal.
   */
  async listAuditEvents(remediationId: string): Promise<RemediationAuditEventListResponse> {
    return ApiClient.request<RemediationAuditEventListResponse>(
      `/remediations/${remediationId}/audit`
    );
  },

  /**
   * Run local deterministic policy-validation dry run.
   * Explicitly local: no infrastructure commands or APIs executed.
   */
  async dryRunPolicy(remediationId: string): Promise<RemediationDryRunResponse> {
    return ApiClient.request<RemediationDryRunResponse>(
      `/remediations/${remediationId}/dry-run`,
      {
        method: "POST",
      }
    );
  },
};

// Also export standalone functions for backward compatibility with existing imports
export const getRemediationProposal = RemediationsApi.get;
export const listRemediationProposals = RemediationsApi.listForIncident;
export const createRemediationProposal = RemediationsApi.create;
export const generateRemediationProposal = RemediationsApi.generate;
export const transitionRemediationStatus = RemediationsApi.transitionStatus;
export const reevaluateRiskAssessment = RemediationsApi.recalculateRisk;
export const approveRemediationProposal = RemediationsApi.approve;
export const rejectRemediationProposal = RemediationsApi.reject;
export const listRemediationApprovals = RemediationsApi.listApprovals;
export const listRemediationAuditEvents = RemediationsApi.listAuditEvents;
export const dryRunRemediationPolicy = RemediationsApi.dryRunPolicy;
export const listOrganizationRemediations = RemediationsApi.listAll;
