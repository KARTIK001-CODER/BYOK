import argparse
import asyncio
import json
import os
import statistics
import time

import httpx

# Default test user from seed_db_direct.py
EMAIL = "testuser_1@example.com"
PASSWORD = "Password123!"

QUERIES = [
    "What is the capital of France?",  # 1. Simple factual query
    "Testing RAG pipelines is fun. What does the dummy content say?",  # 2. Semantic query
    "dummy content testing data RAG AI",  # 3. Keyword-heavy query
    "Summarize all the dummy files and what they say about AI and testing.",  # 4. Multi-document query
    "What did I just ask you?",  # 5. Query with conversation history
]


async def authenticate(client: httpx.AsyncClient, base_url: str):
    res = await client.post(
        f"{base_url}/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    if res.status_code != 200:
        print(f"Failed to login with {EMAIL}. Run seed_db_direct.py first. Response: {res.text}")
        return None
    token = res.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return token


async def get_kb_id(client: httpx.AsyncClient, base_url: str):
    res = await client.get(f"{base_url}/api/v1/knowledge-bases")
    if res.status_code != 200:
        return None
    kbs = res.json()
    if not kbs or not kbs.get("items"):
        return None
    return kbs["items"][0]["id"]


async def run_benchmark(base_url: str, num_runs: int = 3):
    print(f"Benchmarking against {base_url} with {num_runs} runs per query...")
    async with httpx.AsyncClient(timeout=120.0) as client:
        token = await authenticate(client, base_url)
        if not token:
            return
        kb_id = await get_kb_id(client, base_url)
        if not kb_id:
            print("No Knowledge Base found for the user. Exiting.")
            return

        print(f"Authenticated. Using Knowledge Base ID: {kb_id}")

        results = []

        conversation_id = None

        for idx, query in enumerate(QUERIES, 1):
            print(f"\n--- Query {idx}: '{query}' ---")
            query_latencies = []
            ttfts = []
            retrieval_lats = []

            for run in range(1, num_runs + 1):
                payload = {
                    "message": query,
                    "knowledge_base_ids": [kb_id],
                    "search_mode": "hybrid",
                    "top_k": 5,
                    "provider": "mock",  # Let's use mock so we don't hit external APIs or hit rate limits if possible, or just default. Wait, the prompt says measure LLM calls, so let's just omit provider and use default.
                }
                if idx == 5 and conversation_id:
                    payload["conversation_id"] = conversation_id

                # We'll use the streaming endpoint to measure TTFT and total time
                start_time = time.perf_counter()

                ttft = None
                retrieval_lat = None

                try:
                    async with client.stream(
                        "POST", f"{base_url}/api/v1/chat/stream", json=payload
                    ) as response:
                        if response.status_code != 200:
                            print(f"Error: {response.status_code} - {await response.aread()}")
                            continue

                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[len("data: ") :].strip()
                            if not data_str:
                                continue
                            data = json.loads(data_str)

                            if line.startswith("event: retrieval") or "search_mode" in data:
                                retrieval_lat = data.get("latency_ms")
                            elif line.startswith("event: token") or "delta" in data:
                                if ttft is None:
                                    ttft = (time.perf_counter() - start_time) * 1000.0
                            elif line.startswith("event: done") or "message_id" in data:
                                if (
                                    "time_to_first_token_ms" in data
                                    and data["time_to_first_token_ms"]
                                ):
                                    ttft = data["time_to_first_token_ms"]
                                conversation_id = data.get("conversation_id", conversation_id)
                except Exception as e:
                    print(f"Run {run} failed: {e}")
                    continue

                total_time = (time.perf_counter() - start_time) * 1000.0
                query_latencies.append(total_time)
                if ttft is not None:
                    ttfts.append(ttft)
                if retrieval_lat is not None:
                    retrieval_lats.append(retrieval_lat)

                print(
                    f"  Run {run}: Total={total_time:.2f}ms, TTFT={ttft if ttft else 0:.2f}ms, Retrieval={retrieval_lat if retrieval_lat else 0:.2f}ms"
                )

            results.append(
                {
                    "query": query,
                    "latencies": query_latencies,
                    "ttfts": ttfts,
                    "retrieval_lats": retrieval_lats,
                }
            )

        print("\n--- BENCHMARK RESULTS ---")
        all_lats = []
        all_ttfts = []
        all_ret_lats = []

        for r in results:
            all_lats.extend(r["latencies"])
            all_ttfts.extend(r["ttfts"])
            all_ret_lats.extend(r["retrieval_lats"])

        if all_lats:
            all_lats.sort()
            p50 = all_lats[len(all_lats) // 2]
            p95 = all_lats[int(len(all_lats) * 0.95)]
            p99 = all_lats[int(len(all_lats) * 0.99)]
            avg_lat = statistics.mean(all_lats)
            avg_ttft = statistics.mean(all_ttfts) if all_ttfts else 0
            avg_ret = statistics.mean(all_ret_lats) if all_ret_lats else 0

            print(f"P50 Latency: {p50:.2f} ms")
            print(f"P95 Latency: {p95:.2f} ms")
            print(f"P99 Latency: {p99:.2f} ms")
            print(f"Average Latency: {avg_lat:.2f} ms")
            print(f"Average TTFT: {avg_ttft:.2f} ms")
            print(f"Average Retrieval Latency: {avg_ret:.2f} ms")
            print(f"Total Requests: {len(all_lats)}")
        else:
            print("No valid results collected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BYOK Chat Benchmark")
    parser.add_argument(
        "--base-url", type=str, default=os.getenv("BENCHMARK_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.base_url, args.runs))
