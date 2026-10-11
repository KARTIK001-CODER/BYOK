import React, { useState } from "react";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Lock,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import { RemediationProposal } from "../../types/remediation";
import { RemediationsApi } from "../../api/remediations";

interface ApprovalWorkflowModalProps {
  isOpen: boolean;
  decisionType: "approve" | "reject";
  proposal: RemediationProposal;
  reviewerRole?: string | null;
  onClose: () => void;
  onSuccess: () => void;
  onConflictRefresh: () => Promise<void>;
}

export const ApprovalWorkflowModal: React.FC<ApprovalWorkflowModalProps> = ({
  isOpen,
  decisionType,
  proposal,
  reviewerRole,
  onClose,
  onSuccess,
  onConflictRefresh,
}) => {
  const [rationale, setRationale] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isConflict, setIsConflict] = useState<boolean>(false);

  if (!isOpen) return null;

  const isApprove = decisionType === "approve";
  const minRationaleLength = isApprove ? 5 : 10;
  const isRationaleValid = rationale.trim().length >= minRationaleLength;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isRationaleValid || isSubmitting) return;

    setIsSubmitting(true);
    setErrorMessage(null);
    setIsConflict(false);

    try {
      if (isApprove) {
        await RemediationsApi.approve(proposal.id, rationale.trim());
      } else {
        await RemediationsApi.reject(proposal.id, rationale.trim());
      }
      onSuccess();
      onClose();
    } catch (err: unknown) {
      const errorObj = err as { code?: string; message?: string; details?: unknown };
      const statusText = errorObj.message || "An unexpected error occurred during submission.";
      
      // Check for HTTP 409 conflict
      if (errorObj.code === "HTTP_409" || (errorObj.message && errorObj.message.includes("409"))) {
        setIsConflict(true);
        setErrorMessage(
          "Proposal state or version conflict detected. Another decision may have been recorded concurrently or the proposal was modified. Refreshing authoritative server state..."
        );
        // Refresh authoritative proposal state while preserving rationale
        try {
          await onConflictRefresh();
        } catch {
          // ignore refresh error
        }
      } else if (errorObj.code === "HTTP_403" || (errorObj.message && errorObj.message.includes("403"))) {
        setErrorMessage(`Authorization Policy Violation: ${statusText}`);
      } else {
        setErrorMessage(statusText);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleManualConflictRefresh = async () => {
    setIsSubmitting(true);
    try {
      await onConflictRefresh();
      setIsConflict(false);
      setErrorMessage(null);
    } catch (err) {
      setErrorMessage("Failed to refresh proposal. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" data-testid="approval-workflow-modal">
      <div className="modal-content">
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            {isApprove ? (
              <CheckCircle2 size={20} color="#059669" />
            ) : (
              <XCircle size={20} color="#dc2626" />
            )}
            <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>
              {isApprove ? "Confirm Remediation Approval" : "Reject Remediation Proposal"}
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

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {/* Proposal Snapshot Bar */}
            <div
              style={{
                padding: "12px",
                background: "var(--bg-secondary)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
                display: "flex",
                flexDirection: "column",
                gap: "6px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>{proposal.title}</span>
                <span className="badge badge-version">v{proposal.version}</span>
              </div>
              <div style={{ display: "flex", gap: "8px", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                <span>Risk: <strong>{proposal.risk_level.toUpperCase()}</strong></span>
                <span>•</span>
                <span>Reviewer Role: <strong>{reviewerRole || "Member"}</strong></span>
              </div>
            </div>

            {/* Conflict Notification Banner */}
            {isConflict && (
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "8px",
                  padding: "10px 14px",
                  borderRadius: "var(--radius-md)",
                  background: "rgba(239, 68, 68, 0.1)",
                  border: "1px solid rgba(239, 68, 68, 0.3)",
                  color: "#dc2626",
                  fontSize: "0.82rem",
                }}
                data-testid="conflict-error-banner"
              >
                <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: "2px" }} />
                <div style={{ flex: 1 }}>
                  <span>{errorMessage}</span>
                  <div style={{ marginTop: "6px" }}>
                    <button
                      type="button"
                      onClick={handleManualConflictRefresh}
                      className="btn-secondary"
                      style={{ fontSize: "0.75rem", padding: "4px 8px" }}
                      disabled={isSubmitting}
                    >
                      <RefreshCw size={12} /> Sync Server State
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* General Error Banner */}
            {!isConflict && errorMessage && (
              <div
                style={{
                  padding: "10px 14px",
                  borderRadius: "var(--radius-md)",
                  background: "rgba(239, 68, 68, 0.1)",
                  border: "1px solid rgba(239, 68, 68, 0.3)",
                  color: "#dc2626",
                  fontSize: "0.82rem",
                }}
                data-testid="general-error-banner"
              >
                {errorMessage}
              </div>
            )}

            {/* Mandatory Rationale Input */}
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label
                htmlFor="decision-rationale"
                style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--text-primary)" }}
              >
                Decision Rationale {isApprove ? "(Mandatory)" : "(Required for Rejection)"}
              </label>
              <textarea
                id="decision-rationale"
                rows={4}
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                placeholder={
                  isApprove
                    ? "Document verification steps, operational justification, and rollback readiness..."
                    : "Detail why this remediation proposal was rejected (e.g., unacceptable blast radius, flawed hypothesis)..."
                }
                style={{
                  padding: "10px 12px",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border-subtle)",
                  background: "var(--bg-secondary)",
                  color: "var(--text-primary)",
                  fontSize: "0.85rem",
                  fontFamily: "inherit",
                  resize: "vertical",
                  outline: "none",
                }}
                disabled={isSubmitting}
                data-testid="decision-rationale-input"
              />
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "0.75rem",
                  color: "var(--text-muted)",
                }}
              >
                <span>Minimum {minRationaleLength} characters required</span>
                <span>{rationale.length} / 1000</span>
              </div>
            </div>

            {/* Immutable Audit & Execution Boundary Notice */}
            <div
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "8px",
                padding: "8px 12px",
                borderRadius: "var(--radius-sm)",
                background: "var(--bg-secondary)",
                fontSize: "0.78rem",
                color: "var(--text-muted)",
              }}
            >
              <Lock size={14} style={{ flexShrink: 0, marginTop: "2px", color: "var(--accent-primary)" }} />
              <div>
                <strong>Append-Only Audit Notice:</strong> This decision will be appended to the
                immutable audit log with your actor identity. Approval certifies policy compliance only;
                it does not trigger automated infrastructure execution.
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className={isApprove ? "btn-success" : "btn-danger"}
              disabled={!isRationaleValid || isSubmitting}
              data-testid="confirm-decision-button"
            >
              {isSubmitting ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Recording Decision...
                </>
              ) : isApprove ? (
                <>
                  <CheckCircle2 size={14} />
                  Authorize Approval
                </>
              ) : (
                <>
                  <XCircle size={14} />
                  Submit Rejection
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
