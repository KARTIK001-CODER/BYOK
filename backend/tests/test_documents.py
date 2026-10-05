import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.document import DocumentStatus
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.user import User
from app.services.auth.password import PasswordService


@pytest.mark.asyncio
async def test_upload_valid_pdf_document(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify uploading a valid PDF document with %PDF magic header."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = b"%PDF-1.7\nSample PDF body content for RAG testing\n%%EOF"
    files = {"file": ("architecture_overview.pdf", pdf_bytes, "application/pdf")}

    response = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files=files,
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    doc = data["document"]
    version = data["version"]

    assert doc["original_filename"] == "architecture_overview.pdf"
    assert doc["content_type"] == "application/pdf"
    assert doc["file_size"] == len(pdf_bytes)
    assert doc["status"] == DocumentStatus.UPLOADED.value
    assert doc["knowledge_base_id"] == test_kb.id
    assert doc["organization_id"] == test_kb.organization_id
    assert doc["current_version"] == 1
    assert "storage_key" in doc

    assert version["document_id"] == doc["id"]
    assert version["version_number"] == 1
    assert version["checksum"] == doc["checksum"]


@pytest.mark.asyncio
async def test_upload_valid_txt_and_markdown(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify uploading plain text and markdown documents."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Plain Text
    txt_bytes = b"Hello, this is a plain text test document."
    res_txt = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("notes.txt", txt_bytes, "text/plain")},
    )
    assert res_txt.status_code == status.HTTP_201_CREATED
    assert res_txt.json()["document"]["content_type"] == "text/plain"

    # 2. Markdown
    md_bytes = b"# Architecture\n\nThis is a markdown file with headings."
    res_md = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("readme.md", md_bytes, "text/markdown")},
    )
    assert res_md.status_code == status.HTTP_201_CREATED
    assert res_md.json()["document"]["content_type"] == "text/markdown"


@pytest.mark.asyncio
async def test_upload_valid_docx(client: AsyncClient, test_user_and_org: dict, test_kb) -> None:
    """Verify uploading a valid DOCX file containing ZIP magic header."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    docx_bytes = b"PK\x03\x04\x14\x00\x00\x00Mocked DOCX zip structure content"
    files = {
        "file": (
            "spec.docx",
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }

    response = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files=files,
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert "wordprocessingml" in response.json()["document"]["content_type"]


@pytest.mark.asyncio
async def test_reject_invalid_pdf_magic_bytes(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify PDF with corrupted/missing %PDF header is rejected with 422."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    corrupt_pdf = b"NOT_A_REAL_PDF_HEADER_CONTENT"
    response = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("fake.pdf", corrupt_pdf, "application/pdf")},
    )
    assert response.status_code == 422
    assert "Invalid PDF" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_reject_unsupported_file_extension(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify executable or unsupported extensions are rejected."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00"
    response = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("malware.exe", exe_bytes, "application/octet-stream")},
    )
    assert response.status_code == 422
    assert "Unsupported file extension" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_duplicate_document_checksum_rejected(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify uploading an identical document to the same KB raises a 409 Conflict."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = b"%PDF-1.7\nDuplicate test payload\n%%EOF"

    # 1. First upload succeeds
    res1 = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("original.pdf", pdf_bytes, "application/pdf")},
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # 2. Second upload with same content -> 409 Conflict
    res2 = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("another_name.pdf", pdf_bytes, "application/pdf")},
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "Duplicate document" in res2.json()["error"]["message"]
    assert "existing_document_id" in res2.json()["error"]["details"]


@pytest.mark.asyncio
async def test_list_and_archive_document(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify listing documents, getting details, archiving, and soft deleting."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload Document
    pdf_bytes = b"%PDF-1.7\nLifecycle document test\n%%EOF"
    res_upload = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("lifecycle.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = res_upload.json()["document"]["id"]

    # 2. List Documents in KB
    res_list = await client.get(f"/api/v1/knowledge-bases/{test_kb.id}/documents", headers=headers)
    assert res_list.status_code == status.HTTP_200_OK
    assert res_list.json()["total"] >= 1

    # 3. Get Document Details
    res_get = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert res_get.status_code == status.HTTP_200_OK
    assert res_get.json()["id"] == doc_id

    # 4. Archive Document
    res_patch = await client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
        json={"status": DocumentStatus.ARCHIVED.value},
    )
    assert res_patch.status_code == status.HTTP_200_OK
    assert res_patch.json()["status"] == DocumentStatus.ARCHIVED.value

    # 5. Soft Delete Document
    res_del = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
    assert res_del.status_code == status.HTTP_200_OK

    # 6. Verify deleted document is not returned
    res_get_deleted = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert res_get_deleted.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_document_response_embedding_status_and_chunk_count(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify document responses expose embedding_status and chunk_count across lifecycle."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload a markdown file
    md_content = (
        b"# Architecture Overview\n\nSection 1 text with details.\n\nSection 2 text with more info."
    )
    res_upload = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("architecture_doc.md", md_content, "text/markdown")},
    )
    assert res_upload.status_code == status.HTTP_201_CREATED
    upload_doc = res_upload.json()["document"]
    doc_id = upload_doc["id"]

    # Initial upload: chunk_count is 0, embedding_status is None
    assert upload_doc["chunk_count"] == 0
    assert upload_doc["embedding_status"] is None
    assert upload_doc["status"] == DocumentStatus.UPLOADED.value

    # Verify single document detail get
    res_get_initial = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert res_get_initial.status_code == status.HTTP_200_OK
    initial_data = res_get_initial.json()
    assert initial_data["chunk_count"] == 0
    assert initial_data["embedding_status"] is None

    # 2. Trigger ingestion (chunking)
    res_ingest = await client.post(f"/api/v1/documents/{doc_id}/ingest", headers=headers)
    assert res_ingest.status_code == status.HTTP_200_OK

    # Verify document detail has chunk_count > 0 after ingestion
    res_get_post_ingest = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert res_get_post_ingest.status_code == status.HTTP_200_OK
    post_ingest_data = res_get_post_ingest.json()
    assert post_ingest_data["chunk_count"] > 0
    assert post_ingest_data["status"] == DocumentStatus.READY.value
    assert post_ingest_data["embedding_status"] is None

    # 3. Trigger embedding generation
    res_embed = await client.post(f"/api/v1/documents/{doc_id}/embed", headers=headers)
    assert res_embed.status_code == status.HTTP_200_OK

    # Verify document detail has embedding_status == COMPLETED
    res_get_post_embed = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert res_get_post_embed.status_code == status.HTTP_200_OK
    post_embed_data = res_get_post_embed.json()
    assert post_embed_data["chunk_count"] == post_ingest_data["chunk_count"]
    assert post_embed_data["status"] == DocumentStatus.READY.value
    assert post_embed_data["embedding_status"] == "COMPLETED"

    # 4. Verify list endpoint returns embedding_status and chunk_count
    res_list = await client.get(f"/api/v1/knowledge-bases/{test_kb.id}/documents", headers=headers)
    assert res_list.status_code == status.HTTP_200_OK
    items = res_list.json()["items"]
    target_item = next((item for item in items if item["id"] == doc_id), None)
    assert target_item is not None
    assert target_item["chunk_count"] == post_embed_data["chunk_count"]
    assert target_item["embedding_status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_document_storage_key_role_isolation(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify storage_key is exposed to OWNER/ADMIN but redacted (None) for MEMBER."""
    # 1. Owner uploads a document
    owner: User = test_user_and_org["user"]
    owner_token = create_access_token(owner.id)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    res_upload = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=owner_headers,
        files={"file": ("classified.txt", b"Secret data", "text/plain")},
    )
    assert res_upload.status_code == status.HTTP_201_CREATED
    doc_id = res_upload.json()["document"]["id"]

    # Owner sees storage_key
    res_owner_get = await client.get(f"/api/v1/documents/{doc_id}", headers=owner_headers)
    assert res_owner_get.status_code == status.HTTP_200_OK
    assert res_owner_get.json()["storage_key"] is not None
    assert "org/" in res_owner_get.json()["storage_key"]

    res_owner_list = await client.get(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents", headers=owner_headers
    )
    assert res_owner_list.status_code == status.HTTP_200_OK
    owner_item = next(d for d in res_owner_list.json()["items"] if d["id"] == doc_id)
    assert owner_item["storage_key"] is not None

    # 2. Member creates account and membership
    member = User(
        email="doc_member@example.com",
        password_hash=PasswordService.hash("Pass12345!"),
        full_name="Doc Member",
        is_active=True,
    )
    db_session.add(member)
    await db_session.flush()

    membership = OrganizationMembership(
        organization_id=test_kb.organization_id,
        user_id=member.id,
        role=OrganizationRole.MEMBER,
    )
    db_session.add(membership)
    await db_session.commit()

    member_token = create_access_token(member.id)
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # Member can view document, but storage_key must be None
    res_member_get = await client.get(f"/api/v1/documents/{doc_id}", headers=member_headers)
    assert res_member_get.status_code == status.HTTP_200_OK
    assert res_member_get.json()["storage_key"] is None

    # Member list documents also redacts storage_key
    res_member_list = await client.get(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents", headers=member_headers
    )
    assert res_member_list.status_code == status.HTTP_200_OK
    member_item = next(d for d in res_member_list.json()["items"] if d["id"] == doc_id)
    assert member_item["storage_key"] is None


@pytest.mark.asyncio
async def test_delete_document_rbac(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify deleting a document requires ADMIN/OWNER role, MEMBER receives 403."""
    owner: User = test_user_and_org["user"]
    owner_token = create_access_token(owner.id)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    res_upload = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=owner_headers,
        files={"file": ("to_delete.txt", b"Delete me", "text/plain")},
    )
    assert res_upload.status_code == status.HTTP_201_CREATED
    doc_id = res_upload.json()["document"]["id"]

    # Member tries to delete -> 403 Forbidden
    member = User(
        email="del_member@example.com",
        password_hash=PasswordService.hash("Pass12345!"),
        full_name="Del Member",
        is_active=True,
    )
    db_session.add(member)
    await db_session.flush()

    membership = OrganizationMembership(
        organization_id=test_kb.organization_id,
        user_id=member.id,
        role=OrganizationRole.MEMBER,
    )
    db_session.add(membership)
    await db_session.commit()

    member_token = create_access_token(member.id)
    member_headers = {"Authorization": f"Bearer {member_token}"}

    res_member_del = await client.delete(f"/api/v1/documents/{doc_id}", headers=member_headers)
    assert res_member_del.status_code == status.HTTP_403_FORBIDDEN
    assert "ADMIN or OWNER" in res_member_del.json()["error"]["message"]

    # Document still exists
    res_check = await client.get(f"/api/v1/documents/{doc_id}", headers=owner_headers)
    assert res_check.status_code == status.HTTP_200_OK

    # Owner deletes -> 200 OK
    res_owner_del = await client.delete(f"/api/v1/documents/{doc_id}", headers=owner_headers)
    assert res_owner_del.status_code == status.HTTP_200_OK

    # Soft deleted -> 404
    res_after = await client.get(f"/api/v1/documents/{doc_id}", headers=owner_headers)
    assert res_after.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_document_chunk_pagination_and_isolation(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify chunk browsing handles pagination (limit/offset) and non-chunked state."""
    owner: User = test_user_and_org["user"]
    owner_token = create_access_token(owner.id)
    headers = {"Authorization": f"Bearer {owner_token}"}

    # Upload document
    res_upload = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={
            "file": (
                "pagination_doc.md",
                b"# Title\n\nParagraph 1\n\nParagraph 2\n\nParagraph 3",
                "text/markdown",
            )
        },
    )
    doc_id = res_upload.json()["document"]["id"]

    # Before ingestion, chunks should be empty (0 chunks)
    res_empty_chunks = await client.get(
        f"/api/v1/documents/{doc_id}/chunks?limit=10&offset=0", headers=headers
    )
    assert res_empty_chunks.status_code == status.HTTP_200_OK
    assert res_empty_chunks.json()["total"] == 0
    assert len(res_empty_chunks.json()["items"]) == 0

    # Ingest document
    await client.post(f"/api/v1/documents/{doc_id}/ingest", headers=headers)

    # After ingestion, verify paginated chunks
    res_chunks = await client.get(
        f"/api/v1/documents/{doc_id}/chunks?limit=1&offset=0", headers=headers
    )
    assert res_chunks.status_code == status.HTTP_200_OK
    data = res_chunks.json()
    assert data["total"] > 0
    assert len(data["items"]) == 1
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert data["items"][0]["chunk_index"] == 0
