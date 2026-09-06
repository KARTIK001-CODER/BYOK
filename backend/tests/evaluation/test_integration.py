"""Integration: fixture seeding → ingestion → embedding → vector/keyword/hybrid → metrics → report."""
import sys
from pathlib import Path

sys.modules["pytest"] = sys.modules.get("pytest") or type(sys)("pytest")

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.base import Base
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.models.membership import OrganizationMembership, OrganizationRole
from app.services.evaluation.runner import EvaluationRunner
from app.services.evaluation.dataset import EvaluationDatasetLoader


@pytest.mark.asyncio
async def test_full_evaluation_pipeline(tmp_path):
    # Tiny dataset for speed
    dataset_content = {
        "version": "1.0-test",
        "cases": [
            {"id": "eval_001", "query": "refund policy money back?", "category": "semantic", "difficulty": "easy", "expected": [{"document_name": "Refund Policy"}]},
            {"id": "eval_002", "query": "cancellation_fee", "category": "keyword", "expected": [{"document_name": "Refund Policy"}]},
            {"id": "eval_003", "query": "What is the maximum file size?", "category": "factual", "expected": [{"document_name": "Pricing"}]},
        ],
    }
    import json
    p = tmp_path / "ds.json"
    p.write_text(json.dumps(dataset_content), encoding="utf-8")

    # In-memory DB
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # Seed minimal org/kb/docs
    from app.services.embeddings.providers import get_embedding_provider

    provider = get_embedding_provider()
    org_id = None
    async with factory() as session:
        org = Organization(name="Eval Org", slug="eval-org-int")
        user = User(email="eval-int@example.com", password_hash="hash", full_name="Eval")
        session.add_all([org, user])
        await session.flush()
        mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER)
        session.add(mem)
        kb = KnowledgeBase(organization_id=org.id, name="Eval KB", slug="eval-kb-int", created_by=user.id)
        session.add(kb)
        await session.flush()
        org_id = org.id

        # Create two docs matching expected names
        for title, content in [("Refund Policy", "Refund policy: cancellation_fee 15% within 14 days money back."), ("Pricing", "Pricing: maximum file size 25 MB per document.")]:
            doc = Document(knowledge_base_id=kb.id, organization_id=org.id, uploaded_by=user.id, name=title, original_filename=f"{title}.md", content_type="text/markdown", file_size=len(content), storage_key=f"eval/{title}.md", checksum="chk", status=DocumentStatus.READY, current_version=1)
            session.add(doc)
            await session.flush()
            ver = DocumentVersion(document_id=doc.id, version_number=1, storage_key=doc.storage_key, checksum=doc.checksum, file_size=doc.file_size, content_type=doc.content_type, uploaded_by=user.id)
            session.add(ver)
            await session.flush()
            emb = provider.embed_documents([content])[0]
            chunk = DocumentChunk(document_id=doc.id, document_version_id=ver.id, organization_id=org.id, knowledge_base_id=kb.id, chunk_index=0, content=content, character_count=len(content), word_count=len(content.split()), section_title=title, embedding=emb, embedding_model=provider.model_name, embedding_provider=provider.provider_name, embedding_dimension=provider.dimension)
            session.add(chunk)
        await session.commit()

    # Run evaluation for all three retrievers
    for retriever in ["vector", "keyword", "hybrid"]:
        runner = EvaluationRunner(dataset_path=p, retriever=retriever, top_k=5)
        async with factory() as session:
            report = await runner.run(session=session, organization_id=org_id)
            assert report.overall.total_cases == 3
            # Hybrid should at least not crash; vector should hit refund
            assert report.retriever == retriever

    await engine.dispose()
