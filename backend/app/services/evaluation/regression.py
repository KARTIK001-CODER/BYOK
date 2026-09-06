"""Regression detection — compare current report vs baseline with thresholds."""

from __future__ import annotations

from app.services.evaluation.schemas import BaselineRecord, EvaluationReport, RegressionResult, RegressionThresholds


class RegressionChecker:
    """Compare baseline vs current and emit PASS/WARNING/FAIL per metric."""

    @staticmethod
    def compare(
        baseline: BaselineRecord,
        current: EvaluationReport,
        thresholds: RegressionThresholds | None = None,
    ) -> list[RegressionResult]:
        thresholds = thresholds or RegressionThresholds()
        results: list[RegressionResult] = []

        # Map metric name -> (baseline value, current value, threshold, higher_is_better)
        checks = [
            ("MRR", baseline.overall.mrr, current.overall.mrr, thresholds.mrr_max_regression, True),
            ("Hit@5", baseline.overall.hit_at_5, current.overall.hit_at_5, thresholds.hit_at_5_max_regression, True),
            ("Hit@1", baseline.overall.hit_at_1, current.overall.hit_at_1, thresholds.hit_at_1_max_regression, True),
        ]

        for metric, base_val, cur_val, thresh, higher_better in checks:
            delta = cur_val - base_val
            delta_pct = (delta / base_val) if base_val else (0.0 if cur_val == 0 else 1.0)
            # Regression if delta negative and magnitude > threshold
            if higher_better and delta < 0 and abs(delta_pct) > thresh:
                # Fail if >2x threshold? Use FAIL for > threshold, WARNING for >0.5*threshold already FAIL
                # Spec: WARNING for 1.5% vs 2% etc. Simplify: delta_pct > thresh => FAIL
                status = "FAIL"
            elif higher_better and delta < 0 and abs(delta_pct) > (thresh * 0.5):
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                RegressionResult(
                    baseline_id=baseline.baseline_id,
                    current_id=current.evaluation_id,
                    metric=metric,
                    baseline_value=round(base_val, 4),
                    current_value=round(cur_val, 4),
                    delta=round(delta, 4),
                    delta_pct=round(delta_pct, 4),
                    status=status,
                    threshold=thresh,
                )
            )
        return results

    @staticmethod
    def summarize(results: list[RegressionResult]) -> str:
        if not results:
            return "No regression data"
        fails = [r for r in results if r.status == "FAIL"]
        warns = [r for r in results if r.status == "WARNING"]
        if fails:
            return f"REGRESSION FAIL: {', '.join(r.metric + f' {r.delta_pct:.1%}' for r in fails)}"
        if warns:
            return f"REGRESSION WARNING: {', '.join(r.metric + f' {r.delta_pct:.1%}' for r in warns)}"
        return "PASS: No meaningful regression"
