import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { IncidentDashboard } from "../components/incidents/IncidentDashboard";
import { IncidentCreationModal } from "../components/incidents/IncidentCreationModal";
import { Navbar } from "../components/layout/Navbar";
import { Sidebar } from "../components/layout/Sidebar";
import { Incident } from "../types/incident";
import { IncidentsApi } from "../api/incidents";

vi.mock("../api/incidents", () => ({
  IncidentsApi: {
    list: vi.fn(),
    create: vi.fn(),
    get: vi.fn(),
    getTimeline: vi.fn(),
    listEvidence: vi.fn(),
  },
}));

const mockIncidents: Incident[] = [
  {
    id: "inc-001",
    organization_id: "org-1",
    title: "High Latency on Payment Gateway",
    description: "Spike in HTTP 504 gateway timeouts on checkout route",
    severity: "critical",
    status: "open",
    service_name: "payment-gateway",
    environment: "production",
    created_at: "2026-10-11T09:00:00Z",
    updated_at: "2026-10-11T09:05:00Z",
    evidence_count: 5,
  },
  {
    id: "inc-002",
    organization_id: "org-1",
    title: "Redis Connection Pool Exhaustion",
    description: "Session store failing to acquire new connections",
    severity: "high",
    status: "investigating",
    service_name: "session-service",
    environment: "production",
    created_at: "2026-10-11T08:30:00Z",
    updated_at: "2026-10-11T08:45:00Z",
    evidence_count: 3,
  },
];

describe("TracePilot Stage A: Product Identity & Incident Architecture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Incident Dashboard & Landing Experience", () => {
    it("renders Incidents heading and short product description", async () => {
      vi.mocked(IncidentsApi.list).mockResolvedValue({
        items: mockIncidents,
        total: 2,
        limit: 50,
        offset: 0,
      });

      render(<IncidentDashboard />);

      expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Incidents");
      expect(
        screen.getByText(/TracePilot AI-powered operational incident triage/i)
      ).toBeDefined();

      await waitFor(() => {
        expect(screen.getByText("High Latency on Payment Gateway")).toBeDefined();
        expect(screen.getByText("Redis Connection Pool Exhaustion")).toBeDefined();
      });
    });

    it("renders loading state while fetching incidents", () => {
      vi.mocked(IncidentsApi.list).mockReturnValue(new Promise(() => {}));

      render(<IncidentDashboard />);

      expect(screen.getByTestId("incidents-loading")).toBeDefined();
      expect(screen.getByText(/Loading incidents from organization workspace/i)).toBeDefined();
    });

    it("renders empty state when no incidents are present", async () => {
      vi.mocked(IncidentsApi.list).mockResolvedValue({
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
      });

      render(<IncidentDashboard />);

      await waitFor(() => {
        expect(screen.getByTestId("incidents-empty")).toBeDefined();
        expect(screen.getByText("No Incidents Found")).toBeDefined();
        expect(screen.getByTestId("empty-create-incident-btn")).toBeDefined();
      });
    });

    it("renders error state when API request fails", async () => {
      vi.mocked(IncidentsApi.list).mockRejectedValue(new Error("Database connection timed out"));

      render(<IncidentDashboard />);

      await waitFor(() => {
        expect(screen.getByTestId("incidents-error")).toBeDefined();
        expect(screen.getByText(/Database connection timed out/i)).toBeDefined();
      });
    });

    it("filters incidents by search input and severity filter chips", async () => {
      vi.mocked(IncidentsApi.list).mockResolvedValue({
        items: mockIncidents,
        total: 2,
        limit: 50,
        offset: 0,
      });

      render(<IncidentDashboard />);

      await waitFor(() => {
        expect(screen.getByText("High Latency on Payment Gateway")).toBeDefined();
      });

      // Filter by search query
      const searchInput = screen.getByTestId("incident-search-input");
      fireEvent.change(searchInput, { target: { value: "Redis" } });

      expect(screen.queryByText("High Latency on Payment Gateway")).toBeNull();
      expect(screen.getByText("Redis Connection Pool Exhaustion")).toBeDefined();

      // Clear search and filter by severity chip
      fireEvent.change(searchInput, { target: { value: "" } });
      const criticalFilter = screen.getByTestId("filter-critical");
      fireEvent.click(criticalFilter);

      expect(screen.getByText("High Latency on Payment Gateway")).toBeDefined();
      expect(screen.queryByText("Redis Connection Pool Exhaustion")).toBeNull();
    });

    it("selects an incident and displays dedicated Stage B investigation workspace", async () => {
      vi.mocked(IncidentsApi.list).mockResolvedValue({
        items: mockIncidents,
        total: 2,
        limit: 50,
        offset: 0,
      });

      const onNavigateRemediations = vi.fn();
      render(<IncidentDashboard onNavigateRemediations={onNavigateRemediations} />);

      await waitFor(() => {
        expect(screen.getByTestId("incident-card-inc-001")).toBeDefined();
      });

      fireEvent.click(screen.getByTestId("incident-card-inc-001"));

      // Verify workspace panel and tabs
      expect(screen.getByTestId("incident-workspace")).toBeDefined();
      expect(screen.getByTestId("workspace-incident-title").textContent).toContain(
        "High Latency on Payment Gateway"
      );
      expect(screen.getByText("inc-001")).toBeDefined();
      expect(screen.getByTestId("tab-overview")).toBeDefined();
      expect(screen.getByTestId("tab-timeline")).toBeDefined();
      expect(screen.getByTestId("tab-evidence")).toBeDefined();
      expect(screen.getByTestId("tab-investigation")).toBeDefined();
      expect(screen.getByTestId("tab-remediation")).toBeDefined();

      // Back button restores list
      fireEvent.click(screen.getByTestId("back-to-incidents-btn"));
      expect(screen.queryByTestId("incident-workspace")).toBeNull();
      expect(screen.getByTestId("incident-cards-list")).toBeDefined();
    });
  });

  describe("Incident Creation Modal", () => {
    it("validates required title field and blocks submission if empty", async () => {
      const onCreated = vi.fn();
      const onClose = vi.fn();

      render(<IncidentCreationModal isOpen={true} onClose={onClose} onCreated={onCreated} />);

      const submitBtn = screen.getByTestId("submit-incident-btn");
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(screen.getByTestId("creation-error-banner")).toBeDefined();
        expect(screen.getByTestId("creation-error-banner").textContent).toContain(
          "Incident title is required."
        );
      });
      expect(IncidentsApi.create).not.toHaveBeenCalled();
      expect(onCreated).not.toHaveBeenCalled();
    });

    it("submits valid payload to IncidentsApi.create and triggers onCreated callback", async () => {
      const newIncident: Incident = {
        id: "inc-new-123",
        organization_id: "org-1",
        title: "Ingress Controller Memory Leak",
        description: "Pods restarting due to OOMKilled events",
        severity: "high",
        status: "open",
        service_name: "ingress-nginx",
        environment: "production",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      vi.mocked(IncidentsApi.create).mockResolvedValue(newIncident);

      const onCreated = vi.fn();
      const onClose = vi.fn();

      render(<IncidentCreationModal isOpen={true} onClose={onClose} onCreated={onCreated} />);

      fireEvent.change(screen.getByTestId("incident-title-input"), {
        target: { value: "Ingress Controller Memory Leak" },
      });
      fireEvent.change(screen.getByTestId("incident-severity-select"), {
        target: { value: "high" },
      });
      fireEvent.change(screen.getByTestId("incident-service-input"), {
        target: { value: "ingress-nginx" },
      });
      fireEvent.change(screen.getByTestId("incident-description-input"), {
        target: { value: "Pods restarting due to OOMKilled events" },
      });

      fireEvent.click(screen.getByTestId("submit-incident-btn"));

      await waitFor(() => {
        expect(IncidentsApi.create).toHaveBeenCalledWith({
          title: "Ingress Controller Memory Leak",
          description: "Pods restarting due to OOMKilled events",
          severity: "high",
          service_name: "ingress-nginx",
          environment: "production",
        });
        expect(onCreated).toHaveBeenCalledWith(newIncident);
        expect(onClose).toHaveBeenCalled();
      });
    });

    it("disables submit button and shows loading text during in-flight submission", async () => {
      let resolvePromise: (val: Incident) => void = () => {};
      vi.mocked(IncidentsApi.create).mockReturnValue(
        new Promise((resolve) => {
          resolvePromise = resolve;
        })
      );

      render(<IncidentCreationModal isOpen={true} onClose={() => {}} onCreated={() => {}} />);

      fireEvent.change(screen.getByTestId("incident-title-input"), {
        target: { value: "Valid Title" },
      });

      const submitBtn = screen.getByTestId("submit-incident-btn");
      fireEvent.click(submitBtn);

      expect(submitBtn.hasAttribute("disabled")).toBe(true);
      expect(submitBtn.textContent).toContain("Creating...");

      // Resolve and complete
      resolvePromise({
        id: "inc-1",
        organization_id: "org-1",
        title: "Valid Title",
        severity: "medium",
        status: "open",
        environment: "production",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    });
  });

  describe("TracePilot Navbar & Navigation Branding", () => {
    it("displays TracePilot branding and navigation view triggers", () => {
      const onViewChange = vi.fn();

      render(
        <Navbar
          user={null}
          organization={null}
          selectedProvider="groq"
          selectedModel="qwen/qwen3.8-27b"
          onLogout={() => {}}
          activeView="incidents"
          onViewChange={onViewChange}
        />
      );

      // Verify header title
      expect(screen.getByText("TracePilot — Incident Management")).toBeDefined();

      // Verify buttons
      expect(screen.getByTestId("navbar-incidents-button")).toBeDefined();
      expect(screen.getByTestId("navbar-remediations-button")).toBeDefined();
      expect(screen.getByTestId("navbar-knowledge-button")).toBeDefined();
      expect(screen.getByTestId("navbar-chat-button")).toBeDefined();

      // Click to switch views
      fireEvent.click(screen.getByTestId("navbar-remediations-button"));
      expect(onViewChange).toHaveBeenCalledWith("remediations");

      fireEvent.click(screen.getByTestId("navbar-knowledge-button"));
      expect(onViewChange).toHaveBeenCalledWith("knowledge");
    });
  });

  describe("TracePilot Sidebar Branding", () => {
    it("displays TracePilot brand title, subtitle, and navigation options", () => {
      const onViewChange = vi.fn();

      render(
        <Sidebar
          user={null}
          organization={null}
          conversations={[]}
          activeConversationId={null}
          knowledgeBases={[]}
          selectedKbId={null}
          providers={[]}
          selectedProvider="groq"
          selectedModel="qwen/qwen3.8-27b"
          activeView="incidents"
          onSelectConversation={() => {}}
          onNewChat={() => {}}
          onDeleteConversation={() => {}}
          onSelectKnowledgeBase={() => {}}
          onSelectProvider={() => {}}
          onSelectModel={() => {}}
          onViewChange={onViewChange}
        />
      );

      expect(screen.getByText("TracePilot")).toBeDefined();
      expect(screen.getByText("SRE Investigation")).toBeDefined();
      expect(screen.getByTestId("sidebar-incidents-button")).toBeDefined();
      expect(screen.getByTestId("sidebar-remediations-button")).toBeDefined();

      fireEvent.click(screen.getByTestId("sidebar-remediations-button"));
      expect(onViewChange).toHaveBeenCalledWith("remediations");
    });
  });

  describe("Application Shell Integration (App)", () => {
    it("mounts App with Incidents as the default landing view", async () => {
      const { App } = await import("../App");
      vi.mocked(IncidentsApi.list).mockResolvedValue({
        items: mockIncidents,
        total: 2,
        limit: 50,
        offset: 0,
      });

      render(<App />);

      // Verify Incidents is displayed by default
      expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Incidents");
      expect(screen.getByTestId("navbar-incidents-button")).toBeDefined();
      expect(screen.getByText("TracePilot — Incident Management")).toBeDefined();
    });
  });
});
