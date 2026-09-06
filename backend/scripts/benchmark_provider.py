"""
Phase 1.6 provider benchmark — bypass FastAPI, DB, retrieval, RAG, persistence.
Measures provider resolution, init, serialization, TTFT, generation, tokens/sec.

Usage:
  python scripts/benchmark_provider.py --provider groq --model qwen/qwen3.8-27b --runs 5
  python scripts/benchmark_provider.py --provider mock --runs 10

Does NOT log API keys.
"""
import argparse
import asyncio
import statistics
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# avoid pytest tsvector issue
if "pytest" in sys.modules:
    del sys.modules["pytest"]

from app.services.llm.base import LLMRequest, LLMMessage
from app.services.llm.factory import LLMProviderFactory
from app.core.config import get_settings

PROMPTS = {
    "small": "Hello, say a short greeting.",
    "medium": "Summarize the following knowledge base context in 3 sentences: " + ("Hybrid search combines dense vectors and lexical FTS with RRF. " * 20),
    "large": "You are RAGForge. Use this context: " + ("Document content chunk with provenance and citation. " * 400) + "\nQuestion: Explain hybrid search.",
}

def redact(s: str) -> str:
    return s[:4] + "***" if s else "none"

async def single_run(provider_name: str, model: str | None, prompt_key: str = "small"):
    settings = get_settings()
    # provider resolution + init timed
    t0 = time.perf_counter()
    provider, resolved_model = LLMProviderFactory.create(provider=provider_name, model=model)
    init_ms = (time.perf_counter() - t0)*1000

    prompt = PROMPTS[prompt_key]
    prompt_tokens = max(1, len(prompt)//4)
    messages = [LLMMessage(role="user", content=prompt)]

    # request serialization
    t1 = time.perf_counter()
    req = LLMRequest(provider=provider.name, model=resolved_model, messages=messages, stream=False, temperature=0.2, max_tokens=settings.MAX_GENERATION_TOKENS)
    ser_ms = (time.perf_counter() - t1)*1000

    # non-streaming generation
    gen_t0 = time.perf_counter()
    resp = await provider.generate(req)
    gen_ms = (time.perf_counter() - gen_t0)*1000
    tokens = resp.usage.completion_tokens if resp.usage and resp.usage.completion_tokens else max(1, len(resp.content)//4)

    # streaming TTFT + total
    req_s = LLMRequest(provider=provider.name, model=resolved_model, messages=messages, stream=True, temperature=0.2, max_tokens=settings.MAX_GENERATION_TOKENS)
    stream_t0 = time.perf_counter()
    first_token_ms = None
    chunks = 0
    full = ""
    async for chunk in provider.stream(req_s):
        if chunk.delta:
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - stream_t0)*1000
            full += chunk.delta
            chunks += 1
        if chunk.usage:
            pass
    stream_total_ms = (time.perf_counter() - stream_t0)*1000
    ttft = first_token_ms or stream_total_ms
    streaming_ms = stream_total_ms - ttft if first_token_ms else 0
    tps = (tokens / (gen_ms/1000)) if gen_ms else 0

    return {
        "provider": provider.name,
        "model": resolved_model,
        "prompt_key": prompt_key,
        "prompt_tokens": prompt_tokens,
        "prompt_chars": len(prompt),
        "init_ms": round(init_ms,2),
        "serialization_ms": round(ser_ms,2),
        "ttft_ms": round(ttft,2),
        "generation_ms": round(gen_ms,2),
        "stream_total_ms": round(stream_total_ms,2),
        "streaming_ms": round(streaming_ms,2),
        "tokens": tokens,
        "tokens_per_sec": round(tps,2),
        "total_ms": round(init_ms + gen_ms,2),
        "chunks": chunks,
        "chars": len(full),
    }

async def main():
    parser = argparse.ArgumentParser(description="BYOK Provider Benchmark (Phase 1.6)")
    parser.add_argument("--provider", default=None, help="Provider name (groq, openai, gemini, mock). Default uses settings.DEFAULT_LLM_PROVIDER")
    parser.add_argument("--model", default=None, help="Model override")
    parser.add_argument("--runs", type=int, default=5, help="Runs per prompt size")
    parser.add_argument("--prompt", choices=["small","medium","large","all"], default="all", help="Prompt size experiment")
    args = parser.parse_args()

    settings = get_settings()
    provider_name = args.provider or settings.DEFAULT_LLM_PROVIDER
    print(f"Provider benchmark: provider={provider_name} model={args.model or 'default'} runs={args.runs}")
    print(f"Redacted API keys: groq={redact(settings.GROQ_API_KEY or '')} openai={redact(settings.OPENAI_API_KEY or '')} gemini={redact(settings.GEMINI_API_KEY or '')}")

    prompt_keys = ["small","medium","large"] if args.prompt=="all" else [args.prompt]

    for pk in prompt_keys:
        print(f"\n--- Prompt: {pk} ({len(PROMPTS[pk])} chars, ~{len(PROMPTS[pk])//4} tokens) ---")
        results=[]
        for i in range(args.runs):
            try:
                r = await single_run(provider_name, args.model, pk)
                results.append(r)
                print(f"  Run {i+1}: init={r['init_ms']}ms ser={r['serialization_ms']}ms TTFT={r['ttft_ms']}ms gen={r['generation_ms']}ms tokens={r['tokens']} tps={r['tokens_per_sec']}")
            except Exception as e:
                print(f"  Run {i+1} failed: {e}")
                # do not expose full traceback with keys
        if results:
            avg_ttft = statistics.mean(r["ttft_ms"] for r in results)
            avg_gen = statistics.mean(r["generation_ms"] for r in results)
            avg_total = statistics.mean(r["total_ms"] for r in results)
            avg_tps = statistics.mean(r["tokens_per_sec"] for r in results)
            print(f"  Avg TTFT={avg_ttft:.2f}ms Gen={avg_gen:.2f}ms Total={avg_total:.2f}ms TPS={avg_tps:.2f}")
            # also show P50
            sorted_total = sorted(r["total_ms"] for r in results)
            p50 = sorted_total[len(sorted_total)//2]
            print(f"  P50 Total={p50:.2f}ms")

if __name__=="__main__":
    asyncio.run(main())
