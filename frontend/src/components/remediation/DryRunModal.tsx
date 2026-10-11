import React, { useState, useEffect } from "react";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  ShieldCheck,
  Info,
  X,
  Clock,
} from "lucide-react";
import { RemediationDryRunResponse } from "../../types/remediation";
import { RemediationsApi } from "../../api/remediations";

interface DryRunModalProps {
  isOpen: boolean;
  remediationId: string;
  onClose: () => void;
}

export const DryRunModal: React.FC<DryRunModalProps> = ({
  isOpen,
  remediationId,
  onClose,
}) => {
  const [result, setResult] = useState<RemediationDryRunResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [evaluatedAt, setEvaluatedAt] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && remediationId) {
      setIsLoading(true);
      setError(null);
      RemediationsApi.dryRunPolicy(remediationId)
        .then((res) => {
          setResult(res);
          setEvaluatedAt(new Date().toISOString());
        })
        .catch((err) => {
          setError(err?.message || "Failed to execute local policy dry run.");
        })
        .finally(() => {
          setIsLoading(false);
        });
    }
  }, [isOpen, remediationId]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" data-testid="dry-run-modal">
      <div className="modal-content">
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <ShieldCheck size={20} className="text-accent" />
            <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>
              Local Policy Dry-Run Validation
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: "var(--text-muted)",
            }}
            aria-label="Close modal"
          >
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          {/* Explicit Non-Execution Disclaimer */}
          <div
            style={{
              padding: "10px 14px",
              borderRadius: "var(--radius-sm)",
              background: "rgba(59, 130, 246, 0.08)",
              border: "1px solid rgba(59, 130, 246, 0.25)",
              color: "#1d4ed8",
              fontSize: "0.8rem",
              display: "flex",
              alignItems: "flex-start",
              gap: "8px",
            }}
          >
            <Info size={16} style={{ flexShrink: 0, marginTop: "2px" }} />
            <div>
              <strong>Local Policy Simulation Only:</strong> {result?.disclaimer || (
                "This validates the proposal schema and organizational approval policy requirements. " +
                "No shell commands, cloud APIs, Kubernetes clusters, or external infrastructure are touched."
              )}
            </div>
          </div>

          {isLoading ? (
            <div style={{ padding: "30px", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: "10px" }}>
              <Loader2 size={24} className="animate-spin text-accent" />
              <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                Evaluating proposal schema, separation of duties, and role requirements...
              </span>
            </div>
          ) : error ? (
            <div
              style={{
                padding: "12px",
                borderRadius: "var(--radius-sm)",
                background: "rgba(239, 68, 68, 0.1)",
                color: "#dc2626",
                fontSize: "0.85rem",
              }}
            >
              {error}
            </div>
          ) : result ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {/* Overall Decision Status */}
              <div
                style={{
                  padding: "16px",
                  borderRadius: "var(--radius-md)",
                  border: `1px solid ${result.allowed ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
                  background: result.allowed ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.08)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
                data-testid="dry-run-verdict"
              >
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  {result.allowed ? (
                    <CheckCircle2 size={24} color="#059669" />
                  ) : (
                    <XCircle size={24} color="#dc2626" />
                  )}
                  <div>
                    <h4 style={{ fontSize: "0.95rem", fontWeight: 700, color: result.allowed ? "#059669" : "#dc2626" }}>
                      {result.allowed ? "Policy Validation Passed" : "Policy Validation Blocked"}
                    </h4>
                    <p style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                      {result.allowed
                        ? "Proposal satisfies all separation-of-duties and role preconditions for review."
                        : "One or more policy rules prevent approval in the current state."}
                    </p>
                  </div>
                </div>

                <span className="badge badge-version">Policy {result.policy_version}</span>
              </div>

              {/* Checks Matrix */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "10px",
                  background: "var(--bg-secondary)",
                  padding: "14px",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border-subtle)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "0.83rem" }}>
                  <span>Separation of Duties (Non-creator check):</span>
                  <span style={{ fontWeight: 600, color: result.separation_of_duties_passed ? "#059669" : "#dc2626" }}>
                    {result.separation_of_duties_passed ? "PASSED" : "FAILED"}
                  </span>
                </div>

                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "0.83rem" }}>
                  <span>Deterministic Risk Assessment Valid:</span>
                  <span style={{ fontWeight: 600, color: result.risk_assessment_valid ? "#059669" : "#dc2626" }}>
                    {result.risk_assessment_valid ? "VALID" : "INVALID / STALE"}
                  </span>
                </div>

                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "0.83rem" }}>
                  <span>Lifecycle State Eligible:</span>
                  <span style={{ fontWeight: 600, color: result.lifecycle_eligible ? "#059669" : "#dc2626" }}>
                    {result.lifecycle_eligible ? "ELIGIBLE" : "TERMINAL / LOCKED"}
                  </span>
                </div>

                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "0.83rem" }}>
                  <span>Required Reviewer Roles:</span>
                  <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                    {result.required_roles.join(", ")}
                  </span>
                </div>
              </div>

              {/* Violations List if any */}
              {result.violations.length > 0 && (
                <div>
                  <h5 style={{ fontSize: "0.82rem", fontWeight: 700, color: "#dc2626", marginBottom: "6px" }}>
                    Violations & Deficiencies ({result.violations.length}):
                  </h5>
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    {result.violations.map((violation, i) => (
                      <div
                        key={i}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "8px",
                          padding: "8px 10px",
                          borderRadius: "var(--radius-sm)",
                          background: "rgba(239, 68, 68, 0.08)",
                          color: "#dc2626",
                          fontSize: "0.8rem",
                        }}
                      >
                        <AlertTriangle size={13} style={{ flexShrink: 0 }} />
                        <span>{violation}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Timestamp */}
              {evaluatedAt && (
                <div style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                  <Clock size={11} />
                  Evaluated at: {new Date(evaluatedAt).toLocaleString()}
                </div>
              )}
            </div>
          ) : null}
        </div>

        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn-secondary">
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
