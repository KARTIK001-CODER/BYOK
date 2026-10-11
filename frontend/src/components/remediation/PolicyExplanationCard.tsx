import {
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Lock,
} from "lucide-react";
import { RemediationProposal } from "../../types/remediation";
import { User } from "../../types";

interface PolicyExplanationCardProps {
  proposal: RemediationProposal;
  currentUser: User | null;
  currentUserRole?: string | null;
}

export const PolicyExplanationCard: React.FC<PolicyExplanationCardProps> = ({
  proposal,
  currentUser,
  currentUserRole,
}) => {
  const isTerminal = ["rejected", "superseded", "cancelled", "expired"].includes(proposal.status);
  const isApproved = proposal.status === "approved";
  const isCreator = !!(currentUser && proposal.created_by_user_id && currentUser.id === proposal.created_by_user_id);
  
  const roleUpper = (currentUserRole || "MEMBER").toUpperCase();
  const isHighOrCritical = proposal.risk_level === "high" || proposal.risk_level === "critical";
  const hasRequiredRole = isHighOrCritical
    ? roleUpper === "ADMIN" || roleUpper === "OWNER"
    : ["MEMBER", "ADMIN", "OWNER"].includes(roleUpper);

  const hasValidRisk = !!(proposal.risk_assessment && proposal.risk_assessment.risk_score !== undefined);

  // Derive eligibility
  const canApprove = !isTerminal && !isApproved && !isCreator && hasRequiredRole && hasValidRisk;

  return (
    <div className="remediation-section-card" data-testid="policy-explanation-card">
      <div className="remediation-section-header">
        <h3>
          <Lock size={18} className="text-accent" />
          Approval Policy & Separation of Duties
        </h3>
        <span
          className={`badge ${canApprove ? "badge-status-approved" : "badge-status-draft"}`}
          data-testid="policy-eligibility-badge"
        >
          {canApprove ? "ELIGIBLE FOR APPROVAL" : isApproved ? "ALREADY APPROVED" : "APPROVAL RESTRICTED"}
        </span>
      </div>

      <div className="policy-card">
        {/* Rule 1: Tiered Role Hierarchy */}
        <div className="policy-rule-row">
          {hasRequiredRole ? (
            <CheckCircle2 size={16} className="policy-rule-pass" />
          ) : (
            <XCircle size={16} className="policy-rule-fail" />
          )}
          <div>
            <strong>Tiered Role Authorization: </strong>
            {isHighOrCritical ? (
              <span>
                High/Critical risk requires an authorized <strong>ADMIN</strong> or <strong>OWNER</strong>.
                {hasRequiredRole
                  ? ` (You are ${roleUpper})`
                  : ` (Your role is ${roleUpper} — insufficient privilege)`}
              </span>
            ) : (
              <span>
                Low/Medium risk requires any authorized organizational member.
                {hasRequiredRole ? ` (Satisfied as ${roleUpper})` : " (Membership required)"}
              </span>
            )}
          </div>
        </div>

        {/* Rule 2: Separation of Duties */}
        <div className="policy-rule-row">
          {!isCreator ? (
            <CheckCircle2 size={16} className="policy-rule-pass" />
          ) : (
            <XCircle size={16} className="policy-rule-fail" />
          )}
          <div>
            <strong>Separation of Duties: </strong>
            Proposal creator cannot approve their own proposal.
            {isCreator ? (
              <span className="policy-rule-fail" style={{ display: "block", fontSize: "0.8rem" }}>
                You created this proposal ({currentUser?.email}). Another authorized peer must review it.
              </span>
            ) : (
              <span> (Separation of duties satisfied)</span>
            )}
          </div>
        </div>

        {/* Rule 3: Lifecycle Eligibility */}
        <div className="policy-rule-row">
          {!isTerminal ? (
            <CheckCircle2 size={16} className="policy-rule-pass" />
          ) : (
            <XCircle size={16} className="policy-rule-fail" />
          )}
          <div>
            <strong>Proposal Lifecycle Eligibility: </strong>
            Terminal proposals (rejected, superseded, cancelled, expired) cannot be approved.
            {isTerminal ? (
              <span className="policy-rule-fail">
                {" "}
                (Proposal is currently in terminal state: {proposal.status})
              </span>
            ) : (
              <span> (Status '{proposal.status}' is eligible for review)</span>
            )}
          </div>
        </div>

        {/* Rule 4: Risk Freshness */}
        <div className="policy-rule-row">
          {hasValidRisk ? (
            <CheckCircle2 size={16} className="policy-rule-pass" />
          ) : (
            <XCircle size={16} className="policy-rule-fail" />
          )}
          <div>
            <strong>Risk Assessment Completeness: </strong>
            Proposal must carry an up-to-date deterministic risk assessment.
            {hasValidRisk ? (
              <span> (Risk assessed: {proposal.risk_level.toUpperCase()})</span>
            ) : (
              <span className="policy-rule-fail"> (Missing or stale risk assessment)</span>
            )}
          </div>
        </div>
      </div>

      {/* Advisory Notice */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          fontSize: "0.78rem",
          color: "var(--text-muted)",
        }}
      >
        <ShieldAlert size={14} color="var(--accent-primary)" />
        <span>
          Policy decisions are authoritatively verified server-side by the backend on submission.
        </span>
      </div>
    </div>
  );
};
