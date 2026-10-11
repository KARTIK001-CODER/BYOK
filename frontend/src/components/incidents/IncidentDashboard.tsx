import React, { useState, useEffect, useCallback } from "react";
import {
  AlertOctagon,
  Plus,
  RefreshCw,
  Search,
  Filter,
  Clock,
  Server,
} from "lucide-react";
import { Incident } from "../../types/incident";
import { IncidentsApi } from "../../api/incidents";
import { IncidentCreationModal } from "./IncidentCreationModal";

import { IncidentWorkspace } from "./IncidentWorkspace";

interface IncidentDashboardProps {
  onNavigateRemediations?: (incidentId?: string) => void;
}

export const IncidentDashboard: React.FC<IncidentDashboardProps> = ({
  onNavigateRemediations,
}) => {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [showCreationModal, setShowCreationModal] = useState(false);

  const fetchIncidents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await IncidentsApi.list();
      setIncidents(res.items || []);
    } catch (err: unknown) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to load incidents from organization workspace.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  const handleIncidentCreated = (newIncident: Incident) => {
    setIncidents((prev) => [newIncident, ...prev]);
    setSelectedIncident(newIncident);
  };

  const filteredIncidents = incidents.filter((inc) => {
    const matchesSearch =
      inc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (inc.service_name && inc.service_name.toLowerCase().includes(searchQuery.toLowerCase())) ||
      inc.status.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesSeverity =
      severityFilter === "all" || inc.severity.toLowerCase() === severityFilter.toLowerCase();

    return matchesSearch && matchesSeverity;
  });

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return isNaN(d.getTime()) ? dateStr : d.toLocaleString();
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="incident-dashboard-container" data-testid="incident-dashboard">
      <div className="incident-main-view">
        {selectedIncident ? (
          <IncidentWorkspace
            incident={selectedIncident}
            onBack={() => setSelectedIncident(null)}
            onNavigateRemediations={onNavigateRemediations}
          />
        ) : (
          /* Incident List View */
          <>
            <div className="incident-header-section">
              <div className="incident-header-top">
                <div className="incident-title-group">
                  <h1>
                    <AlertOctagon size={24} color="var(--accent-primary)" />
                    Incidents
                  </h1>
                  <p className="incident-subtitle">
                    TracePilot AI-powered operational incident triage, chronological timeline reconstruction, and
                    grounded root-cause investigation.
                  </p>
                </div>

                <div className="incident-actions-group">
                  <button
                    className="btn-secondary-incident"
                    onClick={fetchIncidents}
                    disabled={isLoading}
                    title="Refresh Incidents"
                    data-testid="refresh-incidents-btn"
                  >
                    <RefreshCw size={14} className={isLoading ? "spin" : ""} />
                    Refresh
                  </button>
                  <button
                    className="btn-primary-incident"
                    onClick={() => setShowCreationModal(true)}
                    data-testid="new-incident-btn"
                  >
                    <Plus size={16} />
                    New Incident
                  </button>
                </div>
              </div>

              {/* Controls Bar */}
              <div className="incident-controls-bar">
                <div className="incident-search-input">
                  <Search size={15} color="var(--text-muted)" />
                  <input
                    type="text"
                    placeholder="Filter incidents by title, service, status..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    data-testid="incident-search-input"
                  />
                </div>

                <div className="incident-filters">
                  <Filter size={14} color="var(--text-muted)" style={{ marginRight: 4 }} />
                  {["all", "critical", "high", "medium", "low", "info"].map((sev) => (
                    <button
                      key={sev}
                      className={`filter-chip ${severityFilter === sev ? "active" : ""}`}
                      onClick={() => setSeverityFilter(sev)}
                      data-testid={`filter-${sev}`}
                    >
                      {sev.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Content States */}
            {isLoading ? (
              <div
                style={{
                  padding: "48px 0",
                  textAlign: "center",
                  color: "var(--text-muted)",
                  fontSize: "0.9rem",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: "10px",
                }}
                data-testid="incidents-loading"
              >
                <RefreshCw size={24} className="spin text-accent" />
                <span>Loading incidents from organization workspace...</span>
              </div>
            ) : error ? (
              <div className="incident-error-banner" data-testid="incidents-error">
                <span>{error}</span>
                <button
                  className="btn-secondary-incident"
                  onClick={fetchIncidents}
                  style={{ padding: "4px 10px", fontSize: "0.8rem" }}
                >
                  Retry
                </button>
              </div>
            ) : filteredIncidents.length === 0 ? (
              <div className="incident-empty-state" data-testid="incidents-empty">
                <div className="incident-empty-icon">
                  <AlertOctagon size={24} />
                </div>
                <div className="incident-empty-title">No Incidents Found</div>
                <div className="incident-empty-desc">
                  {searchQuery || severityFilter !== "all"
                    ? "No incidents match your current filter parameters. Try clearing the search query or severity filter."
                    : "No operational incidents have been ingested or created for this organization workspace yet."}
                </div>
                <button
                  className="btn-primary-incident"
                  onClick={() => setShowCreationModal(true)}
                  data-testid="empty-create-incident-btn"
                >
                  <Plus size={16} />
                  Create First Incident
                </button>
              </div>
            ) : (
              <div className="incident-cards-grid" data-testid="incident-cards-list">
                {filteredIncidents.map((inc) => (
                  <div
                    key={inc.id}
                    className="incident-card"
                    onClick={() => setSelectedIncident(inc)}
                    data-testid={`incident-card-${inc.id}`}
                  >
                    <div className="incident-card-top">
                      <div className="incident-card-badges">
                        <span className={`badge-severity badge-severity-${inc.severity}`}>
                          {inc.severity}
                        </span>
                        <span className="badge-status">{inc.status}</span>
                        {inc.service_name && (
                          <span className="badge-service">{inc.service_name}</span>
                        )}
                        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                          ({inc.environment})
                        </span>
                      </div>
                      <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                        {formatDate(inc.created_at)}
                      </span>
                    </div>

                    <h3 className="incident-card-title">{inc.title}</h3>

                    {inc.description && (
                      <p className="incident-card-desc">{inc.description}</p>
                    )}

                    <div className="incident-card-footer">
                      <div className="incident-meta-items">
                        <span className="meta-item">
                          <Server size={13} />
                          {inc.service_name || "Unassigned"}
                        </span>
                        <span className="meta-item">
                          <Clock size={13} />
                          Created: {formatDate(inc.created_at)}
                        </span>
                      </div>
                      <span style={{ color: "var(--accent-primary)", fontWeight: 600 }}>
                        View Investigation &rarr;
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <IncidentCreationModal
        isOpen={showCreationModal}
        onClose={() => setShowCreationModal(false)}
        onCreated={handleIncidentCreated}
      />
    </div>
  );
};
