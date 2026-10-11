import React from "react";
import {
  FileText,
  Clock,
  Tag,
  AlertCircle,
  Database,
  GitCommit,
  Activity,
  Bell,
  CheckCircle2,
} from "lucide-react";
import { EvidenceEvent } from "../../types/incident";
import { HypothesisResponse } from "../../types/investigation";

interface EvidenceProvenanceViewProps {
  hypothesis?: HypothesisResponse | null;
  evidenceEvents?: EvidenceEvent[];
  incidentId: string;
}

export const EvidenceProvenanceView: React.FC<EvidenceProvenanceViewProps> = ({
  hypothesis,
  evidenceEvents = [],
  incidentId,
}) => {
  const getSourceIcon = (sourceType: string) => {
    switch (sourceType.toLowerCase()) {
      case "log":
        return <FileText size={13} />;
      case "metric":
        return <Activity size={13} />;
      case "alert":
        return <Bell size={13} />;
      case "deployment":
      case "git commit":
      case "commit":
        return <GitCommit size={13} />;
      default:
        return <Database size={13} />;
    }
  };

  return (
    <div className="remediation-section-card" data-testid="evidence-provenance-section">
      <div className="remediation-section-header">
        <h3>
          <FileText size={18} className="text-accent" />
          Evidence Provenance & Grounding
        </h3>
        <span className="badge badge-version">
          Incident ID: {incidentId.slice(0, 8)}...
        </span>
      </div>

      {/* Distinction banner */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "8px 12px",
          borderRadius: "var(--radius-sm)",
          background: "var(--bg-secondary)",
          border: "1px solid var(--border-subtle)",
          fontSize: "0.8rem",
          color: "var(--text-secondary)",
        }}
      >
        <CheckCircle2 size={14} color="#059669" style={{ flexShrink: 0 }} />
        <span>
          <strong>Empirical Fact Distinction:</strong> Telemetry below represents immutable observed events.
          Hypotheses and remediation actions are inferential recommendations derived from this telemetry.
        </span>
      </div>

      {/* Linked Hypothesis Card */}
      {hypothesis ? (
        <div
          style={{
            padding: "14px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)",
            background: "var(--bg-secondary)",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
          data-testid="linked-hypothesis-card"
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span
              style={{
                fontSize: "0.76rem",
                fontWeight: 700,
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              Grounding Root-Cause Hypothesis
            </span>
            {hypothesis.groundedness_status && (
              <span className="badge badge-version">
                {hypothesis.groundedness_status.replace("_", " ")}
              </span>
            )}
          </div>
          <p style={{ fontSize: "0.88rem", fontWeight: 600, color: "var(--text-primary)" }}>
            {hypothesis.claim}
          </p>
          <p style={{ fontSize: "0.82rem", color: "var(--text-secondary)" }}>
            {hypothesis.rationale}
          </p>
          {hypothesis.supporting_evidence && hypothesis.supporting_evidence.length > 0 && (
            <div style={{ fontSize: "0.76rem", color: "var(--text-muted)" }}>
              Citing {hypothesis.supporting_evidence.length} validated evidence links
            </div>
          )}
        </div>
      ) : (
        <div
          style={{
            padding: "12px",
            borderRadius: "var(--radius-sm)",
            background: "var(--bg-secondary)",
            border: "1px dashed var(--border-subtle)",
            fontSize: "0.82rem",
            color: "var(--text-muted)",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <AlertCircle size={14} color="var(--warning-text)" />
          <span>No specific root-cause hypothesis attached. Remediation was directly proposed.</span>
        </div>
      )}

      {/* Evidence Events List */}
      <div>
        <h4 style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: "10px" }}>
          Incident Telemetry & Supporting Events ({evidenceEvents.length})
        </h4>

        {evidenceEvents.length === 0 ? (
          <div
            style={{
              padding: "20px",
              textAlign: "center",
              color: "var(--text-muted)",
              fontSize: "0.82rem",
              background: "var(--bg-secondary)",
              borderRadius: "var(--radius-md)",
            }}
          >
            No raw telemetry records available for this incident context.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }} data-testid="evidence-list">
            {evidenceEvents.map((ev) => (
              <div
                key={ev.id}
                style={{
                  padding: "10px 14px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border-subtle)",
                  background: "var(--bg-secondary)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "6px",
                }}
                data-testid={`evidence-event-${ev.id}`}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "6px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span className="badge badge-version">
                      {getSourceIcon(ev.source_type)}
                      {ev.source_type}
                    </span>
                    <span style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--text-primary)" }}>
                      {ev.event_type}
                    </span>
                  </div>

                  <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                    <Clock size={11} />
                    {new Date(ev.event_timestamp).toLocaleString()}
                  </span>
                </div>

                <p style={{ fontSize: "0.82rem", color: "var(--text-secondary)" }}>
                  {ev.summary}
                </p>

                {ev.source_reference && (
                  <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                    <Tag size={10} style={{ display: "inline", marginRight: "4px" }} />
                    Ref: {ev.source_reference}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
