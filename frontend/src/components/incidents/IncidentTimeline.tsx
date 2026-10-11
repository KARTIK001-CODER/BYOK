import React, { useState, useEffect, useCallback } from "react";
import {
  Clock,
  RefreshCw,
  Filter,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Search,
  Bell,
  FileText,
  Activity,
  Rocket,
  GitCommit,
  Radio,
  FileCode,
  AlertTriangle,
} from "lucide-react";
import { TimelineEvent } from "../../types/incident";
import { IncidentsApi } from "../../api/incidents";

interface IncidentTimelineProps {
  incidentId: string;
  onInspectEvidence?: (evidenceId: string) => void;
}

export const IncidentTimeline: React.FC<IncidentTimelineProps> = ({
  incidentId,
  onInspectEvidence,
}) => {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedPayloadIds, setExpandedPayloadIds] = useState<Set<string>>(new Set());

  const fetchTimeline = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await IncidentsApi.getTimeline(incidentId);
      const items = Array.isArray(res) ? res : (res?.events || []);
      setEvents(items);
    } catch (err: unknown) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to load incident timeline.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    fetchTimeline();
  }, [fetchTimeline]);

  const togglePayload = (eventId: string) => {
    setExpandedPayloadIds((prev) => {
      const next = new Set(prev);
      if (next.has(eventId)) {
        next.delete(eventId);
      } else {
        next.add(eventId);
      }
      return next;
    });
  };

  const getSourceIcon = (sourceType: string) => {
    switch (sourceType.toLowerCase()) {
      case "alert":
        return <Bell size={14} className="timeline-icon-alert" />;
      case "log":
        return <FileText size={14} className="timeline-icon-log" />;
      case "metric":
        return <Activity size={14} className="timeline-icon-metric" />;
      case "deployment":
        return <Rocket size={14} className="timeline-icon-deploy" />;
      case "git":
        return <GitCommit size={14} className="timeline-icon-git" />;
      case "trace":
        return <Radio size={14} className="timeline-icon-trace" />;
      default:
        return <FileCode size={14} className="timeline-icon-default" />;
    }
  };

  const formatTimestamp = (ts: string) => {
    try {
      const d = new Date(ts);
      return isNaN(d.getTime()) ? ts : d.toLocaleString();
    } catch {
      return ts;
    }
  };

  const filteredEvents = events.filter((ev) => {
    const matchesSource =
      sourceFilter === "all" ||
      ev.source_type.toLowerCase() === sourceFilter.toLowerCase();

    const matchesSearch =
      ev.summary.toLowerCase().includes(searchQuery.toLowerCase()) ||
      ev.event_type.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (ev.source_reference &&
        ev.source_reference.toLowerCase().includes(searchQuery.toLowerCase()));

    return matchesSource && matchesSearch;
  });

  return (
    <div className="timeline-container" data-testid="incident-timeline">
      {/* Controls & Filter Bar */}
      <div className="timeline-controls-bar">
        <div className="timeline-search-box">
          <Search size={14} color="var(--text-muted)" />
          <input
            type="text"
            placeholder="Filter events by summary, type, reference..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            data-testid="timeline-search-input"
          />
        </div>

        <div className="timeline-filter-group">
          <Filter size={13} color="var(--text-muted)" />
          {["all", "alert", "log", "metric", "deployment", "git", "trace", "manual"].map(
            (src) => (
              <button
                key={src}
                className={`timeline-filter-chip ${sourceFilter === src ? "active" : ""}`}
                onClick={() => setSourceFilter(src)}
                data-testid={`timeline-filter-${src}`}
              >
                {src.toUpperCase()}
              </button>
            )
          )}
        </div>

        <button
          className="btn-secondary-incident"
          onClick={fetchTimeline}
          disabled={isLoading}
          title="Refresh Timeline"
          data-testid="refresh-timeline-btn"
        >
          <RefreshCw size={13} className={isLoading ? "spin" : ""} />
          Refresh
        </button>
      </div>

      {/* Non-causality disclaimer */}
      <div className="timeline-correlation-notice">
        <AlertTriangle size={13} style={{ flexShrink: 0 }} />
        <span>
          Chronological ordering represents observed event timestamps. Temporal proximity does
          not imply direct causality.
        </span>
      </div>

      {/* Content States */}
      {isLoading ? (
        <div className="timeline-loading-state" data-testid="timeline-loading">
          <RefreshCw size={22} className="spin text-accent" />
          <span>Reconstructing incident timeline from operational evidence...</span>
        </div>
      ) : error ? (
        <div className="timeline-error-state" data-testid="timeline-error">
          <span>{error}</span>
          <button
            className="btn-secondary-incident"
            onClick={fetchTimeline}
            style={{ padding: "4px 10px", fontSize: "0.8rem" }}
            data-testid="retry-timeline-btn"
          >
            Retry
          </button>
        </div>
      ) : filteredEvents.length === 0 ? (
        <div className="timeline-empty-state" data-testid="timeline-empty">
          <Clock size={32} color="var(--text-muted)" />
          <h4>No Timeline Events Recorded</h4>
          <p>
            {searchQuery || sourceFilter !== "all"
              ? "No events match the selected filter criteria."
              : "No operational evidence events have been ingested into this incident yet."}
          </p>
        </div>
      ) : (
        <div className="timeline-events-list" data-testid="timeline-events-list">
          {filteredEvents.map((ev, index) => {
            const isExpanded = expandedPayloadIds.has(ev.id);
            const hasPayload =
              ev.normalized_payload && Object.keys(ev.normalized_payload).length > 0;

            return (
              <div
                key={ev.id}
                className="timeline-event-card"
                data-testid={`timeline-event-${ev.id}`}
              >
                <div className="timeline-node">
                  <div className={`timeline-node-dot source-${ev.source_type.toLowerCase()}`}>
                    {getSourceIcon(ev.source_type)}
                  </div>
                  {index < filteredEvents.length - 1 && <div className="timeline-node-line" />}
                </div>

                <div className="timeline-event-body">
                  <div className="timeline-event-header">
                    <div className="timeline-badges">
                      <span className={`badge-source badge-source-${ev.source_type.toLowerCase()}`}>
                        {ev.source_type.toUpperCase()}
                      </span>
                      <span className="badge-event-type">{ev.event_type}</span>
                      {ev.source_reference && (
                        <span className="timeline-reference-tag" title={ev.source_reference}>
                          <ExternalLink size={11} />
                          {ev.source_reference}
                        </span>
                      )}
                    </div>

                    <div className="timeline-timestamp">
                      <Clock size={12} />
                      <span>{formatTimestamp(ev.event_timestamp)}</span>
                    </div>
                  </div>

                  <div className="timeline-event-summary">{ev.summary}</div>

                  <div className="timeline-event-actions">
                    {hasPayload && (
                      <button
                        className="btn-link-action"
                        onClick={() => togglePayload(ev.id)}
                        data-testid={`toggle-payload-${ev.id}`}
                      >
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        {isExpanded ? "Hide Payload" : "View Raw Payload"}
                      </button>
                    )}

                    {onInspectEvidence && (
                      <button
                        className="btn-link-action inspect-link"
                        onClick={() => onInspectEvidence(ev.related_evidence_id || ev.id)}
                        data-testid={`inspect-evidence-${ev.id}`}
                      >
                        Inspect Evidence Detail &rarr;
                      </button>
                    )}
                  </div>

                  {isExpanded && hasPayload && (
                    <div
                      className="timeline-payload-viewer"
                      data-testid={`payload-view-${ev.id}`}
                    >
                      <pre>{JSON.stringify(ev.normalized_payload, null, 2)}</pre>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
