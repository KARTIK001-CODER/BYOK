import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.evaluation.metrics import RetrievalMetrics
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.embeddings.providers import get_embedding_provider
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService

logging.basicConfig(level=logging.WARNING)


class RetrievalEvaluator:
    """Benchmark runner evaluating Vector, Keyword, and Hybrid search against a golden dataset."""

    def __init__(self, dataset_path: Path | None = None) -> None:
        if dataset_path is None:
            dataset_path = Path(__file__).parent / "datasets" / "retrieval_examples.json"
        self.dataset_path = dataset_path

    async def run_evaluation(self, k: int = 5) -> dict[str, dict[str, float]]:
        """
        Execute evaluation suite over golden benchmark dataset.

        Returns:
            dict: Summary metrics (Recall, Precision, MRR) for vector, keyword, and hybrid modes.
        """
        with open(self.dataset_path, encoding="utf-8") as f:
            data = json.load(f)

        docs_data = data["documents"]
        queries_data = data["queries"]

        # Setup in-memory test database
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        embedding_provider = get_embedding_provider()

        # Seed data
        doc_id_to_chunk_id: dict[str, str] = {}

        async with session_factory() as session:
            org = Organization(name="Eval Org", slug="eval-org")
            user = User(email="eval@example.com", password_hash="hash", full_name="Eval User")
            session.add_all([org, user])
            await session.flush()

            kb = KnowledgeBase(
                organization_id=org.id, name="Eval KB", slug="eval-kb", created_by=user.id
            )
            session.add(kb)
            await session.flush()

            for doc_item in docs_data:
                doc = Document(
                    id=doc_item["id"],
                    knowledge_base_id=kb.id,
                    organization_id=org.id,
                    uploaded_by=user.id,
                    name=doc_item["title"],
                    original_filename=f"{doc_item['id']}.md",
                    content_type="text/markdown",
                    file_size=len(doc_item["content"]),
                    storage_key=f"eval/{doc_item['id']}.md",
                    checksum="eval-checksum",
                    status=DocumentStatus.READY,
                    current_version=1,
                )
                session.add(doc)
                await session.flush()

                doc_ver = DocumentVersion(
                    document_id=doc.id,
                    version_number=1,
                    storage_key=doc.storage_key,
                    checksum=doc.checksum,
                    file_size=doc.file_size,
                    content_type=doc.content_type,
                    uploaded_by=user.id,
                )
                session.add(doc_ver)
                await session.flush()

                # Generate embedding for content
                emb = embedding_provider.embed_documents([doc_item["content"]])[0]

                chunk = DocumentChunk(
                    document_id=doc.id,
                    document_version_id=doc_ver.id,
                    organization_id=org.id,
                    knowledge_base_id=kb.id,
                    chunk_index=0,
                    content=doc_item["content"],
                    character_count=len(doc_item["content"]),
                    word_count=len(doc_item["content"].split()),
                    section_title=doc_item["title"],
                    embedding=emb,
                    embedding_model=embedding_provider.model_name,
                    embedding_provider=embedding_provider.provider_name,
                    embedding_dimension=embedding_provider.dimension,
                )
                session.add(chunk)
                await session.flush()
                doc_id_to_chunk_id[doc.id] = chunk.id

            await session.commit()

            # Run evaluation across modes
            results_by_mode: dict[str, list[dict[str, float]]] = {
                "Vector Search": [],
                "Keyword Search": [],
                "Hybrid Search (RRF)": [],
            }

            mode_mapping = {
                "Vector Search": SearchMode.VECTOR,
                "Keyword Search": SearchMode.KEYWORD,
                "Hybrid Search (RRF)": SearchMode.HYBRID,
            }

            for mode_name, search_mode in mode_mapping.items():
                for q in queries_data:
                    query_text = q["query"]
                    # Map expected doc IDs to chunk IDs
                    expected_chunk_ids = [
                        doc_id_to_chunk_id[doc_id]
                        for doc_id in q["relevant_doc_ids"]
                        if doc_id in doc_id_to_chunk_id
                    ]

                    req = RetrievalRequest(
                        query=query_text,
                        top_k=k,
                        candidate_k=50,
                        search_mode=search_mode,
                    )
                    resp = await RetrievalService.search(
                        session=session,
                        organization_id=org.id,
                        request=req,
                        provider=embedding_provider,
                    )

                    retrieved_chunk_ids = [res.chunk_id for res in resp.results]
                    metrics = RetrievalMetrics.evaluate_query(
                        retrieved_ids=retrieved_chunk_ids,
                        relevant_ids=expected_chunk_ids,
                        k=k,
                    )
                    results_by_mode[mode_name].append(metrics)

        await engine.dispose()

        # Aggregate metrics
        aggregated: dict[str, dict[str, float]] = {}
        for mode_name, query_metrics in results_by_mode.items():
            count = len(query_metrics)
            avg_recall = sum(m[f"recall@{k}"] for m in query_metrics) / count
            avg_precision = sum(m[f"precision@{k}"] for m in query_metrics) / count
            avg_mrr = sum(m["mrr"] for m in query_metrics) / count

            aggregated[mode_name] = {
                f"Recall@{k}": round(avg_recall, 4),
                f"Precision@{k}": round(avg_precision, 4),
                "MRR": round(avg_mrr, 4),
            }

        return aggregated


def print_evaluation_report(results: dict[str, dict[str, float]], k: int = 5) -> None:
    """Print ASCII comparison table of evaluation results."""
    print("=" * 65)
    print(f"RAGForge Phase 6 Retrieval Evaluation Benchmark (Top-K = {k})")
    print("=" * 65)
    header = f"{'Search Strategy':<25} | {f'Recall@{k}':<10} | {f'Precision@{k}':<12} | {'MRR':<8}"
    print(header)
    print("-" * 65)
    for strategy, metrics in results.items():
        row = (
            f"{strategy:<25} | "
            f"{metrics[f'Recall@{k}']:<10.4f} | "
            f"{metrics[f'Precision@{k}']:<12.4f} | "
            f"{metrics['MRR']:<8.4f}"
        )
        print(row)
    print("=" * 65)


async def main() -> None:
    evaluator = RetrievalEvaluator()
    results = await evaluator.run_evaluation(k=5)
    print_evaluation_report(results, k=5)


if __name__ == "__main__":
    asyncio.run(main())
