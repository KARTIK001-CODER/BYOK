import React from "react";
import {
  AlertTriangle,
  ShieldAlert,
  ShieldCheck,
  Info,
  Layers,
  RotateCcw,
} from "lucide-react";
import { RemediationRiskLevel, RiskAssessmentDetails } from "../../types/remediation";

interface RiskAssessmentViewProps {
  riskAssessment?: RiskAssessmentDetails | null;
  riskLevel: RemediationRiskLevel;
  hypothesisGroundednessStatus?: string | null;
}

export const RiskAssessmentView: React.FC<RiskAssessmentViewProps> = ({
  riskAssessment,
  riskLevel,
  hypothesisGroundednessStatus,
}) => {
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

  const getRiskIcon = (level: RemediationRiskLevel) => {
    switch (level) {
      case "low":
        return <ShieldCheck size={14} />;
      case "medium":
      case "high":
        return <AlertTriangle size={14} />;
      case "critical":
        return <ShieldAlert size={14} />;
    }
  };

  const scorePercentage = riskAssessment ? Math.round(riskAssessment.risk_score * 100) : 50;

  return (
    <div className="remediation-section-card" data-testid="risk-assessment-section">
      <div className="remediation-section-header">
        <h3>
          <ShieldAlert size={18} className="text-accent" />
          Deterministic Risk Assessment
        </h3>
        <span
          className={`badge ${getRiskBadgeClass(riskLevel)}`}
          aria-label={`Risk level: ${riskLevel}`}
          data-testid="risk-level-badge"
        >
          {getRiskIcon(riskLevel)}
          {riskLevel.toUpperCase()} RISK
        </span>
      </div>

      {/* Disclaimers & Safety Notice */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: "8px",
          padding: "10px 14px",
          borderRadius: "var(--radius-sm)",
          background: "var(--bg-secondary)",
          border: "1px solid var(--border-subtle)",
          fontSize: "0.8rem",
          color: "var(--text-muted)",
        }}
      >
        <Info size={15} style={{ flexShrink: 0, marginTop: "2px", color: "var(--accent-primary)" }} />
        <div>
          <strong>Advisory Risk Heuristic:</strong> This risk level is computed deterministically
          from action blast radius, destructive keywords, reversibility, and hypothesis grounding.
          It is an analytical assessment, not a guarantee of operational safety.
        </div>
      </div>

      {/* Metrics Matrix */}
      <div className="risk-grid">
        <div className="risk-metric-box">
          <span className="risk-metric-label">Composite Risk Score</span>
          <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
            <span className="risk-metric-value" data-testid="risk-score-value">
              {riskAssessment ? riskAssessment.risk_score.toFixed(2) : "0.50"}
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>/ 1.00</span>
          </div>
          <div
            style={{
              height: "6px",
              width: "100%",
              background: "var(--border-subtle)",
              borderRadius: "999px",
              overflow: "hidden",
              marginTop: "4px",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${scorePercentage}%`,
                background:
                  riskLevel === "critical"
                    ? "#dc2626"
                    : riskLevel === "high"
                    ? "#ea580c"
                    : riskLevel === "medium"
                    ? "#d97706"
                    : "#2563eb",
                transition: "width 0.3s ease",
              }}
            />
          </div>
        </div>

        <div className="risk-metric-box">
          <span className="risk-metric-label">Estimated Blast Radius</span>
          <span className="risk-metric-value" data-testid="blast-radius-value">
            <Layers size={14} style={{ display: "inline", marginRight: "6px" }} />
            {riskAssessment?.blast_radius || "Target Service"}
          </span>
        </div>

        <div className="risk-metric-box">
          <span className="risk-metric-label">Reversibility</span>
          <span className="risk-metric-value" data-testid="reversibility-value">
            <RotateCcw size={14} style={{ display: "inline", marginRight: "6px" }} />
            {riskAssessment?.reversibility_assessment || "Reversible with Rollback Plan"}
          </span>
        </div>

        <div className="risk-metric-box">
          <span className="risk-metric-label">Human Approval Mandate</span>
          <span className="risk-metric-value" style={{ color: "#059669" }}>
            {riskAssessment?.requires_human_approval !== false ? "Required" : "Optional"}
          </span>
        </div>
      </div>

      {/* Groundedness Alignment */}
      {hypothesisGroundednessStatus && (
        <div
          style={{
            fontSize: "0.82rem",
            padding: "8px 12px",
            background: "var(--bg-secondary)",
            borderRadius: "var(--radius-sm)",
            borderLeft: "3px solid var(--accent-primary)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span>
            <strong>Hypothesis Grounding:</strong> Remediation risk accounts for empirical evidence support.
          </span>
          <span className="badge badge-version">{hypothesisGroundednessStatus.replace("_", " ")}</span>
        </div>
      )}

      {/* Explainable Risk Factors */}
      <div>
        <h4 style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: "8px" }}>
          Explainable Risk Factors & Rationale:
        </h4>
        {riskAssessment?.risk_factors && riskAssessment.risk_factors.length > 0 ? (
          <div className="risk-factors-list" data-testid="risk-factors-list">
            {riskAssessment.risk_factors.map((factor, idx) => (
              <div key={idx} className="risk-factor-item">
                <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: "2px", color: "var(--warning-text)" }} />
                <span>{factor}</span>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>
            Standard operational action parameters without identified elevated risk factors.
          </p>
        )}
      </div>
    </div>
  );
};
