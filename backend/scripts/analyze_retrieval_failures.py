"""
Analyze retrieval failures per taxonomy — uses Phase 2.0 baseline evaluation reports or live run.

Taxonomy:
  SEMANTIC_MISMATCH, KEYWORD_MISMATCH, MULTI_HOP, AMBIGUOUS_QUERY,
  LONG_QUERY, SHORT_QUERY, ENTITY_AMBIGUITY, NUMERICAL_QUERY, TEMPORAL_QUERY, NO_RELEVANT_CONTEXT
"""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collections import Counter

# Heuristic taxonomy classifier
def classify_failure(query: str, expected: list[str], retrieved: list[str], category: str) -> str:
    q = query.lower()
    word_count = len(re.findall(r"\b\w+\b", query))
    # No relevant context
    if not retrieved:
        return "NO_RELEVANT_CONTEXT"
    # Short
    if word_count <= 3:
        return "SHORT_QUERY"
    # Long
    if word_count >= 20:
        return "LONG_QUERY"
    # Numerical
    if re.search(r"\b\d+\b", query):
        return "NUMERICAL_QUERY"
    # Temporal
    if re.search(r"\b(19|20)\d{2}|january|february|march|april|may|june|july|august|september|october|november|december|today|trial.*period|day 15\b", q):
        return "TEMPORAL_QUERY"
    # Entity ambiguity
    if any(term in q for term in ["policy", "limits", "it", "that"]) and word_count <= 5:
        return "ENTITY_AMBIGUITY"
    # Ambiguous
    if category == "ambiguous" or any(p in q for p in ["how does it work", "tell me about", "what about"]):
        return "AMBIGUOUS_QUERY"
    # Multi-hop
    if category == "multi_hop" or (" and " in q and word_count >= 8):
        return "MULTI_HOP"
    # Keyword mismatch: contains identifier but not retrieved
    if re.search(r"[a-z]+_[a-z_]+|vector_cosine|cancellation_fee|RRF_K|pool_size", query):
        return "KEYWORD_MISMATCH"
    # Semantic
    if category == "semantic":
        return "SEMANTIC_MISMATCH"
    return "SEMANTIC_MISMATCH"

def analyze_dataset(dataset_path: str = "backend/evaluation/datasets/retrieval_baseline.json"):
    import json
    p = Path(dataset_path)
    if not p.exists():
        p = Path(__file__).resolve().parents[1] / dataset_path
    data = json.loads(p.read_text())
    print(f"Dataset {p} version {data.get('version')} cases {len(data['cases'])}")
    # For now, just show taxonomy based on query text without needing retrieval
    counter = Counter()
    for case in data["cases"]:
        query = case["query"]
        expected = [e.get("document_name", "") for e in case.get("expected", [])]
        # Mock retrieved as empty for now, but we can run live evaluation if needed
        # Use category to classify
        failure_type = classify_failure(query, expected, [], case.get("category", ""))
        counter[failure_type] += 1
    print("Failure Taxonomy (heuristic, no retrieval yet):")
    for k, v in counter.most_common():
        print(f"  {k:20s} {v:2d} {v/len(data['cases']):.1%}")
    return counter

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="backend/evaluation/datasets/retrieval_baseline.json")
    parser.add_argument("--reports", nargs="*", help="JSON reports from evaluate_retrieval.py to analyze real failures")
    args = parser.parse_args()
    if args.reports:
        # Real failure analysis from reports
        for report_path in args.reports:
            p = Path(report_path)
            data = json.loads(p.read_text())
            print(f"\nReport {p} retriever {data.get('retriever')} Hit@5 {data.get('overall', {}).get('hit_at_5')}")
            failures = data.get("failures", [])
            counter = Counter()
            for f in failures:
                q = f.get("query", "")
                cat = f.get("category", "")
                # Determine failure type
                ft = classify_failure(q, [], [], cat)
                counter[ft] += 1
            print(f"Failures: {len(failures)}/{data.get('overall', {}).get('total_cases')}")
            for k, v in counter.most_common():
                print(f"  {k:20s} {v}")
    else:
        analyze_dataset(args.dataset)
