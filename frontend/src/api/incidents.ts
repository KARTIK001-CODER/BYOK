import { ApiClient } from "./client";
import {
  EvidenceBatchResponse,
  EvidenceEvent,
  EvidenceEventCreatePayload,
  Incident,
  IncidentCreatePayload,
  TimelineResponse,
} from "../types/incident";

export interface PaginatedList<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export const IncidentsApi = {
  /**
   * List incidents belonging to the caller's organization.
   */
  async list(orgId?: string): Promise<PaginatedList<Incident>> {
    const query = orgId ? `?organization_id=${encodeURIComponent(orgId)}` : "";
    return ApiClient.request<PaginatedList<Incident>>(`/incidents${query}`);
  },

  /**
   * Create a new incident scoped to the organization.
   */
  async create(payload: IncidentCreatePayload): Promise<Incident> {
    return ApiClient.request<Incident>("/incidents", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * Retrieve a single incident by ID.
   */
  async get(incidentId: string): Promise<Incident> {
    return ApiClient.request<Incident>(`/incidents/${incidentId}`);
  },

  /**
   * Retrieve deterministic chronologically ordered timeline for an incident.
   */
  async getTimeline(
    incidentId: string,
    limit: number = 100,
    offset: number = 0
  ): Promise<TimelineResponse> {
    return ApiClient.request<TimelineResponse>(
      `/incidents/${incidentId}/timeline?limit=${limit}&offset=${offset}`
    );
  },

  /**
   * List raw evidence events attached to an incident.
   */
  async listEvidence(
    incidentId: string,
    sourceType?: string,
    limit: number = 50,
    offset: number = 0
  ): Promise<PaginatedList<EvidenceEvent>> {
    const st = sourceType ? `&source_type=${encodeURIComponent(sourceType)}` : "";
    return ApiClient.request<PaginatedList<EvidenceEvent>>(
      `/incidents/${incidentId}/evidence?limit=${limit}&offset=${offset}${st}`
    );
  },

  /**
   * Ingest an operational evidence event (log, alert, metric, deployment, trace, etc.)
   * Supports idempotent deduplication via deduplication_key.
   */
  async ingestEvidence(
    incidentId: string,
    payload: EvidenceEventCreatePayload
  ): Promise<EvidenceEvent> {
    return ApiClient.request<EvidenceEvent>(`/incidents/${incidentId}/evidence`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * Batch ingest multiple operational evidence events.
   * Returns detailed per-item outcomes (accepted, duplicate, rejected, failed).
   */
  async ingestEvidenceBatch(
    incidentId: string,
    items: EvidenceEventCreatePayload[]
  ): Promise<EvidenceBatchResponse> {
    return ApiClient.request<EvidenceBatchResponse>(
      `/incidents/${incidentId}/evidence/batch`,
      {
        method: "POST",
        body: JSON.stringify({ items }),
      }
    );
  },
};
