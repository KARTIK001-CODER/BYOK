import React from "react";
import {
  Terminal,
  Server,
  RotateCcw,
  UserCheck,
  CheckCircle2,
  AlertOctagon,
} from "lucide-react";
import { RemediationActionItem } from "../../types/remediation";

interface ActionStepsListProps {
  actions: RemediationActionItem[];
  rollbackPlan?: string | null;
  estimatedImpact?: string | null;
}

export const ActionStepsList: React.FC<ActionStepsListProps> = ({
  actions,
  rollbackPlan,
  estimatedImpact,
}) => {
  return (
    <div className="remediation-section-card" data-testid="action-steps-section">
      <div className="remediation-section-header">
        <h3>
          <Terminal size={18} className="text-accent" />
          Proposed Remediation Steps ({actions.length})
        </h3>
        <span
          className="badge"
          style={{
            background: "rgba(239, 68, 68, 0.1)",
            color: "#dc2626",
            border: "1px solid rgba(239, 68, 68, 0.25)",
          }}
          data-testid="advisory-only-badge"
        >
          <AlertOctagon size={12} />
          NON-EXECUTABLE SPECIFICATION
        </span>
      </div>

      {actions.length === 0 ? (
        <div style={{ padding: "20px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
          No specific action steps configured for this proposal.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {actions.map((act) => (
            <div key={act.step_number} className="action-step-item" data-testid={`action-step-${act.step_number}`}>
              <div className="action-step-header">
                <div className="action-step-num">
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: "22px",
                      height: "22px",
                      borderRadius: "50%",
                      background: "var(--accent-primary)",
                      color: "white",
                      fontSize: "0.75rem",
                      fontWeight: 700,
                    }}
                  >
                    {act.step_number}
                  </span>
                  <span>{act.description}</span>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className="badge badge-version" title="Target System">
                    <Server size={11} /> {act.target_system}
                  </span>
                  <span className="badge badge-version" style={{ textTransform: "uppercase" }}>
                    {act.action_type.replace("_", " ")}
                  </span>
                </div>
              </div>

              {/* Command or payload block */}
              {act.command && (
                <div className="action-code-block">
                  <span className="action-code-badge">READ ONLY ADVISORY</span>
                  <code>{act.command}</code>
                </div>
              )}

              {act.parameters && Object.keys(act.parameters).length > 0 && (
                <div
                  style={{
                    fontSize: "0.78rem",
                    color: "var(--text-muted)",
                    background: "var(--bg-surface)",
                    padding: "8px 12px",
                    borderRadius: "var(--radius-sm)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  Parameters: {JSON.stringify(act.parameters)}
                </div>
              )}

              {/* Guarantees and constraints */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "14px",
                  fontSize: "0.76rem",
                  color: "var(--text-muted)",
                  paddingTop: "4px",
                  borderTop: "1px dashed var(--border-subtle)",
                }}
              >
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                  <UserCheck size={12} color="#059669" />
                  Requires Human Review
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                  <RotateCcw size={12} color={act.reversible ? "#059669" : "#dc2626"} />
                  {act.reversible ? "Reversible" : "Non-Reversible Action"}
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", color: "#dc2626" }}>
                  <AlertOctagon size={12} />
                  Execution Prohibited (Advisory)
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Rollback & Impact Plan */}
      {(rollbackPlan || estimatedImpact) && (
        <div
          style={{
            marginTop: "10px",
            display: "grid",
            gridTemplateColumns: rollbackPlan && estimatedImpact ? "1fr 1fr" : "1fr",
            gap: "12px",
          }}
        >
          {rollbackPlan && (
            <div
              style={{
                padding: "12px 14px",
                borderRadius: "var(--radius-md)",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <h5
                style={{
                  fontSize: "0.78rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  color: "var(--text-muted)",
                  marginBottom: "4px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <RotateCcw size={13} color="var(--accent-primary)" /> Rollback Plan
              </h5>
              <p style={{ fontSize: "0.83rem", color: "var(--text-secondary)" }}>{rollbackPlan}</p>
            </div>
          )}

          {estimatedImpact && (
            <div
              style={{
                padding: "12px 14px",
                borderRadius: "var(--radius-md)",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <h5
                style={{
                  fontSize: "0.78rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  color: "var(--text-muted)",
                  marginBottom: "4px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <CheckCircle2 size={13} color="#059669" /> Expected Operational Impact
              </h5>
              <p style={{ fontSize: "0.83rem", color: "var(--text-secondary)" }}>{estimatedImpact}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
