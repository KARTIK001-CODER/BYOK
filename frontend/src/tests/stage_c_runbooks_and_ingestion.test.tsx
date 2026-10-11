import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { IncidentWorkspace } from "../components/incidents/IncidentWorkspace";
import { RunbooksPanel } from "../components/incidents/RunbooksPanel";
import { AddEvidenceModal } from "../components/incidents/AddEvidenceModal";
import { HypothesisCard } from "../components/incidents/HypothesisCard";
import { IncidentsApi } from "../api/incidents";
import { RetrievalApi, RetrievalResponse } from "../api/retrieval";
import { Incident, EvidenceEvent } from "../types/incident";
import { HypothesisResponse } from "../types/investigation";

vi.mock("../api/incidents", () => ({
  IncidentsApi: {
    getTimeline: vi.fn(),
    listEvidence: vi.fn(),
    ingestEvidence: vi.fn(),
  },
}));

vi.mock("../api/retrieval", () => ({
  RetrievalApi: {
    search: vi.fn(),
  },
}));

vi.mock("../api/investigations", () => ({
  InvestigationsApi: {
    listForIncident: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    trigger: vi.fn(),
    get: vi.fn(),
    listHypotheses: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    cancel: vi.fn(),
    stream: vi.fn(),
  },
}));

vi.mock("../api/remediations", () => ({
  RemediationsApi: {
    listForIncident: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}));

const mockIncident: Incident = {
  id: "inc-stage-c-1",
  organization_id: "org-1",
  title: "Kafka Consumer Lag Spike in payments-worker",
  description: "Consumer group checkout-consumers lag exceeded 500,000 records",
  severity: "high",
  status: "investigating",
  service_name: "payments-worker",
  environment: "production",
  created_at: "2026-10-11T11:00:00Z",
  updated_at: "2026-10-11T11:20:00Z",
  evidence_count: 5,
};

const mockRetrievalResponse: RetrievalResponse = {
  query: "payments-worker Kafka Consumer Lag Spike in payments-worker",
  search_mode: "hybrid",
  total_results: 2,
  results: [
    {
      chunk_id: "chk-1",
      document_id: "doc-101",
      document_name: "Kafka Consumer Lag & Rebalance Runbook.md",
      document_version_id: "ver-1",
      knowledge_base_id: "kb-sre",
      content:
        "When consumer lag exceeds 100k, inspect partition rebalances and database thread pool timeouts. Check if commit offsets are failing due to downstream deadlocks.",
      score: 0.88,
      rank: 1,
      source: "hybrid",
      section_title: "Remediation Steps for Heavy Lag",
      page_number: 3,
      provenance: {
        organization_id: "org-1",
        knowledge_base_id: "kb-sre",
        document_id: "doc-101",
        document_name: "Kafka Consumer Lag & Rebalance Runbook.md",
        document_version_id: "ver-1",
        chunk_id: "chk-1",
        chunk_index: 2,
      },
    },
    {
      chunk_id: "chk-2",
      document_id: "doc-102",
      document_name: "Payments Architecture & Downstream Dependencies.md",
      document_version_id: "ver-1",
      knowledge_base_id: "kb-arch",
      content:
        "Payments worker drains the checkout Kafka topic and writes to PostgreSQL. If the primary connection pool is saturated, backpressure halts partition commits.",
      score: 0.74,
      rank: 2,
      source: "hybrid",
      section_title: "Backpressure & Queue Throttling",
      provenance: {
        organization_id: "org-1",
        knowledge_base_id: "kb-arch",
        document_id: "doc-102",
        document_name: "Payments Architecture & Downstream Dependencies.md",
        document_version_id: "ver-1",
        chunk_id: "chk-2",
        chunk_index: 5,
      },
    },
  ],
};

const mockIngestedEvidence: EvidenceEvent = {
  id: "ev-stage-c-new",
  incident_id: "inc-stage-c-1",
  organization_id: "org-1",
  source_type: "log",
  event_type: "log.error",
  event_timestamp: "2026-10-11T11:05:00Z",
  ingestion_timestamp: "2026-10-11T11:05:02Z",
  summary: "Database connection pool exhausted: 150/150 connections busy",
  service_name: "payments-worker",
  source_reference: "https://logs.corp.internal/view/log-4421",
  deduplication_key: "db-pool-exhausted-1105",
  normalized_payload: { active_connections: 150, max_connections: 150 },
};

const mockHypothesisWithQuality: HypothesisResponse = {
  id: "hyp-stage-c-1",
  incident_id: "inc-stage-c-1",
  organization_id: "org-1",
  investigation_job_id: "job-inv-stage-c",
  claim: "Database connection pool exhaustion caused consumer lag spike",
  rationale:
    "Log events confirm active connections saturated at 150/150, triggering commit failures.",
  status: "supported",
  confidence: "high",
  confidence_note:
    "Empirical evidence quality score derived from multi-source verification. Not a calibrated probability.",
  groundedness_score: 0.94,
  groundedness_status: "well_supported",
  system_confidence: "high",
  system_confidence_score: 0.91,
  assessment_details: {
    support_score: 0.95,
    contradiction_score: 0.02,
    temporal_score: 0.98,
    diversity_score: 0.85,
    invalid_citation_count: 0,
    calibration_status: "insufficient_evaluation_data",
    assessment_reasons: [
      "Evidence timing correlates with consumer lag alert onset",
      "Multiple distinct telemetry sources confirm resource exhaustion",
    ],
  },
  supporting_evidence: [
    {
      id: "link-1",
      hypothesis_id: "hyp-stage-c-1",
      evidence_event_id: "ev-stage-c-new",
      link_type: "supports",
      excerpt: "Database connection pool exhausted: 150/150 connections busy",
    },
  ],
  contradicting_evidence: [],
  created_at: "2026-10-11T11:15:00Z",
};

describe("TracePilot Stage C — Runbooks, Telemetry Ingestion & Investigation Quality", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Workstream A: Contextual Runbook Discovery (RunbooksPanel)", () => {
    it("synthesizes query from incident context, calls hybrid retrieval, and renders ranked runbooks with advisory notice", async () => {
      vi.mocked(RetrievalApi.search).mockResolvedValue(mockRetrievalResponse);
      const onOpenDocument = vi.fn();

      render(
        <RunbooksPanel
          incident={mockIncident}
          onOpenDocument={onOpenDocument}
        />
      );

      // Verify advisory notice
      expect(screen.getByTestId("runbooks-advisory")).toBeDefined();
      expect(
        screen.getByText(/Advisory Context Only/i)
      ).toBeDefined();

      await waitFor(() => {
        expect(RetrievalApi.search).toHaveBeenCalledWith(
          expect.objectContaining({
            query: "payments-worker Kafka Consumer Lag Spike in payments-worker",
            search_mode: "hybrid",
            top_k: 10,
          })
        );
        expect(
          screen.getByText("Kafka Consumer Lag & Rebalance Runbook.md")
        ).toBeDefined();
        expect(
          screen.getByText("Payments Architecture & Downstream Dependencies.md")
        ).toBeDefined();
      });

      // Verify rank and relevance score
      expect(screen.getByText("#1")).toBeDefined();
      expect(screen.getByText("Relevance: 88.0%")).toBeDefined();
      expect(screen.getByText("Remediation Steps for Heavy Lag")).toBeDefined();

      // Deep link to document view
      const viewDocBtn = screen.getByTestId("view-doc-btn-doc-101");
      fireEvent.click(viewDocBtn);
      expect(onOpenDocument).toHaveBeenCalledWith("doc-101");
    });

    it("allows user to customize search terms and switch search modes", async () => {
      vi.mocked(RetrievalApi.search).mockResolvedValue(mockRetrievalResponse);

      render(<RunbooksPanel incident={mockIncident} />);

      await waitFor(() => {
        expect(RetrievalApi.search).toHaveBeenCalledTimes(1);
      });

      // Change search query
      const input = screen.getByTestId("runbooks-query-input");
      fireEvent.change(input, { target: { value: "PostgreSQL Deadlock Runbook" } });

      // Change mode to keyword
      const modeSelect = screen.getByTestId("runbooks-mode-select");
      fireEvent.change(modeSelect, { target: { value: "keyword" } });

      await waitFor(() => {
        expect(RetrievalApi.search).toHaveBeenCalledWith(
          expect.objectContaining({
            query: "PostgreSQL Deadlock Runbook",
            search_mode: "keyword",
          })
        );
      });
    });

    it("displays friendly empty state when no operational runbooks match query", async () => {
      vi.mocked(RetrievalApi.search).mockResolvedValue({
        query: "unknown-query",
        search_mode: "hybrid",
        total_results: 0,
        results: [],
      });

      render(<RunbooksPanel incident={mockIncident} />);

      await waitFor(() => {
        expect(screen.getByTestId("runbooks-empty")).toBeDefined();
        expect(screen.getByText("No Relevant Runbooks Found")).toBeDefined();
      });
    });
  });

  describe("Workstream B: Operational Evidence Ingestion (AddEvidenceModal)", () => {
    it("renders ingestion form, validates JSON payload, and calls IncidentsApi.ingestEvidence", async () => {
      vi.mocked(IncidentsApi.ingestEvidence).mockResolvedValue(mockIngestedEvidence);
      const onClose = vi.fn();
      const onEvidenceAdded = vi.fn();

      render(
        <AddEvidenceModal
          incident={mockIncident}
          isOpen={true}
          onClose={onClose}
          onEvidenceAdded={onEvidenceAdded}
        />
      );

      // Verify modal is open
      expect(screen.getByTestId("add-evidence-modal")).toBeDefined();

      // Fill in summary
      const summaryInput = screen.getByTestId("evidence-summary-input");
      fireEvent.change(summaryInput, {
        target: { value: "Database connection pool exhausted: 150/150 connections busy" },
      });

      // Fill in deduplication key
      const dedupInput = screen.getByTestId("evidence-dedup-key-input");
      fireEvent.change(dedupInput, {
        target: { value: "db-pool-exhausted-1105" },
      });

      // Submit the form
      const submitBtn = screen.getByTestId("submit-evidence-btn");
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(IncidentsApi.ingestEvidence).toHaveBeenCalledWith(
          mockIncident.id,
          expect.objectContaining({
            source_type: "log",
            event_type: "log.error",
            summary: "Database connection pool exhausted: 150/150 connections busy",
            deduplication_key: "db-pool-exhausted-1105",
          })
        );
        expect(onEvidenceAdded).toHaveBeenCalledWith(mockIngestedEvidence);
      });
    });

    it("blocks submission when JSON payload contains syntax error", async () => {
      render(
        <AddEvidenceModal
          incident={mockIncident}
          isOpen={true}
          onClose={vi.fn()}
          onEvidenceAdded={vi.fn()}
        />
      );

      const payloadInput = screen.getByTestId("evidence-payload-input");
      fireEvent.change(payloadInput, { target: { value: "{ invalid json " } });

      expect(screen.getByText(/Invalid JSON syntax/i)).toBeDefined();
      expect(screen.getByTestId("submit-evidence-btn").hasAttribute("disabled")).toBe(true);
    });
  });

  describe("Workstream C & D: Workspace Shell Integration and Investigation Quality", () => {
    it("switches to Runbooks tab from workspace tabs", async () => {
      vi.mocked(RetrievalApi.search).mockResolvedValue(mockRetrievalResponse);

      render(
        <IncidentWorkspace
          incident={mockIncident}
          onBack={vi.fn()}
        />
      );

      // Click on Runbooks tab
      const runbooksTab = screen.getByTestId("tab-runbooks");
      fireEvent.click(runbooksTab);

      expect(runbooksTab.classList.contains("active")).toBe(true);
      expect(screen.getByTestId("runbooks-panel")).toBeDefined();
    });

    it("opens Add Evidence modal from workspace header button", () => {
      render(
        <IncidentWorkspace
          incident={mockIncident}
          onBack={vi.fn()}
        />
      );

      const openModalBtn = screen.getByTestId("workspace-add-evidence-btn");
      fireEvent.click(openModalBtn);

      expect(screen.getByTestId("add-evidence-modal")).toBeDefined();
    });

    it("renders Investigation Quality metrics including entailment, temporal score, and source diversity", () => {
      render(
        <HypothesisCard
          hypothesis={mockHypothesisWithQuality}
        />
      );

      expect(screen.getByText("Citation Entailment")).toBeDefined();
      expect(screen.getByText("95%")).toBeDefined();
      expect(screen.getByText("Temporal Consistency")).toBeDefined();
      expect(screen.getByText("98%")).toBeDefined();
      expect(screen.getByText("Source Diversity")).toBeDefined();
      expect(screen.getByText("85%")).toBeDefined();
      expect(
        screen.getByText(/Evidence timing correlates with consumer lag alert onset/i)
      ).toBeDefined();
    });
  });
});
