const RAW_BASE = ((import.meta as unknown as { env: Record<string, string | undefined> }).env?.VITE_API_BASE_URL as string | undefined) || "";
const API_BASE_URL = RAW_BASE
  ? `${RAW_BASE.replace(/\/$/, "")}/api/v1`
  : "/api/v1";

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export class ApiClient {
  private static token: string | null = localStorage.getItem("ragforge_token");
  private static refreshToken: string | null = localStorage.getItem("ragforge_refresh_token");
  private static organizationId: string | null = localStorage.getItem("ragforge_org_id");

  static setToken(token: string | null) {
    this.token = token;
    if (token) {
      localStorage.setItem("ragforge_token", token);
    } else {
      localStorage.removeItem("ragforge_token");
    }
  }

  static getToken(): string | null {
    return this.token;
  }

  static setRefreshToken(token: string | null) {
    this.refreshToken = token;
    if (token) {
      localStorage.setItem("ragforge_refresh_token", token);
    } else {
      localStorage.removeItem("ragforge_refresh_token");
    }
  }

  static getRefreshToken(): string | null {
    return this.refreshToken;
  }

  static setOrganizationId(orgId: string | null) {
    this.organizationId = orgId;
    if (orgId) {
      localStorage.setItem("ragforge_org_id", orgId);
    } else {
      localStorage.removeItem("ragforge_org_id");
    }
  }

  static getOrganizationId(): string | null {
    return this.organizationId;
  }

  static async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${API_BASE_URL}${endpoint}`;
    const isFormData = options.body instanceof FormData;
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };
    if (!isFormData && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }

    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }
    if (this.organizationId) {
      headers["X-Organization-ID"] = this.organizationId;
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (response.status === 204) {
      return {} as T;
    }

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      const errorObj = data.error || {
        code: `HTTP_${response.status}`,
        message: data.detail || response.statusText || "Request failed.",
      };
      throw errorObj;
    }

    if (data === null || typeof data !== "object") {
      throw {
        code: "INVALID_RESPONSE",
        message: "Unexpected response format from server.",
      } as ApiError;
    }

    return data as T;
  }

  static async upload<T>(endpoint: string, formData: FormData): Promise<T> {
    return this.request<T>(endpoint, {
      method: "POST",
      body: formData,
    });
  }

  static async stream(
    endpoint: string,
    payload: unknown,
    onEvent: (event: string, data: unknown) => void,
    onError: (error: ApiError) => void,
    onComplete: () => void,
    opts?: { signal?: AbortSignal }
  ): Promise<void> {
    const url = `${API_BASE_URL}${endpoint}`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }
    if (this.organizationId) {
      headers["X-Organization-ID"] = this.organizationId;
    }

    try {
      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: opts?.signal,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const err = data.error || {
          code: `HTTP_${response.status}`,
          message: data.detail || "Streaming connection failed.",
        };
        onError(err);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        onError({ code: "STREAM_ERROR", message: "Response body reader unavailable." });
        return;
      }

      try {
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const block of lines) {
            if (!block.trim()) continue;

            let eventType = "message";
            let dataStr = "";

            for (const line of block.split("\n")) {
              if (line.startsWith("event:")) {
                eventType = line.replace("event:", "").trim();
              } else if (line.startsWith("data:")) {
                // SSE spec: repeated data: lines join with \n
                const piece = line.replace("data:", "").trim();
                dataStr = dataStr ? `${dataStr}\n${piece}` : piece;
              }
            }

            if (dataStr) {
              try {
                const parsed = JSON.parse(dataStr);
                onEvent(eventType, parsed);
              } catch {
                onEvent(eventType, dataStr);
              }
            }
          }
        }

        onComplete();
      } catch (readErr: unknown) {
        // User pressed Stop: end quietly so the app keeps the partial answer.
        if (opts?.signal?.aborted || (readErr instanceof DOMException && readErr.name === "AbortError")) {
          try {
            await reader.cancel();
          } catch {
            /* reader already closed */
          }
          onComplete();
          return;
        }
        throw readErr;
      }
    } catch (err: unknown) {
      if (opts?.signal?.aborted || (err instanceof DOMException && err.name === "AbortError")) {
        onComplete();
        return;
      }
      onError({
        code: "NETWORK_ERROR",
        message: err instanceof Error ? err.message : "Network error during streaming.",
      });
    }
  }
}
