import React, { useState, useEffect, useCallback } from "react";
import {
  Search,
  Filter,
  RefreshCw,
  ExternalLink,
  Clock,
  Layers,
  Database,
  Key,
  X,
  Copy,
  Check,
  PlusCircle,
} from "lucide-react";
import { EvidenceEvent } from "../../types/incident";
import { IncidentsApi } from "../../api/incidents";

interface EvidencePanelProps {
  incidentId: string;
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (id: string | null) => void;
  onAddEvidenceClick?: () => void;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  incidentId,
  selectedEvidenceId,
  onSelectEvidence,
  onAddEvidenceClick,
}) => {
  const [evidenceList, setEvidenceList] = useState<EvidenceEvent[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [activeEvidence, setActiveEvidence] = useState<EvidenceEvent | null>(null);
  const [copiedId, setCopiedId] = useState<boolean>(false);

  const fetchEvidence = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await IncidentsApi.listEvidence(incidentId);
      setEvidenceList(res.items || []);
    } catch (err: unknown) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to load operational evidence.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    fetchEvidence();
  }, [fetchEvidence]);

  // Sync selectedEvidenceId prop if supplied externally (e.g. from Timeline or Citation link)
  useEffect(() => {
    if (selectedEvidenceId && evidenceList.length > 0) {
      const match = evidenceList.find((ev) => ev.id === selectedEvidenceId);
      if (match) {
        setActiveEvidence(match);
      }
    }
  }, [selectedEvidenceId, evidenceList]);

  const handleSelect = (ev: EvidenceEvent) => {
    setActiveEvidence(ev);
    onSelectEvidence?.(ev.id);
  };

  const handleCloseDetail = () => {
    setActiveEvidence(null);
    onSelectEvidence?.(null);
  };

  const handleCopyId = (id: string) => {
    navigator.clipboard.writeText(id).catch(() => {});
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const formatTimestamp = (ts?: string) => {
    if (!ts) return "N/A";
    try {
      const d = new Date(ts);
      return isNaN(d.getTime()) ? ts : d.toLocaleString();
    } catch {
      return ts;
    }
  };

  const filteredEvidence = evidenceList.filter((ev) => {
    const matchesSource =
      sourceFilter === "all" ||
      ev.source_type.toLowerCase() === sourceFilter.toLowerCase();

    const matchesSearch =
      ev.summary.toLowerCase().includes(searchQuery.toLowerCase()) ||
      ev.event_type.toLowerCase().includes(searchQuery.toLowerCase()) ||
      ev.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (ev.source_reference &&
        ev.source_reference.toLowerCase().includes(searchQuery.toLowerCase()));

    return matchesSource && matchesSearch;
  });

  return (
    <div className="evidence-panel-container" data-testid="evidence-panel">
      {/* Controls & Filter Bar */}
      <div className="evidence-controls-bar">
        <div className="evidence-search-box">
          <Search size={14} color="var(--text-muted)" />
          <input
            type="text"
            placeholder="Search evidence by ID, summary, event type..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            data-testid="evidence-search-input"
          />
        </div>

        <div className="evidence-filter-group">
          <Filter size={13} color="var(--text-muted)" />
          {["all", "alert", "log", "metric", "deployment", "git", "trace", "manual"].map(
            (src) => (
              <button
                key={src}
                className={`evidence-filter-chip ${sourceFilter === src ? "active" : ""}`}
                onClick={() => setSourceFilter(src)}
                data-testid={`evidence-filter-${src}`}
              >
                {src.toUpperCase()}
              </button>
            )
          )}
        </div>

        <button
          className="btn-secondary-incident"
          onClick={fetchEvidence}
          disabled={isLoading}
          title="Refresh Evidence"
          data-testid="refresh-evidence-btn"
        >
          <RefreshCw size={13} className={isLoading ? "spin" : ""} />
          Refresh
        </button>

        {onAddEvidenceClick && (
          <button
            type="button"
            className="btn-primary-incident"
            onClick={onAddEvidenceClick}
            data-testid="evidence-panel-add-btn"
          >
            <PlusCircle size={13} />
            Add Evidence
          </button>
        )}
      </div>

      {/* Main Workspace Layout (Cards List + Detail Inspector) */}
      <div className="evidence-split-layout">
        <div className="evidence-list-view">
          {isLoading ? (
            <div className="evidence-loading-state" data-testid="evidence-loading">
              <RefreshCw size={22} className="spin text-accent" />
              <span>Loading incident evidence records...</span>
            </div>
          ) : error ? (
            <div className="evidence-error-state" data-testid="evidence-error">
              <span>{error}</span>
              <button
                className="btn-secondary-incident"
                onClick={fetchEvidence}
                style={{ padding: "4px 10px", fontSize: "0.8rem" }}
              >
                Retry
              </button>
            </div>
          ) : filteredEvidence.length === 0 ? (
            <div className="evidence-empty-state" data-testid="evidence-empty">
              <Database size={32} color="var(--text-muted)" />
              <h4>No Operational Evidence Found</h4>
              <p>
                {searchQuery || sourceFilter !== "all"
                  ? "No evidence records match the selected filter criteria."
                  : "No operational evidence records have been ingested into this incident yet."}
              </p>
            </div>
          ) : (
            <div className="evidence-cards-list" data-testid="evidence-cards-list">
              {filteredEvidence.map((ev) => {
                const isSelected = activeEvidence?.id === ev.id;
                return (
                  <div
                    key={ev.id}
                    className={`evidence-item-card ${isSelected ? "selected" : ""}`}
                    onClick={() => handleSelect(ev)}
                    data-testid={`evidence-item-${ev.id}`}
                  >
                    <div className="evidence-item-top">
                      <div className="evidence-badges">
                        <span className={`badge-source badge-source-${ev.source_type.toLowerCase()}`}>
                          {ev.source_type.toUpperCase()}
                        </span>
                        <span className="badge-event-type">{ev.event_type}</span>
                        <span className="badge-raw-evidence">Original Telemetry</span>
                      </div>
                      <div className="evidence-card-timestamp">
                        <Clock size={11} />
                        <span>{formatTimestamp(ev.event_timestamp)}</span>
                      </div>
                    </div>

                    <div className="evidence-item-summary">{ev.summary}</div>

                    <div className="evidence-item-footer">
                      <span className="evidence-id-tag">ID: {ev.id.substring(0, 13)}...</span>
                      {ev.source_reference && (
                        <span className="evidence-ref-tag" title={ev.source_reference}>
                          <ExternalLink size={11} />
                          {ev.source_reference}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Selected Evidence Detail Inspector */}
        {activeEvidence && (
          <div className="evidence-inspector-drawer" data-testid="evidence-detail-inspector">
            <div className="evidence-inspector-header">
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <Layers size={16} color="var(--accent-primary)" />
                <h3>Evidence Inspector</h3>
              </div>
              <button
                className="btn-icon-close"
                onClick={handleCloseDetail}
                data-testid="close-evidence-detail"
                title="Close Inspector"
              >
                <X size={16} />
              </button>
            </div>

            <div className="evidence-inspector-body">
              {/* Evidence ID & Copy */}
              <div className="inspector-field-group">
                <label className="inspector-label">Evidence Identifier</label>
                <div className="inspector-id-row">
                  <code>{activeEvidence.id}</code>
                  <button
                    className="btn-copy-id"
                    onClick={() => handleCopyId(activeEvidence.id)}
                    title="Copy Evidence ID"
                  >
                    {copiedId ? <Check size={13} color="#10b981" /> : <Copy size={13} />}
                  </button>
                </div>
              </div>

              {/* Source & Type */}
              <div className="inspector-grid-2">
                <div className="inspector-field-group">
                  <label className="inspector-label">Source Type</label>
                  <span className={`badge-source badge-source-${activeEvidence.source_type.toLowerCase()}`}>
                    {activeEvidence.source_type.toUpperCase()}
                  </span>
                </div>
                <div className="inspector-field-group">
                  <label className="inspector-label">Discriminator Event</label>
                  <span className="inspector-value-code">{activeEvidence.event_type}</span>
                </div>
              </div>

              {/* Timestamps: Event Time vs Ingestion Time */}
              <div className="inspector-grid-2">
                <div className="inspector-field-group">
                  <label className="inspector-label">Event Timestamp (Telemetry)</label>
                  <span className="inspector-value">{formatTimestamp(activeEvidence.event_timestamp)}</span>
                </div>
                <div className="inspector-field-group">
                  <label className="inspector-label">Ingestion Timestamp</label>
                  <span className="inspector-value">
                    {formatTimestamp(activeEvidence.ingestion_timestamp || activeEvidence.created_at)}
                  </span>
                </div>
              </div>

              {/* Source Reference & Deduplication */}
              {activeEvidence.source_reference && (
                <div className="inspector-field-group">
                  <label className="inspector-label">Source Reference</label>
                  <span className="inspector-value" style={{ wordBreak: "break-all" }}>
                    {activeEvidence.source_reference}
                  </span>
                </div>
              )}

              {activeEvidence.deduplication_key && (
                <div className="inspector-field-group">
                  <label className="inspector-label">
                    <Key size={11} style={{ display: "inline", marginRight: "4px" }} />
                    Deduplication Key
                  </label>
                  <span className="inspector-value-code">{activeEvidence.deduplication_key}</span>
                </div>
              )}

              {/* Summary */}
              <div className="inspector-field-group">
                <label className="inspector-label">Human-Readable Summary</label>
                <div className="inspector-summary-box">{activeEvidence.summary}</div>
              </div>

              {/* Normalized Payload JSON */}
              <div className="inspector-field-group">
                <label className="inspector-label">Normalized Payload (Structured Telemetry)</label>
                <div className="inspector-json-box">
                  {activeEvidence.normalized_payload &&
                  Object.keys(activeEvidence.normalized_payload).length > 0 ? (
                    <pre>{JSON.stringify(activeEvidence.normalized_payload, null, 2)}</pre>
                  ) : (
                    <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
                      No structured payload attributes present.
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
