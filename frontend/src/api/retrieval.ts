import { ApiClient } from "./client";

export type SearchMode = "vector" | "keyword" | "hybrid";

export interface RetrievalFilter {
  knowledge_base_ids?: string[];
  document_ids?: string[];
  document_version_ids?: string[];
}

export interface RetrievalRequest {
  query: string;
  knowledge_base_ids?: string[];
  document_ids?: string[];
  top_k?: number;
  candidate_k?: number;
  search_mode?: SearchMode;
  filters?: RetrievalFilter;
  debug?: boolean;
}

export interface ChunkProvenance {
  organization_id: string;
  knowledge_base_id: string;
  document_id: string;
  document_name?: string | null;
  document_version_id: string;
  chunk_id: string;
  chunk_index: number;
  page_number?: number | null;
  section_title?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface RetrievalResult {
  chunk_id: string;
  document_id: string;
  document_name?: string | null;
  document_version_id: string;
  knowledge_base_id: string;
  content: string;
  score: number;
  rank: number;
  source: string;
  vector_score?: number | null;
  keyword_score?: number | null;
  rrf_score?: number | null;
  page_number?: number | null;
  section_title?: string | null;
  metadata?: Record<string, unknown> | null;
  provenance: ChunkProvenance;
}

export interface RetrievalResponse {
  query: string;
  search_mode: SearchMode;
  total_results: number;
  results: RetrievalResult[];
}

export const RetrievalApi = {
  /**
   * Execute multi-tenant semantic vector, keyword, or hybrid retrieval over runbooks & docs.
   */
  async search(
    request: RetrievalRequest,
    orgId?: string
  ): Promise<RetrievalResponse> {
    const headers: Record<string, string> = {};
    if (orgId) {
      headers["X-Organization-ID"] = orgId;
    }

    return ApiClient.request<RetrievalResponse>("/retrieval/search", {
      method: "POST",
      headers,
      body: JSON.stringify(request),
    });
  },
};
