import React from "react";
import {
  History,
  CheckCircle2,
  XCircle,
  FilePlus,
  RefreshCw,
  AlertTriangle,
  ArrowRight,
  Shield,
  Clock,
  User,
  Hash,
} from "lucide-react";
import { RemediationAuditEvent, RemediationApproval } from "../../types/remediation";

interface AuditTrailTimelineProps {
  events: RemediationAuditEvent[];
  approvals: RemediationApproval[];
  isLoading: boolean;
  error?: string | null;
  onRefresh: () => void;
}

export const AuditTrailTimeline: React.FC<AuditTrailTimelineProps> = ({
  events,
  approvals,
  isLoading,
  error,
  onRefresh,
}) => {
  const getEventIcon = (eventType: string) => {
    switch (eventType) {
      case "proposal_approved":
        return <CheckCircle2 size={14} color="#059669" />;
      case "proposal_rejected":
        return <XCircle size={14} color="#dc2626" />;
      case "approval_invalidated":
        return <AlertTriangle size={14} color="#ea580c" />;
      case "proposal_created":
      case "proposal_generated":
        return <FilePlus size={14} color="var(--accent-primary)" />;
      case "risk_assessed":
        return <Shield size={14} color="#8b5cf6" />;
      default:
        return <History size={14} color="var(--text-muted)" />;
    }
  };

  const formatEventType = (eventType: string) => {
    return eventType
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  };

  return (
    <div className="remediation-section-card" data-testid="audit-trail-section">
      <div className="remediation-section-header">
        <h3>
          <History size={18} className="text-accent" />
          Append-Only Audit Trail ({events.length})
        </h3>
        <button
          onClick={onRefresh}
          className="btn-secondary"
          style={{ fontSize: "0.75rem", padding: "4px 8px" }}
          disabled={isLoading}
          aria-label="Refresh audit history"
        >
          <RefreshCw size={12} className={isLoading ? "animate-spin" : ""} /> Refresh Log
        </button>
      </div>

      <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
        Append-only application audit log recording state transitions, human reviewer decisions,
        and invalidation events. Historical events are durable and preserved.
      </p>

      {error && (
        <div
          style={{
            padding: "10px 14px",
            borderRadius: "var(--radius-sm)",
            background: "rgba(239, 68, 68, 0.1)",
            color: "#dc2626",
            fontSize: "0.82rem",
          }}
        >
          {error}
        </div>
      )}

      {isLoading && events.length === 0 ? (
        <div style={{ padding: "20px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
          Loading audit events...
        </div>
      ) : events.length === 0 ? (
        <div
          style={{
            padding: "20px",
            textAlign: "center",
            color: "var(--text-muted)",
            fontSize: "0.85rem",
            background: "var(--bg-secondary)",
            borderRadius: "var(--radius-md)",
          }}
          data-testid="empty-audit-log"
        >
          No audit entries recorded for this remediation proposal yet.
        </div>
      ) : (
        <div className="audit-timeline" data-testid="audit-events-stream">
          {events.map((ev) => {
            // Check if there is an associated approval record with rationale
            const relatedDecision = approvals.find(
              (a) => a.proposal_version === ev.proposal_version && a.created_at === ev.created_at
            );
            const rationale = relatedDecision?.rationale || (ev.details?.rationale as string);

            return (
              <div key={ev.id} className="audit-event-item" data-testid={`audit-event-${ev.id}`}>
                <div className="audit-event-dot" />

                <div className="audit-event-header">
                  <span className="audit-event-title">
                    {getEventIcon(ev.event_type)}
                    {formatEventType(ev.event_type)}
                    <span className="badge badge-version">v{ev.proposal_version}</span>
                  </span>

                  <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                    <Clock size={11} />
                    {new Date(ev.created_at).toLocaleString()}
                  </span>
                </div>

                {/* State transition if present */}
                {(ev.from_status || ev.to_status) && (
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.78rem" }}>
                    <span className="badge badge-version">{ev.from_status || "none"}</span>
                    <ArrowRight size={11} color="var(--text-muted)" />
                    <span className="badge badge-status-proposed">{ev.to_status || "none"}</span>
                  </div>
                )}

                {/* Rationale if present */}
                {rationale && (
                  <div className="audit-event-rationale">
                    "{rationale}"
                  </div>
                )}

                {/* Actor & Metadata */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "12px",
                    fontSize: "0.74rem",
                    color: "var(--text-muted)",
                    flexWrap: "wrap",
                  }}
                >
                  {ev.actor_user_id && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                      <User size={11} />
                      Actor: {ev.actor_user_id.slice(0, 8)}... ({ev.actor_role || "member"})
                    </span>
                  )}
                  {ev.request_id && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontFamily: "var(--font-mono)" }}>
                      <Hash size={10} />
                      Req: {ev.request_id.slice(0, 8)}...
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
