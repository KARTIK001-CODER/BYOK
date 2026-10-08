import { useCallback, useEffect, useRef, useState } from "react";
import { InvestigationsApi } from "../api/investigations";
import {
  InvestigationJob,
  InvestigationStatus,
  InvestigationStreamEventPayload,
  UseInvestigationStreamOptions,
  UseInvestigationStreamResult,
} from "../types/investigation";

const DEFAULT_MAX_RECONNECT = 5;
const DEFAULT_BASE_DELAY_MS = 1000;
const DEFAULT_POLL_INTERVAL_MS = 3000;

export function useInvestigationStream(
  jobId: string | null,
  options: UseInvestigationStreamOptions = {}
): UseInvestigationStreamResult {
  const {
    autoConnect = true,
    maxReconnectAttempts = DEFAULT_MAX_RECONNECT,
    reconnectBaseDelayMs = DEFAULT_BASE_DELAY_MS,
    pollingFallbackIntervalMs = DEFAULT_POLL_INTERVAL_MS,
    onEvent,
    onTerminal,
    onError,
  } = options;

  const [status, setStatus] = useState<InvestigationStatus | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [resultSummary, setResultSummary] = useState<Record<string, unknown> | null>(null);
  const [errorSummary, setErrorSummary] = useState<string | null>(null);
  const [errorCategory, setErrorCategory] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean>(false);
  const [isTerminal, setIsTerminal] = useState<boolean>(false);
  const [isPollingFallback, setIsPollingFallback] = useState<boolean>(false);
  const [reconnectAttempts, setReconnectAttempts] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  // Mutable refs to prevent stale closure issues in timers/callbacks
  const abortControllerRef = useRef<AbortController | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const isTerminalRef = useRef<boolean>(false);
  const attemptsRef = useRef<number>(0);

  // Sync ref with state
  useEffect(() => {
    isTerminalRef.current = isTerminal;
  }, [isTerminal]);

  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const stopActiveStream = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  const applyPayload = useCallback(
    (payload: InvestigationStreamEventPayload) => {
      setStatus(payload.status);
      setStage(payload.stage);
      setProgress(payload.progress ?? 0);
      if (payload.result_summary) {
        setResultSummary(payload.result_summary);
      }
      if (payload.error_summary) {
        setErrorSummary(payload.error_summary);
      }
      if (payload.error_category) {
        setErrorCategory(payload.error_category);
      }

      const terminal =
        payload.status === "completed" ||
        payload.status === "failed" ||
        payload.status === "cancelled";

      if (terminal) {
        setIsTerminal(true);
        isTerminalRef.current = true;
        setConnected(false);
        clearTimers();
        onTerminal?.(payload);
      }
    },
    [clearTimers, onTerminal]
  );

  const applyJobState = useCallback(
    (job: InvestigationJob) => {
      setStatus(job.status);
      setStage(typeof job.stage === "string" ? job.stage : String(job.stage));
      setProgress(job.progress ?? 0);
      if (job.result_summary) {
        setResultSummary(job.result_summary);
      }
      if (job.error_summary) {
        setErrorSummary(job.error_summary);
      }
      if (job.error_category) {
        setErrorCategory(job.error_category);
      }

      const terminal =
        job.status === "completed" ||
        job.status === "failed" ||
        job.status === "cancelled";

      if (terminal) {
        setIsTerminal(true);
        isTerminalRef.current = true;
        setConnected(false);
        clearTimers();
      }
    },
    [clearTimers]
  );

  /**
   * Manual refresh to fetch the authoritative database state.
   */
  const refresh = useCallback(async (): Promise<InvestigationJob | null> => {
    if (!jobId) return null;
    try {
      const job = await InvestigationsApi.get(jobId);
      applyJobState(job);
      return job;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to refresh investigation.";
      setError(msg);
      return null;
    }
  }, [jobId, applyJobState]);

  /**
   * Cancel the current investigation job.
   */
  const cancel = useCallback(async (): Promise<void> => {
    if (!jobId) return;
    try {
      const updated = await InvestigationsApi.cancel(jobId);
      applyJobState(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to cancel investigation.";
      setError(msg);
    }
  }, [jobId, applyJobState]);

  /**
   * Start fallback polling when SSE reconnect limit is exhausted.
   */
  const startPollingFallback = useCallback(() => {
    clearTimers();
    setIsPollingFallback(true);
    setConnected(false);

    const poll = async () => {
      if (!jobId || isTerminalRef.current) {
        clearTimers();
        return;
      }
      try {
        const job = await InvestigationsApi.get(jobId);
        applyJobState(job);
        if (
          job.status === "completed" ||
          job.status === "failed" ||
          job.status === "cancelled"
        ) {
          clearTimers();
        }
      } catch (err) {
        // Polling retry continues silently on temporary hiccups
      }
    };

    // Immediate initial poll, then set interval
    poll();
    pollTimerRef.current = window.setInterval(poll, pollingFallbackIntervalMs);
  }, [jobId, clearTimers, pollingFallbackIntervalMs, applyJobState]);

  /**
   * Establish SSE connection with backoff and recovery.
   */
  const connect = useCallback(() => {
    if (!jobId || isTerminalRef.current) return;

    stopActiveStream();
    clearTimers();

    const controller = new AbortController();
    abortControllerRef.current = controller;

    InvestigationsApi.stream(
      jobId,
      {
        onEvent: (evtType, payload) => {
          onEvent?.(evtType, payload);
        },
        onConnected: (payload) => {
          setConnected(true);
          setError(null);
          // Connection successful: reset reconnect attempts
          attemptsRef.current = 0;
          setReconnectAttempts(0);
          applyPayload(payload);
        },
        onSnapshot: (payload) => {
          applyPayload(payload);
        },
        onProgress: (payload) => {
          applyPayload(payload);
        },
        onCompleted: (payload) => {
          applyPayload(payload);
        },
        onFailed: (payload) => {
          applyPayload(payload);
        },
        onCancelled: (payload) => {
          applyPayload(payload);
        },
        onError: (apiErr) => {
          // If already terminal, ignore stream closure errors
          if (isTerminalRef.current) return;

          setConnected(false);
          const errMessage = apiErr.message || "Investigation stream disconnected.";
          setError(errMessage);
          onError?.(new Error(errMessage));

          // Attempt bounded reconnect
          if (attemptsRef.current < maxReconnectAttempts) {
            attemptsRef.current += 1;
            setReconnectAttempts(attemptsRef.current);
            const delay = Math.min(
              reconnectBaseDelayMs * Math.pow(1.5, attemptsRef.current - 1),
              10000
            );
            reconnectTimerRef.current = window.setTimeout(() => {
              connect();
            }, delay);
          } else {
            // Reconnect limit reached, transition to REST polling fallback
            startPollingFallback();
          }
        },
        onComplete: () => {
          setConnected(false);
          // If the stream completed normally without terminal event, poll once to sync final state
          if (!isTerminalRef.current && jobId) {
            refresh();
          }
        },
      },
      { signal: controller.signal }
    );
  }, [
    jobId,
    stopActiveStream,
    clearTimers,
    onEvent,
    applyPayload,
    onError,
    maxReconnectAttempts,
    reconnectBaseDelayMs,
    startPollingFallback,
    refresh,
  ]);

  // Manage connection lifecycle on jobId change
  useEffect(() => {
    // Reset state for new jobId
    setStatus(null);
    setStage(null);
    setProgress(0);
    setResultSummary(null);
    setErrorSummary(null);
    setErrorCategory(null);
    setConnected(false);
    setIsTerminal(false);
    setIsPollingFallback(false);
    setReconnectAttempts(0);
    setError(null);
    isTerminalRef.current = false;
    attemptsRef.current = 0;

    clearTimers();
    stopActiveStream();

    if (jobId && autoConnect) {
      connect();
    }

    return () => {
      clearTimers();
      stopActiveStream();
    };
  }, [jobId, autoConnect, connect, clearTimers, stopActiveStream]);

  return {
    jobId,
    status,
    stage,
    progress,
    resultSummary,
    errorSummary,
    errorCategory,
    connected,
    isTerminal,
    isPollingFallback,
    reconnectAttempts,
    error,
    refresh,
    cancel,
  };
}
