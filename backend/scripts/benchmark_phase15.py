"""
Phase 1.5 benchmark: cold vs warm, detailed tracing, resource monitoring.
Writes JSON report + prints human summary.

Requires backend running on BENCHMARK_BASE_URL and a seeded DB.
"""
import argparse
import asyncio
import json
import os
import statistics
import time
from typing import Any

import httpx
import psutil  # type: ignore

QUERIES = [
    "What is the capital of France?",
    "Testing RAG pipelines is fun. What does the dummy content say?",
    "dummy content testing data RAG AI",
    "Summarize all the dummy files and what they say about AI and testing.",
    "What did I just ask you?",
]

EMAIL = "testuser_1@example.com"
PASSWORD = "Password123!"

async def authenticate(client: httpx.AsyncClient, base_url: str) -> str:
    res = await client.post(f"{base_url}/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if res.status_code != 200:
        raise RuntimeError(f"Login failed: {res.text}")
    token = res.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return token

async def get_kb_id(client: httpx.AsyncClient, base_url: str) -> str | None:
    res = await client.get(f"{base_url}/api/v1/knowledge-bases")
    if res.status_code != 200:
        return None
    data = res.json()
    items = data.get("items") if isinstance(data, dict) else data
    if not items:
        return None
    return items[0]["id"]

async def fetch_diagnostics(client: httpx.AsyncClient, base_url: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in ["/api/v1/diagnostics/pool", "/api/v1/diagnostics/embedding?query=test", "/api/v1/diagnostics/provider?provider_name=mock", "/api/v1/diagnostics/query-plan"]:
        try:
            r = await client.get(f"{base_url}{path}", timeout=30)
            out[path] = r.json() if r.status_code == 200 else {"error": r.text[:500], "status": r.status_code}
        except Exception as e:
            out[path] = {"error": str(e)}
    return out


async def single_request(client: httpx.AsyncClient, base_url: str, kb_id: str, query: str, conversation_id: str | None, use_stream: bool = True) -> dict[str, Any]:
    payload = {
        "message": query,
        "knowledge_base_ids": [kb_id],
        "search_mode": "hybrid",
        "top_k": 5,
        "provider": "mock",
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    start = time.perf_counter()
    ttft = None
    retrieval_lat = None
    first_token_sent = None
    done_lat = None
    trace_id = None
    request_id = None
    result_conv_id = conversation_id
    events: list[dict] = []
    try:
        if use_stream:
            async with client.stream("POST", f"{base_url}/api/v1/chat/stream", json=payload) as resp:
                trace_id = resp.headers.get("X-Trace-ID")
                request_id = resp.headers.get("X-Request-ID")
                if resp.status_code != 200:
                    body = await resp.aread()
                    return {"error": body.decode()[:500], "status": resp.status_code}
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[len("data: "):])
                        except Exception:
                            continue
                        # crude event type inference from line prefix is lost here; use keys
                        events.append(data)
                        if "latency_ms" in data and "search_mode" in data:
                            retrieval_lat = data.get("latency_ms")
                        if "delta" in data and ttft is None:
                            ttft = (time.perf_counter() - start) * 1000.0
                        if "time_to_first_token_ms" in data and data.get("time_to_first_token_ms"):
                            ttft = data["time_to_first_token_ms"]
                        if "conversation_id" in data:
                            result_conv_id = data.get("conversation_id", result_conv_id)
                total = (time.perf_counter() - start) * 1000.0
        else:
            # non-streaming
            resp = await client.post(f"{base_url}/api/v1/chat", json=payload)
            trace_id = resp.headers.get("X-Trace-ID")
            request_id = resp.headers.get("X-Request-ID")
            if resp.status_code != 200:
                return {"error": resp.text[:500], "status": resp.status_code}
            data = resp.json()
            retrieval_lat = data.get("retrieval", {}).get("latency_ms") if isinstance(data.get("retrieval"), dict) else None
            total = (time.perf_counter() - start) * 1000.0
            # for non-stream TTFT == total - retrieval approx
            ttft = total
            result_conv_id = data.get("conversation_id", result_conv_id)
    except Exception as e:
        return {"error": str(e), "query": query}
    total = (time.perf_counter() - start) * 1000.0
    return {
        "query": query,
        "total_ms": round(total, 2),
        "ttft_ms": round(ttft, 2) if ttft else None,
        "retrieval_ms": retrieval_lat,
        "trace_id": trace_id,
        "request_id": request_id,
        "conversation_id": result_conv_id,
        "events": events[:2],  # sample
    }


async def run_benchmark(base_url: str, warm_runs: int = 12, cold_runs: int = 1) -> dict[str, Any]:
    print(f"Benchmarking {base_url} cold_runs={cold_runs} warm_runs={warm_runs}")
    async with httpx.AsyncClient(timeout=120.0) as client:
        await authenticate(client, base_url)
        kb_id = await get_kb_id(client, base_url)
        if not kb_id:
            raise RuntimeError("No KB found — seed DB first")
        print(f"KB: {kb_id}")

        # diagnostics
        diag = await fetch_diagnostics(client, base_url)

        # Cold: first request(s) after restart — server already warm here, but we treat first as cold-ish
        # We explicitly hit embedding endpoint cold then warm
        cold_results = []
        for i in range(cold_runs):
            q = QUERIES[i % len(QUERIES)]
            r = await single_request(client, base_url, kb_id, q, None, use_stream=True)
            cold_results.append(r)
            print(f"  Cold {i+1}: total={r.get('total_ms')} ttft={r.get('ttft_ms')} ret={r.get('retrieval_ms')}")
            await asyncio.sleep(0.5)

        # Warm: many runs
        warm_results = []
        conv_id = cold_results[-1].get("conversation_id") if cold_results else None
        for i in range(warm_runs):
            q = QUERIES[i % len(QUERIES)]
            # CPU snapshot
            cpu_before = psutil.cpu_percent(interval=None)
            mem_before = psutil.virtual_memory().percent
            r = await single_request(client, base_url, kb_id, q, conv_id if i == warm_runs -1 else None, use_stream=True)
            cpu_after = psutil.cpu_percent(interval=None)
            r["cpu_before"] = cpu_before
            r["cpu_after"] = cpu_after
            r["mem"] = mem_before
            warm_results.append(r)
            print(f"  Warm {i+1}: total={r.get('total_ms')} ttft={r.get('ttft_ms')} ret={r.get('retrieval_ms')} cpu={cpu_before}->{cpu_after}")
            # small sleep to avoid overwhelming pool
            await asyncio.sleep(0.2)

        # Aggregate
        def agg(results):
            totals = [r["total_ms"] for r in results if r.get("total_ms")]
            ttfts = [r["ttft_ms"] for r in results if r.get("ttft_ms")]
            rets = [r["retrieval_ms"] for r in results if r.get("retrieval_ms")]
            if not totals:
                return {}
            totals_sorted = sorted(totals)
            def pct(p):
                idx = min(int(len(totals_sorted) * p), len(totals_sorted)-1)
                return totals_sorted[idx]
            return {
                "count": len(totals),
                "p50": round(pct(0.5), 2),
                "p95": round(pct(0.95), 2),
                "p99": round(pct(0.99), 2),
                "avg": round(statistics.mean(totals), 2),
                "min": round(min(totals), 2),
                "max": round(max(totals), 2),
                "avg_ttft": round(statistics.mean(ttfts),2) if ttfts else None,
                "avg_retrieval": round(statistics.mean(rets),2) if rets else None,
                "ttft_p50": round(sorted(ttfts)[len(ttfts)//2],2) if ttfts else None,
            }

        report = {
            "base_url": base_url,
            "cold": agg(cold_results),
            "warm": agg(warm_results),
            "cold_details": cold_results,
            "warm_details": warm_results,
            "diagnostics": diag,
            "system": {
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(interval=1),
                "mem_percent": psutil.virtual_memory().percent,
            }
        }
        return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("BENCHMARK_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--warm-runs", type=int, default=12)
    parser.add_argument("--cold-runs", type=int, default=1)
    parser.add_argument("--out", default="phase15_report.json")
    args = parser.parse_args()
    report = asyncio.run(run_benchmark(args.base_url, args.warm_runs, args.cold_runs))
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport written to {args.out}")
    print(json.dumps({k: v for k, v in report.items() if k in ("cold","warm","system")}, indent=2))
