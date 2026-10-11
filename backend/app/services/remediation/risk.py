import re
from typing import Any

from app.models.investigation import GroundednessStatus, RootCauseHypothesis, SystemConfidenceLevel
from app.models.remediation import RemediationActionType, RemediationRiskLevel
from app.schemas.remediations import RemediationActionItem, RiskAssessmentDetails

_CRITICAL_KEYWORDS = re.compile(
    r"\b(delete|drop|truncate|rm\s+-rf|mkfs|drain|kill|terminate|shutdown)\b",
    re.IGNORECASE,
)
_MUTATING_KEYWORDS = re.compile(
    r"\b(restart|reboot|rollback|deploy|scale|apply|patch|kubectl|helm|terraform)\b",
    re.IGNORECASE,
)
_BROAD_BLAST_RADIUS_TARGETS = {
    "database",
    "db",
    "postgres",
    "rds",
    "redis",
    "gateway",
    "ingress",
    "auth",
    "iam",
    "vpc",
    "network",
    "cluster",
    "core",
    "router",
}


class RiskEvaluator:
    """Deterministic, explainable risk assessment engine for remediation proposals."""

    @classmethod
    def evaluate(
        cls,
        actions: list[RemediationActionItem | dict[str, Any]],
        target_incident_severity: str | None = None,
        hypothesis: RootCauseHypothesis | None = None,
    ) -> RiskAssessmentDetails:
        _ = target_incident_severity
        if not actions:
            return RiskAssessmentDetails(
                overall_risk_level=RemediationRiskLevel.LOW,
                risk_score=0.10,
                risk_factors=["No mutating actions specified in proposal."],
                blast_radius="none",
                reversibility_assessment="Fully reversible; no operations proposed.",
                groundedness_alignment="No operational risk.",
                requires_human_approval=False,
                execution_restricted=True,
            )

        base_scores: list[float] = []
        factors: list[str] = []
        has_irreversible = False
        broad_targets_found: set[str] = set()

        for idx, act in enumerate(actions):
            if isinstance(act, dict):
                act_type = act.get("action_type", RemediationActionType.MANUAL.value)
                desc = act.get("description", "")
                cmd = act.get("command", "") or ""
                target = act.get("target_system", "").lower()
                rev = act.get("reversible", True)
            else:
                act_type = act.action_type.value if hasattr(act.action_type, "value") else str(act.action_type)
                desc = act.description
                cmd = act.command or ""
                target = act.target_system.lower()
                rev = act.reversible

            text_corpus = f"{desc} {cmd} {target}".lower()

            # Action type baseline
            if act_type == RemediationActionType.MANUAL.value:
                score = 0.20
            elif act_type == RemediationActionType.CONFIG_CHANGE.value:
                score = 0.35
            elif act_type == RemediationActionType.SCALE.value:
                score = 0.40
            elif act_type == RemediationActionType.SERVICE_RESTART.value:
                score = 0.50
            elif act_type == RemediationActionType.ROLLBACK.value:
                score = 0.60
            elif act_type == RemediationActionType.DEPENDENCY_UPDATE.value:
                score = 0.65
            elif act_type == RemediationActionType.FIREWALL_RULE.value:
                score = 0.70
            else:
                score = 0.35

            # Destructive keyword detection
            if _CRITICAL_KEYWORDS.search(text_corpus):
                score = max(score, 0.85)
                factors.append(
                    f"Action #{idx + 1} contains high-impact or destructive keywords ({cmd or desc})."
                )
            elif _MUTATING_KEYWORDS.search(text_corpus):
                score = max(score, 0.55)

            # Reversibility
            if not rev:
                has_irreversible = True
                score = min(1.0, score + 0.20)

            # Target system blast radius check
            if any(bt in target for bt in _BROAD_BLAST_RADIUS_TARGETS):
                broad_targets_found.add(target)
                score = min(1.0, score + 0.15)

            base_scores.append(score)

        composite_score = sum(base_scores) / len(base_scores)

        # Multi-action compounding
        if len(actions) > 3:
            composite_score = min(1.0, composite_score + 0.10)
            factors.append(
                f"Multi-step complexity: proposal comprises {len(actions)} distinct actions."
            )

        # Reversibility factor
        if has_irreversible:
            factors.append(
                "Proposal contains one or more irreversible actions requiring manual rollback."
            )
            reversibility_assessment = "Partially irreversible; requires explicit contingency."
        else:
            reversibility_assessment = "Reversible; actions can be undone with standard procedure."

        # Blast radius
        if broad_targets_found:
            blast_radius = f"Broad: touches critical infrastructure ({', '.join(sorted(broad_targets_found))})."
            factors.append(blast_radius)
        elif len(actions) > 1:
            blast_radius = "Multiple targeted services."
        else:
            blast_radius = "Single isolated service component."

        # Groundedness & Confidence Alignment
        groundedness_note = "Proposal evaluated independently of root cause hypothesis."
        if hypothesis is not None:
            g_score = hypothesis.groundedness_score
            g_status = hypothesis.groundedness_status
            s_conf = hypothesis.system_confidence

            if g_score is not None and g_score < 0.50:
                composite_score = min(1.0, composite_score + 0.20)
                factors.append(
                    f"Weak evidence grounding: linked hypothesis score is {g_score:.2f} (< 0.50); "
                    "remediation risk is elevated as it may address the wrong underlying cause."
                )
                groundedness_note = f"Elevated risk: hypothesis evidence score is {g_score:.2f}."
            elif g_status in (
                GroundednessStatus.CONTESTED.value,
                GroundednessStatus.REJECTED.value,
                GroundednessStatus.WEAKLY_SUPPORTED.value,
            ):
                composite_score = min(1.0, composite_score + 0.25)
                factors.append(
                    f"Linked hypothesis status is {g_status}; potential risk of misdirected mitigation."
                )
                groundedness_note = f"Elevated risk: hypothesis is {g_status}."
            elif s_conf == SystemConfidenceLevel.LOW.value:
                composite_score = min(1.0, composite_score + 0.15)
                factors.append("Linked hypothesis has LOW system confidence.")
                groundedness_note = "Elevated risk: low system confidence."
            else:
                groundedness_note = (
                    f"Aligned: supported hypothesis (groundedness={g_score or 1.0:.2f}, status={g_status or 'supported'})."
                )

        composite_score = max(0.05, min(0.99, round(composite_score, 2)))

        # Assign risk level
        if composite_score >= 0.80:
            level = RemediationRiskLevel.CRITICAL
        elif composite_score >= 0.60:
            level = RemediationRiskLevel.HIGH
        elif composite_score >= 0.35:
            level = RemediationRiskLevel.MEDIUM
        else:
            level = RemediationRiskLevel.LOW

        if not factors:
            factors.append("Standard operational mitigation with bounded impact.")

        return RiskAssessmentDetails(
            overall_risk_level=level,
            risk_score=composite_score,
            risk_factors=factors,
            blast_radius=blast_radius,
            reversibility_assessment=reversibility_assessment,
            groundedness_alignment=groundedness_note,
            requires_human_approval=True,
            execution_restricted=True,
            restrictions_note=(
                "TracePilot action proposals are strictly advisory and non-executable. "
                "Automated or unattended execution is restricted."
            ),
        )
