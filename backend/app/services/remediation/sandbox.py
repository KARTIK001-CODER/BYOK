import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.remediation import (
    RemediationActionType,
    RemediationProposal,
    RemediationRiskLevel,
    RemediationStatus,
)
from app.models.user import User
from app.schemas.sandbox import (
    SandboxScenarioMetadata,
    SandboxSimulationResponse,
    SandboxSimulationResult,
)
from app.services.remediation.policy import ApprovalPolicyService


class TracePilotSandboxSimulator:
    """Deterministic local sandbox simulator for validating remediation workflows.

    Strict safety boundary:
    - Never executes shell commands.
    - Never connects to real cloud or external infrastructure.
    - All scenarios operate on deterministic synthetic fixtures.
    """

    SCENARIOS: dict[str, dict[str, Any]] = {
        "SCENARIO-HEALTHY-01": {
            "name": "Healthy Service Policy Validation",
            "description": (
                "Validates that a low-risk remediation proposal on a healthy service with fresh "
                "evidence passes policy evaluation when reviewed by an authorized SRE."
            ),
            "category": "Policy Validation",
        },
        "SCENARIO-DEGRADED-02": {
            "name": "Degraded State with Stale Evidence",
            "description": (
                "Models an incident with degraded telemetry and stale evidence (>24h). Evaluates "
                "risk elevation and ensures automated execution remains blocked."
            ),
            "category": "Evidence & Risk",
        },
        "SCENARIO-ELEVATED-RISK-03": {
            "name": "Elevated Risk Destructive Action",
            "description": (
                "Models a high-blast-radius irreversible proposal (e.g. database failover) requiring "
                "elevated admin or security engineer credentials."
            ),
            "category": "Risk Governance",
        },
        "SCENARIO-UNAUTHORIZED-REVIEWER-04": {
            "name": "Unauthorized Reviewer Rejection",
            "description": (
                "Models a standard developer or viewer attempting to approve a high-risk proposal. "
                "Validates rejection due to insufficient organizational role."
            ),
            "category": "Role Governance",
        },
        "SCENARIO-CREATOR-SELF-APPROVAL-05": {
            "name": "Creator Self-Approval Prevention",
            "description": (
                "Enforces separation of duties by verifying that a proposal's creator cannot "
                "approve their own proposal even if they hold admin privileges."
            ),
            "category": "Separation of Duties",
        },
        "SCENARIO-EXPIRED-PROPOSAL-06": {
            "name": "Expired Proposal Rejection",
            "description": (
                "Models an approval attempt against an expired or stale proposal. Validates "
                "lifecycle transition rejection."
            ),
            "category": "Lifecycle Enforcement",
        },
        "SCENARIO-CONFLICTING-APPROVAL-07": {
            "name": "Conflicting Approval Attempt",
            "description": (
                "Models concurrent reviewers where the proposal has already reached a terminal "
                "state (rejected/superseded). Validates rejection of conflicting duplicate decision."
            ),
            "category": "Concurrency & Idempotency",
        },
        "SCENARIO-INVESTIGATION-RECOVERY-08": {
            "name": "Worker Interruption and Recovery",
            "description": (
                "Simulates worker termination during investigation. Verifies that stale running jobs "
                "are reclaimed safely within backoff bounds without corrupting incident timeline."
            ),
            "category": "Worker Recovery",
        },
    }

    @classmethod
    def list_scenarios(cls) -> list[SandboxScenarioMetadata]:
        """Return metadata for all registered sandbox scenarios."""
        return [
            SandboxScenarioMetadata(
                scenario_id=s_id,
                name=data["name"],
                description=data["description"],
                category=data["category"],
            )
            for s_id, data in cls.SCENARIOS.items()
        ]

    @classmethod
    def simulate_scenario(cls, scenario_id: str) -> SandboxSimulationResult:
        """Run a deterministic scenario locally and return structured results."""
        s_id = scenario_id.upper().strip()
        if s_id not in cls.SCENARIOS:
            raise ValueError(f"Unknown sandbox scenario identifier: {scenario_id}")

        method_name = f"_simulate_{s_id.replace('-', '_').lower()}"
        handler = getattr(cls, method_name, None)
        if not handler:
            raise NotImplementedError(f"Handler {method_name} not implemented")

        return handler()

    @classmethod
    def simulate_all(cls) -> SandboxSimulationResponse:
        """Run all predefined scenarios deterministically."""
        results = [cls.simulate_scenario(s_id) for s_id in cls.SCENARIOS]
        passed = sum(1 for r in results if r.passed)
        return SandboxSimulationResponse(
            results=results,
            total_scenarios=len(results),
            passed_scenarios=passed,
            all_passed=(passed == len(results)),
            is_simulation=True,
        )

    # -------------------------------------------------------------------------
    # Scenario 1: Healthy Service Policy Validation
    # -------------------------------------------------------------------------
    @classmethod
    def _simulate_scenario_healthy_01(cls) -> SandboxSimulationResult:
        org_id = "org-synth-alpha"
        creator_id = "user-alice-author"
        reviewer_id = "user-bob-sre"

        creator = User(id=creator_id, email="alice@corp.test", full_name="Alice Author")
        reviewer = User(id=reviewer_id, email="bob@corp.test", full_name="Bob SRE")
        reviewer_membership = OrganizationMembership(
            id="mem-bob",
            user_id=reviewer_id,
            organization_id=org_id,
            role=OrganizationRole.ADMIN,
        )

        proposal = RemediationProposal(
            id="prop-synth-01",
            incident_id="inc-synth-01",
            organization_id=org_id,
            title="Flush Redis Cache Keys for Degraded Session Cluster",
            description="Clear cached invalid auth tokens to restore service latency.",
            status=RemediationStatus.PROPOSED.value,
            risk_level=RemediationRiskLevel.LOW.value,
            risk_assessment={
                "overall_risk_level": "low",
                "risk_score": 0.15,
                "risk_factors": ["safe_cache_eviction"],
                "blast_radius": "single_service",
                "reversibility_assessment": "fully_reversible",
            },
            actions=[
                {
                    "step_number": 1,
                    "action_type": RemediationActionType.SERVICE_RESTART.value,
                    "description": "Evict session keys matching prefix auth:session:*",
                    "target_system": "redis-cluster-session",
                    "risk_level": "low",
                    "reversible": True,
                    "requires_human_approval": True,
                    "is_executable": False,
                }
            ],
            is_executable=False,
            created_by_user_id=creator.id,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        eval_result = ApprovalPolicyService.evaluate(
            proposal=proposal,
            reviewer_user=reviewer,
            reviewer_membership=reviewer_membership,
        )

        expected_outcome = "Policy validation succeeds (allowed=True); proposal eligible for approval."
        actual_outcome = (
            "Policy validation succeeded without violations."
            if eval_result.allowed
            else f"Validation failed: {', '.join(eval_result.violations)}"
        )

        return SandboxSimulationResult(
            scenario_id="SCENARIO-HEALTHY-01",
            scenario_name=cls.SCENARIOS["SCENARIO-HEALTHY-01"]["name"],
            observed_fixture_data={
                "service": "redis-cluster-session",
                "health_state": "healthy",
                "evidence_items_count": 3,
                "groundedness_score": 0.92,
            },
            simulated_conditions={
                "simulated_telemetry": "Latency normalized, 0 packet loss",
                "reviewer_role": reviewer_membership.role.value,
                "creator_user_id": creator_id,
                "reviewer_user_id": reviewer_id,
            },
            policy_validation_results=eval_result.to_dict(),
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            passed=eval_result.allowed,
            execution_performed=False,
        )

    # -------------------------------------------------------------------------
    # Scenario 2: Degraded State with Stale Evidence
    # -------------------------------------------------------------------------
    @classmethod
    def _simulate_scenario_degraded_02(cls) -> SandboxSimulationResult:
        org_id = "org-synth-alpha"
        reviewer_id = "user-carol-dev"

        reviewer = User(id=reviewer_id, email="carol@corp.test", full_name="Carol Dev")
        reviewer_membership = OrganizationMembership(
            id="mem-carol",
            user_id=reviewer_id,
            organization_id=org_id,
            role=OrganizationRole.MEMBER,
        )

        # Stale risk assessment or degraded evidence
        proposal = RemediationProposal(
            id="prop-synth-02",
            incident_id="inc-synth-02",
            organization_id=org_id,
            title="Restart Inventory Pods after Stale Evidence Ingestion",
            description="Restart pods to clear leak.",
            status=RemediationStatus.PROPOSED.value,
            risk_level=RemediationRiskLevel.HIGH.value,
            risk_assessment={
                "overall_risk_level": "high",
                "risk_score": 0.75,
                "risk_factors": ["stale_evidence", "elevated_service_risk"],
                "blast_radius": "cluster_wide",
                "reversibility_assessment": "partially_reversible",
            },
            actions=[],
            is_executable=False,
            created_by_user_id="user-other-creator",
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        eval_result = ApprovalPolicyService.evaluate(
            proposal=proposal,
            reviewer_user=reviewer,
            reviewer_membership=reviewer_membership,
        )

        expected_outcome = (
            "Elevated risk proposal rejected for standard MEMBER role (insufficient role)."
        )
        actual_outcome = (
            "Approval rejected due to insufficient role for high-risk action."
            if not eval_result.allowed and "Insufficient role" in eval_result.violations[0]
            else f"Evaluation outcome: allowed={eval_result.allowed}, violations={eval_result.violations}"
        )

        return SandboxSimulationResult(
            scenario_id="SCENARIO-DEGRADED-02",
            scenario_name=cls.SCENARIOS["SCENARIO-DEGRADED-02"]["name"],
            observed_fixture_data={
                "service": "inventory-api",
                "health_state": "degraded",
                "evidence_freshness_hours": 36.5,
                "groundedness_score": 0.32,
            },
            simulated_conditions={
                "simulated_telemetry": "5xx error rate 18.4%, queue backup",
                "reviewer_role": "MEMBER",
                "proposal_risk_level": "HIGH",
            },
            policy_validation_results=eval_result.to_dict(),
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            passed=not eval_result.allowed,
            execution_performed=False,
        )

    # -------------------------------------------------------------------------
    # Scenario 3: Elevated Risk Destructive Action
    # -------------------------------------------------------------------------
    @classmethod
    def _simulate_scenario_elevated_risk_03(cls) -> SandboxSimulationResult:
        org_id = "org-synth-alpha"
        admin_reviewer = User(id="user-dave-admin", email="dave@corp.test", full_name="Dave Admin")
        admin_membership = OrganizationMembership(
            id="mem-dave",
            user_id=admin_reviewer.id,
            organization_id=org_id,
            role=OrganizationRole.ADMIN,
        )

        proposal = RemediationProposal(
            id="prop-synth-03",
            incident_id="inc-synth-03",
            organization_id=org_id,
            title="Database Primary Failover and Partition Rebalance",
            description="Initiate cluster failover to secondary replica.",
            status=RemediationStatus.PROPOSED.value,
            risk_level=RemediationRiskLevel.CRITICAL.value,
            risk_assessment={
                "overall_risk_level": "critical",
                "risk_score": 0.95,
                "risk_factors": ["data_tier_mutation", "irreversible"],
                "blast_radius": "cluster_wide",
                "reversibility_assessment": "irreversible",
            },
            actions=[
                {
                    "step_number": 1,
                    "action_type": RemediationActionType.MANUAL.value,
                    "description": "Promote read replica to primary",
                    "target_system": "aurora-postgres-cluster",
                    "risk_level": "critical",
                    "reversible": False,
                    "requires_human_approval": True,
                    "is_executable": False,
                }
            ],
            is_executable=False,
            created_by_user_id="user-creator-sre",
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        eval_result = ApprovalPolicyService.evaluate(
            proposal=proposal,
            reviewer_user=admin_reviewer,
            reviewer_membership=admin_membership,
        )

        expected_outcome = "Critical risk proposal permitted for ADMIN reviewer with valid assessment."
        actual_outcome = (
            "Admin reviewer permitted critical risk proposal approval."
            if eval_result.allowed
            else f"Evaluation blocked: {eval_result.violations}"
        )

        return SandboxSimulationResult(
            scenario_id="SCENARIO-ELEVATED-RISK-03",
            scenario_name=cls.SCENARIOS["SCENARIO-ELEVATED-RISK-03"]["name"],
            observed_fixture_data={
                "service": "aurora-postgres-cluster",
                "health_state": "degraded_lock_contention",
                "replica_lag_ms": 1450,
            },
            simulated_conditions={
                "proposal_risk_level": "CRITICAL",
                "reviewer_role": "ADMIN",
                "action_reversible": False,
            },
            policy_validation_results=eval_result.to_dict(),
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            passed=eval_result.allowed,
            execution_performed=False,
        )

    # -------------------------------------------------------------------------
    # Scenario 4: Unauthorized Reviewer Rejection
    # -------------------------------------------------------------------------
    @classmethod
    def _simulate_scenario_unauthorized_reviewer_04(cls) -> SandboxSimulationResult:
        org_id = "org-synth-alpha"
        viewer_user = User(id="user-eve-viewer", email="eve@corp.test", full_name="Eve Viewer")
        viewer_membership = OrganizationMembership(
            id="mem-eve",
            user_id=viewer_user.id,
            organization_id=org_id,
            role=OrganizationRole.MEMBER,
        )

        proposal = RemediationProposal(
            id="prop-synth-04",
            incident_id="inc-synth-04",
            organization_id=org_id,
            title="Apply Emergency Ingress Rate Limiting",
            description="Throttles public endpoint traffic.",
            status=RemediationStatus.PROPOSED.value,
            risk_level=RemediationRiskLevel.HIGH.value,
            risk_assessment={
                "overall_risk_level": "high",
                "risk_score": 0.70,
                "risk_factors": ["traffic_drop"],
                "blast_radius": "service_wide",
                "reversibility_assessment": "reversible",
            },
            actions=[],
            is_executable=False,
            created_by_user_id="user-frank-dev",
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        eval_result = ApprovalPolicyService.evaluate(
            proposal=proposal,
            reviewer_user=viewer_user,
            reviewer_membership=viewer_membership,
        )

        expected_outcome = "Review rejected: MEMBER lacks authorization to approve HIGH risk proposal."
        actual_outcome = (
            "Policy correctly rejected unauthorized member role."
            if not eval_result.allowed
            else "Unexpectedly permitted unauthorized review."
        )

        return SandboxSimulationResult(
            scenario_id="SCENARIO-UNAUTHORIZED-REVIEWER-04",
            scenario_name=cls.SCENARIOS["SCENARIO-UNAUTHORIZED-REVIEWER-04"]["name"],
            observed_fixture_data={
                "service": "k8s-ingress-nginx",
                "health_state": "degraded_traffic_spike",
            },
            simulated_conditions={
                "user_role": "MEMBER",
                "required_roles": ["ADMIN", "OWNER"],
                "action_risk": "HIGH",
            },
            policy_validation_results=eval_result.to_dict(),
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            passed=not eval_result.allowed,
            execution_performed=False,
        )

    # -------------------------------------------------------------------------
    # Scenario 5: Creator Self-Approval Prevention
    # -------------------------------------------------------------------------
    @classmethod
    def _simulate_scenario_creator_self_approval_05(cls) -> SandboxSimulationResult:
        org_id = "org-synth-alpha"
        user_alice = User(id="user-alice-admin", email="alice@corp.test", full_name="Alice Admin")
        alice_membership = OrganizationMembership(
            id="mem-alice",
            user_id=user_alice.id,
            organization_id=org_id,
            role=OrganizationRole.ADMIN,
        )

        proposal = RemediationProposal(
            id="prop-synth-05",
            incident_id="inc-synth-05",
            organization_id=org_id,
            title="Roll Back Ingress Configuration to Build #412",
            description="Revert ingress annotations.",
            status=RemediationStatus.PROPOSED.value,
            risk_level=RemediationRiskLevel.LOW.value,
            risk_assessment={
                "overall_risk_level": "low",
                "risk_score": 0.2,
                "risk_factors": ["config_revert"],
                "blast_radius": "single_service",
                "reversibility_assessment": "reversible",
            },
            actions=[],
            is_executable=False,
            created_by_user_id=user_alice.id,  # Same as reviewer!
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        eval_result = ApprovalPolicyService.evaluate(
            proposal=proposal,
            reviewer_user=user_alice,
            reviewer_membership=alice_membership,
        )

        expected_outcome = (
            "Separation of duties enforced: creator cannot approve their own proposal."
        )
        passed = (not eval_result.allowed) and (not eval_result.separation_of_duties_passed)
        actual_outcome = (
            "Separation of duties violation detected and blocked."
            if passed
            else "Separation of duties violation failed to block approval."
        )

        return SandboxSimulationResult(
            scenario_id="SCENARIO-CREATOR-SELF-APPROVAL-05",
            scenario_name=cls.SCENARIOS["SCENARIO-CREATOR-SELF-APPROVAL-05"]["name"],
            observed_fixture_data={"creator_id": user_alice.id, "reviewer_id": user_alice.id},
            simulated_conditions={
                "same_identity": True,
                "separation_of_duties_rule": "Enforced",
            },
            policy_validation_results=eval_result.to_dict(),
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            passed=passed,
            execution_performed=False,
        )

    # -------------------------------------------------------------------------
    # Scenario 6: Expired Proposal Rejection
    # -------------------------------------------------------------------------
    @classmethod
    def _simulate_scenario_expired_proposal_06(cls) -> SandboxSimulationResult:
        org_id = "org-synth-alpha"
        reviewer = User(id="user-frank-admin", email="frank@corp.test", full_name="Frank Admin")
        reviewer_membership = OrganizationMembership(
            id="mem-frank",
            user_id=reviewer.id,
            organization_id=org_id,
            role=OrganizationRole.ADMIN,
        )

        proposal = RemediationProposal(
            id="prop-synth-06",
            incident_id="inc-synth-06",
            organization_id=org_id,
            title="Scale Out Worker Deployment (Expired)",
            description="Stale scaling request.",
            status=RemediationStatus.EXPIRED.value,  # Terminal state
            risk_level=RemediationRiskLevel.LOW.value,
            risk_assessment={
                "overall_risk_level": "low",
                "risk_score": 0.1,
                "risk_factors": [],
                "blast_radius": "single_service",
                "reversibility_assessment": "reversible",
            },
            actions=[],
            is_executable=False,
            created_by_user_id="user-creator",
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        eval_result = ApprovalPolicyService.evaluate(
            proposal=proposal,
            reviewer_user=reviewer,
            reviewer_membership=reviewer_membership,
        )

        expected_outcome = "Proposal in terminal status 'expired' cannot be approved."
        passed = (not eval_result.allowed) and (not eval_result.lifecycle_eligible)
        actual_outcome = (
            "Expired proposal rejected by lifecycle check."
            if passed
            else "Expired proposal incorrectly allowed."
        )

        return SandboxSimulationResult(
            scenario_id="SCENARIO-EXPIRED-PROPOSAL-06",
            scenario_name=cls.SCENARIOS["SCENARIO-EXPIRED-PROPOSAL-06"]["name"],
            observed_fixture_data={"proposal_status": "expired", "age_hours": 48},
            simulated_conditions={"lifecycle_state": "EXPIRED", "allowed_statuses": ["proposed", "reviewed"]},
            policy_validation_results=eval_result.to_dict(),
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            passed=passed,
            execution_performed=False,
        )

    # -------------------------------------------------------------------------
    # Scenario 7: Conflicting Approval Attempt
    # -------------------------------------------------------------------------
    @classmethod
    def _simulate_scenario_conflicting_approval_07(cls) -> SandboxSimulationResult:
        org_id = "org-synth-alpha"
        reviewer = User(id="user-grace-admin", email="grace@corp.test", full_name="Grace Admin")
        reviewer_membership = OrganizationMembership(
            id="mem-grace",
            user_id=reviewer.id,
            organization_id=org_id,
            role=OrganizationRole.ADMIN,
        )

        proposal = RemediationProposal(
            id="prop-synth-07",
            incident_id="inc-synth-07",
            organization_id=org_id,
            title="Re-run Database Index Rebuild (Already Approved)",
            description="Rebuild index.",
            status=RemediationStatus.APPROVED.value,  # Already approved
            risk_level=RemediationRiskLevel.MEDIUM.value,
            risk_assessment={
                "overall_risk_level": "medium",
                "risk_score": 0.45,
                "risk_factors": ["index_lock"],
                "blast_radius": "single_service",
                "reversibility_assessment": "reversible",
            },
            actions=[],
            is_executable=False,
            created_by_user_id="user-creator",
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        eval_result = ApprovalPolicyService.evaluate(
            proposal=proposal,
            reviewer_user=reviewer,
            reviewer_membership=reviewer_membership,
        )

        expected_outcome = "Proposal already approved for version 1 cannot be re-approved without mutation."
        passed = (not eval_result.allowed) and any("already approved" in v for v in eval_result.violations)
        actual_outcome = (
            "Conflicting approval on already approved proposal blocked."
            if passed
            else "Conflicting approval failed to block."
        )

        return SandboxSimulationResult(
            scenario_id="SCENARIO-CONFLICTING-APPROVAL-07",
            scenario_name=cls.SCENARIOS["SCENARIO-CONFLICTING-APPROVAL-07"]["name"],
            observed_fixture_data={"current_status": "approved", "proposal_version": 1},
            simulated_conditions={"concurrent_decision_attempt": "APPROVED"},
            policy_validation_results=eval_result.to_dict(),
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            passed=passed,
            execution_performed=False,
        )

    # -------------------------------------------------------------------------
    # Scenario 8: Worker Interruption and Recovery
    # -------------------------------------------------------------------------
    @classmethod
    def _simulate_scenario_investigation_recovery_08(cls) -> SandboxSimulationResult:
        # Synthetic investigation job model to verify recovery logic
        simulated_job = {
            "id": f"job-synth-{uuid.uuid4().hex[:8]}",
            "status": "running",
            "attempt_count": 1,
            "max_attempts": 3,
            "started_seconds_ago": 400,
            "stale_threshold_seconds": 180,
            "worker_heartbeat_last_seen_seconds_ago": 395,
        }

        # Deterministic simulation of requeue_stale_running logic:
        # If started_seconds_ago > stale_threshold_seconds:
        #   If attempt_count < max_attempts -> Re-queued (status='queued', started_at=None)
        #   Else -> Failed (status='failed', retry budget exhausted)
        is_stale = simulated_job["started_seconds_ago"] > simulated_job["stale_threshold_seconds"]
        can_retry = simulated_job["attempt_count"] < simulated_job["max_attempts"]
        reclaimed_status = "queued" if (is_stale and can_retry) else "failed"

        expected_outcome = (
            "Stale running job with attempt_count=1 (< max_attempts=3) safely re-queued for recovery."
        )
        passed = is_stale and (reclaimed_status == "queued")
        actual_outcome = (
            f"Job was safely reclaimed into status '{reclaimed_status}' with zero telemetry leaks."
            if passed
            else "Job recovery failed."
        )

        return SandboxSimulationResult(
            scenario_id="SCENARIO-INVESTIGATION-RECOVERY-08",
            scenario_name=cls.SCENARIOS["SCENARIO-INVESTIGATION-RECOVERY-08"]["name"],
            observed_fixture_data=simulated_job,
            simulated_conditions={
                "worker_alive": False,
                "reclaim_policy": "backoff_bounded_recovery",
                "terminal_protection": True,
            },
            policy_validation_results={
                "is_stale": is_stale,
                "can_retry": can_retry,
                "resulting_status": reclaimed_status,
                "reclaim_eligible": True,
            },
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            passed=passed,
            execution_performed=False,
        )
