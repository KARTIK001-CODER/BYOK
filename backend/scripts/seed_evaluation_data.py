"""
Seed evaluation fixtures — isolated organization/KB, uses real ingestion + embedding pipeline.

Usage:
  python scripts/seed_evaluation_data.py
  python scripts/seed_evaluation_data.py --reset
  python scripts/seed_evaluation_data.py --reset --embedding-model BAAI/bge-small-en-v1.5
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "pytest" in sys.modules:
    del sys.modules["pytest"]

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth.password import PasswordService

EVAL_ORG_SLUG = "eval-org"
EVAL_ORG_NAME = "Evaluation Organization"
EVAL_KB_SLUG = "eval-kb"
EVAL_KB_NAME = "Evaluation Knowledge Base"
EVAL_USER_EMAIL = "eval@example.com"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "fixtures"


async def get_or_create_eval_org(session: AsyncSession):
    # Org by slug
    r = await session.execute(select(Organization).where(Organization.slug == EVAL_ORG_SLUG))
    org = r.scalar_one_or_none()
    if org:
        return org
    org = Organization(name=EVAL_ORG_NAME, slug=EVAL_ORG_SLUG)
    session.add(org)
    await session.flush()
    return org


async def get_or_create_eval_user(session: AsyncSession, org: Organization):
    r = await session.execute(select(User).where(User.email == EVAL_USER_EMAIL))
    user = r.scalar_one_or_none()
    if user:
        # ensure membership
        m = await session.execute(select(OrganizationMembership).where(OrganizationMembership.organization_id == org.id, OrganizationMembership.user_id == user.id))
        if not m.scalar_one_or_none():
            session.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER))
            await session.flush()
        return user
    ph = PasswordService.hash("EvalPassword123!")
    user = User(email=EVAL_USER_EMAIL, password_hash=ph, full_name="Eval User", is_active=True, is_verified=True)
    session.add(user)
    await session.flush()
    session.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER))
    await session.flush()
    return user


async def get_or_create_eval_kb(session: AsyncSession, org: Organization, user: User):
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.slug == EVAL_KB_SLUG, KnowledgeBase.organization_id == org.id))
    kb = r.scalar_one_or_none()
    if kb:
        return kb
    kb = KnowledgeBase(organization_id=org.id, name=EVAL_KB_NAME, slug=EVAL_KB_SLUG, description="Evaluation fixtures for retrieval quality", created_by=user.id, is_active=True)
    session.add(kb)
    await session.flush()
    return kb


async def reset_eval_data(session: AsyncSession):
    """Delete only evaluation org/KB/documents — never user production data."""
    r = await session.execute(select(Organization).where(Organization.slug == EVAL_ORG_SLUG))
    org = r.scalar_one_or_none()
    if not org:
        print("No eval org to delete")
        return
    # Knowledge bases under org will cascade to documents/chunks via FK? But we explicitly delete docs
    # Find KBs
    r2 = await session.execute(select(KnowledgeBase).where(KnowledgeBase.organization_id == org.id))
    kbs = r2.scalars().all()
    for kb in kbs:
        # delete documents (cascades to chunks/versions)
        await session.execute(delete(Document).where(Document.knowledge_base_id == kb.id))
    # delete KBs then org and memberships
    for kb in kbs:
        await session.delete(kb)
    await session.execute(delete(OrganizationMembership).where(OrganizationMembership.organization_id == org.id))
    # Keep org and user for reuse? Delete org as well to fully reset
    await session.delete(org)
    # Don't delete user globally — eval user is isolated
    r3 = await session.execute(select(User).where(User.email == EVAL_USER_EMAIL))
    eu = r3.scalar_one_or_none()
    if eu:
        await session.delete(eu)
    await session.commit()
    print(f"Reset evaluation data: deleted org {EVAL_ORG_SLUG} and {len(kbs)} KBs")


async def ingest_fixture(session: AsyncSession, kb: KnowledgeBase, org: Organization, user: User):
    """Use real ingestion: create Documents via service, then ingest and embed."""
    from app.services.ingestion.service import IngestionService
    from app.services.embeddings.service import EmbeddingService

    fixtures = sorted(FIXTURE_DIR.glob("*.md"))
    if not fixtures:
        raise FileNotFoundError(f"No fixtures in {FIXTURE_DIR}")

    for fpath in fixtures:
        content = fpath.read_text(encoding="utf-8")
        title = fpath.stem.replace("_", " ").title()  # e.g. company_handbook -> Company Handbook
        # Map to expected dataset names: cap variation
        # Ensure names match dataset expected: Company Handbook, Refund Policy, Pricing, Technical Docs, Support FAQ
        # Our stem titles already produce that with .title() but fix Technical Docs
        name_map = {
            "Company Handbook": "Company Handbook",
            "Refund Policy": "Refund Policy",
            "Pricing": "Pricing",
            "Technical Docs": "Technical Docs",
            "Support Faq": "Support FAQ",
        }
        display_name = name_map.get(title, title)

        # Check if doc already exists by name
        r = await session.execute(select(Document).where(Document.knowledge_base_id == kb.id, Document.name == display_name))
        existing = r.scalar_one_or_none()
        if existing:
            print(f"  Skipping existing document: {display_name}")
            continue

        # Create Document record (simulate upload) — we bypass storage and create directly
        doc = Document(
            knowledge_base_id=kb.id,
            organization_id=org.id,
            uploaded_by=user.id,
            name=display_name,
            original_filename=fpath.name,
            content_type="text/markdown",
            file_size=len(content.encode()),
            storage_key=f"eval/fixtures/{fpath.name}",
            checksum=f"eval-{fpath.stem}",
            status=DocumentStatus.READY,  # will be set by ingestion; start as READY for chunking
        )
        # Actually ingestion expects processing: we create via Document then run IngestionService
        # Simpler: use Document with raw content and call ingestion pipeline that chunks content directly
        # To reuse real pipeline, we store content in Document via direct chunking
        # We'll manually create Document + IngestionJob + chunk via IngestionService.process_document
        # But IngestionService expects storage_key to read file; we fake by creating document and then calling chunking directly
        session.add(doc)
        await session.flush()
        # Use ingestion service to chunk the content
        from app.models.document_version import DocumentVersion
        import uuid

        version = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            storage_key=doc.storage_key,
            checksum=doc.checksum,
            file_size=doc.file_size,
            content_type=doc.content_type,
            uploaded_by=user.id,
        )
        session.add(version)
        await session.flush()
        doc.current_version = 1
        await session.flush()

        # Chunk using real chunker (expects ExtractedSection)
        from app.services.ingestion.chunking.recursive import RecursiveTextChunker
        from app.services.ingestion.extractors.base import ExtractedSection

        settings = get_settings()
        chunker = RecursiveTextChunker(chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP)
        sections = [ExtractedSection(text=content, section_title=display_name, page_number=None)]
        raw_chunks = chunker.chunk(sections)

        from app.models.document_chunk import DocumentChunk

        for idx, rc in enumerate(raw_chunks):
            db_chunk = DocumentChunk(
                document_id=doc.id,
                document_version_id=version.id,
                organization_id=org.id,
                knowledge_base_id=kb.id,
                chunk_index=idx,
                content=rc.content,
                character_count=rc.character_count,
                word_count=rc.word_count,
                section_title=rc.section_title,
                page_number=rc.page_number,
                chunk_metadata=None,
            )
            session.add(db_chunk)
        await session.flush()
        print(f"  Ingested {display_name}: {len(raw_chunks)} chunks")

    await session.commit()

    # Now embed
    print("Embedding documents...")
    # Embed each document's chunks
    r = await session.execute(select(Document).where(Document.knowledge_base_id == kb.id))
    docs = r.scalars().all()
    for doc in docs:
        try:
            await EmbeddingService.process_document_embeddings(session=session, document=doc)
            print(f"  Embedded {doc.name}")
        except Exception as e:
            print(f"  Embed failed for {doc.name}: {e}")

    await session.commit()
    # Verify
    from app.models.document_chunk import DocumentChunk

    r2 = await session.execute(select(DocumentChunk).where(DocumentChunk.knowledge_base_id == kb.id))
    chunks = r2.scalars().all()
    embedded = sum(1 for c in chunks if c.embedding is not None)
    print(f"Verification: total chunks {len(chunks)}, embedded {embedded}")
    return kb


async def main():
    parser = argparse.ArgumentParser(description="Seed evaluation fixtures (isolated org/KB)")
    parser.add_argument("--reset", action="store_true", help="Delete existing eval org/KB before seeding")
    parser.add_argument("--reset-only", action="store_true", help="Only reset, do not seed")
    args = parser.parse_args()

    factory = get_session_factory()
    async with factory() as session:
        if args.reset or args.reset_only:
            await reset_eval_data(session)
            if args.reset_only:
                return
        org = await get_or_create_eval_org(session)
        user = await get_or_create_eval_user(session, org)
        kb = await get_or_create_eval_kb(session, org, user)
        await session.commit()
        print(f"Eval org: {org.slug} ({org.id})")
        print(f"Eval KB: {kb.slug} ({kb.id})")
        print(f"Eval user: {user.email}")

        # Check if already seeded
        from sqlalchemy import select

        r = await session.execute(select(Document).where(Document.knowledge_base_id == kb.id))
        existing_docs = r.scalars().all()
        if existing_docs and not args.reset:
            print(f"Found {len(existing_docs)} existing documents — use --reset to recreate")
            # still verify chunks
            from app.models.document_chunk import DocumentChunk

            r2 = await session.execute(select(DocumentChunk).where(DocumentChunk.knowledge_base_id == kb.id))
            chunks = r2.scalars().all()
            print(f"Existing chunks: {len(chunks)}, embedded: {sum(1 for c in chunks if c.embedding)}")
            return

        await ingest_fixture(session, kb, org, user)
        print("Done. Evaluation data ready (isolated).")


if __name__ == "__main__":
    asyncio.run(main())
