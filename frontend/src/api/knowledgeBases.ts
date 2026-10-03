import { ApiClient } from "./client";
import { KnowledgeBase } from "../types";

interface PaginatedKB {
  items: KnowledgeBase[];
  total: number;
  limit: number;
  offset: number;
}

export interface KnowledgeBaseStats {
  knowledge_base_id: string;
  total_documents: number;
  total_chunks: number;
  total_file_size_bytes: number;
  ready_documents: number;
  processing_documents: number;
  failed_documents: number;
  pending_embeddings: number;
  failed_embeddings: number;
}

export const KnowledgeBasesApi = {
  async list(): Promise<KnowledgeBase[]> {
    const data = await ApiClient.request<PaginatedKB | KnowledgeBase[]>("/knowledge-bases");
    if (Array.isArray(data)) return data;
    return (data as PaginatedKB).items ?? [];
  },

  async get(id: string): Promise<KnowledgeBase> {
    return ApiClient.request<KnowledgeBase>(`/knowledge-bases/${id}`);
  },

  async getStats(id: string): Promise<KnowledgeBaseStats> {
    return ApiClient.request<KnowledgeBaseStats>(`/knowledge-bases/${id}/stats`);
  },

  async create(payload: { name: string; description?: string; organization_id?: string }): Promise<KnowledgeBase> {
    return ApiClient.request<KnowledgeBase>("/knowledge-bases", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async update(id: string, payload: { name?: string; description?: string; is_active?: boolean }): Promise<KnowledgeBase> {
    return ApiClient.request<KnowledgeBase>(`/knowledge-bases/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  async delete(id: string): Promise<void> {
    await ApiClient.request<void>(`/knowledge-bases/${id}`, { method: "DELETE" });
  },
};

