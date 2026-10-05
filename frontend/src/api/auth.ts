import { ApiClient } from "./client";
import { Organization, User } from "../types";

export interface TokenPayload {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface LoginResponse extends TokenPayload {}

export interface RegisterResponse {
  user: User;
  organization: Organization;
  tokens: TokenPayload;
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

  async refresh(refreshToken: string): Promise<LoginResponse> {
    return ApiClient.request<LoginResponse>("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  },

  async logout(refreshToken: string): Promise<{ message: string }> {
    return ApiClient.request<{ message: string }>("/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  },

  async getUserOrganizations(): Promise<import("../types").MembershipResponse[]> {
    return ApiClient.request<import("../types").MembershipResponse[]>("/organizations");
  },
};
