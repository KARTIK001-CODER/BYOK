import React, { useState, useEffect } from "react";
import {
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  History,
  FileCheck2,
  AlertOctagon,
  Calendar,
  Layers,
  RotateCw,
  Terminal,
  FileText,
} from "lucide-react";
import {
  RemediationApproval,
  RemediationAuditEvent,
  RemediationProposal,
} from "../../types/remediation";
import { EvidenceEvent, Incident } from "../../types/incident";
import { HypothesisResponse } from "../../types/investigation";
import { User } from "../../types";
import { RemediationsApi } from "../../api/remediations";
import { RiskAssessmentView } from "./RiskAssessmentView";
import { ActionStepsList } from "./ActionStepsList";
import { EvidenceProvenanceView } from "./EvidenceProvenanceView";
import { PolicyExplanationCard } from "./PolicyExplanationCard";
import { ApprovalWorkflowModal } from "./ApprovalWorkflowModal";
import { AuditTrailTimeline } from "./AuditTrailTimeline";
import { DryRunModal } from "./DryRunModal";

interface ProposalDetailViewProps {
  proposal: RemediationProposal;
  incident?: Incident | null;
  hypothesis?: HypothesisResponse | null;
  evidenceEvents?: EvidenceEvent[];
  currentUser: User | null;
  currentUserRole?: string | null;
  onProposalUpdated: (updated: RemediationProposal) => void;
  onSelectIncident?: (incidentId: string) => void;
}

export const ProposalDetailView: React.FC<ProposalDetailViewProps> = ({
  proposal,
  incident,
  hypothesis,
  evidenceEvents = [],
  currentUser,
  currentUserRole,
  onProposalUpdated,
  onSelectIncident,
}) => {
  const [activeTab, setActiveTab] = useState<"overview" | "actions" | "evidence" | "audit">("overview");
  const [showApprovalModal, setShowApprovalModal] = useState<boolean>(false);
  const [modalDecision, setModalDecision] = useState<"approve" | "reject">("approve");
  const [showDryRunModal, setShowDryRunModal] = useState<boolean>(false);

  // Audit history state
  const [auditEvents, setAuditEvents] = useState<RemediationAuditEvent[]>([]);
  const [approvals, setApprovals] = useState<RemediationApproval[]>([]);
  const [auditLoading, setAuditLoading] = useState<boolean>(false);
  const [auditError, setAuditError] = useState<string | null>(null);

  const fetchAuditData = async () => {
    setAuditLoading(true);
    setAuditError(null);
    try {
      const [eventsResp, approvalsResp] = await Promise.all([
        RemediationsApi.listAuditEvents(proposal.id),
        RemediationsApi.listApprovals(proposal.id),
      ]);
      setAuditEvents(eventsResp.items || []);
      setApprovals(approvalsResp.items || []);
    } catch (err: unknown) {
      const errorObj = err as { message?: string };
      setAuditError(errorObj?.message || "Failed to load audit history.");
    } finally {
      setAuditLoading(false);
    }
  };

  useEffect(() => {
    fetchAuditData();
  }, [proposal.id, proposal.version]);

  const reloadProposal = async () => {
    try {
      const latest = await RemediationsApi.get(proposal.id);
      onProposalUpdated(latest);
      await fetchAuditData();
    } catch (err) {
      console.error("Failed to reload proposal state:", err);
    }
  };

  const isTerminal = ["rejected", "superseded", "cancelled", "expired"].includes(proposal.status);
  const isApproved = proposal.status === "approved";
  const isCreator = !!(currentUser && proposal.created_by_user_id && currentUser.id === proposal.created_by_user_id);

  const roleUpper = (currentUserRole || "MEMBER").toUpperCase();
  const isHighOrCritical = proposal.risk_level === "high" || proposal.risk_level === "critical";
  const hasRequiredRole = isHighOrCritical
    ? roleUpper === "ADMIN" || roleUpper === "OWNER"
    : ["MEMBER", "ADMIN", "OWNER"].includes(roleUpper);

  const canApprove = !isTerminal && !isApproved && !isCreator && hasRequiredRole;
  const canReject = !isTerminal && !isApproved;

  const handleOpenDecision = (decision: "approve" | "reject") => {
    setModalDecision(decision);
    setShowApprovalModal(true);
  };

  const getStatusBadgeClass = (status: string) => {
    switch (status) {
      case "approved":
        return "badge-status-approved";
      case "rejected":
        return "badge-status-rejected";
      case "reviewed":
        return "badge-status-reviewed";
      case "proposed":
        return "badge-status-proposed";
      default:
        return "badge-status-draft";
    }
  };

  return (
    <div className="remediation-detail-panel" data-testid="proposal-detail-view">
      {/* Top Header */}
      <div className="remediation-detail-header">
        <div className="remediation-detail-topbar">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
              <span className={`badge ${getStatusBadgeClass(proposal.status)}`} data-testid="proposal-status-badge">
                {proposal.status.toUpperCase()}
              </span>
              <span className="badge badge-version" data-testid="proposal-version-badge">
                v{proposal.version}
              </span>
              {incident && (
                <button
                  type="button"
                  onClick={() => onSelectIncident?.(incident.id)}
                  className="badge badge-version"
                  style={{ cursor: "pointer", background: "none" }}
                  title="Incident reference"
                >
                  <Layers size={11} /> Incident: {incident.title}
                </button>
              )}
            </div>

            <h1 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }} data-testid="proposal-title">
              {proposal.title}
            </h1>
          </div>

          {/* Action Buttons */}
          <div className="remediation-actions-bar">
            <button
              type="button"
              onClick={() => setShowDryRunModal(true)}
              className="btn-secondary"
              title="Execute local policy dry-run simulation"
              data-testid="validate-proposal-dry-run-button"
            >
              <FileCheck2 size={14} /> Validate Proposal (Dry-Run)
            </button>

            <button
              type="button"
              onClick={() => handleOpenDecision("reject")}
              className="btn-danger"
              disabled={!canReject}
              title={
                isTerminal
                  ? "Proposal is in terminal state"
                  : isApproved
                  ? "Proposal is already approved"
                  : "Submit rejection with mandatory rationale"
              }
              data-testid="open-reject-button"
            >
              <XCircle size={14} /> Reject
            </button>

            <button
              type="button"
              onClick={() => handleOpenDecision("approve")}
              className="btn-success"
              disabled={!canApprove}
              title={
                isCreator
                  ? "Creator cannot approve own proposal"
                  : !hasRequiredRole
                  ? "Insufficient role privilege (requires ADMIN/OWNER for high/critical)"
                  : isTerminal
                  ? "Proposal is in terminal state"
                  : isApproved
                  ? "Proposal is already approved"
                  : "Authorize proposal under organization policy"
              }
              data-testid="open-approve-button"
            >
              <CheckCircle2 size={14} /> Authorize Approval
            </button>
          </div>
        </div>

        {/* Execution Safety Barrier Notice */}
        <div className="execution-barrier-banner" data-testid="execution-safety-barrier-banner">
          <AlertOctagon size={18} style={{ flexShrink: 0 }} />
          <div>
            <strong>Safe Execution Barrier:</strong> TracePilot action execution is permanently
            disabled in this release. Approvals enforce organizational policy compliance and audit
            provenance only—automated remediation execution is prohibited.
          </div>
        </div>

        {/* Navigation Tabs */}
        <div style={{ display: "flex", gap: "6px", borderBottom: "1px solid var(--border-subtle)", marginTop: "4px" }}>
          <button
            type="button"
            onClick={() => setActiveTab("overview")}
            style={{
              padding: "8px 14px",
              border: "none",
              borderBottom: activeTab === "overview" ? "2px solid var(--accent-primary)" : "2px solid transparent",
              background: "transparent",
              color: activeTab === "overview" ? "var(--text-primary)" : "var(--text-muted)",
              fontWeight: activeTab === "overview" ? 600 : 500,
              fontSize: "0.85rem",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
            data-testid="tab-overview"
          >
            <ShieldAlert size={14} /> Risk & Policy
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("actions")}
            style={{
              padding: "8px 14px",
              border: "none",
              borderBottom: activeTab === "actions" ? "2px solid var(--accent-primary)" : "2px solid transparent",
              background: "transparent",
              color: activeTab === "actions" ? "var(--text-primary)" : "var(--text-muted)",
              fontWeight: activeTab === "actions" ? 600 : 500,
              fontSize: "0.85rem",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
            data-testid="tab-actions"
          >
            <Terminal size={14} /> Action Steps ({proposal.actions.length})
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("evidence")}
            style={{
              padding: "8px 14px",
              border: "none",
              borderBottom: activeTab === "evidence" ? "2px solid var(--accent-primary)" : "2px solid transparent",
              background: "transparent",
              color: activeTab === "evidence" ? "var(--text-primary)" : "var(--text-muted)",
              fontWeight: activeTab === "evidence" ? 600 : 500,
              fontSize: "0.85rem",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
            data-testid="tab-evidence"
          >
            <FileText size={14} /> Evidence Grounding ({evidenceEvents.length})
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("audit")}
            style={{
              padding: "8px 14px",
              border: "none",
              borderBottom: activeTab === "audit" ? "2px solid var(--accent-primary)" : "2px solid transparent",
              background: "transparent",
              color: activeTab === "audit" ? "var(--text-primary)" : "var(--text-muted)",
              fontWeight: activeTab === "audit" ? 600 : 500,
              fontSize: "0.85rem",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
            data-testid="tab-audit"
          >
            <History size={14} /> Audit Trail ({auditEvents.length})
          </button>
        </div>
      </div>

      {/* Tab Content Body */}
      <div className="remediation-detail-body">
        {activeTab === "overview" && (
          <>
            {/* Proposal Summary Card */}
            <div className="remediation-section-card" data-testid="proposal-summary-card">
              <h3 style={{ fontSize: "0.95rem", fontWeight: 700 }}>Summary & Description</h3>
              <p style={{ fontSize: "0.88rem", color: "var(--text-secondary)", lineHeight: "1.6" }}>
                {proposal.description}
              </p>

              {proposal.mitigation_rationale && (
                <div
                  style={{
                    padding: "10px 14px",
                    background: "var(--bg-secondary)",
                    borderRadius: "var(--radius-sm)",
                    borderLeft: "3px solid var(--accent-primary)",
                    fontSize: "0.82rem",
                    color: "var(--text-secondary)",
                  }}
                >
                  <strong>Mitigation Rationale:</strong> {proposal.mitigation_rationale}
                </div>
              )}

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "16px",
                  fontSize: "0.75rem",
                  color: "var(--text-muted)",
                  paddingTop: "8px",
                  borderTop: "1px solid var(--border-subtle)",
                }}
              >
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                  <Calendar size={12} /> Created: {new Date(proposal.created_at).toLocaleString()}
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                  <RotateCw size={12} /> Last Updated: {new Date(proposal.updated_at).toLocaleString()}
                </span>
                {proposal.approved_at && (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", color: "#059669" }}>
                    <ShieldCheck size={12} /> Approved: {new Date(proposal.approved_at).toLocaleString()}
                  </span>
                )}
              </div>
            </div>

            {/* Policy Rules & Separation of Duties */}
            <PolicyExplanationCard
              proposal={proposal}
              currentUser={currentUser}
              currentUserRole={currentUserRole}
            />

            {/* Deterministic Risk Breakdown */}
            <RiskAssessmentView
              riskAssessment={proposal.risk_assessment}
              riskLevel={proposal.risk_level}
              hypothesisGroundednessStatus={hypothesis?.groundedness_status}
            />
          </>
        )}

        {activeTab === "actions" && (
          <ActionStepsList
            actions={proposal.actions}
            rollbackPlan={proposal.rollback_plan}
            estimatedImpact={proposal.estimated_impact}
          />
        )}

        {activeTab === "evidence" && (
          <EvidenceProvenanceView
            hypothesis={hypothesis}
            evidenceEvents={evidenceEvents}
            incidentId={proposal.incident_id}
          />
        )}

        {activeTab === "audit" && (
          <AuditTrailTimeline
            events={auditEvents}
            approvals={approvals}
            isLoading={auditLoading}
            error={auditError}
            onRefresh={fetchAuditData}
          />
        )}
      </div>

      {/* Decision Workflow Confirmation Modal */}
      <ApprovalWorkflowModal
        isOpen={showApprovalModal}
        decisionType={modalDecision}
        proposal={proposal}
        reviewerRole={currentUserRole}
        onClose={() => setShowApprovalModal(false)}
        onSuccess={reloadProposal}
        onConflictRefresh={reloadProposal}
      />

      {/* Local Policy Dry-Run Modal */}
      <DryRunModal
        isOpen={showDryRunModal}
        remediationId={proposal.id}
        onClose={() => setShowDryRunModal(false)}
      />
    </div>
  );
};
