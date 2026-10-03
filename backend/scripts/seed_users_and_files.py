import asyncio
import uuid

import httpx

API_BASE = "http://localhost:8000/api/v1"


async def create_user(client: httpx.AsyncClient, i: int):
    # Register user
    email = f"testuser{i}_{uuid.uuid4().hex[:8]}@example.com"
    password = "Password123!"
    full_name = f"Test User {i}"

    register_payload = {
        "email": email,
        "password": password,
        "full_name": full_name,
        "organization_name": f"Org {i}",
    }

    res = await client.post(f"{API_BASE}/auth/register", json=register_payload)
    if res.status_code != 201:
        print(f"Failed to register user {i}: {res.text}")
        return None

    data = res.json()
    token = data["tokens"]["access_token"]
    org_id = data["organization"]["id"]
    print(f"[{i}] User {email} registered (Org: {org_id})")

    # Create KB
    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}
    kb_payload = {
        "name": f"Knowledge Base {i}",
        "description": "Seed data KB",
        "organization_id": org_id,
    }
    res = await client.post(f"{API_BASE}/knowledge-bases", json=kb_payload, headers=headers)
    if res.status_code != 201:
        print(f"Failed to create KB for user {i}: {res.text}")
        return None

    kb_id = res.json()["id"]
    print(f"[{i}] Knowledge Base {kb_id} created.")

    # Upload files
    for f_idx in range(1, 4):
        file_content = f"This is some dummy content for user {i} file {f_idx}. It contains important testing data. AI is the future. Testing RAG pipelines is fun."
        files = {"file": (f"dummy_file_{f_idx}.txt", file_content.encode("utf-8"), "text/plain")}
        res = await client.post(
            f"{API_BASE}/knowledge-bases/{kb_id}/documents", files=files, headers=headers
        )
        if res.status_code != 201:
            print(f"[{i}] Failed to upload file {f_idx}: {res.text}")
            continue

        doc_id = res.json()["document"]["id"]
        print(f"[{i}] File {f_idx} uploaded. Doc ID: {doc_id}")

        # Trigger Ingestion
        res = await client.post(f"{API_BASE}/documents/{doc_id}/ingest", headers=headers)
        if res.status_code != 200:
            print(f"[{i}] Failed to ingest document {doc_id}: {res.text}")
        else:
            print(f"[{i}] Document {doc_id} ingested.")


async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(1, 21):
            await create_user(client, i)


if __name__ == "__main__":
    asyncio.run(main())
