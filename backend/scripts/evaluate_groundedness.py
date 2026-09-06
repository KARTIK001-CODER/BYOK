"""
Evaluate groundedness verification — accuracy, confusion matrix, hallucination metrics.

Usage:
  python scripts/evaluate_groundedness.py --verifier heuristic
  python scripts/evaluate_groundedness.py --verifier mock --dataset evaluation/groundedness/datasets/groundedness_baseline.json
  python scripts/evaluate_groundedness.py --verifier heuristic --save-baseline --compare-baseline
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.verification.evaluation import GroundednessEvaluator
from datetime import datetime, timezone
import subprocess

DEFAULT_DATASET = Path("backend/evaluation/groundedness/datasets/groundedness_baseline.json")

def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except:
        return None

async def main():
    parser = argparse.ArgumentParser(description="Groundedness evaluation")
    parser.add_argument("--verifier", default="heuristic", choices=["heuristic", "mock", "llm"], help="Verifier provider")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output", default="backend/evaluation/groundedness/reports")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--compare-baseline", action="store_true")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        # try alternative resolve
        alt = Path(__file__).resolve().parents[1] / args.dataset
        if alt.exists():
            dataset_path = alt
        else:
            # try backend-relative
            alt2 = Path(__file__).resolve().parents[1] / "evaluation" / "groundedness" / "datasets" / "groundedness_baseline.json"
            if alt2.exists():
                dataset_path = alt2

    print(f"Dataset: {dataset_path}")
    result = await GroundednessEvaluator.evaluate(dataset_path, verifier_provider=args.verifier)
    print("="*70)
    print("GROUNDEDNESS EVALUATION")
    print("="*70)
    print(f"Dataset version: {result['dataset_version']} verifier: {result['verifier_provider']}")
    print(f"Total: {result['total']} Correct: {result['correct']} Accuracy: {result['accuracy']:.3f}")
    print(f"Precision: {result['precision']:.3f} Recall: {result['recall']:.3f} F1: {result['f1']:.3f}")
    print(f"Unsupported Precision: {result['unsupported_precision']:.3f} Recall: {result['unsupported_recall']:.3f}")
    print(f"Contradicted Precision: {result['contradicted_precision']:.3f} Recall: {result['contradicted_recall']:.3f}")
    print(f"Latency P50: {result['latency']['p50']}ms P95: {result['latency']['p95']}ms avg: {result['latency']['avg']}ms")
    print("\nConfusion Matrix (Expected -> Predicted):")
    # pretty print
    all_labels = ["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "UNCERTAIN", "NON_VERIFIABLE"]
    header = "Expected".ljust(20) + "".join(l[:6].ljust(8) for l in all_labels)
    print(header)
    print("-"* (20 + 8*len(all_labels)))
    for exp in all_labels:
        row = exp.ljust(20)
        for pred in all_labels:
            cnt = result["confusion"].get(exp, {}).get(pred, 0)
            row += str(cnt).ljust(8)
        print(row)
    print("\nFailure types:")
    for k, v in result["failure_types"].items():
        print(f"  {k}: {v}")
    if result["failures"]:
        print("\nWorst failures (first 5):")
        for f in result["failures"][:5]:
            print(f"  {f['id']} [{f['expected']} -> {f['predicted']}] {f['claim'][:60]}")

    # Save JSON report
    out_dir = Path(args.output)
    if not out_dir.is_absolute():
        out_dir = Path(__file__).resolve().parents[1] / out_dir if (Path(__file__).resolve().parents[1] / out_dir).parent.exists() else Path.cwd() / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"groundedness_eval_{args.verifier}_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({**result, "timestamp": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit()}, f, indent=2)
    print(f"\nJSON report: {json_path}")

    # Markdown
    md_path = out_dir / f"groundedness_eval_{args.verifier}_{ts}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Groundedness Evaluation — {args.verifier}\n\n")
        f.write(f"- Dataset: `{dataset_path}` v{result['dataset_version']}\n")
        f.write(f"- Total: {result['total']} Accuracy: {result['accuracy']:.3f}\n")
        f.write(f"- Precision: {result['precision']:.3f} Recall: {result['recall']:.3f} F1: {result['f1']:.3f}\n")
        f.write(f"- Unsupported Recall: {result['unsupported_recall']:.3f} Contradicted Recall: {result['contradicted_recall']:.3f}\n")
        f.write(f"- Latency P50 {result['latency']['p50']}ms\n\n")
        f.write("## Confusion Matrix\n\n")
        f.write("| Expected | " + " | ".join(all_labels) + " |\n")
        f.write("|---" + "|---"*len(all_labels) + "|\n")
        for exp in all_labels:
            row = f"| {exp} |"
            for pred in all_labels:
                cnt = result["confusion"].get(exp, {}).get(pred, 0)
                row += f" {cnt} |"
            f.write(row + "\n")
    print(f"Markdown: {md_path}")

    # Baseline handling
    if args.save_baseline:
        baseline_dir = Path("backend/evaluation/groundedness/baselines")
        if not baseline_dir.is_absolute():
            baseline_dir = Path(__file__).resolve().parents[1] / baseline_dir
        baseline_dir.mkdir(parents=True, exist_ok=True)
        bpath = baseline_dir / f"groundedness_baseline_{args.verifier}_v{result['dataset_version']}.json"
        with open(bpath, "w", encoding="utf-8") as bf:
            json.dump(result, bf, indent=2)
        print(f"Baseline saved: {bpath}")

    if args.compare_baseline:
        baseline_path = Path(f"backend/evaluation/groundedness/baselines/groundedness_baseline_{args.verifier}_v{result['dataset_version']}.json")
        if not baseline_path.is_absolute():
            baseline_path = Path(__file__).resolve().parents[1] / baseline_path
        if baseline_path.exists():
            with open(baseline_path, encoding="utf-8") as bf:
                base = json.load(bf)
            # Simple regression check
            acc_delta = result["accuracy"] - base["accuracy"]
            print(f"\nRegression check vs baseline accuracy {base['accuracy']:.3f} -> {result['accuracy']:.3f} delta {acc_delta:+.3f}")
            if acc_delta < -0.02:
                print("FAIL: Accuracy regression >2%")
            elif acc_delta < -0.01:
                print("WARNING: regression 1-2%")
            else:
                print("PASS")
        else:
            print(f"No baseline found at {baseline_path}")

if __name__ == "__main__":
    asyncio.run(main())
