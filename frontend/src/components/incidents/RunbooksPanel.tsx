import React, { useState, useEffect, useCallback } from "react";
import {
  BookOpen,
  Search,
  RefreshCw,
  Sliders,
  ExternalLink,
  AlertTriangle,
  Info,
  Layers,
  ChevronRight,
} from "lucide-react";
import { Incident } from "../../types/incident";
import { RetrievalApi, RetrievalResult, SearchMode } from "../../api/retrieval";

interface RunbooksPanelProps {
  incident: Incident;
  onOpenDocument?: (documentId: string) => void;
}

export const RunbooksPanel: React.FC<RunbooksPanelProps> = ({
  incident,
  onOpenDocument,
}) => {
  // Synthesize initial contextual query from incident metadata
  const defaultQuery = incident.service_name
    ? `${incident.service_name} ${incident.title}`
    : incident.title;

  const [query, setQuery] = useState<string>(defaultQuery);
  const [searchMode, setSearchMode] = useState<SearchMode>("hybrid");
  const [topK, setTopK] = useState<number>(10);
  const [results, setResults] = useState<RetrievalResult[]>([]);
  const [totalResults, setTotalResults] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState<boolean>(false);

  const executeSearch = useCallback(
    async (searchQuery: string, mode: SearchMode, limit: number) => {
      const trimmed = searchQuery.trim();
      if (!trimmed) {
        setError("Please enter a search query to discover relevant runbooks.");
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const resp = await RetrievalApi.search({
          query: trimmed,
          search_mode: mode,
          top_k: limit,
          candidate_k: Math.max(limit * 3, 30),
        });
        setResults(resp.results || []);
        setTotalResults(resp.total_results || 0);
        setHasSearched(true);
      } catch (err: unknown) {
        const msg =
          err instanceof Error
            ? err.message
            : "Failed to retrieve contextual runbooks.";
        setError(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    // Initial contextual discovery on mount or when incident changes
    executeSearch(defaultQuery, searchMode, topK);
  }, [defaultQuery, executeSearch, searchMode, topK]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    executeSearch(query, searchMode, topK);
  };

  const handleResetQuery = () => {
    setQuery(defaultQuery);
    executeSearch(defaultQuery, searchMode, topK);
  };

  return (
    <div className="runbooks-panel" data-testid="runbooks-panel">
      {/* Header and Advisory Notice */}
      <div className="runbooks-header">
        <div>
          <h3 className="tab-section-title">
            <BookOpen size={18} className="tab-section-icon" />
            Operational Runbooks & Context
          </h3>
          <p className="tab-section-subtitle">
            Discovered from incident service (
            <code>{incident.service_name || "all services"}</code>) and symptoms
            via hybrid vector and keyword retrieval.
          </p>
        </div>

        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => executeSearch(query, searchMode, topK)}
          disabled={loading}
          data-testid="refresh-runbooks-btn"
        >
          <RefreshCw size={14} className={loading ? "spin" : ""} />
          Refresh Search
        </button>
      </div>

      {/* Advisory Banner */}
      <div className="runbooks-advisory-banner" data-testid="runbooks-advisory">
        <Info size={16} className="text-info shrink-0" />
        <div className="text-xs">
          <strong>Advisory Context Only:</strong> Retrieved runbooks and
          operational documents provide guidance and standard operating
          procedures. They represent reference documentation, not verified
          proof of incident root cause.
        </div>
      </div>

      {/* Search Bar & Filter Controls */}
      <form onSubmit={handleSubmit} className="runbooks-search-bar" data-testid="runbooks-search-form">
        <div className="runbooks-input-wrapper">
          <Search size={16} className="runbooks-search-icon" />
          <input
            type="text"
            className="runbooks-search-input"
            placeholder="Search runbooks, postmortems, or architecture docs..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            data-testid="runbooks-query-input"
          />
          {query !== defaultQuery && (
            <button
              type="button"
              className="runbooks-reset-btn"
              onClick={handleResetQuery}
              title="Reset to incident context query"
            >
              Reset Context
            </button>
          )}
        </div>

        <div className="runbooks-controls">
          <div className="runbooks-control-item">
            <label htmlFor="search-mode-select" className="runbooks-control-label">
              <Sliders size={12} /> Mode:
            </label>
            <select
              id="search-mode-select"
              className="runbooks-select"
              value={searchMode}
              onChange={(e) => {
                const newMode = e.target.value as SearchMode;
                setSearchMode(newMode);
                executeSearch(query, newMode, topK);
              }}
              data-testid="runbooks-mode-select"
            >
              <option value="hybrid">Hybrid (RRF Dense+FTS)</option>
              <option value="vector">Dense Vector (Cosine)</option>
              <option value="keyword">Keyword (PostgreSQL FTS)</option>
            </select>
          </div>

          <div className="runbooks-control-item">
            <label htmlFor="top-k-select" className="runbooks-control-label">Limit:</label>
            <select
              id="top-k-select"
              className="runbooks-select"
              value={topK}
              onChange={(e) => {
                const newLimit = parseInt(e.target.value, 10);
                setTopK(newLimit);
                executeSearch(query, searchMode, newLimit);
              }}
              data-testid="runbooks-limit-select"
            >
              <option value={5}>Top 5</option>
              <option value={10}>Top 10</option>
              <option value={20}>Top 20</option>
            </select>
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-sm"
            disabled={loading || !query.trim()}
            data-testid="runbooks-search-submit-btn"
          >
            {loading ? "Searching..." : "Search"}
          </button>
        </div>
      </form>

      {/* Error state */}
      {error && (
        <div className="incident-error-banner" data-testid="runbooks-error">
          <AlertTriangle size={16} />
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => executeSearch(query, searchMode, topK)}
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="runbooks-loading" data-testid="runbooks-loading">
          <RefreshCw size={24} className="spin" />
          <p>Scanning indexed operational runbooks via {searchMode} retrieval...</p>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && hasSearched && results.length === 0 && (
        <div className="empty-state-box" data-testid="runbooks-empty">
          <BookOpen size={40} className="empty-state-icon" />
          <h4>No Relevant Runbooks Found</h4>
          <p>
            No indexed operational documents matched the query{" "}
            <code>&quot;{query}&quot;</code>.
          </p>
          <div className="runbooks-empty-hint">
            Ensure runbooks are uploaded and embedded in the Knowledge Base, or
            broaden your search terms.
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleResetQuery}
          >
            Reset to Incident Context
          </button>
        </div>
      )}

      {/* Results List */}
      {!loading && !error && results.length > 0 && (
        <div className="runbooks-results-container" data-testid="runbooks-results">
          <div className="runbooks-results-summary">
            <span>
              Found <strong>{totalResults}</strong> candidate sections for incident context
            </span>
            <span className="badge badge-info">Search Mode: {searchMode}</span>
          </div>

          <div className="runbooks-cards-list">
            {results.map((result) => (
              <div
                key={result.chunk_id}
                className="runbook-card"
                data-testid={`runbook-card-${result.chunk_id}`}
              >
                <div className="runbook-card-header">
                  <div className="runbook-title-group">
                    <span className="runbook-rank-badge">#{result.rank}</span>
                    <h4 className="runbook-doc-title">
                      {result.document_name || "Operational Runbook"}
                    </h4>
                    {result.section_title && (
                      <span className="runbook-section-tag">
                        <ChevronRight size={12} />
                        {result.section_title}
                      </span>
                    )}
                  </div>

                  <div className="runbook-meta-badges">
                    <span
                      className={`badge ${
                        result.score >= 0.7
                          ? "badge-success"
                          : result.score >= 0.4
                          ? "badge-info"
                          : "badge-neutral"
                      }`}
                      title={`Relevance score from ${result.source} ranking`}
                    >
                      Relevance: {(result.score * 100).toFixed(1)}%
                    </span>
                    <span className="badge badge-neutral">
                      {result.source.toUpperCase()}
                    </span>
                  </div>
                </div>

                <div className="runbook-card-body">
                  <div className="runbook-excerpt">
                    {result.content}
                  </div>
                </div>

                <div className="runbook-card-footer">
                  <div className="runbook-provenance">
                    <span className="provenance-item">
                      <Layers size={11} /> Chunk {result.provenance?.chunk_index ?? 0}
                    </span>
                    <span className="provenance-item">
                      Doc ID: <code>{result.document_id.slice(0, 8)}...</code>
                    </span>
                    {result.page_number && (
                      <span className="provenance-item">
                        Page {result.page_number}
                      </span>
                    )}
                  </div>

                  {onOpenDocument && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-xs"
                      onClick={() => onOpenDocument(result.document_id)}
                      data-testid={`view-doc-btn-${result.document_id}`}
                    >
                      <ExternalLink size={12} />
                      View Document
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
