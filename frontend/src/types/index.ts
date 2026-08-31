export interface User {
  id: string;
  email: string;
  full_name?: string;
  is_active: boolean;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
}

export interface MembershipResponse {
  id: string;
  organization_id: string;
  user_id: string;
  role: string;
  created_at: string;
  organization: Organization;
}

export interface KnowledgeBase {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description?: string;
  is_active: boolean;
}

export interface ModelCapability {
  streaming: boolean;
  context_window: number;
  max_output_tokens: number;
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  capabilities: ModelCapability;
  description?: string;
  is_default: boolean;
}

export interface ProviderInfo {
  id: string;
  name: string;
  description: string;
  is_configured: boolean;
  default_model: string;
  models: ModelInfo[];
}

export interface CitationItem {
  id: number;
  chunk_id: string;
  document_id: string;
  document_version_id: string;
  document_name: string;
  page_number?: number | null;
  section_title?: string | null;
  content_preview?: string | null;
}

export interface MessageMetadata {
  provider?: string;
  model?: string;
  citations?: CitationItem[];
  retrieval?: {
    search_mode: string;
    result_count: number;
    latency_ms: number;
  };
  usage?: {
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    total_tokens?: number | null;
  } | null;
  latency_ms?: number;
  time_to_first_token_ms?: number | null;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  message_metadata?: MessageMetadata | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  organization_id: string;
  user_id: string;
  title: string;
  knowledge_base_ids?: string[] | null;
  created_at: string;
  updated_at: string;
  message_count?: number;
  messages?: Message[];
}

export interface RAGChatRequest {
  message: string;
  conversation_id?: string | null;
  knowledge_base_ids?: string[] | null;
  provider?: string | null;
  model?: string | null;
  top_k?: number;
  search_mode?: "vector" | "keyword" | "hybrid";
  temperature?: number;
}
