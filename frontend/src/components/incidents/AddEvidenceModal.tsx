import React, { useState } from "react";
import {
  X,
  PlusCircle,
  Clock,
  Code,
  Tag,
  Link,
  Key,
  AlertTriangle,
  CheckCircle2,
  FileText,
  Layers,
  RotateCcw,
  AlertCircle,
  Check,
} from "lucide-react";
import {
  EvidenceBatchResponse,
  EvidenceEvent,
  EvidenceEventCreatePayload,
  EvidenceSourceType,
  Incident,
} from "../../types/incident";
import { IncidentsApi } from "../../api/incidents";

interface AddEvidenceModalProps {
  incident: Incident;
  isOpen: boolean;
  onClose: () => void;
  onEvidenceAdded: (evidence?: EvidenceEvent) => void;
}

type IngestionMode = "single" | "bulk";

const SOURCE_TYPE_OPTIONS: {
  value: EvidenceSourceType;
  label: string;
  placeholderEvent: string;
}[] = [
  { value: "alert", label: "Alert (Prometheus, Datadog, PagerDuty)", placeholderEvent: "alert.fired" },
  { value: "log", label: "Application / System Log", placeholderEvent: "log.error" },
  { value: "metric", label: "Metric Threshold / Anomaly", placeholderEvent: "metric.spike" },
  { value: "deployment", label: "Deployment / Kubernetes Rollout", placeholderEvent: "deployment.rollout" },
  { value: "git", label: "Git Commit / Release Tag", placeholderEvent: "git.commit" },
  { value: "trace", label: "Distributed Trace / Span", placeholderEvent: "trace.span_error" },
  { value: "manual", label: "Manual SRE Observation", placeholderEvent: "operator.observation" },
];

export const AddEvidenceModal: React.FC<AddEvidenceModalProps> = ({
  incident,
  isOpen,
  onClose,
  onEvidenceAdded,
}) => {
  const [mode, setMode] = useState<IngestionMode>("single");

  // Single mode state
  const [sourceType, setSourceType] = useState<EvidenceSourceType>("log");
  const [eventType, setEventType] = useState<string>("log.error");
  const [summary, setSummary] = useState<string>("");
  const [eventTimestamp, setEventTimestamp] = useState<string>(
    new Date().toISOString()
  );
  const [sourceReference, setSourceReference] = useState<string>("");
  const [deduplicationKey, setDeduplicationKey] = useState<string>("");
  const [rawPayload, setRawPayload] = useState<string>(
    JSON.stringify({ service: incident.service_name || "unknown", severity: "error" }, null, 2)
  );
  const [singleJsonError, setSingleJsonError] = useState<string | null>(null);

  // Bulk mode state
  const getSampleBatchJson = () =>
    JSON.stringify(
      [
        {
          source_type: "alert",
          event_type: "alert.fired",
          event_timestamp: new Date(Date.now() - 300000).toISOString(),
          summary: `High error rate alert fired on ${incident.service_name || "service"}`,
          deduplication_key: `alert-${incident.id}-001`,
          normalized_payload: { threshold: "5%", error_rate: "12.4%" },
        },
        {
          source_type: "deployment",
          event_type: "deployment.rollout",
          event_timestamp: new Date(Date.now() - 600000).toISOString(),
          summary: `Canary rollout revision v2.4.1 deployed to ${incident.environment}`,
          deduplication_key: `deploy-${incident.id}-001`,
          source_reference: "https://git.internal/repo/commit/7a89b1",
          normalized_payload: { revision: "v2.4.1", replicas: 3 },
        },
        {
          source_type: "log",
          event_type: "log.error",
          event_timestamp: new Date().toISOString(),
          summary: `Connection pool exhausted: 150/150 connections busy`,
          deduplication_key: `log-${incident.id}-001`,
          normalized_payload: { active_conns: 150, max_conns: 150 },
        },
      ],
      null,
      2
    );

  const [bulkJson, setBulkJson] = useState<string>(getSampleBatchJson());
  const [parsedBulkCount, setParsedBulkCount] = useState<number>(3);
  const [bulkJsonError, setBulkJsonError] = useState<string | null>(null);
  const [batchResponse, setBatchResponse] = useState<EvidenceBatchResponse | null>(null);

  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSourceTypeChange = (type: EvidenceSourceType) => {
    setSourceType(type);
    const opt = SOURCE_TYPE_OPTIONS.find((o) => o.value === type);
    if (opt) {
      setEventType(opt.placeholderEvent);
    }
  };

  const handleTimestampNow = () => {
    setEventTimestamp(new Date().toISOString());
  };

  const handleBulkJsonChange = (val: string) => {
    setBulkJson(val);
    setBatchResponse(null);
    setSubmitError(null);
    if (!val.trim()) {
      setParsedBulkCount(0);
      setBulkJsonError("Batch payload cannot be empty.");
      return;
    }
    try {
      const parsed = JSON.parse(val);
      if (!Array.isArray(parsed)) {
        setBulkJsonError("Bulk payload must be a JSON array of evidence items.");
        setParsedBulkCount(0);
        return;
      }
      if (parsed.length === 0) {
        setBulkJsonError("Bulk array must contain at least 1 evidence item.");
        setParsedBulkCount(0);
        return;
      }
      if (parsed.length > 100) {
        setBulkJsonError("Batch exceeds server limit (maximum 100 items per batch).");
        setParsedBulkCount(parsed.length);
        return;
      }
      // Check required fields on each item
      for (let i = 0; i < parsed.length; i++) {
        const item = parsed[i];
        if (!item.source_type || !item.event_type || !item.event_timestamp || !item.summary) {
          setBulkJsonError(
            `Item #${i + 1} is missing required fields (source_type, event_type, event_timestamp, summary).`
          );
          setParsedBulkCount(parsed.length);
          return;
        }
      }
      setParsedBulkCount(parsed.length);
      setBulkJsonError(null);
    } catch {
      setBulkJsonError("Invalid JSON syntax.");
      setParsedBulkCount(0);
    }
  };

  const handleSingleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    setSubmitSuccess(null);

    if (!summary.trim()) {
      setSubmitError("Event summary is required.");
      return;
    }

    if (!eventType.trim()) {
      setSubmitError("Event type discriminator is required.");
      return;
    }

    let normalizedPayload: Record<string, unknown> = {};
    if (rawPayload.trim()) {
      try {
        normalizedPayload = JSON.parse(rawPayload);
        if (typeof normalizedPayload !== "object" || normalizedPayload === null || Array.isArray(normalizedPayload)) {
          setSingleJsonError("Normalized payload must be a JSON object.");
          return;
        }
        setSingleJsonError(null);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Invalid JSON syntax.";
        setSingleJsonError(msg);
        return;
      }
    }

    const dateObj = new Date(eventTimestamp);
    if (isNaN(dateObj.getTime())) {
      setSubmitError("Invalid event timestamp. Must be a valid ISO 8601 date.");
      return;
    }

    const payload: EvidenceEventCreatePayload = {
      source_type: sourceType,
      event_type: eventType.trim(),
      event_timestamp: dateObj.toISOString(),
      summary: summary.trim(),
      normalized_payload: normalizedPayload,
      source_reference: sourceReference.trim() || null,
      deduplication_key: deduplicationKey.trim() || null,
    };

    setSubmitting(true);
    try {
      const created = await IncidentsApi.ingestEvidence(incident.id, payload);
      setSubmitSuccess("Evidence successfully ingested and attached to incident.");
      onEvidenceAdded(created);
      setTimeout(() => {
        onClose();
      }, 700);
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : "Failed to ingest evidence event.";
      setSubmitError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleBulkSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    setSubmitSuccess(null);

    let items: EvidenceEventCreatePayload[] = [];
    try {
      items = JSON.parse(bulkJson);
      if (!Array.isArray(items) || items.length === 0) {
        setSubmitError("Bulk payload must contain at least 1 item.");
        return;
      }
      if (items.length > 100) {
        setSubmitError("Batch size exceeds 100 items limit.");
        return;
      }
    } catch {
      setSubmitError("Cannot submit malformed JSON.");
      return;
    }

    setSubmitting(true);
    try {
      const resp = await IncidentsApi.ingestEvidenceBatch(incident.id, items);
      setBatchResponse(resp);
      onEvidenceAdded();
      if (resp.failed_count === 0 && resp.rejected_count === 0) {
        setSubmitSuccess(
          `Batch completed: ${resp.accepted_count} newly accepted, ${resp.duplicate_count} deduplicated.`
        );
      } else {
        setSubmitError(
          `Batch completed with issues: ${resp.accepted_count} accepted, ${resp.duplicate_count} duplicates, ${resp.rejected_count} rejected, ${resp.failed_count} failed.`
        );
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : "Batch evidence ingestion failed.";
      setSubmitError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetryFailedItems = () => {
    if (!batchResponse) return;
    try {
      const originalItems: EvidenceEventCreatePayload[] = JSON.parse(bulkJson);
      const failedIndices = new Set(
        batchResponse.results
          .filter((r) => r.status === "failed" || r.status === "rejected")
          .map((r) => r.index)
      );
      const filtered = originalItems.filter((_, idx) => failedIndices.has(idx));
      const newJson = JSON.stringify(filtered, null, 2);
      setBulkJson(newJson);
      setParsedBulkCount(filtered.length);
      setBatchResponse(null);
      setSubmitError(null);
      setSubmitSuccess(null);
    } catch {
      // ignore
    }
  };

  return (
    <div className="modal-backdrop" data-testid="add-evidence-modal-backdrop">
      <div className="modal-container add-evidence-modal" data-testid="add-evidence-modal">
        {/* Header */}
        <div className="modal-header">
          <div className="flex items-center gap-2">
            <PlusCircle size={20} className="text-primary" />
            <div>
              <h3 className="modal-title">Ingest Operational Evidence</h3>
              <p className="modal-subtitle">
                Attach telemetry to incident <code>{incident.id}</code> ({incident.service_name || "general"})
              </p>
            </div>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close dialog"
            data-testid="close-evidence-modal-btn"
          >
            <X size={18} />
          </button>
        </div>

        {/* Mode Switcher Tabs */}
        <div className="modal-mode-tabs flex border-b px-6 pt-2 bg-secondary" role="tablist">
          <button
            type="button"
            className={`btn-mode-tab py-2 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 ${
              mode === "single"
                ? "border-primary text-primary active"
                : "border-transparent text-muted"
            }`}
            onClick={() => {
              setMode("single");
              setSubmitError(null);
              setSubmitSuccess(null);
            }}
            data-testid="mode-single-tab"
          >
            <FileText size={14} />
            Single Evidence Event
          </button>
          <button
            type="button"
            className={`btn-mode-tab py-2 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 ${
              mode === "bulk"
                ? "border-primary text-primary active"
                : "border-transparent text-muted"
            }`}
            onClick={() => {
              setMode("bulk");
              setSubmitError(null);
              setSubmitSuccess(null);
            }}
            data-testid="mode-bulk-tab"
          >
            <Layers size={14} />
            Bulk Telemetry (JSON Batch)
          </button>
        </div>

        {/* Messages */}
        <div className="px-6 pt-3">
          {submitError && (
            <div className="incident-error-banner mb-3" data-testid="evidence-submit-error">
              <AlertTriangle size={16} />
              <span>{submitError}</span>
            </div>
          )}

          {submitSuccess && (
            <div className="alert-success flex items-center gap-2 p-2 rounded mb-3" data-testid="evidence-submit-success">
              <CheckCircle2 size={16} />
              <span>{submitSuccess}</span>
            </div>
          )}
        </div>

        {/* Mode: Single Event Form */}
        {mode === "single" && (
          <form onSubmit={handleSingleSubmit} className="modal-body space-y-4 pt-1">
            {/* Source Type Selector */}
            <div className="form-group">
              <label htmlFor="source-type-select" className="form-label">
                <Tag size={13} /> Source Telemetry Type:
              </label>
              <select
                id="source-type-select"
                className="form-input"
                value={sourceType}
                onChange={(e) =>
                  handleSourceTypeChange(e.target.value as EvidenceSourceType)
                }
                data-testid="evidence-source-type-select"
              >
                {SOURCE_TYPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Event Type & Timestamp */}
            <div className="grid grid-cols-2 gap-3">
              <div className="form-group">
                <label htmlFor="event-type-input" className="form-label">Event Discriminator Type:</label>
                <input
                  id="event-type-input"
                  type="text"
                  className="form-input"
                  placeholder="e.g. log.error, alert.fired"
                  value={eventType}
                  onChange={(e) => setEventType(e.target.value)}
                  required
                  data-testid="evidence-event-type-input"
                />
              </div>

              <div className="form-group">
                <div className="flex justify-between items-center mb-1">
                  <label htmlFor="event-timestamp-input" className="form-label mb-0">
                    <Clock size={12} /> Event Timestamp (UTC):
                  </label>
                  <button
                    type="button"
                    className="btn-link text-xs"
                    onClick={handleTimestampNow}
                    title="Use current UTC timestamp"
                  >
                    Set to Now
                  </button>
                </div>
                <input
                  id="event-timestamp-input"
                  type="text"
                  className="form-input"
                  value={eventTimestamp}
                  onChange={(e) => setEventTimestamp(e.target.value)}
                  required
                  data-testid="evidence-timestamp-input"
                />
              </div>
            </div>

            {/* Summary */}
            <div className="form-group">
              <label htmlFor="evidence-summary-input" className="form-label">Event Summary:</label>
              <textarea
                id="evidence-summary-input"
                className="form-input"
                rows={2}
                placeholder="e.g. Connection pool exhausted: 150/150 connections busy after deployment v2.4.1"
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                required
                data-testid="evidence-summary-input"
              />
            </div>

            {/* Source Reference & Deduplication Key */}
            <div className="grid grid-cols-2 gap-3">
              <div className="form-group">
                <label htmlFor="source-reference-input" className="form-label">
                  <Link size={12} /> Source Reference (Optional):
                </label>
                <input
                  id="source-reference-input"
                  type="text"
                  className="form-input"
                  placeholder="URL, commit SHA, alert ID"
                  value={sourceReference}
                  onChange={(e) => setSourceReference(e.target.value)}
                  data-testid="evidence-reference-input"
                />
              </div>

              <div className="form-group">
                <label htmlFor="dedup-key-input" className="form-label">
                  <Key size={12} /> Deduplication Key (Optional):
                </label>
                <input
                  id="dedup-key-input"
                  type="text"
                  className="form-input"
                  placeholder="Stable key to prevent duplicate ingestion"
                  value={deduplicationKey}
                  onChange={(e) => setDeduplicationKey(e.target.value)}
                  data-testid="evidence-dedup-key-input"
                />
              </div>
            </div>

            {/* Normalized JSON Payload */}
            <div className="form-group">
              <div className="flex justify-between items-center mb-1">
                <label htmlFor="payload-json-input" className="form-label mb-0">
                  <Code size={12} /> Normalized Payload (JSON):
                </label>
                {singleJsonError ? (
                  <span className="text-xs text-danger">{singleJsonError}</span>
                ) : (
                  <span className="text-xs text-muted">Valid JSON object required</span>
                )}
              </div>
              <textarea
                id="payload-json-input"
                className={`form-input font-mono text-xs ${
                  singleJsonError ? "border-danger" : ""
                }`}
                rows={4}
                value={rawPayload}
                onChange={(e) => {
                  setRawPayload(e.target.value);
                  try {
                    JSON.parse(e.target.value);
                    setSingleJsonError(null);
                  } catch {
                    setSingleJsonError("Invalid JSON syntax");
                  }
                }}
                data-testid="evidence-payload-input"
              />
            </div>

            {/* Footer */}
            <div className="modal-footer flex justify-end gap-2 pt-3 border-t">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={onClose}
                disabled={submitting}
                data-testid="cancel-evidence-btn"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={submitting || !summary.trim() || !!singleJsonError}
                data-testid="submit-evidence-btn"
              >
                {submitting ? "Ingesting Evidence..." : "Ingest Evidence"}
              </button>
            </div>
          </form>
        )}

        {/* Mode: Bulk Batch Form */}
        {mode === "bulk" && (
          <form onSubmit={handleBulkSubmit} className="modal-body space-y-4 pt-1">
            <div className="flex justify-between items-center">
              <div className="text-xs text-muted">
                Paste JSON array of evidence objects (max 100 items per batch).
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-xs"
                onClick={() => handleBulkJsonChange(getSampleBatchJson())}
                data-testid="load-sample-batch-btn"
              >
                Load Sample Batch
              </button>
            </div>

            <div className="form-group">
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-semibold text-secondary">
                  Batch Items:{" "}
                  <strong className={parsedBulkCount > 0 && !bulkJsonError ? "text-success" : "text-muted"}>
                    {parsedBulkCount} item{parsedBulkCount === 1 ? "" : "s"}
                  </strong>
                </span>
                {bulkJsonError && (
                  <span className="text-xs text-danger flex items-center gap-1">
                    <AlertCircle size={12} /> {bulkJsonError}
                  </span>
                )}
              </div>
              <textarea
                className={`form-input font-mono text-xs ${bulkJsonError ? "border-danger" : ""}`}
                rows={10}
                value={bulkJson}
                onChange={(e) => handleBulkJsonChange(e.target.value)}
                placeholder="[ { 'source_type': 'alert', 'event_type': 'alert.fired', ... } ]"
                data-testid="bulk-json-input"
              />
            </div>

            {/* Batch Response Outcome Breakdown */}
            {batchResponse && (
              <div className="batch-outcome-panel p-3 border rounded bg-surface" data-testid="batch-outcome-summary">
                <div className="flex justify-between items-center mb-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider">
                    Batch Ingestion Summary
                  </h4>
                  {(batchResponse.rejected_count > 0 || batchResponse.failed_count > 0) && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-xs flex items-center gap-1"
                      onClick={handleRetryFailedItems}
                      data-testid="retry-failed-batch-btn"
                    >
                      <RotateCcw size={12} />
                      Retry Failed Items ({batchResponse.rejected_count + batchResponse.failed_count})
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-4 gap-2 mb-3 text-center">
                  <div className="p-2 rounded bg-secondary">
                    <div className="text-lg font-bold">{batchResponse.total_submitted}</div>
                    <div className="text-xs text-muted">Submitted</div>
                  </div>
                  <div className="p-2 rounded bg-success-subtle">
                    <div className="text-lg font-bold text-success">{batchResponse.accepted_count}</div>
                    <div className="text-xs text-success">Accepted</div>
                  </div>
                  <div className="p-2 rounded bg-warning-subtle">
                    <div className="text-lg font-bold text-warning">{batchResponse.duplicate_count}</div>
                    <div className="text-xs text-warning">Duplicates</div>
                  </div>
                  <div className="p-2 rounded bg-danger-subtle">
                    <div className="text-lg font-bold text-danger">
                      {batchResponse.rejected_count + batchResponse.failed_count}
                    </div>
                    <div className="text-xs text-danger">Issues</div>
                  </div>
                </div>

                {/* Per-item list */}
                <div className="max-h-36 overflow-y-auto border rounded text-xs">
                  {batchResponse.results.map((res) => (
                    <div
                      key={res.index}
                      className="flex justify-between items-center p-2 border-b last:border-0"
                      data-testid={`batch-item-result-${res.index}`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-muted">#{res.index + 1}</span>
                        <span
                          className={`badge ${
                            res.status === "accepted"
                              ? "badge-success"
                              : res.status === "duplicate"
                              ? "badge-warning"
                              : "badge-danger"
                          }`}
                        >
                          {res.status.toUpperCase()}
                        </span>
                        <span className="truncate max-w-xs">{res.summary || res.event_type}</span>
                      </div>
                      {res.error_message && (
                        <span className="text-danger truncate max-w-xs" title={res.error_message}>
                          {res.error_message}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Footer */}
            <div className="modal-footer flex justify-end gap-2 pt-3 border-t">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={onClose}
                disabled={submitting}
                data-testid="cancel-bulk-btn"
              >
                Close
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm flex items-center gap-1"
                disabled={submitting || parsedBulkCount === 0 || !!bulkJsonError}
                data-testid="submit-bulk-btn"
              >
                <Check size={14} />
                {submitting
                  ? "Ingesting Batch..."
                  : `Ingest Batch (${parsedBulkCount} item${parsedBulkCount === 1 ? "" : "s"})`}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
