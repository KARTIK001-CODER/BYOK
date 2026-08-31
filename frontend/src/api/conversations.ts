import { ApiClient } from "./client";
import { Conversation } from "../types";

export const ConversationsApi = {
  async list(limit = 50, offset = 0): Promise<Conversation[]> {
    return ApiClient.request<Conversation[]>(`/conversations?limit=${limit}&offset=${offset}`);
  },

  async get(id: string): Promise<Conversation> {
    return ApiClient.request<Conversation>(`/conversations/${id}`);
  },

  async create(payload: { title?: string; knowledge_base_ids?: string[] }): Promise<Conversation> {
    return ApiClient.request<Conversation>("/conversations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async delete(id: string): Promise<void> {
    return ApiClient.request<void>(`/conversations/${id}`, {
      method: "DELETE",
    });
  },
};
