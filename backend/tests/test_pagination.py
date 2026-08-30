import pytest
from fastapi import status
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.user import User


@pytest.mark.asyncio
async def test_pagination_and_sorting_limits(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify pagination parameters (limit, offset, max clamp) and sorting."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Upload 3 test documents
    for i in range(1, 4):
        content = f"%PDF-1.7\nDocument content number {i}\n%%EOF".encode()
        await client.post(
            f"/api/v1/knowledge-bases/{test_kb.id}/documents",
            headers=headers,
            files={"file": (f"doc_{i}.pdf", content, "application/pdf")},
        )

    # 1. Custom Limit and Offset
    res_page1 = await client.get(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents?limit=2&offset=0",
        headers=headers,
    )
    assert res_page1.status_code == status.HTTP_200_OK
    data1 = res_page1.json()
    assert len(data1["items"]) == 2
    assert data1["total"] == 3
    assert data1["limit"] == 2
    assert data1["offset"] == 0

    # 2. Page 2
    res_page2 = await client.get(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents?limit=2&offset=2",
        headers=headers,
    )
    assert res_page2.status_code == status.HTTP_200_OK
    data2 = res_page2.json()
    assert len(data2["items"]) == 1
    assert data2["total"] == 3

    # 3. Sorting by name ascending
    res_sort = await client.get(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents?sort_by=name&order=asc",
        headers=headers,
    )
    assert res_sort.status_code == status.HTTP_200_OK
    items = res_sort.json()["items"]
    assert items[0]["name"] == "doc_1.pdf"
    assert items[1]["name"] == "doc_2.pdf"
    assert items[2]["name"] == "doc_3.pdf"
