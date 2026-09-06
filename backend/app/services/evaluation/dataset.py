"""Dataset loading, validation, and stable-identifier resolution."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.services.evaluation.schemas import EvaluationDataset

logger = logging.getLogger("app.services.evaluation.dataset")


class EvaluationDatasetLoader:
    """Load and validate versioned evaluation datasets."""

    @staticmethod
    def load(path: Path | str) -> EvaluationDataset:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Evaluation dataset not found: {p}")
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        # Support both new format {version, cases} and legacy {documents, queries}
        if "cases" in raw:
            ds = EvaluationDataset.model_validate(raw)
        elif "queries" in raw:
            # Legacy retrieval_examples.json -> convert
            ds = EvaluationDatasetLoader._from_legacy(raw, p)
        else:
            raise ValueError(f"Unknown dataset format in {p}")

        EvaluationDatasetLoader.validate(ds)
        logger.info("Loaded evaluation dataset %s version=%s cases=%d", p, ds.version, len(ds.cases))
        return ds

    @staticmethod
    def _from_legacy(raw: dict, path: Path) -> EvaluationDataset:
        from app.services.evaluation.schemas import EvaluationCase, EvaluationCategory, ExpectedResult

        cases = []
        for idx, q in enumerate(raw.get("queries", [])):
            relevant = q.get("relevant_doc_ids", [])
            expected = [ExpectedResult(document_name=doc_id, relevance_grade=1) for doc_id in relevant]
            # Heuristic category
            query_lower = q["query"].lower()
            if any(kw in query_lower for kw in ["what is", "how does", "explain"]):
                cat = EvaluationCategory.factual
            else:
                cat = EvaluationCategory.semantic
            cases.append(
                EvaluationCase(
                    id=f"legacy_{idx+1:03d}",
                    query=q["query"],
                    category=cat,
                    difficulty="medium",
                    expected=expected,
                    notes=f"Migrated from {path.name}",
                )
            )
        return EvaluationDataset(
            version="0.9-migrated",
            description=raw.get("description", "Migrated legacy dataset"),
            cases=cases,
        )

    @staticmethod
    def validate(ds: EvaluationDataset) -> None:
        errors: list[str] = []
        if not ds.cases:
            errors.append("Dataset has no cases")
        for c in ds.cases:
            if not c.query.strip():
                errors.append(f"Case {c.id}: missing query")
            if not c.expected:
                errors.append(f"Case {c.id}: no expected results (relevance empty)")
            for exp in c.expected:
                if not exp.document_name and not exp.document_slug and not exp.chunk_content_snippet:
                    errors.append(f"Case {c.id}: expected result has no stable identifier (document_name/slug/snippet)")
            if c.category not in list(c.category.__class__):
                errors.append(f"Case {c.id}: invalid category {c.category}")
        if errors:
            msg = "Dataset validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(msg)
