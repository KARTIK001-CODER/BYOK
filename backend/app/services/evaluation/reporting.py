"""Reporting — console, JSON, Markdown."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.evaluation.schemas import EvaluationReport


def console_report(report: EvaluationReport) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("BYOK RETRIEVAL EVALUATION")
    lines.append("=" * 70)
    lines.append(f"Dataset:    {report.dataset_path} (v{report.dataset_version})")
    lines.append(f"Retriever:  {report.retriever} (top_k={report.top_k}, candidate_k={report.config.candidate_k})")
    lines.append(f"Cases:      {report.overall.total_cases}")
    lines.append(f"Timestamp:  {report.timestamp}")
    if report.git_commit:
        lines.append(f"Commit:     {report.git_commit}")
    lines.append("")
    lines.append("OVERALL")
    lines.append(f"  Hit@1:       {report.overall.hit_at_1:.3f}")
    lines.append(f"  Hit@3:       {report.overall.hit_at_3:.3f}")
    lines.append(f"  Hit@5:       {report.overall.hit_at_5:.3f}")
    if report.overall.hit_at_10 is not None:
        lines.append(f"  Hit@10:      {report.overall.hit_at_10:.3f}")
    lines.append(f"  MRR:         {report.overall.mrr:.3f}")
    lines.append(f"  NDCG@3:      {report.overall.ndcg_at_3:.3f}")
    lines.append(f"  NDCG@5:      {report.overall.ndcg_at_5:.3f}")
    if report.overall.ndcg_at_10 is not None:
        lines.append(f"  NDCG@10:     {report.overall.ndcg_at_10:.3f}")
    lines.append(f"  Precision@{report.top_k}: {report.overall.precision_at_k:.3f}")
    lines.append(f"  Recall@{report.top_k}:    {report.overall.recall_at_k:.3f}")
    lines.append("")
    lines.append("BY CATEGORY")
    for cat, metrics in sorted(report.by_category.items()):
        lines.append(f"  {cat:12s} Hit@5: {metrics.hit_at_5:.3f}  MRR: {metrics.mrr:.3f}  NDCG@5: {metrics.ndcg_at_5:.3f}  Prec@{report.top_k}: {metrics.precision_at_k:.3f}")
    if report.by_difficulty:
        lines.append("")
        lines.append("BY DIFFICULTY")
        for diff, metrics in sorted(report.by_difficulty.items()):
            lines.append(f"  {diff:12s} Hit@5: {metrics.hit_at_5:.3f}  MRR: {metrics.mrr:.3f}")
    lines.append("")
    if report.failures:
        lines.append(f"FAILURES ({len(report.failures)}/{report.overall.total_cases} misses):")
        for f in report.failures[:5]:
            lines.append(f"  - {f.case_id} [{f.category.value}] {f.query[:60]} -> rank {f.first_relevant_rank} ({f.status})")
    else:
        lines.append("FAILURES: 0 (all hit)")
    lines.append("")
    if report.worst_queries:
        lines.append("WORST QUERIES (lowest MRR):")
        for w in report.worst_queries[:5]:
            lines.append(f"  - {w.case_id} {w.query[:60]} -> MRR {w.mrr:.3f} rank {w.first_relevant_rank}")
    lines.append("=" * 70)
    return "\n".join(lines)


def write_json_report(report: EvaluationReport, output_dir: Path | str) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out / f"retrieval_eval_{report.retriever}_{ts}.json"
    # Use model_dump for full serialisation
    data = report.model_dump()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def write_markdown_report(report: EvaluationReport, output_dir: Path | str) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out / f"retrieval_eval_{report.retriever}_{ts}.md"
    lines: list[str] = []
    lines.append(f"# Retrieval Evaluation — {report.retriever} (top_k={report.top_k})")
    lines.append("")
    lines.append(f"- **Dataset:** `{report.dataset_path}` v`{report.dataset_version}`")
    lines.append(f"- **Cases:** {report.overall.total_cases}")
    lines.append(f"- **Timestamp:** {report.timestamp}")
    lines.append(f"- **Commit:** `{report.git_commit or 'n/a'}`")
    lines.append(f"- **Config:** `embedding={report.config.embedding_model} dim={report.config.embedding_dimension} candidate_k={report.config.candidate_k} rrf_k={report.config.rrf_k}`")
    lines.append("")
    lines.append("## Overall Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Hit@1 | {report.overall.hit_at_1:.3f} |")
    lines.append(f"| Hit@3 | {report.overall.hit_at_3:.3f} |")
    lines.append(f"| Hit@5 | {report.overall.hit_at_5:.3f} |")
    if report.overall.hit_at_10 is not None:
        lines.append(f"| Hit@10 | {report.overall.hit_at_10:.3f} |")
    lines.append(f"| MRR | {report.overall.mrr:.3f} |")
    lines.append(f"| NDCG@3 | {report.overall.ndcg_at_3:.3f} |")
    lines.append(f"| NDCG@5 | {report.overall.ndcg_at_5:.3f} |")
    if report.overall.ndcg_at_10 is not None:
        lines.append(f"| NDCG@10 | {report.overall.ndcg_at_10:.3f} |")
    lines.append(f"| Precision@{report.top_k} | {report.overall.precision_at_k:.3f} |")
    lines.append(f"| Recall@{report.top_k} | {report.overall.recall_at_k:.3f} |")
    lines.append("")
    lines.append("## By Category")
    lines.append("")
    lines.append("| Category | Hit@5 | MRR | NDCG@5 | Prec | Recall | Cases |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for cat, m in sorted(report.by_category.items()):
        lines.append(f"| {cat} | {m.hit_at_5:.3f} | {m.mrr:.3f} | {m.ndcg_at_5:.3f} | {m.precision_at_k:.3f} | {m.recall_at_k:.3f} | {m.total_cases} |")
    lines.append("")
    if report.by_difficulty:
        lines.append("## By Difficulty")
        lines.append("")
        lines.append("| Difficulty | Hit@5 | MRR | Cases |")
        lines.append("|---|---:|---:|---:|")
        for diff, m in sorted(report.by_difficulty.items()):
            lines.append(f"| {diff} | {m.hit_at_5:.3f} | {m.mrr:.3f} | {m.total_cases} |")
        lines.append("")
    lines.append("## Failures")
    lines.append("")
    if report.failures:
        for f in report.failures:
            exp = ", ".join(e.document_name or e.document_slug or "?" for e in f.expected)
            retr = ", ".join((r.document_name or r.chunk_id)[:20] for r in f.retrieved[:3])
            lines.append(f"- **{f.case_id}** [{f.category.value}/{f.difficulty.value}] `{f.query}` — expected `{exp}` — retrieved `{retr}` — rank `{f.first_relevant_rank}` — `{f.status}`")
    else:
        lines.append("No failures (all hit).")
    lines.append("")
    lines.append("## Worst Queries")
    lines.append("")
    for w in report.worst_queries:
        lines.append(f"- {w.case_id} MRR {w.mrr:.3f} rank {w.first_relevant_rank} — `{w.query}`")
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    # Simple heuristic
    if report.overall.hit_at_5 < 0.85:
        lines.append("- Retrieval Hit@5 below 0.85 — consider improving hybrid fusion or candidate_k.")
    if report.by_category.get("keyword") and report.by_category["keyword"].hit_at_5 < 0.85:
        lines.append("- Keyword category weak — verify GIN index and lexical matching.")
    if report.by_category.get("multi_hop") and report.by_category["multi_hop"].hit_at_5 < 0.75:
        lines.append("- Multi-hop weak — may need query decomposition or multi-query retrieval (future).")
    if not any("improve" in l for l in lines[-5:]):
        lines.append("- Baseline is strong; maintain via regression checks.")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
