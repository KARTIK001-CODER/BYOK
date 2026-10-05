import { ApiClient } from "./client";

export interface DocumentResponse {
  id: string;
  organization_id: string;
  knowledge_base_id: string;
  name: string;
  original_filename: string;
  content_type?: string | null;
  file_size: number;
  checksum: string;
  status: string;
  embedding_status?: string | null;
  current_version: number;
  chunk_count?: number;
  storage_key?: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentChunkResponse {
  id: string;
  document_id: string;
  document_version_id: string;
  chunk_index: number;
  content: string;
  character_count: number;
  word_count: number;
  page_number?: number | null;
  section_title?: string | null;
  chunk_metadata?: Record<string, unknown> | null;
  embedding_model?: string | null;
  embedding_provider?: string | null;
  embedding_dimension?: number | null;
  embedded_at?: string | null;
  created_at: string;
}

export interface PaginatedChunks {
  items: DocumentChunkResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentVersionResponse {
  id: string;
  document_id: string;
  version_number: number;
  storage_key: string;
  checksum: string;
  file_size: number;
  created_at: string;
}

export interface DocumentUploadResponse {
  document: DocumentResponse;
  version: DocumentVersionResponse;
  message: string;
}

interface PaginatedDoc {
  items: DocumentResponse[];
  total: number;
  limit: number;
  offset: number;
}

export const DocumentsApi = {
  async list(kbId: string, limit = 50, offset = 0): Promise<{ items: DocumentResponse[]; total: number }> {
    const data = await ApiClient.request<PaginatedDoc>(`/knowledge-bases/${kbId}/documents?limit=${limit}&offset=${offset}`);
    return { items: data.items ?? [], total: data.total ?? 0 };
  },

  async upload(kbId: string, file: File): Promise<DocumentUploadResponse> {
    const fd = new FormData();
    fd.append("file", file);
    return ApiClient.upload<DocumentUploadResponse>(`/knowledge-bases/${kbId}/documents`, fd);
  },

  async get(documentId: string): Promise<DocumentResponse> {
    return ApiClient.request<DocumentResponse>(`/documents/${documentId}`);
  },

  async delete(documentId: string): Promise<void> {
    await ApiClient.request<void>(`/documents/${documentId}`, { method: "DELETE" });
  },

  async ingest(documentId: string): Promise<{ job_id: string; status: string }> {
    return ApiClient.request(`/documents/${documentId}/ingest`, { method: "POST" });
  },

  async embed(documentId: string): Promise<{ job_id: string; status: string; total_chunks: number }> {
    return ApiClient.request(`/documents/${documentId}/embed`, { method: "POST" });
  },

  async process(documentId: string): Promise<void> {
    // Orchestrate ingest + embed sequentially for one-click processing
    await DocumentsApi.ingest(documentId);
    await DocumentsApi.embed(documentId);
  },

  async getChunks(documentId: string, limit = 20, offset = 0): Promise<PaginatedChunks> {
    return ApiClient.request<PaginatedChunks>(`/documents/${documentId}/chunks?limit=${limit}&offset=${offset}`);
  },
};

