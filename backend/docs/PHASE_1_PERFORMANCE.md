# BYOK Phase 1 Performance Report

## Objective

Reduce unnecessary request/database work and improve RAG latency without changing functionality.

## Baseline

| Metric | Before |
|---|---:|
| P50 Latency | ~35,977.77 ms |
| P95 Latency | ~36,352.93 ms |
| P99 Latency | ~36,352.93 ms |
| TTFT | ~0.06 ms |
| Retrieval latency | ~8,555.77 ms |
| DB queries/request | N+1 scaling (2 + N for lookups) |
| External calls | 1 Embedding + 1 LLM (Mocked) |
| Embedding calls | Synchronous & Blocking |

## Changes

### 1. Conversation loading

- Removed `selectinload(Conversation.messages)` in `ConversationService.get_or_create_conversation` since messages are loaded explicitly via a separate targeted paginated query.

### 2. Hybrid retrieval

- Parallelized `HybridRetriever.retrieve` to execute vector and keyword search concurrently via `asyncio.gather`.
- Passed independent `AsyncSession` instances to each retriever using `get_session_factory()` to respect SQLAlchemy concurrency rules while drastically reducing fusion overhead latency.

### 3. Document metadata

- Replaced the secondary `_get_document_names` loop with a direct `JOIN Document` in `VectorRetriever` and `KeywordRetriever`.
- `Document.name` is now eagerly propagated through `CandidateMatch` and `RetrievalResult`.

### 4. Embedding execution

- Wrapped the synchronous CPU-bound `embed_query` execution in `asyncio.to_thread` to prevent it from stalling the FastAPI event loop for other concurrent users.

### 5. Persistence

- Decoupled UUID generation for the assistant message to permit tracking without blocking generation logic (SSE emission remains strict, as required).

## Results

| Metric | Before | After | Improvement |
|---|---:|---:|---:|
| P50 Latency | ~35,977.77 ms | 18,935.41 ms | **47.3%** |
| P95 Latency | ~36,352.93 ms | 25,668.30 ms | **29.4%** |
| P99 Latency | ~36,352.93 ms | 25,668.30 ms | **29.4%** |
| Average Latency| ~34,609.21 ms | 20,777.50 ms | **40.0%** |
| Retrieval | ~8,555.77 ms | 6,797.17 ms | **20.5%** |
| DB queries | N+1 lookups | Constant (O(1)) | N database roundtrips saved |

## Correctness

- [x] Tests pass
- [x] Retrieval preserved
- [x] Citations preserved
- [x] Tenant isolation preserved
- [x] SSE preserved
- [x] Persistence preserved

## Remaining Bottlenecks

1. Generation is still taking a massive amount of time (~13-14 seconds after retrieval) despite being mocked. The LLM provider framework needs investigation for internal delays.
2. Synchronous model tokenization or text parsing might still be executing synchronously within the `RAGService.generate` flow.
3. Network connection stability to external API providers (e.g. `httpx.ReadTimeout` and `wsarecv` aborted connections) needs retry logic or improved connection pooling.

## Next Phase

Production RAG quality improvements:
- Hybrid retrieval evaluation
- Reranking
- Retrieval metrics
- Context optimization
