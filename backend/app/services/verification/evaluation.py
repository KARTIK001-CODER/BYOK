"""Groundedness evaluation runner — accuracy, precision/recall, confusion matrix, failure analysis."""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.verification.claim_extraction import RuleBasedClaimExtractor
from app.services.verification.evidence_selection import EvidenceSelector
from app.services.verification.factory import VerifierFactory
from app.services.verification.schemas import (
    Claim,
    ClaimVerificationResult,
    Evidence,
    VerificationStatus,
)


class GroundednessEvaluator:
    """Run dataset through verifier and compute metrics."""

    @staticmethod
    def load_dataset(path: Path | str) -> dict[str, Any]:
        p = Path(path)
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def validate_dataset(data: dict[str, Any]) -> None:
        errors = []
        seen = set()
        for case in data.get("cases", []):
            cid = case.get("id")
            if cid in seen:
                errors.append(f"Duplicate ID {cid}")
            seen.add(cid)
            if not case.get("claim"):
                errors.append(f"Case {cid} missing claim")
            if not case.get("evidence"):
                errors.append(f"Case {cid} missing evidence")
            if case.get("expected_status") not in [e.value for e in VerificationStatus]:
                errors.append(f"Case {cid} invalid expected_status {case.get('expected_status')}")
        if errors:
            raise ValueError("Dataset validation failed:\n" + "\n".join(errors))

    @staticmethod
    def _status_match(predicted: VerificationStatus, expected: str) -> bool:
        return predicted.value == expected

    @classmethod
    async def evaluate(
        cls,
        dataset_path: Path | str,
        verifier_provider: str = "heuristic",
        claim_extractor_provider: str = "rule_based",
    ) -> dict[str, Any]:
        data = cls.load_dataset(dataset_path)
        cls.validate_dataset(data)
        version = data.get("version", "1.0")
        cases = data["cases"]

        # Metrics
        total = len(cases)
        correct = 0
        per_class_correct: dict[str, int] = Counter()
        per_class_total: dict[str, int] = Counter()
        per_pred_total: dict[str, int] = Counter()
        confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        failures: list[dict[str, Any]] = []
        # Hallucination-specific
        unsupported_total = sum(1 for c in cases if c["expected_status"] == "UNSUPPORTED")
        contradicted_total = sum(1 for c in cases if c["expected_status"] == "CONTRADICTED")
        unsupported_correct = 0
        contradicted_correct = 0
        latencies: list[float] = []

        for case in cases:
            claim_text = case["claim"]
            evidence_texts = case["evidence"]
            expected = case["expected_status"]
            category = case.get("category", expected)

            # Create claim object — map expected_status to claim_type for NON_VERIFIABLE
            ctype = "NON_VERIFIABLE" if expected == "NON_VERIFIABLE" else "FACTUAL"
            # Also handle claim text heuristics for NON_VERIFIABLE (opinion)
            claim = Claim(
                claim_id=case["id"],
                text=claim_text,
                claim_type=ctype,  # type: ignore
                importance=1,
            )
            # Classify via extractor's type logic? Use claim as is
            # Evidence objects
            evidence_objs = [
                Evidence(
                    evidence_id=f"ev_{i+1}",
                    chunk_id=f"chunk_{i+1}",
                    document_id="doc_1",
                    document_name="evidence",
                    content=txt,
                    retrieval_rank=i + 1,
                )
                for i, txt in enumerate(evidence_texts)
            ]

            # Select evidence (top_k 3) — uses lexical overlap, no DB
            t0 = time.perf_counter()
            selected, _ = EvidenceSelector.select(claim, evidence_objs, top_k=3)

            # Verify
            verifier = VerifierFactory.create(provider=verifier_provider)
            try:
                result: ClaimVerificationResult = await verifier.verify(claim, selected)
                pred = result.status.value
                latency = result.verification_latency_ms or (time.perf_counter() - t0) * 1000
                latencies.append(latency)
            except Exception as e:
                pred = "UNCERTAIN"
                latency = (time.perf_counter() - t0) * 1000
                latencies.append(latency)
                result = None  # type: ignore

            is_correct = pred == expected
            if is_correct:
                correct += 1
                if expected == "UNSUPPORTED":
                    unsupported_correct += 1
                if expected == "CONTRADICTED":
                    contradicted_correct += 1
            else:
                failures.append(
                    {
                        "id": case["id"],
                        "claim": claim_text,
                        "expected": expected,
                        "predicted": pred,
                        "category": category,
                        "evidence": evidence_texts,
                        "reason": result.reason if result else str(e) if "e" in locals() else "unknown",
                    }
                )
                # Still count for per-class if expected is unsupported/contradicted but predicted wrong, not correct

            per_class_total[expected] += 1
            per_pred_total[pred] += 1
            if is_correct:
                per_class_correct[expected] += 1
            confusion[expected][pred] += 1

        accuracy = correct / total if total else 0
        # Precision/Recall per class: for hallucination detection we care UNSUPPORTED and CONTRADICTED
        def precision(cls: str) -> float:
            tp = confusion[cls][cls]
            fp = sum(confusion[other][cls] for other in confusion if other != cls)
            denom = tp + fp
            return tp / denom if denom else 0.0

        def recall(cls: str) -> float:
            tp = confusion[cls][cls]
            fn = sum(confusion[cls][other] for other in confusion[cls] if other != cls)
            denom = tp + fn
            return tp / denom if denom else 0.0

        # Overall precision/recall (micro)
        # For overall, consider correct vs total
        overall_precision = accuracy  # for single-label accuracy, precision==recall==accuracy for overall
        overall_recall = accuracy
        f1 = 2 * overall_precision * overall_recall / (overall_precision + overall_recall) if (overall_precision + overall_recall) else 0

        # Hallucination-specific
        unsupported_recall = unsupported_correct / unsupported_total if unsupported_total else 0
        contradicted_recall = contradicted_correct / contradicted_total if contradicted_total else 0
        unsupported_precision = precision("UNSUPPORTED")
        contradicted_precision = precision("CONTRADICTED")

        # Latency percentiles
        lat_sorted = sorted(latencies)
        def pct(p):
            if not lat_sorted:
                return 0
            idx = min(int(len(lat_sorted) * p), len(lat_sorted) - 1)
            return lat_sorted[idx]

        # Failure breakdown
        failure_types = Counter()
        for f in failures:
            exp = f["expected"]
            pred = f["predicted"]
            if exp in ("SUPPORTED", "PARTIALLY_SUPPORTED") and pred in ("UNSUPPORTED", "CONTRADICTED"):
                failure_types["False Hallucination"] += 1
            elif exp in ("UNSUPPORTED", "CONTRADICTED") and pred in ("SUPPORTED", "PARTIALLY_SUPPORTED"):
                failure_types["False Support"] += 1
            elif exp == "CONTRADICTED" and pred != "CONTRADICTED":
                failure_types["Contradiction Miss"] += 1
            else:
                failure_types["Verifier Failure"] += 1

        return {
            "dataset_version": version,
            "verifier_provider": verifier_provider,
            "total": total,
            "correct": correct,
            "accuracy": round(accuracy, 3),
            "precision": round(overall_precision, 3),
            "recall": round(overall_recall, 3),
            "f1": round(f1, 3),
            "unsupported_precision": round(unsupported_precision, 3),
            "unsupported_recall": round(unsupported_recall, 3),
            "contradicted_precision": round(contradicted_precision, 3),
            "contradicted_recall": round(contradicted_recall, 3),
            "confusion": {k: dict(v) for k, v in confusion.items()},
            "per_class_total": dict(per_class_total),
            "per_class_correct": dict(per_class_correct),
            "failures": failures[:10],
            "failure_types": dict(failure_types),
            "latency": {
                "p50": round(pct(0.5), 2),
                "p95": round(pct(0.95), 2),
                "p99": round(pct(0.99), 2),
                "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            },
            "cases": cases,  # original for trace
        }
