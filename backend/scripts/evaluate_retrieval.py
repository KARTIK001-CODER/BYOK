"""
BYOK Phase 2.0 Retrieval Evaluation CLI.

Usage:
  python scripts/evaluate_retrieval.py
  python scripts/evaluate_retrieval.py --retriever vector --top-k 5
  python scripts/evaluate_retrieval.py --retriever all --dataset evaluation/datasets/retrieval_baseline.json --output evaluation/reports
  python scripts/evaluate_retrieval.py --retriever hybrid --save-baseline --compare-baseline
"""
import argparse
import asyncio
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# evaluation DB uses real postgres when available else sqlite fallback; do not delete pytest dummy for this script
# keep whatever env has

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.services.evaluation.baseline import BaselineManager
from app.services.evaluation.dataset import EvaluationDatasetLoader
from app.services.evaluation.regression import RegressionChecker
from app.services.evaluation.reporting import console_report, write_json_report, write_markdown_report
from app.services.evaluation.runner import EvaluationRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("evaluate_retrieval")

DEFAULT_DATASET = Path("evaluation/datasets/retrieval_baseline.json")
DEFAULT_OUTPUT = Path("evaluation/reports")


async def find_eval_org_kb():
    """Find evaluation org/KB seeded via seed_evaluation_data.py; fallback to any org/kb."""
    factory = get_session_factory()
    async with factory() as session:
        # Try eval org slug
        r = await session.execute(select(Organization).where(Organization.slug == "eval-org"))
        org = r.scalar_one_or_none()
        if org:
            r2 = await session.execute(select(KnowledgeBase).where(KnowledgeBase.organization_id == org.id, KnowledgeBase.slug == "eval-kb"))
            kb = r2.scalar_one_or_none()
            if kb:
                return org.id, kb.id
        # Fallback: first org/kb with documents
        r3 = await session.execute(select(Organization).limit(1))
        any_org = r3.scalar_one_or_none()
        if any_org:
            r4 = await session.execute(select(KnowledgeBase).where(KnowledgeBase.organization_id == any_org.id).limit(1))
            any_kb = r4.scalar_one_or_none()
            if any_kb:
                logger.warning("Using fallback org/kb %s / %s (run seed_evaluation_data.py for isolated fixtures)", any_org.slug, any_kb.slug)
                return any_org.id, any_kb.id
    raise RuntimeError("No evaluation organization/kb found. Run: python scripts/seed_evaluation_data.py  (and ensure DB is reachable)")


async def evaluate_single(retriever: str, dataset_path: Path, top_k: int, output_dir: Path, save_baseline: bool, compare_baseline: bool):
    # Validate dataset
    ds = EvaluationDatasetLoader.load(dataset_path)
    print(f"Dataset {dataset_path} version={ds.version} cases={len(ds.cases)}")

    # Find eval org
    org_id, kb_id = await find_eval_org_kb()
    print(f"Evaluation scope: org={org_id} kb={kb_id} (isolated via eval-org)")

    # Runner — we pass organization_id, runner will use it for all queries
    # Knowledge base filter is not strictly required because org isolation already scopes, but we pass top_k
    runner = EvaluationRunner(dataset_path=dataset_path, retriever=retriever, top_k=top_k)

    factory = get_session_factory()
    async with factory() as session:
        report = await runner.run(session=session, organization_id=org_id)

    # Console
    print(console_report(report))

    # Phase 2.1 extra: routing distribution + strategy quality for adaptive
    if retriever == "adaptive":
        from app.services.query_intelligence.analyzer import QueryAnalyzer
        from collections import Counter
        dist = Counter()
        strat_quality: dict[str, list[float]] = {"VECTOR": [], "KEYWORD": [], "HYBRID": [], "HYBRID_WIDE": []}
        for case in ds.cases:
            analysis = QueryAnalyzer.analyze(case.query)
            strat = analysis.strategy.strategy.value
            dist[strat] += 1
            # find case result to get hit
            cr = next((c for c in report.cases if c.case_id == case.id), None)
            if cr:
                # store per-strategy hit
                strat_quality.setdefault(strat, []).append(1.0 if cr.status == "hit" else 0.0)
        print("\nAdaptive Routing Distribution:")
        total = len(ds.cases)
        for strat in ["VECTOR", "KEYWORD", "HYBRID", "HYBRID_WIDE"]:
            cnt = dist.get(strat, 0)
            print(f"  {strat:12s} {cnt:2d}/{total} {cnt/total:5.1%}")
        print("\nStrategy Quality (Hit@5 per routed group):")
        for strat, hits in strat_quality.items():
            if hits:
                avg = sum(hits)/len(hits)
                print(f"  {strat:12s} queries {len(hits):2d} Hit@5 {avg:.3f}")

    # Reports
    json_path = write_json_report(report, output_dir)
    md_path = write_markdown_report(report, output_dir)
    print(f"\nJSON report:  {json_path}")
    print(f"Markdown:     {md_path}")

    # Baseline
    if save_baseline:
        bpath = BaselineManager.save(report)
        print(f"Baseline saved: {bpath} (also _latest.json)")

    if compare_baseline:
        baseline = BaselineManager.load_latest(retriever=retriever)
        if baseline:
            results = RegressionChecker.compare(baseline, report)
            print("\nRegression check vs baseline:")
            for r in results:
                print(f"  {r.metric}: baseline {r.baseline_value:.3f} -> current {r.current_value:.3f} delta {r.delta_pct:+.1%} status {r.status} (threshold {r.threshold:.0%})")
            print(RegressionChecker.summarize(results))
        else:
            print(f"No baseline found for retriever {retriever} — run with --save-baseline first")

    return report


async def main():
    parser = argparse.ArgumentParser(description="BYOK Retrieval Evaluation (Phase 2.0 + 2.1 adaptive)")
    parser.add_argument("--retriever", default="all", choices=["vector", "keyword", "hybrid", "adaptive", "all"], help="Retriever to evaluate (adaptive = Phase 2.1 query intelligence)")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Dataset path")
    parser.add_argument("--top-k", type=int, default=5, help="Top K for evaluation")
    parser.add_argument("--candidate-k", type=int, default=None, help="Candidate K (default top_k*4)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output directory for reports")
    parser.add_argument("--save-baseline", action="store_true", help="Save baseline after run")
    parser.add_argument("--compare-baseline", action="store_true", help="Compare against saved baseline")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger("app.services.evaluation").setLevel(logging.DEBUG)

    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        # try resolve relative to repo root and backend
        candidates = [Path.cwd() / dataset_path, Path(__file__).resolve().parents[1] / dataset_path, dataset_path]
        for c in candidates:
            if c.exists():
                dataset_path = c
                break

    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = Path(__file__).resolve().parents[1] / output_dir

    # Expand "all" to include adaptive if present
    if args.retriever == "all":
        retrievers = ["vector", "keyword", "hybrid", "adaptive"]
    else:
        retrievers = [args.retriever]

    reports = []
    for ret in retrievers:
        print(f"\n{'='*70}")
        print(f"Evaluating retriever: {ret} (top_k={args.top_k})")
        print(f"{'='*70}")
        report = await evaluate_single(
            retriever=ret,
            dataset_path=dataset_path,
            top_k=args.top_k,
            output_dir=output_dir,
            save_baseline=args.save_baseline,
            compare_baseline=args.compare_baseline,
        )
        reports.append(report)

    # Per-retriever comparison table if all
    if len(reports) > 1:
        print("\n" + "="*70)
        print("RETRIEVER COMPARISON")
        print("="*70)
        hdr = f"{'Retriever':<15} | {'Hit@1':<6} | {'Hit@3':<6} | {'Hit@5':<6} | {'MRR':<6} | {'Prec@5':<7} | {'Recall@5'}"
        print(hdr)
        print("-"*70)
        for r in reports:
            print(f"{r.retriever:<15} | {r.overall.hit_at_1:<6.3f} | {r.overall.hit_at_3:<6.3f} | {r.overall.hit_at_5:<6.3f} | {r.overall.mrr:<6.3f} | {r.overall.precision_at_k:<7.3f} | {r.overall.recall_at_k:.3f}")
        print("="*70)
        # Oracle upper bound (best per query across vector/keyword/hybrid)
        if len(reports) >= 3 and any(r.retriever == "hybrid" for r in reports):
            # Find best per case across non-adaptive retrievers
            try:
                # Collect per-case hits
                cases_by_id: dict[str, dict[str, float]] = {}
                for r in reports:
                    if r.retriever in ("vector", "keyword", "hybrid"):
                        for c in r.cases:
                            cases_by_id.setdefault(c.case_id, {})[r.retriever] = c.mrr
                oracle_mrrs = []
                oracle_hits = []
                for cid, mrrs in cases_by_id.items():
                    best = max(mrrs.values()) if mrrs else 0.0
                    oracle_mrrs.append(best)
                    oracle_hits.append(1.0 if best > 0 else 0.0)
                oracle_mrr = sum(oracle_mrrs)/len(oracle_mrrs) if oracle_mrrs else 0
                oracle_hit5 = sum(oracle_hits)/len(oracle_hits) if oracle_hits else 0
                hybrid = next((r for r in reports if r.retriever=="hybrid"), None)
                adaptive = next((r for r in reports if r.retriever=="adaptive"), None)
                print("\nORACLE UPPER BOUND (best of vector/keyword/hybrid per query):")
                print(f"  Hybrid:   Hit@5 {hybrid.overall.hit_at_5:.3f} MRR {hybrid.overall.mrr:.3f}" if hybrid else "")
                if adaptive:
                    print(f"  Adaptive: Hit@5 {adaptive.overall.hit_at_5:.3f} MRR {adaptive.overall.mrr:.3f}")
                print(f"  Oracle:   Hit@5 {oracle_hit5:.3f} MRR {oracle_mrr:.3f} (max possible)")
            except Exception as e:
                print(f"Oracle calculation failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
