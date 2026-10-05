import { ApiClient, ApiError } from "./client";
import { CitationItem, ProviderInfo, RAGChatRequest } from "../types";

export interface SyncChatResponse {
  conversation_id: string;
  message_id: string;
  user_message_id: string;
  answer: string;
  citations: CitationItem[];
  retrieval: {
    search_mode: string;
    result_count: number;
    latency_ms: number;
  };
  model: string;
  provider: string;
  usage?: {
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    total_tokens?: number | null;
  } | null;
  latency_ms: number;
}

export const ChatApi = {
  async getModels(): Promise<ProviderInfo[]> {
    return ApiClient.request<ProviderInfo[]>("/chat/models");
  },

  async generate(payload: RAGChatRequest): Promise<SyncChatResponse> {
    return ApiClient.request<SyncChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async streamChat(
    payload: RAGChatRequest,
    callbacks: {
      onStart?: (data: { conversation_id: string; user_message_id: string; provider: string; model: string }) => void;
      onRetrieval?: (data: { search_mode: string; result_count: number; latency_ms: number }) => void;
      onToken?: (data: { delta: string }) => void;
      onCitation?: (data: CitationItem) => void;
      onGroundedness?: (data: unknown) => void;
      onDone?: (data: {
        message_id: string;
        conversation_id: string;
        latency_ms: number;
        time_to_first_token_ms?: number | null;
        usage?: {
          prompt_tokens?: number | null;
          completion_tokens?: number | null;
          total_tokens?: number | null;
        } | null;
      }) => void;
      onError?: (error: ApiError) => void;
      onComplete?: () => void;
    },
    opts?: { signal?: AbortSignal }
  ): Promise<void> {
    return ApiClient.stream(
      "/chat/stream",
      payload,
      (event, data) => {
        // Guard against malformed SSE payloads before casting to callback shapes.
        if (data !== null && typeof data === "object") {
          switch (event) {
          case "start":
            callbacks.onStart?.(data as Parameters<NonNullable<typeof callbacks.onStart>>[0]);
            break;
          case "retrieval":
            callbacks.onRetrieval?.(data as Parameters<NonNullable<typeof callbacks.onRetrieval>>[0]);
            break;
          case "token":
            callbacks.onToken?.(data as Parameters<NonNullable<typeof callbacks.onToken>>[0]);
            break;
          case "citation":
            callbacks.onCitation?.(data as Parameters<NonNullable<typeof callbacks.onCitation>>[0]);
            break;
          case "groundedness":
            callbacks.onGroundedness?.(data);
            break;
          case "done":
            callbacks.onDone?.(data as Parameters<NonNullable<typeof callbacks.onDone>>[0]);
            break;
          case "error":
            callbacks.onError?.(data as ApiError);
            break;
          }
        }
      },
      (error) => {
        callbacks.onError?.(error);
      },
      () => {
        callbacks.onComplete?.();
      },
      { signal: opts?.signal }
    );
  },
};
