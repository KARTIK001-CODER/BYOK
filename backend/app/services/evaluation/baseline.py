"""Baseline management — save and load versioned baselines."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.evaluation.schemas import BaselineRecord, EvaluationReport


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


class BaselineManager:
    """Persist baselines under evaluation/baselines/ for regression comparison."""

    DEFAULT_DIR = Path("backend/evaluation/baselines")

    @staticmethod
    def save(report: EvaluationReport, output_dir: Path | str | None = None) -> Path:
        out_dir = Path(output_dir) if output_dir else BaselineManager.DEFAULT_DIR
        # Handle relative from repo root vs backend — prefer file-based absolute to avoid backend/backend
        if not out_dir.is_absolute():
            # Repo root is 4 parents up from this file: .../BYOK/backend/app/services/evaluation -> BYOK
            repo_root = Path(__file__).resolve().parents[4]
            repo_root_candidate = repo_root / out_dir
            if repo_root_candidate.parent.exists() or repo_root_candidate.exists():
                out_dir = repo_root_candidate
            else:
                # fallback to cwd
                out_dir = Path.cwd() / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        baseline = BaselineRecord(
            baseline_id=report.evaluation_id,
            created_at=report.timestamp,
            dataset_version=report.dataset_version,
            retriever=report.retriever,
            top_k=report.top_k,
            config=report.config,
            overall=report.overall,
            by_category=report.by_category,
            git_commit=report.git_commit or _git_commit(),
        )
        # filename: retrieval_baseline_<retriever>_v<dataset_version>.json
        fname = f"retrieval_baseline_{report.retriever}_v{report.dataset_version}.json"
        path = out_dir / fname
        with open(path, "w", encoding="utf-8") as f:
            json.dump(baseline.model_dump(), f, indent=2, ensure_ascii=False)
        # also save latest alias
        latest = out_dir / f"retrieval_baseline_{report.retriever}_latest.json"
        with open(latest, "w", encoding="utf-8") as f:
            json.dump(baseline.model_dump(), f, indent=2, ensure_ascii=False)
        return path

    @staticmethod
    def load(path: Path | str) -> BaselineRecord:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Baseline not found: {p}")
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        return BaselineRecord.model_validate(raw)

    @staticmethod
    def load_latest(retriever: str = "hybrid", baseline_dir: Path | str | None = None) -> BaselineRecord | None:
        bdir = Path(baseline_dir) if baseline_dir else BaselineManager.DEFAULT_DIR
        if not bdir.is_absolute():
            repo_root = Path(__file__).resolve().parents[4] / bdir
            if repo_root.parent.exists() or repo_root.exists():
                bdir = repo_root
            else:
                bdir = Path.cwd() / bdir
        latest = bdir / f"retrieval_baseline_{retriever}_latest.json"
        if latest.exists():
            return BaselineManager.load(latest)
        # fallback any baseline for retriever
        matches = list(bdir.glob(f"retrieval_baseline_{retriever}_*.json"))
        if matches:
            return BaselineManager.load(sorted(matches)[-1])
        return None
