"""Investigation execution engine: retrieve -> generate -> validate -> persist.

Runs against an already-claimed (running) job. All failures funnel through
safe error categories — raw tracebacks, provider keys, and model payloads are
logged server-side only and never persisted to client-visible fields.
"""

import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictException
from app.models.investigation import (
    HypothesisStatus,
    InvestigationErrorCategory,
    InvestigationJob,
    InvestigationStatus,
)
from app.schemas.investigations import LLMInvestigationOutput, LLMNextStep
from app.services.incidents.service import IncidentService
from app.services.investigations.prompts import (
    build_investigation_prompt,
    build_user_query,
)
from app.services.investigations.retrieval import InvestigationRetrievalService
from app.services.investigations.service import InvestigationService
from app.services.llm.base import LLMMessage, LLMRequest
from app.services.llm.errors import LLMErrorCode, LLMException
from app.services.llm.factory import LLMProviderFactory

logger = logging.getLogger("app.services.investigations.engine")

_SAFE_ERROR_SUMMARIES = {
    InvestigationErrorCategory.PROVIDER_UNAVAILABLE: "AI provider is unavailable; no hypotheses were generated.",
    InvestigationErrorCategory.PROVIDER_TIMEOUT: "AI provider timed out; no hypotheses were generated.",
    InvestigationErrorCategory.PROVIDER_RATE_LIMITED: "AI provider rate limit reached; try again later.",
    InvestigationErrorCategory.INVALID_PROVIDER_OUTPUT: "AI provider returned unusable output; no hypotheses were generated.",
    InvestigationErrorCategory.CITATION_VALIDATION_FAILED: "AI output cited unknown evidence; unsafe hypotheses were rejected.",
    InvestigationErrorCategory.INTERNAL_ERROR: "Investigation failed due to an internal error.",
}

_MAX_HYPOTHESES_FALLBACK = 5

# Next-step actions matching these (case-insensitive, word-boundary) are
# mutating/remediation-adjacent. The model must never be able to mark them as
# safe-to-run-without-approval: the flag is forced to True server-side.
# Diagnostic, read-only steps are unaffected.
_RISKY_ACTION_PATTERNS = (
    r"\bdelete\b",
    r"\bdrop\b",
    r"\btruncate\b",
    r"\brestart\b",
    r"\breboot\b",
    r"\bshutdown\b",
    r"\broll\s?back\b",
    r"\bdeploy\b",
    r"\bscale\b",
    r"\bkill\b",
    r"\bterminate\b",
    r"\bkubectl\b",
    r"\bhelm\b",
    r"\bterraform\b",
    r"\bansible\b",
    r"\brm\s+-rf?\b",
    r"\bmkfs\b",
    r"\bfailover\b",
    r"\bdrain\b",
    r"\bexec\b",
)
_RISKY_ACTION_RE = re.compile("|".join(_RISKY_ACTION_PATTERNS), re.IGNORECASE)


def _strip_code_fences(content: str) -> str:
    text = content.strip()
    # Tolerate ```json ... ``` on one line, multi-line fences, and a missing
    # closing fence. Anything else is left for the JSON parser to reject.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    return text


def _map_llm_error(exc: LLMException) -> str:
    code = str(exc.code)
    if code == LLMErrorCode.LLM_TIMEOUT.value:
        return InvestigationErrorCategory.PROVIDER_TIMEOUT.value
    if code == LLMErrorCode.LLM_RATE_LIMITED.value:
        return InvestigationErrorCategory.PROVIDER_RATE_LIMITED.value
    if code in (
        LLMErrorCode.LLM_AUTHENTICATION_FAILED.value,
        LLMErrorCode.LLM_PROVIDER_NOT_CONFIGURED.value,
        LLMErrorCode.LLM_PROVIDER_ERROR.value,
    ):
        return InvestigationErrorCategory.PROVIDER_UNAVAILABLE.value
    return InvestigationErrorCategory.PROVIDER_UNAVAILABLE.value


async def execute_claimed_job(session: AsyncSession, job: InvestigationJob) -> InvestigationJob:
    """Run the full investigation pipeline for a claimed (running) job."""
    settings = get_settings()
    if job.status != InvestigationStatus.RUNNING.value:
        raise ValueError(f"Job {job.id} must be running to execute (is {job.status}).")

    # Snapshot plain IDs up front: after any session.rollback() the ORM
    # instance is expired, and attribute access would raise (async lazy-load
    # is unavailable). Failure paths must only use these locals.
    job_id: str = job.id
    org_id: str = job.organization_id

    provider_name: str | None = job.provider
    model_name: str | None = job.model
    try:
        # A re-queued retry must not duplicate a previous attempt's output.
        await InvestigationService.clear_attempt_artifacts(session, job)

        # ── 1. Load incident + timeline ──────────────────────────────────
        await InvestigationService.update_progress(session, job, "retrieving_evidence", 15)
        incident = await IncidentService.get_incident(session, job.incident_id, job.organization_id)
        if incident is None:  # incident deleted mid-flight
            return await InvestigationService.fail_job(
                session,
                job,
                InvestigationErrorCategory.INTERNAL_ERROR.value,
                _SAFE_ERROR_SUMMARIES[InvestigationErrorCategory.INTERNAL_ERROR],
            )
        query = build_user_query(incident)

        retrieved = await InvestigationRetrievalService.retrieve_evidence(
            session,
            job.organization_id,
            job.incident_id,
            query,
            limit=settings.INVESTIGATION_DEFAULT_RESULT_LIMIT,
        )
        await InvestigationService.update_progress(session, job, "building_timeline", 30)
        timeline_events, _total = await IncidentService.get_timeline(
            session, job.incident_id, job.organization_id, limit=500, offset=0
        )
        runbooks = await InvestigationRetrievalService.retrieve_runbooks(
            session, job.organization_id, query, top_k=settings.INVESTIGATION_RUNBOOK_TOP_K
        )

        if not retrieved:
            # Honest empty result: complete with explicit uncertainty, no fabrication.
            summary = _build_result_summary(
                incident_title=incident.title,
                observed_facts=[],
                uncertainty_notes=[
                    "No evidence events are recorded for this incident yet. "
                    "Ingest alerts, logs, metrics, or deployment records, then re-run the investigation."
                ],
                next_steps=[
                    {
                        "action": "Ingest relevant alerts, logs, and deployment records for the incident window, then re-run the investigation.",
                        "requires_human_approval": False,
                        "rationale": "Hypotheses require evidence; none is available yet.",
                    }
                ],
                retrieved=[],
                runbooks=runbooks,
            )
            return await InvestigationService.complete_job(session, job, summary)

        # ── 2. Generate structured hypotheses ────────────────────────────
        await InvestigationService.update_progress(session, job, "generating_hypotheses", 55)
        system_prompt, user_message = build_investigation_prompt(
            incident,
            [r.event for r in retrieved],
            runbooks,
            allowed_evidence_note=(
                f"Valid evidence IDs for citations: {sorted(r.event.id for r in retrieved)}. "
                "Cite ONLY these IDs."
            ),
        )
        provider, resolved_model = LLMProviderFactory.create()
        provider_name = provider.name
        model_name = resolved_model
        job.provider = provider_name
        job.model = model_name
        await session.commit()

        response = await provider.generate(
            LLMRequest(
                provider=provider_name,
                model=model_name,
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_message),
                ],
                temperature=0.2,
                max_tokens=min(settings.MAX_GENERATION_TOKENS, 2048),
                request_id=job.id,
            )
        )
        output, truncated_count = _parse_structured_output(
            response.content,
            max_hypotheses=min(settings.INVESTIGATION_MAX_HYPOTHESES, _MAX_HYPOTHESES_FALLBACK),
        )

        # ── 3. Validate citations, persist ───────────────────────────────
        await InvestigationService.update_progress(session, job, "validating_citations", 75)
        # Ownership check: the job may have been cancelled or re-queued while
        # generation was in flight (in-flight provider calls cannot be
        # interrupted). Never persist results for a job we no longer own.
        fresh_owner = await InvestigationService.get_job(session, job_id, org_id)
        if fresh_owner is None or fresh_owner.status != InvestigationStatus.RUNNING.value:
            await session.rollback()
            current = await InvestigationService.get_job(session, job_id, org_id)
            return current if current is not None else job
        allowed_ids = {r.event.id for r in retrieved}  # scoped to incident+org by retrieval
        drafts = _validate_and_build_drafts(output, allowed_ids)

        await InvestigationService.update_progress(session, job, "persisting", 90)
        await InvestigationService.persist_hypotheses(
            session, job, drafts, provider_name, model_name
        )

        uncertainty = list(output.uncertainty_notes) or _default_uncertainty(drafts)
        if truncated_count:
            uncertainty.append(
                f"The model returned {truncated_count} hypotheses; only the first "
                f"{len(drafts)} were retained."
            )
        next_steps = [_enforce_approval(ns) for ns in output.recommended_next_steps]
        summary = _build_result_summary(
            incident_title=incident.title,
            observed_facts=output.observed_facts,
            uncertainty_notes=uncertainty,
            next_steps=[ns.model_dump() for ns in next_steps],
            retrieved=retrieved,
            runbooks=runbooks,
        )
        return await InvestigationService.complete_job(session, job, summary)

    except LLMException as exc:
        # Safe summary only — never persist raw provider errors (may leak keys/config).
        logger.warning("Investigation %s provider failure: %s", job_id, type(exc).__name__)
        category = _map_llm_error(exc)
        return await InvestigationService.fail_job(
            session,
            job,
            category,
            _SAFE_ERROR_SUMMARIES.get(
                category, _SAFE_ERROR_SUMMARIES[InvestigationErrorCategory.PROVIDER_UNAVAILABLE]
            ),
        )
    except ValueError as exc:
        # Structured-output validation failure (invalid JSON / schema).
        logger.warning("Investigation %s invalid provider output: %s", job_id, type(exc).__name__)
        return await InvestigationService.fail_job(
            session,
            job,
            InvestigationErrorCategory.INVALID_PROVIDER_OUTPUT.value,
            _SAFE_ERROR_SUMMARIES[InvestigationErrorCategory.INVALID_PROVIDER_OUTPUT],
        )
    except ConflictException:
        # Lost ownership mid-flight (cancelled / re-queued / finished by
        # another executor). Surface current state instead of overwriting it.
        logger.info("Investigation %s lost ownership mid-flight; returning current state", job_id)
        try:
            await session.rollback()
            current = await InvestigationService.get_job(session, job_id, org_id)
            return current if current is not None else job
        except Exception:
            logger.exception("Investigation %s ownership-recovery read failed", job_id)
            return job
    except Exception:
        logger.exception("Investigation %s failed with internal error", job_id)
        # Re-fetch job state defensively: the session may be in a failed state.
        try:
            await session.rollback()
            fresh = await InvestigationService.get_job(session, job_id, org_id)
            if fresh is not None and fresh.status == InvestigationStatus.RUNNING.value:
                return await InvestigationService.fail_job(
                    session,
                    fresh,
                    InvestigationErrorCategory.INTERNAL_ERROR.value,
                    _SAFE_ERROR_SUMMARIES[InvestigationErrorCategory.INTERNAL_ERROR],
                )
            return fresh if fresh is not None else job
        except Exception:
            logger.exception("Investigation %s failure-path rollback also failed", job_id)
            return job


def _parse_structured_output(
    content: str, max_hypotheses: int = _MAX_HYPOTHESES_FALLBACK
) -> tuple[LLMInvestigationOutput, int]:
    """Parse and Pydantic-validate model output. Raises ValueError on any defect.

    Returns (output, truncated_count): oversized hypothesis arrays are truncated
    to ``max_hypotheses`` instead of discarding the whole investigation; the
    caller surfaces the truncation in the uncertainty notes.
    """
    try:
        payload = json.loads(_strip_code_fences(content))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Provider output is not valid JSON: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Provider output must be a JSON object.")
    truncated_count = 0
    hyps = payload.get("hypotheses")
    if isinstance(hyps, list) and len(hyps) > max_hypotheses:
        truncated_count = len(hyps) - max_hypotheses
        payload["hypotheses"] = hyps[:max_hypotheses]
    try:
        return LLMInvestigationOutput.model_validate(payload), truncated_count
    except Exception as exc:
        raise ValueError(f"Provider output failed schema validation: {type(exc).__name__}") from exc


def _enforce_approval(next_step: LLMNextStep) -> LLMNextStep:
    """Force requires_human_approval on remediation-adjacent actions.

    The model must not be able to bless a mutating action as safe to run
    unattended. Diagnostic, read-only steps pass through untouched.
    """
    if not next_step.requires_human_approval and _RISKY_ACTION_RE.search(next_step.action):
        next_step.requires_human_approval = True
        suffix = " [Flagged by TracePilot: mutating action requires human approval.]"
        if next_step.rationale:
            next_step.rationale = (next_step.rationale + suffix)[:1000]
        else:
            next_step.rationale = suffix.strip()
    return next_step


def _validate_and_build_drafts(
    output: LLMInvestigationOutput,
    allowed_ids: set[str],
) -> list[dict]:
    """Keep only citations resolving to retrieved evidence for this incident+org.

    Hypotheses left with zero valid citations are persisted as rejected (never
    silently dropped, never saved with foreign IDs). Duplicate IDs are
    naturally deduplicated; an ID cited as both supporting and contradicting
    yields both links (evidence can genuinely cut both ways).
    """
    drafts: list[dict] = []
    for draft in output.hypotheses:
        valid_support = sorted({i for i in draft.supporting_evidence_ids if i in allowed_ids})
        valid_contra = sorted({i for i in draft.contradicting_evidence_ids if i in allowed_ids})
        rejected_ids = sorted(
            (set(draft.supporting_evidence_ids) | set(draft.contradicting_evidence_ids))
            - allowed_ids
        )
        links = [{"evidence_event_id": eid, "link_type": "supports"} for eid in valid_support] + [
            {"evidence_event_id": eid, "link_type": "contradicts"} for eid in valid_contra
        ]
        if not links:
            drafts.append(
                {
                    "claim": draft.claim.strip(),
                    "rationale": draft.rationale.strip(),
                    "confidence": draft.confidence.value,
                    "confidence_score": draft.confidence_score,
                    "status": HypothesisStatus.REJECTED.value,
                    "rejection_reason": (
                        f"Rejected: cited {len(rejected_ids)} unsupported evidence reference(s) "
                        "that do not resolve to retrieved evidence for this incident. "
                        "No foreign or fabricated citations were saved."
                    ),
                    "links": [],
                }
            )
        else:
            status = (
                HypothesisStatus.CONTESTED.value
                if valid_contra
                else HypothesisStatus.SUPPORTED.value
            )
            drafts.append(
                {
                    "claim": draft.claim.strip(),
                    "rationale": draft.rationale.strip(),
                    "confidence": draft.confidence.value,
                    "confidence_score": draft.confidence_score,
                    "status": status,
                    "rejection_reason": None,
                    "links": links,
                }
            )
    return drafts


def _default_uncertainty(drafts: list[dict]) -> list[str]:
    notes = [
        "Temporal correlation alone does not establish causation; timeline order is not proof."
    ]
    if any(d["status"] == HypothesisStatus.REJECTED.value for d in drafts):
        notes.append(
            "One or more model-proposed hypotheses were rejected because they cited "
            "evidence that could not be resolved to this incident."
        )
    if any(d["status"] == HypothesisStatus.CONTESTED.value for d in drafts):
        notes.append(
            "At least one hypothesis has contradicting evidence; treat it as contested, not confirmed."
        )
    return notes


def _build_result_summary(
    incident_title: str,
    observed_facts: list[str],
    uncertainty_notes: list[str],
    next_steps: list[dict],
    retrieved: list,
    runbooks: list[dict],
) -> dict:
    return {
        "incident_title": incident_title,
        "observed_facts": observed_facts,
        "uncertainty_notes": uncertainty_notes,
        "recommended_next_steps": next_steps,
        "correlation_disclaimer": (
            "Temporal correlation alone does not establish causation. "
            "Timeline order must not be presented as proof of causality."
        ),
        "evidence_used": [
            {
                "evidence_id": r.event.id,
                "source_type": r.event.source_type,
                "event_type": r.event.event_type,
                "event_timestamp": r.event.event_timestamp.isoformat(),
                "summary": r.event.summary,
                "source_reference": r.event.source_reference,
                "retrieval_method": r.retrieval_method,
                "retrieval_sources": getattr(r, "retrieval_sources", [r.retrieval_method]),
                "score": r.score,
                "rank": r.rank,
            }
            for r in retrieved
        ],
        "runbooks_used": runbooks,
    }
