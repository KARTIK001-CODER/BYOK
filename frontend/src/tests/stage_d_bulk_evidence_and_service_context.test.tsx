import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AddEvidenceModal } from "../components/incidents/AddEvidenceModal";
import { IncidentOverview } from "../components/incidents/IncidentOverview";
import { IncidentsApi } from "../api/incidents";
import { Incident, EvidenceBatchResponse } from "../types/incident";

vi.mock("../api/incidents", () => ({
  IncidentsApi: {
    listEvidence: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    getTimeline: vi.fn().mockResolvedValue({ events: [], total_events: 0 }),
    ingestEvidence: vi.fn(),
    ingestEvidenceBatch: vi.fn(),
  },
}));

vi.mock("../api/investigations", () => ({
  InvestigationsApi: {
    listForIncident: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}));

vi.mock("../api/remediations", () => ({
  RemediationsApi: {
    listForIncident: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}));

const mockIncident: Incident = {
  id: "inc-stage-d-1",
  organization_id: "org-1",
  title: "Cassandra Read Timeout Surge in payments-storage",
  description: "Read latencies spiked above 2500ms following cluster rebalance",
  severity: "critical",
  status: "investigating",
  service_name: "payments-storage",
  environment: "production",
  created_at: "2026-10-11T12:00:00Z",
  updated_at: "2026-10-11T12:30:00Z",
  evidence_count: 6,
};

const mockBatchResponse: EvidenceBatchResponse = {
  incident_id: "inc-stage-d-1",
  total_submitted: 3,
  accepted_count: 2,
  duplicate_count: 1,
  rejected_count: 0,
  failed_count: 0,
  results: [
    {
      index: 0,
      status: "accepted",
      evidence_id: "ev-101",
      deduplication_key: "alert-001",
      event_type: "alert.fired",
      summary: "High read latency alert",
    },
    {
      index: 1,
      status: "accepted",
      evidence_id: "ev-102",
      deduplication_key: "deploy-001",
      event_type: "deployment.rollout",
      summary: "Rollout revision v2.4.1",
    },
    {
      index: 2,
      status: "duplicate",
      evidence_id: "ev-100",
      deduplication_key: "log-001",
      event_type: "log.error",
      summary: "Connection pool exhausted",
    },
  ],
};

const mockPartialFailBatchResponse: EvidenceBatchResponse = {
  incident_id: "inc-stage-d-1",
  total_submitted: 2,
  accepted_count: 1,
  duplicate_count: 0,
  rejected_count: 1,
  failed_count: 0,
  results: [
    {
      index: 0,
      status: "accepted",
      evidence_id: "ev-101",
      summary: "Valid alert event",
    },
    {
      index: 1,
      status: "rejected",
      summary: "Invalid metric event",
      error_message: "Malformed timestamp: 2026-99-99",
    },
  ],
};

describe("TracePilot Stage D — Evidence Ingestion Pipelines, Bulk Telemetry & Service Context", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Workstream B: Bulk Telemetry (JSON Batch) Ingestion in AddEvidenceModal", () => {
    it("toggles between Single Event and Bulk Telemetry modes and previews item counts", () => {
      render(
        <AddEvidenceModal
          incident={mockIncident}
          isOpen={true}
          onClose={vi.fn()}
          onEvidenceAdded={vi.fn()}
        />
      );

      // Default mode is single
      expect(screen.getByTestId("evidence-summary-input")).toBeDefined();

      // Switch to bulk mode
      const bulkTab = screen.getByTestId("mode-bulk-tab");
      fireEvent.click(bulkTab);

      expect(bulkTab.classList.contains("active")).toBe(true);
      expect(screen.getByTestId("bulk-json-input")).toBeDefined();
      expect(screen.getAllByText(/3 items/i).length).toBeGreaterThan(0);
    });

    it("validates bulk JSON syntax and displays actionable error when malformed", () => {
      render(
        <AddEvidenceModal
          incident={mockIncident}
          isOpen={true}
          onClose={vi.fn()}
          onEvidenceAdded={vi.fn()}
        />
      );

      fireEvent.click(screen.getByTestId("mode-bulk-tab"));
      const bulkInput = screen.getByTestId("bulk-json-input");

      // Inject invalid JSON
      fireEvent.change(bulkInput, { target: { value: "[ { malformed json " } });

      expect(screen.getByText(/Invalid JSON syntax/i)).toBeDefined();
      expect(screen.getByTestId("submit-bulk-btn").hasAttribute("disabled")).toBe(true);

      // Click Load Sample Batch resets to valid payload
      const loadSampleBtn = screen.getByTestId("load-sample-batch-btn");
      fireEvent.click(loadSampleBtn);

      expect(screen.queryByText(/Invalid JSON syntax/i)).toBeNull();
      expect(screen.getByTestId("submit-bulk-btn").hasAttribute("disabled")).toBe(false);
    });

    it("submits valid telemetry batch to IncidentsApi.ingestEvidenceBatch and renders outcome summary", async () => {
      vi.mocked(IncidentsApi.ingestEvidenceBatch).mockResolvedValue(mockBatchResponse);
      const onEvidenceAdded = vi.fn();

      render(
        <AddEvidenceModal
          incident={mockIncident}
          isOpen={true}
          onClose={vi.fn()}
          onEvidenceAdded={onEvidenceAdded}
        />
      );

      fireEvent.click(screen.getByTestId("mode-bulk-tab"));
      const submitBtn = screen.getByTestId("submit-bulk-btn");
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(IncidentsApi.ingestEvidenceBatch).toHaveBeenCalledWith(
          mockIncident.id,
          expect.any(Array)
        );
        expect(onEvidenceAdded).toHaveBeenCalled();
        expect(screen.getByTestId("batch-outcome-summary")).toBeDefined();
        expect(screen.getByText("Batch Ingestion Summary")).toBeDefined();
      });

      // Verify outcomes breakdown
      expect(screen.getByTestId("batch-item-result-0")).toBeDefined();
      expect(screen.getByTestId("batch-item-result-1")).toBeDefined();
      expect(screen.getByTestId("batch-item-result-2")).toBeDefined();
      expect(screen.getAllByText("ACCEPTED").length).toBe(2);
      expect(screen.getAllByText("DUPLICATE").length).toBe(1);
    });

    it("supports Retrying Failed Items when partial failure occurs", async () => {
      vi.mocked(IncidentsApi.ingestEvidenceBatch).mockResolvedValue(mockPartialFailBatchResponse);

      render(
        <AddEvidenceModal
          incident={mockIncident}
          isOpen={true}
          onClose={vi.fn()}
          onEvidenceAdded={vi.fn()}
        />
      );

      fireEvent.click(screen.getByTestId("mode-bulk-tab"));
      fireEvent.click(screen.getByTestId("submit-bulk-btn"));

      await waitFor(() => {
        expect(screen.getByTestId("retry-failed-batch-btn")).toBeDefined();
        expect(screen.getByText("Malformed timestamp: 2026-99-99")).toBeDefined();
      });

      // Click retry failed items
      const retryBtn = screen.getByTestId("retry-failed-batch-btn");
      fireEvent.click(retryBtn);

      // JSON input is now pre-populated with only the failed item
      expect(screen.getAllByText(/1 item/i).length).toBeGreaterThan(0);
    });
  });

  describe("Workstream C: Service and Environment Context in IncidentOverview", () => {
    it("renders service and environment context from real incident metadata", () => {
      render(
        <IncidentOverview
          incident={mockIncident}
          onNavigateTab={vi.fn()}
        />
      );

      expect(screen.getByTestId("overview-service-context")).toBeDefined();
      expect(screen.getByTestId("context-service-name").textContent).toBe("payments-storage");
      expect(screen.getByTestId("context-environment").textContent).toContain("PRODUCTION");
    });

    it("renders honest unspecified state when service_name is absent", () => {
      const incidentWithoutService: Incident = {
        ...mockIncident,
        service_name: null,
      };

      render(
        <IncidentOverview
          incident={incidentWithoutService}
          onNavigateTab={vi.fn()}
        />
      );

      expect(screen.getByTestId("context-service-name").textContent).toContain(
        "Unspecified / Multi-service"
      );
    });
  });
});
