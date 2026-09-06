"""BYOK Phase 2.0 — Retrieval Evaluation Framework (reusable, deterministic, versioned)."""

from app.services.evaluation.baseline import BaselineManager
from app.services.evaluation.dataset import EvaluationDatasetLoader
from app.services.evaluation.metrics import EvaluationMetrics
from app.services.evaluation.regression import RegressionChecker
from app.services.evaluation.runner import EvaluationRunner, RetrieverAdapter

__all__ = [
    "BaselineManager",
    "EvaluationDatasetLoader",
    "EvaluationMetrics",
    "EvaluationRunner",
    "RegressionChecker",
    "RetrieverAdapter",
]
