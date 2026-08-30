import pytest
from fastapi import status
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.document import DocumentStatus
from app.models.user import User


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
