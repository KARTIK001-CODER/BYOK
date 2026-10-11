import React, { useState, useEffect, useCallback } from "react";
import {
  Sparkles,
  Play,
  RotateCcw,
  RefreshCw,
  XCircle,
  AlertCircle,
  CheckCircle,
  Radio,
  Wifi,
  WifiOff,
  Sliders,
} from "lucide-react";
import {
  HypothesisResponse,
  InvestigationJob,
} from "../../types/investigation";
import { InvestigationsApi } from "../../api/investigations";
import { useInvestigationStream } from "../../hooks/useInvestigationStream";
import { HypothesisCard } from "./HypothesisCard";

interface InvestigationPanelProps {
  incidentId: string;
  onInspectEvidence?: (evidenceId: string) => void;
  onNavigateRemediations?: () => void;
}

export const InvestigationPanel: React.FC<InvestigationPanelProps> = ({
  incidentId,
  onInspectEvidence,
  onNavigateRemediations,
}) => {
  const [jobs, setJobs] = useState<InvestigationJob[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [hypotheses, setHypotheses] = useState<HypothesisResponse[]>([]);
  const [isLoadingJobs, setIsLoadingJobs] = useState<boolean>(true);
  const [isLoadingHypotheses, setIsLoadingHypotheses] = useState<boolean>(false);
  const [panelError, setPanelError] = useState<string | null>(null);

  // Trigger Form state
  const [isTriggering, setIsTriggering] = useState<boolean>(false);
  const [resultLimit, setResultLimit] = useState<number>(20);
  const [triggerError, setTriggerError] = useState<string | null>(null);

  // 1. Fetch existing investigation jobs for this incident
  const fetchJobs = useCallback(async () => {
    setIsLoadingJobs(true);
    setPanelError(null);
    try {
      const res = await InvestigationsApi.listForIncident(incidentId);
      const items = res.items || [];
      setJobs(items);
      if (items.length > 0 && !selectedJobId) {
        setSelectedJobId(items[0].id);
      }
    } catch (err: unknown) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to load incident investigation jobs.";
      setPanelError(msg);
    } finally {
      setIsLoadingJobs(false);
    }
  }, [incidentId, selectedJobId]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // 2. Real-time SSE streaming for selected job
  const streamState = useInvestigationStream(selectedJobId, {
    autoConnect: true,
    onTerminal: () => {
      // Refresh hypotheses on completion
      if (selectedJobId) {
        loadHypotheses(selectedJobId);
      }
    },
  });

  // 3. Load hypotheses for selected job
  const loadHypotheses = useCallback(async (jobId: string) => {
    setIsLoadingHypotheses(true);
    try {
      const res = await InvestigationsApi.listHypotheses(jobId);
      setHypotheses(res.items || []);
    } catch {
      setHypotheses([]);
    } finally {
      setIsLoadingHypotheses(false);
    }
  }, []);

  useEffect(() => {
    if (selectedJobId) {
      loadHypotheses(selectedJobId);
    } else {
      setHypotheses([]);
    }
  }, [selectedJobId, loadHypotheses]);

  // Refresh hypotheses when job completes in stream
  useEffect(() => {
    if (streamState.status === "completed" && selectedJobId) {
      loadHypotheses(selectedJobId);
    }
  }, [streamState.status, selectedJobId, loadHypotheses]);

  // Trigger new investigation
  const handleStartInvestigation = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsTriggering(true);
    setTriggerError(null);

    const idempotencyKey = `inv-${incidentId}-${Date.now()}`;

    try {
      const job = await InvestigationsApi.trigger(incidentId, {
        idempotency_key: idempotencyKey,
        result_limit: resultLimit,
      });
      setJobs((prev) => [job, ...prev]);
      setSelectedJobId(job.id);
    } catch (err: unknown) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to trigger investigation job.";
      setTriggerError(msg);
    } finally {
      setIsTriggering(false);
    }
  };

  const handleCancel = async () => {
    if (!selectedJobId) return;
    try {
      await streamState.cancel();
      fetchJobs();
    } catch {
      // error surfaced in streamState
    }
  };

  const currentJob = jobs.find((j) => j.id === selectedJobId) || null;
  const activeStatus = streamState.status || currentJob?.status || "queued";
  const activeStage = streamState.stage || currentJob?.stage || "queued";
  const activeProgress = streamState.progress ?? currentJob?.progress ?? 0;
  const isJobActive = activeStatus === "queued" || activeStatus === "running";

  return (
    <div className="investigation-panel-container" data-testid="investigation-panel">
      {/* Top Header / Job Selector */}
      <div className="investigation-header-bar">
        <div className="investigation-title-group">
          <h3>
            <Sparkles size={18} color="var(--accent-primary)" />
            Root-Cause Investigation Engine
          </h3>
          <p className="investigation-subtitle">
            Correlates operational evidence, synthesizes candidate root-cause hypotheses, and assesses
            citation groundedness.
          </p>
        </div>

        <div className="investigation-actions">
          {jobs.length > 0 && (
            <select
              className="custom-select job-select"
              value={selectedJobId || ""}
              onChange={(e) => setSelectedJobId(e.target.value)}
              data-testid="investigation-job-selector"
            >
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  Job #{j.id.substring(0, 8)} ({j.status.toUpperCase()} · {new Date(j.created_at).toLocaleTimeString()})
                </option>
              ))}
            </select>
          )}

          <button
            className="btn-secondary-incident"
            onClick={() => {
              fetchJobs();
              if (selectedJobId) streamState.refresh();
            }}
            disabled={isLoadingJobs}
            title="Refresh Status"
            data-testid="refresh-investigation-btn"
          >
            <RefreshCw size={13} className={isLoadingJobs ? "spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {panelError && (
        <div className="investigation-error-banner" data-testid="investigation-error-banner">
          <AlertCircle size={15} />
          <span>{panelError}</span>
        </div>
      )}

      {/* Main Content: Trigger Wizard if no jobs; Progress & Hypotheses if jobs exist */}
      {isLoadingJobs && jobs.length === 0 ? (
        <div className="investigation-loading-state" data-testid="investigation-loading">
          <RefreshCw size={24} className="spin text-accent" />
          <span>Checking active incident investigation jobs...</span>
        </div>
      ) : jobs.length === 0 ? (
        /* Zero Jobs: Start Investigation Intake */
        <div className="investigation-trigger-card" data-testid="investigation-trigger-card">
          <div className="trigger-icon-circle">
            <Sparkles size={28} />
          </div>
          <h4>Start Automated Root-Cause Investigation</h4>
          <p>
            The investigation engine will retrieve relevant incident logs, metrics, alerts, and deployment
            events, reconstruct temporal dependencies, synthesize candidate root-cause hypotheses, and evaluate
            citation groundedness.
          </p>

          {triggerError && (
            <div className="trigger-error-banner" data-testid="trigger-error-banner">
              <AlertCircle size={15} />
              <span>{triggerError}</span>
            </div>
          )}

          <form onSubmit={handleStartInvestigation} className="trigger-form">
            <div className="form-group-inline">
              <label htmlFor="result-limit-input">
                <Sliders size={14} style={{ display: "inline", marginRight: "6px" }} />
                Evidence Assembly Budget (Limit)
              </label>
              <input
                id="result-limit-input"
                type="number"
                min={5}
                max={100}
                value={resultLimit}
                onChange={(e) => setResultLimit(Number(e.target.value))}
                className="form-input"
                style={{ width: "100px" }}
                disabled={isTriggering}
                data-testid="result-limit-input"
              />
            </div>

            <button
              type="submit"
              className="btn-primary-incident btn-trigger-large"
              disabled={isTriggering}
              data-testid="start-investigation-btn"
            >
              {isTriggering ? (
                <>
                  <RefreshCw size={16} className="spin" />
                  Triggering Job...
                </>
              ) : (
                <>
                  <Play size={16} />
                  Start Investigation
                </>
              )}
            </button>
          </form>
        </div>
      ) : (
        /* Active or Completed Job View */
        <div className="investigation-active-workspace">
          {/* Progress Tracker Card */}
          <div className="investigation-status-card" data-testid="investigation-status-card">
            <div className="status-card-header">
              <div className="status-badge-group">
                <span className={`status-badge status-${activeStatus}`} data-testid="investigation-status-badge">
                  {activeStatus.toUpperCase()}
                </span>
                <span className="stage-badge" data-testid="investigation-stage-badge">
                  Stage: {activeStage.replace(/_/g, " ")}
                </span>
              </div>

              {/* Streaming Connection Indicator */}
              <div className="stream-connection-badge">
                {streamState.isPollingFallback ? (
                  <span className="badge-stream-polling">
                    <Radio size={12} /> REST Polling Fallback
                  </span>
                ) : streamState.connected ? (
                  <span className="badge-stream-connected" data-testid="stream-connected-indicator">
                    <Wifi size={12} /> Live SSE Stream
                  </span>
                ) : isJobActive ? (
                  <span className="badge-stream-reconnecting">
                    <WifiOff size={12} /> Reconnecting ({streamState.reconnectAttempts})...
                  </span>
                ) : (
                  <span className="badge-stream-completed">
                    <CheckCircle size={12} /> Synced from DB
                  </span>
                )}
              </div>
            </div>

            {/* Progress Bar */}
            <div className="progress-bar-container">
              <div
                className="progress-bar-fill"
                style={{ width: `${Math.max(activeProgress, 5)}%` }}
                data-testid="investigation-progress-bar"
              />
            </div>

            <div className="progress-details-row">
              <span className="progress-text">{activeProgress}% Processed</span>
              {isJobActive && (
                <button
                  className="btn-cancel-job"
                  onClick={handleCancel}
                  data-testid="cancel-investigation-btn"
                >
                  <XCircle size={13} /> Cancel Investigation
                </button>
              )}
            </div>

            {/* Error Display if Failed */}
            {streamState.errorSummary && (
              <div className="job-error-callout" data-testid="job-error-callout">
                <AlertCircle size={15} />
                <span>
                  <strong>{streamState.errorCategory || "Investigation Error"}:</strong>{" "}
                  {streamState.errorSummary}
                </span>
              </div>
            )}
          </div>

          {/* Hypotheses Section */}
          <div className="hypotheses-section" data-testid="hypotheses-section">
            <div className="hypotheses-section-header">
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <Sparkles size={18} color="var(--accent-primary)" />
                <h4>Root-Cause Hypotheses ({hypotheses.length})</h4>
              </div>

              {/* Trigger Another Run option if terminal */}
              {!isJobActive && (
                <button
                  className="btn-secondary-incident"
                  onClick={handleStartInvestigation}
                  disabled={isTriggering}
                  data-testid="rerun-investigation-btn"
                >
                  <RotateCcw size={13} />
                  Re-run Investigation
                </button>
              )}
            </div>

            {isLoadingHypotheses ? (
              <div className="hypotheses-loading-state" data-testid="hypotheses-loading">
                <RefreshCw size={20} className="spin text-accent" />
                <span>Retrieving evidence-grounded hypotheses...</span>
              </div>
            ) : hypotheses.length === 0 ? (
              <div className="hypotheses-empty-state" data-testid="hypotheses-empty">
                {isJobActive ? (
                  <>
                    <RefreshCw size={24} className="spin text-accent" />
                    <h5>Synthesizing candidate hypotheses...</h5>
                    <p>Evidence retrieval and citation verification in progress.</p>
                  </>
                ) : (
                  <>
                    <AlertCircle size={28} color="var(--text-muted)" />
                    <h5>No Hypotheses Generated</h5>
                    <p>
                      The investigation job completed without producing candidate hypotheses for this incident.
                      Verify that evidence records have been ingested into the incident timeline.
                    </p>
                  </>
                )}
              </div>
            ) : (
              <div className="hypotheses-cards-list" data-testid="hypotheses-cards-list">
                {hypotheses.map((hyp) => (
                  <HypothesisCard
                    key={hyp.id}
                    hypothesis={hyp}
                    onInspectEvidence={onInspectEvidence}
                    onNavigateRemediations={onNavigateRemediations}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
