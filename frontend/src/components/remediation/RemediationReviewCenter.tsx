import React, { useState, useEffect, useCallback } from "react";
import {
  ShieldAlert,
  Search,
  RefreshCw,
  AlertOctagon,
  Clock,
  Inbox,
  AlertTriangle,
} from "lucide-react";
import {
  RemediationProposal,
  RemediationRiskLevel,
  RemediationStatus,
} from "../../types/remediation";
import { EvidenceEvent, Incident } from "../../types/incident";
import { HypothesisResponse } from "../../types/investigation";
import { User, Organization } from "../../types";
import { RemediationsApi } from "../../api/remediations";
import { IncidentsApi } from "../../api/incidents";
import { InvestigationsApi } from "../../api/investigations";
import { ProposalDetailView } from "./ProposalDetailView";

interface RemediationReviewCenterProps {
  currentUser: User | null;
  currentUserRole?: string | null;
  organization: Organization | null;
  initialIncidentId?: string | null;
}

export const RemediationReviewCenter: React.FC<RemediationReviewCenterProps> = ({
  currentUser,
  currentUserRole,
  organization,
  initialIncidentId,
}) => {
  const [proposals, setProposals] = useState<RemediationProposal[]>([]);
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [riskFilter, setRiskFilter] = useState<string>("");

  // Context for selected proposal
  const [activeIncident, setActiveIncident] = useState<Incident | null>(null);
  const [activeHypothesis, setActiveHypothesis] = useState<HypothesisResponse | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<EvidenceEvent[]>([]);

  const loadProposals = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const resp = await RemediationsApi.listAll(
        {
          incident_id: initialIncidentId || undefined,
          status: statusFilter || undefined,
        },
        organization?.id
      );
      setProposals(resp.items || []);
      if (resp.items && resp.items.length > 0 && !selectedProposalId) {
        setSelectedProposalId(resp.items[0].id);
      }
    } catch (err: unknown) {
      const errorObj = err as { message?: string };
      setError(errorObj?.message || "Failed to load remediation proposals.");
    } finally {
      setIsLoading(false);
    }
  }, [initialIncidentId, statusFilter, organization?.id, selectedProposalId]);

  useEffect(() => {
    loadProposals();
  }, [loadProposals]);

  const selectedProposal = proposals.find((p) => p.id === selectedProposalId) || proposals[0] || null;

  // Load Incident & Hypothesis context when selected proposal changes
  useEffect(() => {
    if (!selectedProposal) {
      setActiveIncident(null);
      setActiveHypothesis(null);
      setActiveEvidence([]);
      return;
    }

    // Fetch incident
    IncidentsApi.get(selectedProposal.incident_id)
      .then((inc) => setActiveIncident(inc))
      .catch(() => setActiveIncident(null));

    // Fetch evidence events
    IncidentsApi.listEvidence(selectedProposal.incident_id)
      .then((evResp) => setActiveEvidence(evResp.items || []))
      .catch(() => setActiveEvidence([]));

    // Fetch linked hypothesis if present
    if (selectedProposal.hypothesis_id) {
      InvestigationsApi.getHypothesis(selectedProposal.hypothesis_id)
        .then((hyp) => setActiveHypothesis(hyp))
        .catch(() => setActiveHypothesis(null));
    } else {
      setActiveHypothesis(null);
    }
  }, [selectedProposal?.id, selectedProposal?.incident_id, selectedProposal?.hypothesis_id]);

  const handleProposalUpdated = (updated: RemediationProposal) => {
    setProposals((prev) =>
      prev.map((p) => (p.id === updated.id ? updated : p))
    );
  };

  // Filter proposals
  const filteredProposals = proposals.filter((p) => {
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchTitle = p.title.toLowerCase().includes(q);
      const matchDesc = p.description.toLowerCase().includes(q);
      if (!matchTitle && !matchDesc) return false;
    }
    if (statusFilter && p.status !== statusFilter) return false;
    if (riskFilter && p.risk_level !== riskFilter) return false;
    return true;
  });

  const getRiskBadgeClass = (level: RemediationRiskLevel) => {
    switch (level) {
      case "low":
        return "badge-risk-low";
      case "medium":
        return "badge-risk-medium";
      case "high":
        return "badge-risk-high";
      case "critical":
        return "badge-risk-critical";
      default:
        return "badge-risk-medium";
    }
  };

  const getStatusBadgeClass = (status: RemediationStatus) => {
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
    <div className="remediation-center-container" data-testid="remediation-review-center">
      {/* Master Proposal Sidebar */}
      <div className="remediation-sidebar">
        <div className="remediation-sidebar-header">
          <div className="remediation-sidebar-title">
            <h2>
              <ShieldAlert size={18} className="text-accent" />
              Remediation Proposals
            </h2>
            <button
              onClick={() => loadProposals()}
              className="btn-secondary"
              style={{ padding: "4px 8px", fontSize: "0.75rem" }}
              title="Refresh proposal list"
              aria-label="Refresh proposals"
            >
              <RefreshCw size={12} className={isLoading ? "animate-spin" : ""} />
            </button>
          </div>

          {/* Search box */}
          <div className="remediation-search-box">
            <Search size={14} color="var(--text-muted)" />
            <input
              type="text"
              placeholder="Filter by title or keywords..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Filter proposals"
            />
          </div>

          {/* Filter row */}
          <div className="remediation-filter-row">
            <select
              className="remediation-filter-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              aria-label="Filter by status"
            >
              <option value="">All Statuses</option>
              <option value="proposed">Proposed</option>
              <option value="reviewed">Reviewed</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="superseded">Superseded</option>
              <option value="cancelled">Cancelled</option>
            </select>

            <select
              className="remediation-filter-select"
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              aria-label="Filter by risk"
            >
              <option value="">All Risks</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
        </div>

        {/* Proposals List */}
        <div className="remediation-list" data-testid="remediation-proposals-list">
          {isLoading && proposals.length === 0 ? (
            <div style={{ padding: "30px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
              Loading proposals...
            </div>
          ) : error ? (
            <div
              style={{
                padding: "14px",
                borderRadius: "var(--radius-md)",
                background: "rgba(239, 68, 68, 0.1)",
                color: "#dc2626",
                fontSize: "0.82rem",
              }}
            >
              <AlertTriangle size={14} style={{ display: "inline", marginRight: "4px" }} />
              {error}
            </div>
          ) : filteredProposals.length === 0 ? (
            <div
              style={{
                padding: "30px 16px",
                textAlign: "center",
                color: "var(--text-muted)",
                fontSize: "0.82rem",
              }}
              data-testid="no-proposals-message"
            >
              <Inbox size={24} style={{ margin: "0 auto 8px auto", opacity: 0.5 }} />
              No remediation proposals match the current filter criteria.
            </div>
          ) : (
            filteredProposals.map((prop) => {
              const isActive = selectedProposal?.id === prop.id;
              return (
                <div
                  key={prop.id}
                  className={`remediation-card ${isActive ? "active" : ""}`}
                  onClick={() => setSelectedProposalId(prop.id)}
                  data-testid={`proposal-card-${prop.id}`}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      setSelectedProposalId(prop.id);
                    }
                  }}
                >
                  <div className="remediation-card-header">
                    <span className="remediation-card-title">{prop.title}</span>
                    <span className={`badge ${getRiskBadgeClass(prop.risk_level)}`}>
                      {prop.risk_level}
                    </span>
                  </div>

                  <div className="remediation-card-meta">
                    <span className={`badge ${getStatusBadgeClass(prop.status)}`}>
                      {prop.status}
                    </span>
                    <span className="badge-version">v{prop.version}</span>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "3px" }}>
                      <Clock size={10} />
                      {new Date(prop.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Detail Pane */}
      {selectedProposal ? (
        <ProposalDetailView
          proposal={selectedProposal}
          incident={activeIncident}
          hypothesis={activeHypothesis}
          evidenceEvents={activeEvidence}
          currentUser={currentUser}
          currentUserRole={currentUserRole}
          onProposalUpdated={handleProposalUpdated}
        />
      ) : (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexDirection: "column",
            gap: "12px",
            color: "var(--text-muted)",
          }}
          data-testid="no-proposal-selected-pane"
        >
          <AlertOctagon size={36} style={{ opacity: 0.4 }} />
          <h3 style={{ fontSize: "1rem", fontWeight: 600 }}>No Remediation Proposal Selected</h3>
          <p style={{ fontSize: "0.84rem" }}>
            Select a proposal from the sidebar to review risk assessment and audit policy.
          </p>
        </div>
      )}
    </div>
  );
};
