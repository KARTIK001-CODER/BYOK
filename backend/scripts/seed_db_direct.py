import asyncio
import os
import sys

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import get_session_factory
from app.schemas.auth import RegisterRequest
from app.services.auth.service import AuthService
from app.services.documents.service import DocumentService
from app.services.ingestion.service import IngestionService
from app.services.knowledge_bases.service import KnowledgeBaseService


async def seed_data():
    session_factory = get_session_factory()
    async with session_factory() as session:
        for i in range(1, 21):
            try:
                # 1. Register User
                email = f"testuser_{i}@example.com"
                req = RegisterRequest(
                    email=email,
                    password="Password123!",
                    full_name=f"Test User {i}",
                    organization_name=f"Org {i}",
                )

                # We catch exceptions to skip if user exists
                try:
                    user, org, _, _, _ = await AuthService.register(session, req)
                    print(f"[{i}] User {user.email} created in Org {org.id}")
                except Exception as e:
                    print(f"[{i}] Skipping user {email} creation (may exist): {e}")
                    continue

                # 2. Create Knowledge Base
                kb = await KnowledgeBaseService.create_knowledge_base(
                    session=session,
                    organization_id=org.id,
                    name=f"Knowledge Base {i}",
                    description="Seed Data KB",
                    created_by=user.id,
                )
                print(f"[{i}] Knowledge Base {kb.id} created")

                # 3. Upload Files
                for f_idx in range(1, 4):
                    content = f"This is some dummy content for user {i} file {f_idx}. It contains important testing data. AI is the future. Testing RAG pipelines is fun."

                    doc, version = await DocumentService.upload_document(
                        session=session,
                        kb=kb,
                        organization_id=org.id,
                        user_id=user.id,
                        original_filename=f"dummy_file_{f_idx}.txt",
                        content=content.encode("utf-8"),
                        content_type="text/plain",
                    )
                    print(f"[{i}] File {f_idx} uploaded. Doc ID: {doc.id}")

                    # 4. Ingest (which will chunk & embed)
                    job = await IngestionService.process_document(
                        session=session,
                        document=doc,
                    )
                    print(f"[{i}] Document {doc.id} ingestion job: {job.id}")

            except Exception as e:
                print(f"[{i}] Fatal error processing user {i}: {e}")

        # Final commit just in case, though services should handle it
        await session.commit()
        print("Seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed_data())
