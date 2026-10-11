import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RiskAssessmentView } from "../components/remediation/RiskAssessmentView";
import { ActionStepsList } from "../components/remediation/ActionStepsList";
import { EvidenceProvenanceView } from "../components/remediation/EvidenceProvenanceView";
import { PolicyExplanationCard } from "../components/remediation/PolicyExplanationCard";
import { ApprovalWorkflowModal } from "../components/remediation/ApprovalWorkflowModal";
import { AuditTrailTimeline } from "../components/remediation/AuditTrailTimeline";
import { DryRunModal } from "../components/remediation/DryRunModal";
import { ProposalDetailView } from "../components/remediation/ProposalDetailView";
import { RemediationProposal, RiskAssessmentDetails } from "../types/remediation";
import { User } from "../types";
import { RemediationsApi } from "../api/remediations";

const mockRiskAssessment: RiskAssessmentDetails = {
  overall_risk_level: "high",
  risk_score: 0.75,
  risk_factors: [
    "Mutating restart action on core API server",
    "High incident severity (critical)",
  ],
  blast_radius: "Critical Ingress Gateway",
  reversibility_assessment: "Rollback via deploy history",
  requires_human_approval: true,
  execution_restricted: true,
  restrictions_note: "TracePilot actions are strictly advisory.",
};

const mockProposal: RemediationProposal = {
  id: "rem-123",
  incident_id: "inc-456",
  organization_id: "org-789",
  hypothesis_id: "hyp-999",
  title: "Rolling Restart of Gateway Service",
  description: "Recycles exhausted proxy workers to alleviate 504 timeouts.",
  status: "proposed",
  risk_level: "high",
  risk_assessment: mockRiskAssessment,
  actions: [
    {
      step_number: 1,
      action_type: "service_restart",
      description: "Perform graceful rolling restart of ingress pods",
      target_system: "ingress-gateway",
      command: "kubectl rollout restart deployment/ingress",
      parameters: { grace_period: 30 },
      risk_level: "high",
      reversible: true,
      requires_human_approval: true,
      is_executable: false,
    },
  ],
  is_executable: false,
  rollback_plan: "Cancel rollout and revert deployment image tag",
  estimated_impact: "Restores client ingress traffic within 60 seconds",
  created_by_user_id: "user-creator",
  version: 1,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const mockUserMember: User = {
  id: "user-member",
  email: "member@example.com",
  is_active: true,
};

const mockUserAdmin: User = {
  id: "user-admin",
  email: "admin@example.com",
  is_active: true,
};

const mockUserCreator: User = {
  id: "user-creator",
  email: "creator@example.com",
  is_active: true,
};

describe("Remediation Review & Approval UI (Milestone 5C)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe("Risk Assessment & Visual Hierarchy", () => {
    it("renders risk level badge, composite score, blast radius, and explainable factors", () => {
      render(
        <RiskAssessmentView
          riskAssessment={mockRiskAssessment}
          riskLevel="high"
          hypothesisGroundednessStatus="well_supported"
        />
      );

      expect(screen.getByTestId("risk-level-badge").textContent).toContain("HIGH RISK");
      expect(screen.getByTestId("risk-score-value").textContent).toContain("0.75");
      expect(screen.getByTestId("blast-radius-value").textContent).toContain("Critical Ingress Gateway");
      expect(screen.getByTestId("reversibility-value").textContent).toContain("Rollback via deploy history");
      expect(screen.getByTestId("risk-factors-list").textContent).toContain(
        "Mutating restart action on core API server"
      );
      // Explains heuristic nature
      expect(screen.getByText(/Advisory Risk Heuristic/i)).toBeTruthy();
    });
  });

  describe("Action Steps & Execution Safety Boundary", () => {
    it("renders action steps as strictly non-executable advisory specifications", () => {
      render(
        <ActionStepsList
          actions={mockProposal.actions}
          rollbackPlan={mockProposal.rollback_plan}
          estimatedImpact={mockProposal.estimated_impact}
        />
      );

      expect(screen.getByTestId("advisory-only-badge").textContent).toContain(
        "NON-EXECUTABLE SPECIFICATION"
      );
      expect(screen.getByText("READ ONLY ADVISORY")).toBeTruthy();
      expect(screen.getByText("kubectl rollout restart deployment/ingress")).toBeTruthy();
      expect(screen.getByText(/Execution Prohibited \(Advisory\)/i)).toBeTruthy();
      expect(screen.getByText("Rollback Plan")).toBeTruthy();

      // Ensure no execution button exists
      expect(screen.queryByRole("button", { name: /execute/i })).toBeNull();
    });
  });

  describe("Evidence Provenance & Telemetry Grounding", () => {
    it("renders linked hypothesis and telemetry events while distinguishing empirical facts", () => {
      const mockHypothesis = {
        id: "hyp-999",
        investigation_job_id: "job-1",
        incident_id: "inc-456",
        organization_id: "org-789",
        claim: "Upstream ingress proxy connection pool exhausted",
        rationale: "Corroborated by HTTP 504 errors in ingress access logs",
        confidence: "high" as const,
        confidence_note: "Directly corroborated",
        status: "supported" as const,
        created_at: new Date().toISOString(),
        supporting_evidence: [],
        contradicting_evidence: [],
        groundedness_status: "well_supported",
      };

      const mockEvidence = [
        {
          id: "ev-1",
          incident_id: "inc-456",
          organization_id: "org-789",
          source_type: "log",
          event_type: "http_gateway_timeout",
          event_timestamp: new Date().toISOString(),
          summary: "Upstream connection timed out after 30000ms",
          created_at: new Date().toISOString(),
        },
      ];

      render(
        <EvidenceProvenanceView
          hypothesis={mockHypothesis}
          evidenceEvents={mockEvidence}
          incidentId="inc-456"
        />
      );

      expect(screen.getByTestId("linked-hypothesis-card").textContent).toContain(
        "Upstream ingress proxy connection pool exhausted"
      );
      expect(screen.getByTestId("evidence-event-ev-1").textContent).toContain(
        "Upstream connection timed out after 30000ms"
      );
      expect(screen.getByText(/Empirical Fact Distinction/i)).toBeTruthy();
    });
  });

  describe("Policy Explanation & Separation of Duties", () => {
    it("blocks creator self-approval when current user is the proposal author", () => {
      render(
        <PolicyExplanationCard
          proposal={mockProposal}
          currentUser={mockUserCreator}
          currentUserRole="ADMIN"
        />
      );

      expect(screen.getByTestId("policy-eligibility-badge").textContent).toContain(
        "APPROVAL RESTRICTED"
      );
      expect(screen.getByText(/You created this proposal/i)).toBeTruthy();
    });

    it("restricts member approval on high-risk proposals requiring ADMIN or OWNER", () => {
      render(
        <PolicyExplanationCard
          proposal={mockProposal}
          currentUser={mockUserMember}
          currentUserRole="MEMBER"
        />
      );

      expect(screen.getByTestId("policy-eligibility-badge").textContent).toContain(
        "APPROVAL RESTRICTED"
      );
      expect(screen.getByText(/Your role is MEMBER — insufficient privilege/i)).toBeTruthy();
    });

    it("allows approval for authorized ADMIN peer who is not the creator", () => {
      render(
        <PolicyExplanationCard
          proposal={mockProposal}
          currentUser={mockUserAdmin}
          currentUserRole="ADMIN"
        />
      );

      expect(screen.getByTestId("policy-eligibility-badge").textContent).toContain(
        "ELIGIBLE FOR APPROVAL"
      );
      expect(screen.getByText(/Separation of duties satisfied/i)).toBeTruthy();
    });

    it("restricts approval when proposal is in terminal state", () => {
      const terminalProposal = { ...mockProposal, status: "rejected" as const };
      render(
        <PolicyExplanationCard
          proposal={terminalProposal}
          currentUser={mockUserAdmin}
          currentUserRole="ADMIN"
        />
      );

      expect(screen.getByTestId("policy-eligibility-badge").textContent).toContain(
        "APPROVAL RESTRICTED"
      );
      expect(screen.getByText(/currently in terminal state: rejected/i)).toBeTruthy();
    });
  });

  describe("Approval & Rejection Workflow Modal", () => {
    it("validates mandatory rejection rationale before allowing submission", async () => {
      render(
        <ApprovalWorkflowModal
          isOpen={true}
          decisionType="reject"
          proposal={mockProposal}
          reviewerRole="ADMIN"
          onClose={vi.fn()}
          onSuccess={vi.fn()}
          onConflictRefresh={vi.fn()}
        />
      );

      const confirmBtn = screen.getByTestId("confirm-decision-button") as HTMLButtonElement;
      expect(confirmBtn.disabled).toBe(true);

      const textarea = screen.getByTestId("decision-rationale-input");
      fireEvent.change(textarea, { target: { value: "Short" } });
      expect(confirmBtn.disabled).toBe(true);

      fireEvent.change(textarea, {
        target: { value: "Restarting ingress poses too high a blast radius during peak traffic." },
      });
      expect(confirmBtn.disabled).toBe(false);
    });

    it("submits approval with rationale and triggers success callback", async () => {
      const approveSpy = vi.spyOn(RemediationsApi, "approve").mockResolvedValue({
        id: "app-1",
        organization_id: "org-789",
        remediation_proposal_id: "rem-123",
        proposal_version: 1,
        reviewer_user_id: "user-admin",
        decision: "approved",
        rationale: "Approved after verifying traffic redirection readiness.",
        risk_level_at_decision: "high",
        policy_version: "1.0.0",
        snapshot: {},
        created_at: new Date().toISOString(),
      });

      const onSuccess = vi.fn();
      const onClose = vi.fn();

      render(
        <ApprovalWorkflowModal
          isOpen={true}
          decisionType="approve"
          proposal={mockProposal}
          reviewerRole="ADMIN"
          onClose={onClose}
          onSuccess={onSuccess}
          onConflictRefresh={vi.fn()}
        />
      );

      const textarea = screen.getByTestId("decision-rationale-input");
      fireEvent.change(textarea, {
        target: { value: "Approved after verifying traffic redirection readiness." },
      });

      const confirmBtn = screen.getByTestId("confirm-decision-button");
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(approveSpy).toHaveBeenCalledWith(
          "rem-123",
          "Approved after verifying traffic redirection readiness."
        );
        expect(onSuccess).toHaveBeenCalled();
        expect(onClose).toHaveBeenCalled();
      });
    });

    it("handles HTTP 409 conflict safely by alerting user and triggering state refresh without losing rationale", async () => {
      vi.spyOn(RemediationsApi, "approve").mockRejectedValue({
        code: "HTTP_409",
        message: "Proposal version has already been approved or rejected.",
      });

      const onConflictRefresh = vi.fn().mockResolvedValue(undefined);

      render(
        <ApprovalWorkflowModal
          isOpen={true}
          decisionType="approve"
          proposal={mockProposal}
          reviewerRole="ADMIN"
          onClose={vi.fn()}
          onSuccess={vi.fn()}
          onConflictRefresh={onConflictRefresh}
        />
      );

      const textarea = screen.getByTestId("decision-rationale-input") as HTMLTextAreaElement;
      fireEvent.change(textarea, {
        target: { value: "Verified healthy replicas before approving." },
      });

      const confirmBtn = screen.getByTestId("confirm-decision-button");
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(screen.getByTestId("conflict-error-banner")).toBeTruthy();
        expect(onConflictRefresh).toHaveBeenCalled();
        // Rationale preserved
        expect(textarea.value).toBe("Verified healthy replicas before approving.");
      });
    });
  });

  describe("Append-Only Audit Trail", () => {
    it("renders chronological audit events and displays empty state cleanly", () => {
      const mockEvents = [
        {
          id: "aud-1",
          organization_id: "org-789",
          remediation_proposal_id: "rem-123",
          event_type: "proposal_created",
          actor_user_id: "user-creator",
          actor_role: "member",
          proposal_version: 1,
          to_status: "proposed",
          created_at: new Date(Date.now() - 60000).toISOString(),
        },
        {
          id: "aud-2",
          organization_id: "org-789",
          remediation_proposal_id: "rem-123",
          event_type: "proposal_approved",
          actor_user_id: "user-admin",
          actor_role: "admin",
          proposal_version: 1,
          from_status: "proposed",
          to_status: "approved",
          details: { rationale: "Verified capacity headroom." },
          created_at: new Date().toISOString(),
        },
      ];

      render(
        <AuditTrailTimeline
          events={mockEvents}
          approvals={[]}
          isLoading={false}
          onRefresh={vi.fn()}
        />
      );

      expect(screen.getByTestId("audit-events-stream")).toBeTruthy();
      expect(screen.getByTestId("audit-event-aud-1").textContent).toContain("Proposal Created");
      expect(screen.getByTestId("audit-event-aud-2").textContent).toContain("Proposal Approved");
      expect(screen.getByText(/"Verified capacity headroom."/)).toBeTruthy();
    });

    it("renders empty audit state when no events exist", () => {
      render(
        <AuditTrailTimeline
          events={[]}
          approvals={[]}
          isLoading={false}
          onRefresh={vi.fn()}
        />
      );

      expect(screen.getByTestId("empty-audit-log").textContent).toContain(
        "No audit entries recorded for this remediation proposal yet."
      );
    });
  });

  describe("Local Policy Dry-Run Simulation", () => {
    it("executes local policy validation and renders pass status with disclaimer", async () => {
      vi.spyOn(RemediationsApi, "dryRunPolicy").mockResolvedValue({
        dry_run_type: "local_policy_validation",
        allowed: true,
        risk_level: "high",
        required_roles: ["admin", "owner"],
        separation_of_duties_passed: true,
        risk_assessment_valid: true,
        lifecycle_eligible: true,
        violations: [],
        policy_version: "v1",
        disclaimer: "Local policy simulation only. No infrastructure APIs contacted.",
      });

      render(
        <DryRunModal
          isOpen={true}
          remediationId="rem-123"
          onClose={vi.fn()}
        />
      );

      await waitFor(() => {
        const modal = screen.getByTestId("dry-run-modal");
        expect(modal.textContent).toContain("Policy Validation Passed");
        expect(modal.textContent).toContain("Local Policy Simulation Only");
        expect(modal.textContent).toContain("admin, owner");
      });
    });
  });

  describe("ProposalDetailView Master View & Strict Non-Execution", () => {
    it("renders safety banner and never exposes an execution button", async () => {
      vi.spyOn(RemediationsApi, "listAuditEvents").mockResolvedValue({ items: [], total: 0 });
      vi.spyOn(RemediationsApi, "listApprovals").mockResolvedValue({ items: [], total: 0 });

      render(
        <ProposalDetailView
          proposal={mockProposal}
          currentUser={mockUserAdmin}
          currentUserRole="ADMIN"
          onProposalUpdated={vi.fn()}
        />
      );

      await waitFor(() => {
        expect(screen.getByTestId("execution-safety-barrier-banner").textContent).toContain(
          "Safe Execution Barrier"
        );
      });
      expect(screen.queryByRole("button", { name: /execute remediation/i })).toBeNull();
      expect(screen.queryByRole("button", { name: /^execute$/i })).toBeNull();
    });
  });
});
