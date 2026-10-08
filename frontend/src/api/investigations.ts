import { ApiClient, ApiError } from "./client";
import {
  InvestigationEventType,
  InvestigationJob,
  InvestigationStreamEventPayload,
} from "../types/investigation";

export interface StreamInvestigationCallbacks {
  onEvent?: (eventType: InvestigationEventType, data: InvestigationStreamEventPayload) => void;
  onConnected?: (data: InvestigationStreamEventPayload) => void;
  onSnapshot?: (data: InvestigationStreamEventPayload) => void;
  onProgress?: (data: InvestigationStreamEventPayload) => void;
  onCompleted?: (data: InvestigationStreamEventPayload) => void;
  onFailed?: (data: InvestigationStreamEventPayload) => void;
  onCancelled?: (data: InvestigationStreamEventPayload) => void;
  onError?: (error: ApiError) => void;
  onComplete?: () => void;
}

export const InvestigationsApi = {
  /**
   * Fetch the authoritative investigation job state from PostgreSQL.
   */
  async get(jobId: string): Promise<InvestigationJob> {
    return ApiClient.request<InvestigationJob>(`/investigations/${jobId}`);
  },

  /**
   * Cancel an ongoing investigation job.
   */
  async cancel(jobId: string): Promise<InvestigationJob> {
    return ApiClient.request<InvestigationJob>(`/investigations/${jobId}/cancel`, {
      method: "POST",
    });
  },

  /**
   * Open a Server-Sent Events (SSE) stream for real-time investigation updates.
   * PostgreSQL remains the authoritative source of truth.
   */
  async stream(
    jobId: string,
    callbacks: StreamInvestigationCallbacks,
    opts?: { signal?: AbortSignal }
  ): Promise<void> {
    return ApiClient.streamGet(
      `/investigations/${jobId}/stream`,
      (eventTypeStr, rawData) => {
        const eventType = eventTypeStr as InvestigationEventType;
        const payload = rawData as InvestigationStreamEventPayload;

        callbacks.onEvent?.(eventType, payload);

        switch (eventType) {
          case "investigation.connected":
            callbacks.onConnected?.(payload);
            break;
          case "investigation.snapshot":
            callbacks.onSnapshot?.(payload);
            break;
          case "investigation.progress":
            callbacks.onProgress?.(payload);
            break;
          case "investigation.completed":
            callbacks.onCompleted?.(payload);
            break;
          case "investigation.failed":
            callbacks.onFailed?.(payload);
            break;
          case "investigation.cancelled":
            callbacks.onCancelled?.(payload);
            break;
        }
      },
      (error) => {
        callbacks.onError?.(error);
      },
      () => {
        callbacks.onComplete?.();
      },
      opts
    );
  },
};
