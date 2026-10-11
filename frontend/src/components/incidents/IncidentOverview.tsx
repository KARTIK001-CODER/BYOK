import React, { useState, useEffect } from "react";
import {
  Clock,
  Sparkles,
  ShieldAlert,
  CheckCircle,
  Database,
  Server,
} from "lucide-react";
import { Incident } from "../../types/incident";
import { IncidentsApi } from "../../api/incidents";
import { InvestigationsApi } from "../../api/investigations";
import { RemediationsApi } from "../../api/remediations";

interface IncidentOverviewProps {
  incident: Incident;
  onNavigateTab: (tab: "timeline" | "evidence" | "investigation" | "remediation" | "runbooks") => void;
  onNavigateRemediations?: (incidentId?: string) => void;
}

export const IncidentOverview: React.FC<IncidentOverviewProps> = ({
  incident,
  onNavigateTab,
  onNavigateRemediations,
}) => {
  const [timelineCount, setTimelineCount] = useState<number | null>(null);
  const [evidenceCount, setEvidenceCount] = useState<number | null>(null);
  const [investigationJobCount, setInvestigationJobCount] = useState<number | null>(null);
  const [remediationCount, setRemediationCount] = useState<number | null>(null);

  useEffect(() => {
    let isMounted = true;

    const fetchCounts = async () => {
      try {
        if (typeof IncidentsApi?.getTimeline === "function") {
          const tlRes = await IncidentsApi.getTimeline(incident.id, 100, 0);
          if (isMounted && tlRes) {
            setTimelineCount(
              Array.isArray(tlRes)
                ? tlRes.length
                : ((tlRes as { total?: number; total_events?: number }).total ??
                   (tlRes as { total?: number; total_events?: number }).total_events ??
                   0)
            );
          }
        }
      } catch {
        // Safe fallback
      }

      try {
        if (typeof IncidentsApi?.listEvidence === "function") {
          const evRes = await IncidentsApi.listEvidence(incident.id, undefined, 1, 0);
          if (isMounted && evRes) {
            setEvidenceCount(
              evRes.total ?? (Array.isArray(evRes.items) ? evRes.items.length : 0)
            );
          }
        }
      } catch {
        // Safe fallback
      }

      try {
        if (typeof InvestigationsApi?.listForIncident === "function") {
          const invRes = await InvestigationsApi.listForIncident(incident.id, 1, 0);
          if (isMounted && invRes) {
            setInvestigationJobCount(
              invRes.total ?? (Array.isArray(invRes.items) ? invRes.items.length : 0)
            );
          }
        }
      } catch {
        // Safe fallback
      }

      try {
        if (typeof RemediationsApi?.listForIncident === "function") {
          const remRes = await RemediationsApi.listForIncident(incident.id);
          if (isMounted && remRes) {
            setRemediationCount(
              remRes.total ?? (Array.isArray(remRes.items) ? remRes.items.length : 0)
            );
          }
        }
      } catch {
        // Safe fallback
      }
    };

    fetchCounts();

    return () => {
      isMounted = false;
    };
  }, [incident.id]);

  const formatDate = (dateStr?: string | null) => {
    if (!dateStr) return "Not recorded";
    try {
      const d = new Date(dateStr);
      return isNaN(d.getTime()) ? dateStr : d.toLocaleString();
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="incident-overview-container" data-testid="incident-overview">
      {/* Incident Description / Summary Banner */}
      <div className="overview-summary-banner">
        <div className="overview-desc-header">
          <h4>Incident Summary & Symptoms</h4>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Reported: {formatDate(incident.created_at)}
            </span>
            <span className="badge-environment">ENV: {incident.environment.toUpperCase()}</span>
          </div>
        </div>
        <p className="overview-desc-text">
          {incident.description || "No detailed operational description provided at intake."}
        </p>
      </div>

      {/* Service & Operational Context (Stage D) */}
      <div className="overview-service-context-box p-4 border rounded bg-surface" data-testid="overview-service-context">
        <div className="flex justify-between items-center mb-3">
          <div className="flex items-center gap-2">
            <Server size={16} className="text-primary" />
            <h4 className="m-0 text-sm font-semibold">Service & Environment Context</h4>
          </div>
          <span className="text-xs text-muted">Tenant-Scoped SRE Boundary</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div className="p-2 rounded bg-secondary">
            <span className="text-muted block mb-1">Affected Service</span>
            <span className="font-mono font-bold block truncate" data-testid="context-service-name">
              {incident.service_name || "Unspecified / Multi-service"}
            </span>
          </div>
          <div className="p-2 rounded bg-secondary">
            <span className="text-muted block mb-1">Target Environment</span>
            <span className="badge-environment font-semibold block uppercase" data-testid="context-environment">
              {(incident.environment || "production").toUpperCase()}
            </span>
          </div>
          <div className="p-2 rounded bg-secondary">
            <span className="text-muted block mb-1">Severity Rating</span>
            <span className={`badge-severity badge-severity-${incident.severity} block`}>
              {incident.severity.toUpperCase()}
            </span>
          </div>
          <div className="p-2 rounded bg-secondary">
            <span className="text-muted block mb-1">Lifecycle State</span>
            <span className="badge-status block">{incident.status.toUpperCase()}</span>
          </div>
        </div>
      </div>

      {/* Operational Domain Cards Grid */}
      <div className="overview-domains-grid">
        {/* Timeline Domain */}
        <div
          className="overview-domain-card"
          onClick={() => onNavigateTab("timeline")}
          data-testid="overview-timeline-card"
        >
          <div className="domain-card-header">
            <div className="domain-icon-circle timeline-icon">
              <Clock size={18} />
            </div>
            <span className="domain-count">
              {timelineCount !== null ? timelineCount : incident.evidence_count ?? "—"}
            </span>
          </div>
          <h5>Chronological Timeline</h5>
          <p>Deterministic sequence of operational alerts, logs, metrics, and deployment events.</p>
          <button className="domain-action-btn">
            View Timeline &rarr;
          </button>
        </div>

        {/* Evidence Domain */}
        <div
          className="overview-domain-card"
          onClick={() => onNavigateTab("evidence")}
          data-testid="overview-evidence-card"
        >
          <div className="domain-card-header">
            <div className="domain-icon-circle evidence-icon">
              <Database size={18} />
            </div>
            <span className="domain-count">
              {evidenceCount !== null ? evidenceCount : incident.evidence_count ?? "—"}
            </span>
          </div>
          <h5>Operational Evidence</h5>
          <p>Multi-source normalized telemetry events with cryptographic deduplication keys.</p>
          <button className="domain-action-btn">
            Browse Evidence &rarr;
          </button>
        </div>

        {/* Investigation Domain */}
        <div
          className="overview-domain-card"
          onClick={() => onNavigateTab("investigation")}
          data-testid="overview-investigation-card"
        >
          <div className="domain-card-header">
            <div className="domain-icon-circle investigation-icon">
              <Sparkles size={18} />
            </div>
            <span className="domain-count">
              {investigationJobCount !== null ? investigationJobCount : "0"}
            </span>
          </div>
          <h5>Investigation Engine</h5>
          <p>Real-time SSE streamed hypothesis generation and citation groundedness scoring.</p>
          <button className="domain-action-btn">
            Open Investigation &rarr;
          </button>
        </div>

        {/* Remediation Domain */}
        <div
          className="overview-domain-card"
          onClick={() =>
            onNavigateRemediations
              ? onNavigateRemediations(incident.id)
              : onNavigateTab("remediation")
          }
          data-testid="overview-remediation-card"
        >
          <div className="domain-card-header">
            <div className="domain-icon-circle remediation-icon">
              <ShieldAlert size={18} />
            </div>
            <span className="domain-count">
              {remediationCount !== null ? remediationCount : "0"}
            </span>
          </div>
          <h5>Remediation Actions</h5>
          <p>Advisory proposals with deterministic risk scoring and mandatory human approval.</p>
          <button className="domain-action-btn">
            Review Remediations &rarr;
          </button>
        </div>
      </div>

      {/* SRE Investigation Workflow Checklist */}
      <div className="overview-workflow-card">
        <h4>TracePilot SRE Investigation Lifecycle</h4>
        <div className="workflow-steps-track">
          <div className="workflow-step completed">
            <div className="step-circle">
              <CheckCircle size={14} />
            </div>
            <div className="step-content">
              <strong>1. Incident Intake</strong>
              <span>Scope defined ({incident.service_name || "service"}, {incident.severity})</span>
            </div>
          </div>

          <div className="workflow-step active">
            <div className="step-circle">2</div>
            <div className="step-content">
              <strong>2. Evidence Collection</strong>
              <span>Logs, metrics, alerts ingested with deduplication</span>
            </div>
          </div>

          <div className="workflow-step">
            <div className="step-circle">3</div>
            <div className="step-content">
              <strong>3. Timeline Reconstruction</strong>
              <span>Deterministic timestamp-based event ordering</span>
            </div>
          </div>

          <div className="workflow-step">
            <div className="step-circle">4</div>
            <div className="step-content">
              <strong>4. Investigation Engine</strong>
              <span>Hybrid retrieval & root-cause hypotheses</span>
            </div>
          </div>

          <div className="workflow-step">
            <div className="step-circle">5</div>
            <div className="step-content">
              <strong>5. Human Remediation Review</strong>
              <span>Risk rating, policy validation & multi-sig approval</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
