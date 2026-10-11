import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { IncidentWorkspace } from "../components/incidents/IncidentWorkspace";
import { IncidentTimeline } from "../components/incidents/IncidentTimeline";
import { EvidencePanel } from "../components/incidents/EvidencePanel";
import { InvestigationPanel } from "../components/incidents/InvestigationPanel";
import { IncidentRemediationTab } from "../components/incidents/IncidentRemediationTab";
import { IncidentsApi } from "../api/incidents";
import { InvestigationsApi } from "../api/investigations";
import { RemediationsApi } from "../api/remediations";
import { Incident, TimelineEvent, EvidenceEvent, TimelineResponse } from "../types/incident";
import { InvestigationJob, HypothesisResponse } from "../types/investigation";
import { RemediationProposal } from "../types/remediation";

vi.mock("../api/incidents", () => ({
  IncidentsApi: {
    getTimeline: vi.fn(),
    listEvidence: vi.fn(),
  },
}));

vi.mock("../api/investigations", () => ({
  InvestigationsApi: {
    listForIncident: vi.fn(),
    trigger: vi.fn(),
    get: vi.fn(),
    listHypotheses: vi.fn(),
    cancel: vi.fn(),
    stream: vi.fn(),
  },
}));

vi.mock("../api/remediations", () => ({
  RemediationsApi: {
    listForIncident: vi.fn(),
  },
}));

const mockIncident: Incident = {
  id: "inc-stage-b-1",
  organization_id: "org-1",
  title: "Cassandra Read Timeouts & Pod CrashLoopBackOff",
  description: "High p99 latency observed on storage cluster node-03",
  severity: "critical",
  status: "investigating",
  service_name: "storage-service",
  environment: "production",
  created_at: "2026-10-11T10:00:00Z",
  updated_at: "2026-10-11T10:15:00Z",
  evidence_count: 4,
};

const mockTimelineEvents: TimelineEvent[] = [
  {
    id: "tl-1",
    incident_id: "inc-stage-b-1",
    event_timestamp: "2026-10-11T10:00:00Z",
    source_type: "alert",
    event_type: "alert.fired",
    summary: "CassandraReadLatencyCritical alert fired",
    related_evidence_id: "ev-1",
    normalized_payload: { threshold_ms: 500, measured_p99_ms: 1820 },
  },
  {
    id: "tl-2",
    incident_id: "inc-stage-b-1",
    event_timestamp: "2026-10-11T10:02:00Z",
    source_type: "deployment",
    event_type: "deployment.rollout",
    summary: "Deployment rollout v2.4.1 completed",
    related_evidence_id: "ev-2",
    normalized_payload: { replica_count: 5, revision: "v2.4.1" },
  },
];

const mockTimelineResponse: TimelineResponse = {
  incident_id: "inc-stage-b-1",
  total_events: mockTimelineEvents.length,
  events: mockTimelineEvents,
  limit: 100,
  offset: 0,
};

const mockEmptyTimelineResponse: TimelineResponse = {
  incident_id: "inc-stage-b-1",
  total_events: 0,
  events: [],
  limit: 100,
  offset: 0,
};

const mockEvidenceList: EvidenceEvent[] = [
  {
    id: "ev-1",
    incident_id: "inc-stage-b-1",
    organization_id: "org-1",
    source_type: "alert",
    event_type: "alert.fired",
    service_name: "storage-service",
    event_timestamp: "2026-10-11T10:00:00Z",
    ingestion_timestamp: "2026-10-11T10:00:05Z",
    summary: "Alert rule CassandraReadLatencyCritical triggered by Prometheus",
    normalized_payload: { alert_name: "CassandraReadLatencyCritical", value: 1820 },
  },
  {
    id: "ev-2",
    incident_id: "inc-stage-b-1",
    organization_id: "org-1",
    source_type: "deployment",
    event_type: "deployment.rollout",
    service_name: "storage-service",
    event_timestamp: "2026-10-11T10:02:00Z",
    ingestion_timestamp: "2026-10-11T10:02:03Z",
    summary: "Kube deployment rollout v2.4.1",
    normalized_payload: { commit: "a89cf12", author: "sre-lead" },
  },
];

const mockJob: InvestigationJob = {
  id: "job-inv-101",
  incident_id: "inc-stage-b-1",
  organization_id: "org-1",
  status: "completed",
  stage: "completed",
  progress: 100,
  created_at: "2026-10-11T10:05:00Z",
  updated_at: "2026-10-11T10:08:00Z",
};

const mockHypothesis: HypothesisResponse = {
  id: "hypo-1",
  investigation_job_id: "job-inv-101",
  incident_id: "inc-stage-b-1",
  organization_id: "org-1",
  claim: "Connection pool starvation caused by memory leak in v2.4.1",
  rationale: "Deployment v2.4.1 increased pool leaks, causing cascading read timeouts",
  confidence: "high",
  confidence_score: 0.88,
  confidence_note: "Model-generated score — not a calibrated probability. Verification recommended.",
  status: "supported",
  groundedness_score: 0.92,
  groundedness_status: "well_supported",
  system_confidence: "high",
  system_confidence_score: 0.95,
  supporting_evidence: [
    {
      id: "link-1",
      hypothesis_id: "hypo-1",
      evidence_event_id: "ev-1",
      link_type: "supports",
      excerpt: "Latency rose to 1820ms immediately following release",
    },
    {
      id: "link-2",
      hypothesis_id: "hypo-1",
      evidence_event_id: "ev-2",
      link_type: "supports",
      excerpt: "Rollout revision v2.4.1",
    },
  ],
  contradicting_evidence: [],
  assessment_details: {
    support_score: 0.92,
    contradiction_score: 0.05,
    calibration_status: "validated",
    assessment_reasons: ["Strong temporal alignment between release and alert"],
  },
  created_at: "2026-10-11T10:08:00Z",
};

const mockRemediationProposal: RemediationProposal = {
  id: "rem-prop-1",
  incident_id: "inc-stage-b-1",
  investigation_job_id: "job-inv-101",
  organization_id: "org-1",
  title: "Rollback storage-service to v2.4.0",
  description: "Revert deployment to restore connection pool stability",
  status: "proposed",
  risk_level: "low",
  actions: [
    {
      step_number: 1,
      action_type: "rollback",
      description: "Revert deployment to v2.4.0",
      target_system: "storage-service",
      risk_level: "low",
      reversible: true,
      requires_human_approval: true,
      is_executable: false,
    },
  ],
  version: 1,
  is_executable: false,
  risk_assessment: {
    overall_risk_level: "low",
    risk_score: 0.2,
    risk_factors: ["Stateless deployment rollback"],
    blast_radius: "1 pod replica restart",
    reversibility_assessment: "Standard k8s deployment rollout undo",
    requires_human_approval: true,
    execution_restricted: true,
    restrictions_note: "Remediation execution disabled",
  },
  created_at: "2026-10-11T10:09:00Z",
  updated_at: "2026-10-11T10:09:00Z",
};

describe("TracePilot Stage B — Core Incident Investigation Experience", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("IncidentWorkspace Component", () => {
    it("renders incident header metadata, tabs, and switches views while preserving incident context", async () => {
      const onBack = vi.fn();
      render(<IncidentWorkspace incident={mockIncident} onBack={onBack} />);

      // Verify header details
      expect(screen.getByTestId("workspace-incident-title").textContent).toContain(
        "Cassandra Read Timeouts & Pod CrashLoopBackOff"
      );
      expect(screen.getByText("inc-stage-b-1")).toBeDefined();
      expect(screen.getAllByText(/critical/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText("storage-service").length).toBeGreaterThan(0);

      // Default tab is overview
      expect(screen.getByTestId("tab-overview")).toBeDefined();
      expect(screen.getByText("Incident Summary & Symptoms")).toBeDefined();

      // Switch to Timeline
      vi.mocked(IncidentsApi.getTimeline).mockResolvedValue(mockTimelineResponse);
      fireEvent.click(screen.getByTestId("tab-timeline"));
      expect(screen.getByTestId("tab-timeline").classList.contains("active")).toBe(true);

      // Switch to Evidence
      vi.mocked(IncidentsApi.listEvidence).mockResolvedValue({
        items: mockEvidenceList,
        total: 2,
        limit: 50,
        offset: 0,
      });
      fireEvent.click(screen.getByTestId("tab-evidence"));
      expect(screen.getByTestId("tab-evidence").classList.contains("active")).toBe(true);

      // Switch to Investigation
      vi.mocked(InvestigationsApi.listForIncident).mockResolvedValue({
        items: [mockJob],
        total: 1,
        limit: 50,
        offset: 0,
      });
      fireEvent.click(screen.getByTestId("tab-investigation"));
      expect(screen.getByTestId("tab-investigation").classList.contains("active")).toBe(true);

      // Switch to Remediation
      vi.mocked(RemediationsApi.listForIncident).mockResolvedValue({
        items: [mockRemediationProposal],
        total: 1,
      });
      fireEvent.click(screen.getByTestId("tab-remediation"));
      expect(screen.getByTestId("tab-remediation").classList.contains("active")).toBe(true);

      // Back navigation triggers onBack
      fireEvent.click(screen.getByTestId("back-to-incidents-btn"));
      expect(onBack).toHaveBeenCalled();
    });
  });

  describe("IncidentTimeline Component", () => {
    it("fetches chronological events, filters by source type, and toggles payload preview", async () => {
      vi.mocked(IncidentsApi.getTimeline).mockResolvedValue(mockTimelineResponse);
      const onInspectEvidence = vi.fn();

      render(
        <IncidentTimeline
          incidentId={mockIncident.id}
          onInspectEvidence={onInspectEvidence}
        />
      );

      await waitFor(() => {
        expect(IncidentsApi.getTimeline).toHaveBeenCalledWith(mockIncident.id);
        expect(
          screen.getByText("CassandraReadLatencyCritical alert fired")
        ).toBeDefined();
        expect(
          screen.getByText("Deployment rollout v2.4.1 completed")
        ).toBeDefined();
      });

      // Toggle payload view on first event
      const toggleBtn = screen.getByTestId("toggle-payload-tl-1");
      fireEvent.click(toggleBtn);
      expect(screen.getByText(/measured_p99_ms/i)).toBeDefined();

      // Cross link to inspect evidence
      const inspectBtn = screen.getByTestId("inspect-evidence-tl-1");
      fireEvent.click(inspectBtn);
      expect(onInspectEvidence).toHaveBeenCalledWith("ev-1");

      // Filter by alert chip
      const alertPill = screen.getByTestId("timeline-filter-alert");
      fireEvent.click(alertPill);
      expect(
        screen.getByText("CassandraReadLatencyCritical alert fired")
      ).toBeDefined();
      expect(
        screen.queryByText("Deployment rollout v2.4.1 completed")
      ).toBeNull();
    });

    it("renders empty timeline state when no events exist", async () => {
      vi.mocked(IncidentsApi.getTimeline).mockResolvedValue(mockEmptyTimelineResponse);

      render(<IncidentTimeline incidentId={mockIncident.id} />);

      await waitFor(() => {
        expect(screen.getByTestId("timeline-empty")).toBeDefined();
        expect(screen.getByText("No Timeline Events Recorded")).toBeDefined();
      });
    });

    it("renders error banner and supports retry on API failure", async () => {
      vi.mocked(IncidentsApi.getTimeline).mockRejectedValue(
        new Error("Network timeout reaching incident timeline")
      );

      render(<IncidentTimeline incidentId={mockIncident.id} />);

      await waitFor(() => {
        expect(screen.getByTestId("timeline-error")).toBeDefined();
        expect(
          screen.getByText(/Network timeout reaching incident timeline/i)
        ).toBeDefined();
      });

      // Click retry
      vi.mocked(IncidentsApi.getTimeline).mockResolvedValue(mockTimelineResponse);
      fireEvent.click(screen.getByTestId("retry-timeline-btn"));

      await waitFor(() => {
        expect(
          screen.getByText("CassandraReadLatencyCritical alert fired")
        ).toBeDefined();
      });
    });
  });

  describe("EvidencePanel Component", () => {
    it("renders evidence items, handles search filter, and opens inspector drawer", async () => {
      vi.mocked(IncidentsApi.listEvidence).mockResolvedValue({
        items: mockEvidenceList,
        total: 2,
        limit: 50,
        offset: 0,
      });

      render(<EvidencePanel incidentId={mockIncident.id} />);

      await waitFor(() => {
        expect(IncidentsApi.listEvidence).toHaveBeenCalledWith(mockIncident.id);
        expect(
          screen.getByText("Alert rule CassandraReadLatencyCritical triggered by Prometheus")
        ).toBeDefined();
      });

      // Search filter
      const searchInput = screen.getByTestId("evidence-search-input");
      fireEvent.change(searchInput, { target: { value: "Kube" } });
      expect(screen.queryByTestId("evidence-item-ev-1")).toBeNull();
      expect(screen.getByTestId("evidence-item-ev-2")).toBeDefined();

      // Click card to open drawer
      fireEvent.click(screen.getByTestId("evidence-item-ev-2"));
      expect(screen.getByTestId("evidence-detail-inspector")).toBeDefined();
      expect(screen.getByText("Evidence Inspector")).toBeDefined();
    });
  });

  describe("InvestigationPanel & HypothesisCard Component", () => {
    it("triggers a new investigation, shows running state, and lists hypotheses with groundedness and uncalibrated confidence note", async () => {
      vi.mocked(InvestigationsApi.listForIncident).mockResolvedValue({
        items: [mockJob],
        total: 1,
        limit: 50,
        offset: 0,
      });
      vi.mocked(InvestigationsApi.listHypotheses).mockResolvedValue({
        items: [mockHypothesis],
        total: 1,
        limit: 50,
        offset: 0,
      });

      const onInspectEvidence = vi.fn();
      render(
        <InvestigationPanel
          incidentId={mockIncident.id}
          onInspectEvidence={onInspectEvidence}
        />
      );

      await waitFor(() => {
        expect(InvestigationsApi.listForIncident).toHaveBeenCalledWith(mockIncident.id);
        expect(InvestigationsApi.listHypotheses).toHaveBeenCalledWith("job-inv-101");
      });

      // Verify Hypothesis Card details
      expect(
        screen.getByText("Connection pool starvation caused by memory leak in v2.4.1")
      ).toBeDefined();

      // Model confidence disclaimer (truthful, uncalibrated)
      expect(
        screen.getByText(/Model-generated score — not a calibrated probability/i)
      ).toBeDefined();

      // Groundedness score chip
      expect(screen.getByText("92% Grounded")).toBeDefined();

      // Supporting citations
      expect(screen.getByTestId("citation-link-ev-1")).toBeDefined();
      fireEvent.click(screen.getByTestId("citation-link-ev-1"));
      expect(onInspectEvidence).toHaveBeenCalledWith("ev-1");
    });

    it("triggers a new investigation job with disabled state during in-flight submission", async () => {
      vi.mocked(InvestigationsApi.listForIncident).mockResolvedValue({
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
      });
      let resolveTrigger: (job: InvestigationJob) => void = () => {};
      vi.mocked(InvestigationsApi.trigger).mockReturnValue(
        new Promise((resolve) => {
          resolveTrigger = resolve;
        })
      );

      render(<InvestigationPanel incidentId={mockIncident.id} />);

      await waitFor(() => {
        expect(screen.getByTestId("start-investigation-btn")).toBeDefined();
      });

      const triggerBtn = screen.getByTestId("start-investigation-btn");
      fireEvent.click(triggerBtn);

      // Button is disabled and shows Triggering Job...
      expect(triggerBtn.hasAttribute("disabled")).toBe(true);
      expect(triggerBtn.textContent).toContain("Triggering Job...");

      // Resolve creation
      resolveTrigger({
        id: "job-inv-new",
        incident_id: mockIncident.id,
        organization_id: "org-1",
        status: "queued",
        stage: "queued",
        progress: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      await waitFor(() => {
        expect(InvestigationsApi.trigger).toHaveBeenCalledWith(
          mockIncident.id,
          expect.objectContaining({ result_limit: 20 })
        );
      });
    });
  });

  describe("IncidentRemediationTab Component", () => {
    it("renders remediation proposals with strict non-execution safety boundary banner and navigates to review center", async () => {
      vi.mocked(RemediationsApi.listForIncident).mockResolvedValue({
        items: [mockRemediationProposal],
        total: 1,
      });
      const onOpenReviewCenter = vi.fn();

      render(
        <IncidentRemediationTab
          incidentId={mockIncident.id}
          onOpenReviewCenter={onOpenReviewCenter}
        />
      );

      await waitFor(() => {
        expect(RemediationsApi.listForIncident).toHaveBeenCalledWith(mockIncident.id);
        expect(screen.getByTestId("safety-boundary-banner")).toBeDefined();
        expect(
          screen.getByText(/Automated remediation execution is strictly disabled/i)
        ).toBeDefined();
        expect(
          screen.getByText("Rollback storage-service to v2.4.0")
        ).toBeDefined();
        expect(screen.getByText("PROPOSED")).toBeDefined();
      });

      // Click to open review center
      const reviewBtn = screen.getByTestId("open-review-center-btn");
      fireEvent.click(reviewBtn);
      expect(onOpenReviewCenter).toHaveBeenCalledWith(mockIncident.id);
    });
  });
});
