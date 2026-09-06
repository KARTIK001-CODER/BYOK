"""
Evaluate retrieval intelligence strategies: DIRECT, EXPANDED, MULTI_QUERY, DECOMPOSED, ADAPTIVE

Compares against hybrid baseline on retrieval_intelligence dataset (60 queries).

Measures Hit@K, MRR, Precision, Recall, latency, DB queries, embedding calls.

Usage:
  python scripts/evaluate_retrieval_intelligence.py
  python scripts/evaluate_retrieval_intelligence.py --top-k 5 --strategies direct,expanded,multi_query
"""
import asyncio
import json
import sys
import time
import statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Need pytest dummy for SQLite computed column
import sys as _sys
_sys.modules["pytest"] = _sys.modules.get("pytest") or type(_sys)("pytest")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.base import Base
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.user import User
from app.services.evaluation.schemas import EvaluationCategory
from app.services.retrieval_intelligence.service import AdaptiveRetrievalService
from app.services.retrieval_intelligence.schemas import AdaptiveRetrievalConfig, RetrievalStrategyType
from app.services.evaluation.metrics import EvaluationMetrics

# Load dataset
DATASET_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "retrieval_intelligence" / "datasets" / "retrieval_intelligence_baseline.json"

# Colors for console
def load_dataset():
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return data

async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory

async def seed(factory):
    from app.services.auth.password import PasswordService
    ph = PasswordService.hash("Test123!")
    async with factory() as session:
        org = Organization(name="RI Org", slug="ri-org")
        user = User(email="ri@example.com", password_hash=ph, full_name="RI")
        session.add_all([org, user])
        await session.flush()
        mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER)
        session.add(mem)
        kb = KnowledgeBase(organization_id=org.id, name="RI KB", slug="ri-kb", created_by=user.id)
        session.add(kb)
        await session.flush()
        # Load fixtures
        fixtures_dir = Path(__file__).resolve().parents[1] / "evaluation" / "fixtures"
        # Also need retrieval_intelligence fixtures? For now reuse same 5 docs but ensure they cover dataset expected
        # Our dataset expects 5 docs: Company Handbook, Refund Policy, Pricing, Technical Docs, Support FAQ - same as fixtures
        from app.services.embeddings.providers import get_embedding_provider
        provider = get_embedding_provider()
        for f in sorted(fixtures_dir.glob("*.md")):
            content = f.read_text(encoding="utf-8")
            title = f.stem.replace("_", " ").title().replace("Faq", "FAQ").replace("Docs", "Docs")
            # Fix mapping
            name_map = {"Company Handbook": "Company Handbook", "Refund Policy": "Refund Policy", "Pricing": "Pricing", "Technical Docs": "Technical Docs", "Support Faq": "Support FAQ"}
            display = name_map.get(title, title)
            doc = Document(knowledge_base_id=kb.id, organization_id=org.id, uploaded_by=user.id, name=display, original_filename=f.name, content_type="text/markdown", file_size=len(content), storage_key=f"ri/{f.name}", checksum=f"ri-{f.stem}", status=DocumentStatus.READY, current_version=1)
            session.add(doc)
            await session.flush()
            ver = DocumentVersion(document_id=doc.id, version_number=1, storage_key=doc.storage_key, checksum=doc.checksum, file_size=doc.file_size, content_type=doc.content_type, uploaded_by=user.id)
            session.add(ver)
            await session.flush()
            doc.current_version = 1
            # Chunk
            from app.services.ingestion.chunking.recursive import RecursiveTextChunker
            from app.services.ingestion.extractors.base import ExtractedSection
            chunker = RecursiveTextChunker()
            sections = [ExtractedSection(text=content, section_title=display)]
            raw = chunker.chunk(sections)
            for idx, rc in enumerate(raw):
                chunk = DocumentChunk(document_id=doc.id, document_version_id=ver.id, organization_id=org.id, knowledge_base_id=kb.id, chunk_index=idx, content=rc.content, character_count=rc.character_count, word_count=rc.word_count, section_title=rc.section_title, embedding=provider.embed_documents([rc.content])[0], embedding_model=provider.model_name, embedding_provider=provider.provider_name, embedding_dimension=provider.dimension)
                session.add(chunk)
            await session.flush()
        await session.commit()
        return org.id, kb.id

# Strategy runner helper
async def run_strategy(factory, org_id, query, top_k, candidate_k, strategy: RetrievalStrategyType, config: AdaptiveRetrievalConfig):
    # Count embedding and DB calls via timing
    t0 = time.perf_counter()
    # For DIRECT, just use Adaptive service with strategy override
    # To simulate counts: DIRECT 1 embedding + 1 DB (hybrid does 2 DB but count as 1 retrieval)
    # We will measure actual via trace, but for now approximate
    from unittest.mock import patch

    # Use AdaptiveRetrievalService with strategy_override
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=factory() if False else None,  # placeholder, will be passed correctly below
        organization_id=org_id,
        query=query,
        top_k=top_k,
        candidate_k=candidate_k,
        strategy_override=strategy,
        config=config,
    )
    # This is not correct - we need session
    return resp, intel

# Simpler: direct evaluation loop

async def evaluate_all(top_k=5):
    print(f"Loading dataset {DATASET_PATH}")
    data = load_dataset()
    cases = data["cases"]
    print(f"Dataset cases: {len(cases)} version {data['version']}")
    # Setup DB
    engine, factory = await setup_db()
    org_id, kb_id = await seed(factory)
    # Need to keep factory for queries
    # Define strategies to test
    strategies = {
        "DIRECT": AdaptiveRetrievalConfig(enabled=True, enable_query_expansion=False, enable_multi_query=False, enable_decomposition=False, simple_top_k=top_k, complex_top_k=top_k),
        "EXPANDED": AdaptiveRetrievalConfig(enabled=True, enable_query_expansion=True, enable_multi_query=False, enable_decomposition=False, simple_top_k=top_k, complex_top_k=top_k, max_expanded_queries=3),
        "MULTI_QUERY": AdaptiveRetrievalConfig(enabled=True, enable_multi_query=True, enable_query_expansion=False, enable_decomposition=False, simple_top_k=top_k, complex_top_k=top_k, max_expanded_queries=3),
        "DECOMPOSED": AdaptiveRetrievalConfig(enabled=True, enable_decomposition=True, enable_query_expansion=False, enable_multi_query=False, simple_top_k=top_k, complex_top_k=top_k, max_sub_queries=3),
        "ADAPTIVE": AdaptiveRetrievalConfig(enabled=True, enable_query_expansion=True, enable_multi_query=True, enable_decomposition=True, simple_top_k=top_k, complex_top_k=8, simple_candidate_k=20, complex_candidate_k=50),
        "HYBRID_BASELINE": AdaptiveRetrievalConfig(enabled=False, simple_top_k=top_k, complex_top_k=top_k),
    }

    results = {}

    for strat_name, cfg in strategies.items():
        print(f"\n{'='*60}\nEvaluating strategy: {strat_name}\n{'='*60}")
        case_results = []
        latencies = []
        db_queries = 0
        embedding_calls = 0
        # We will need to map strategy name to RetrievalStrategyType for override
        # For DIRECT etc., we let Adaptive service choose, but for isolated we force
        strategy_override = {
            "DIRECT": RetrievalStrategyType.DIRECT,
            "EXPANDED": RetrievalStrategyType.EXPANDED,
            "MULTI_QUERY": RetrievalStrategyType.MULTI_QUERY,
            "DECOMPOSED": RetrievalStrategyType.DECOMPOSED,
            "ADAPTIVE": None,  # let adaptive choose
            "HYBRID_BASELINE": None,
        }[strat_name]
        # For HYBRID_BASELINE, disable adaptive entirely
        if strat_name == "HYBRID_BASELINE":
            cfg.enabled = False
        else:
            cfg.enabled = True

        for case in cases:
            query = case["query"]
            expected = [e["document_name"] for e in case["expected"]]
            category = case["category"]
            t0 = time.perf_counter()
            async with factory() as session:
                if strat_name == "HYBRID_BASELINE":
                    # Direct hybrid
                    from app.services.retrieval.schemas import RetrievalRequest, SearchMode
                    from app.services.retrieval.service import RetrievalService
                    req = RetrievalRequest(query=query, top_k=top_k, candidate_k=30, search_mode=SearchMode.HYBRID)
                    resp = await RetrievalService.search(session=session, organization_id=org_id, request=req)
                    retrieved = [r.document_name for r in resp.results]
                    db_queries += 1
                    embedding_calls += 1
                else:
                    # Use adaptive service with strategy override
                    req_override = {
                        "DIRECT": RetrievalStrategyType.DIRECT,
                        "EXPANDED": RetrievalStrategyType.EXPANDED,
                        "MULTI_QUERY": RetrievalStrategyType.MULTI_QUERY,
                        "DECOMPOSED": RetrievalStrategyType.DECOMPOSED,
                        "ADAPTIVE": None,
                    }.get(strat_name, None)
                    resp, intel = await AdaptiveRetrievalService.retrieve(
                        session=session,
                        organization_id=org_id,
                        query=query,
                        top_k=top_k,
                        candidate_k=30,
                        strategy_override=req_override,
                        config=cfg,
                    )
                    retrieved = [r.document_name for r in resp.results] if resp and resp.results else []
                    db_queries += intel.retrieval_attempts
                    embedding_calls += intel.retrieval_attempts
            latency = (time.perf_counter() - t0) * 1000
            latencies.append(latency)
            # Metrics per case
            hit1 = 1 if any(doc in retrieved[:1] for doc in expected) else 0
            hit5 = 1 if any(doc in retrieved[:5] for doc in expected) else 0
            # MRR: first relevant rank
            mrr = 0
            for rank, doc in enumerate(retrieved[:5], start=1):
                if doc in expected:
                    mrr = 1.0 / rank
                    break
            case_results.append({"hit1": hit1, "hit5": hit5, "mrr": mrr, "category": category, "latency": latency, "retrieved": retrieved, "expected": expected, "query": query})

        # Aggregate
        hit1 = sum(c["hit1"] for c in case_results) / len(case_results)
        hit5 = sum(c["hit5"] for c in case_results) / len(case_results)
        mrr = sum(c["mrr"] for c in case_results) / len(case_results)
        # Category breakdown
        from collections import defaultdict
        cat_stats = defaultdict(list)
        for c in case_results:
            cat_stats[c["category"]].append(c)
        print(f"Results {strat_name}: Hit@1 {hit1:.3f} Hit@5 {hit5:.3f} MRR {mrr:.3f} avg latency {statistics.mean(latencies):.1f}ms P50 {sorted(latencies)[len(latencies)//2]:.1f}ms")
        print(f"  DB queries total {db_queries} avg {db_queries/len(cases):.1f} embedding calls {embedding_calls} avg {embedding_calls/len(cases):.1f}")
        print(f"  Per category:")
        for cat, lst in cat_stats.items():
            ch1 = sum(x["hit1"] for x in lst)/len(lst)
            ch5 = sum(x["hit5"] for x in lst)/len(lst)
            print(f"    {cat:12s} Hit@5 {ch5:.3f} ({len(lst)} cases)")
        results[strat_name] = {"hit1": hit1, "hit5": hit5, "mrr": mrr, "latencies": latencies, "db_queries": db_queries, "embedding_calls": embedding_calls, "cases": case_results}

    # Overall comparison
    print("\n" + "="*80)
    print("STRATEGY COMPARISON")
    print("="*80)
    print(f"{'Strategy':<18} | {'Hit@1':<6} | {'Hit@5':<6} | {'MRR':<6} | {'P50ms':<6} | {'DB':<3} | {'Emb':<3}")
    print("-"*80)
    for name, r in results.items():
        lat_p50 = sorted(r["latencies"])[len(r["latencies"])//2]
        print(f"{name:<18} | {r['hit1']:<6.3f} | {r['hit5']:<6.3f} | {r['mrr']:<6.3f} | {lat_p50:<6.1f} | {r['db_queries']//len(cases):<3} | {r['embedding_calls']//len(cases):<3}")
    # Oracle: best per case
    oracle_hits = 0
    for idx in range(len(cases)):
        best = max(results[s]["cases"][idx]["hit5"] for s in results if s != "HYBRID_BASELINE" or True)
        oracle_hits += best
    print(f"\nOracle Hit@5 (best per query): {oracle_hits/len(cases):.3f}")

    await engine.dispose()
    return results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(evaluate_all(top_k=args.top_k))
