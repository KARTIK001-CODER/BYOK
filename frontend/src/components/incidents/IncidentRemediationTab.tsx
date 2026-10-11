import React, { useState, useEffect, useCallback } from "react";
import {
  ShieldAlert,
  RefreshCw,
  ExternalLink,
  Lock,
  Sparkles,
} from "lucide-react";
import { RemediationProposal, RemediationRiskLevel } from "../../types/remediation";
import { RemediationsApi } from "../../api/remediations";

interface IncidentRemediationTabProps {
  incidentId: string;
  onOpenReviewCenter?: (incidentId?: string) => void;
  onNavigateInvestigation?: () => void;
}

export const IncidentRemediationTab: React.FC<IncidentRemediationTabProps> = ({
  incidentId,
  onOpenReviewCenter,
  onNavigateInvestigation,
}) => {
  const [proposals, setProposals] = useState<RemediationProposal[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProposals = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await RemediationsApi.listForIncident(incidentId);
      setProposals(res.items || []);
    } catch (err: unknown) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to load remediation proposals.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    fetchProposals();
  }, [fetchProposals]);

  const getRiskBadgeClass = (riskLevel: RemediationRiskLevel) => {
    switch (riskLevel) {
      case "critical":
        return "badge-risk-critical";
      case "high":
        return "badge-risk-high";
      case "medium":
        return "badge-risk-medium";
      case "low":
        return "badge-risk-low";
      default:
        return "";
    }
  };

  return (
    <div className="incident-remediation-tab-container" data-testid="incident-remediation-tab">
      {/* Top Header & Context */}
      <div className="remediation-tab-header">
        <div className="remediation-tab-title-group">
          <h3>
            <ShieldAlert size={18} color="var(--accent-primary)" />
            Remediation Proposals ({proposals.length})
          </h3>
          <p className="remediation-tab-subtitle">
            Evidence-grounded action plans with deterministic blast-radius assessment and human approval
            workflows.
          </p>
        </div>

        <div className="remediation-tab-actions">
          <button
            className="btn-secondary-incident"
            onClick={fetchProposals}
            disabled={isLoading}
            title="Refresh Proposals"
            data-testid="refresh-remediations-btn"
          >
            <RefreshCw size={13} className={isLoading ? "spin" : ""} />
            Refresh
          </button>

          {onOpenReviewCenter && (
            <button
              className="btn-primary-incident"
              onClick={() => onOpenReviewCenter(incidentId)}
              data-testid="open-review-center-btn"
            >
              <ExternalLink size={14} />
              Open Remediation Review Center
            </button>
          )}
        </div>
      </div>

      {/* Mandatory Safety Boundary Banner */}
      <div className="safety-boundary-banner" data-testid="safety-boundary-banner">
        <Lock size={15} style={{ flexShrink: 0 }} />
        <span>
          <strong>SAFETY BOUNDARY:</strong> Automated remediation execution is strictly disabled (HTTP
          403 Forbidden). All proposals are advisory specifications requiring authorized human approval.
        </span>
      </div>

      {/* Content States */}
      {isLoading ? (
        <div className="remediation-loading-state" data-testid="remediation-loading">
          <RefreshCw size={22} className="spin text-accent" />
          <span>Loading remediation proposals for incident...</span>
        </div>
      ) : error ? (
        <div className="remediation-error-state" data-testid="remediation-error">
          <span>{error}</span>
          <button
            className="btn-secondary-incident"
            onClick={fetchProposals}
            style={{ padding: "4px 10px", fontSize: "0.8rem" }}
          >
            Retry
          </button>
        </div>
      ) : proposals.length === 0 ? (
        <div className="remediation-empty-state" data-testid="remediation-empty">
          <ShieldAlert size={36} color="var(--text-muted)" />
          <h4>No Remediation Proposals Generated</h4>
          <p>
            No remediation proposals are linked to this incident. Once an automated investigation produces
            grounded root-cause hypotheses, remediation actions can be synthesized.
          </p>
          {onNavigateInvestigation && (
            <button
              className="btn-primary-incident"
              onClick={onNavigateInvestigation}
              data-testid="empty-go-investigation-btn"
            >
              <Sparkles size={15} />
              Go to Investigation Engine
            </button>
          )}
        </div>
      ) : (
        <div className="remediation-cards-grid" data-testid="remediation-cards-list">
          {proposals.map((proposal) => (
            <div
              key={proposal.id}
              className="remediation-proposal-card"
              data-testid={`remediation-card-${proposal.id}`}
            >
              <div className="proposal-card-top">
                <div className="proposal-badges">
                  <span className={`badge-risk ${getRiskBadgeClass(proposal.risk_level)}`}>
                    RISK: {proposal.risk_level.toUpperCase()}
                  </span>
                  <span className="badge-status">{proposal.status.replace(/_/g, " ").toUpperCase()}</span>
                  <span className="badge-advisory">ADVISORY ONLY</span>
                </div>
                <span className="proposal-timestamp">
                  {proposal.created_at ? new Date(proposal.created_at).toLocaleString() : "Recently"}
                </span>
              </div>

              <h4 className="proposal-card-title">{proposal.title}</h4>
              <p className="proposal-card-desc">{proposal.description}</p>

              {/* Action Steps & Blast Radius Metadata */}
              <div className="proposal-meta-grid">
                <div>
                  <div className="meta-label">Action Steps</div>
                  <div className="meta-value">{proposal.actions?.length ?? 0} Steps Defined</div>
                </div>
                <div>
                  <div className="meta-label">Blast Radius</div>
                  <div className="meta-value">
                    {proposal.risk_assessment?.blast_radius || "Unassessed"}
                  </div>
                </div>
                <div>
                  <div className="meta-label">Reversibility</div>
                  <div className="meta-value">
                    {proposal.risk_assessment?.reversibility_assessment || "Manual Rollback"}
                  </div>
                </div>
                <div>
                  <div className="meta-label">Human Approval</div>
                  <div className="meta-value" style={{ color: "#ef4444" }}>
                    Mandatory
                  </div>
                </div>
              </div>

              {/* Action button to open full review center */}
              {onOpenReviewCenter && (
                <div className="proposal-card-footer">
                  <button
                    className="btn-link-action"
                    onClick={() => onOpenReviewCenter(incidentId)}
                    data-testid={`review-proposal-${proposal.id}`}
                  >
                    Open in Remediation Review Center &rarr;
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
