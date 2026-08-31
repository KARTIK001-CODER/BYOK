import { ApiClient } from "./client";
import { Organization, User } from "../types";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface RegisterResponse {
  user: User;
  organization: Organization;
  access_token: string;
}

export const AuthApi = {
  async register(payload: { email: string; password: string; full_name?: string; organization_name?: string }): Promise<RegisterResponse> {
    return ApiClient.request<RegisterResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async login(payload: { email: string; password: string }): Promise<LoginResponse> {
    return ApiClient.request<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async getCurrentUser(): Promise<User> {
    return ApiClient.request<User>("/auth/me");
  },

  async getUserOrganizations(): Promise<import("../types").MembershipResponse[]> {
    return ApiClient.request<import("../types").MembershipResponse[]>("/organizations");
  },
};
