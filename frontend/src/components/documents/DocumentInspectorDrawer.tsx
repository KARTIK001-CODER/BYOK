import React, { useState, useEffect, useCallback } from "react";
import {
  X,
  FileText,
  Layers,
  Cpu,
  Copy,
  Check,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
  Trash2,
  CheckCircle2,
  XCircle,
  FileCode,
} from "lucide-react";
import { DocumentResponse, DocumentChunkResponse, DocumentsApi } from "../../api/documents";

interface Props {
  isOpen: boolean;
  document: DocumentResponse | null;
  userRole?: string | null;
  onClose: () => void;
  onProcess: (docId: string, actionType?: "full" | "embed") => Promise<void>;
  onDelete: (docId: string) => Promise<boolean | void>;
}

const statusColor = (status: string) => {
  switch (status?.toLowerCase()) {
    case "ready":
    case "completed":
      return "#10b981"; // emerald
    case "processing":
    case "uploading":
      return "#f59e0b"; // amber
    case "failed":
      return "#ef4444"; // red
    case "uploaded":
    case "pending":
      return "#6366f1"; // indigo
    default:
      return "#94a3b8"; // slate
  }
};

const formatStatus = (s?: string | null) => {
  if (!s) return "Not Started";
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase().replace("_", " ");
};

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes <= 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

const formatDate = (isoStr?: string | null): string => {
  if (!isoStr) return "N/A";
  try {
    return new Date(isoStr).toLocaleString();
  } catch {
    return isoStr;
  }
};

export const DocumentInspectorDrawer: React.FC<Props> = ({
  isOpen,
  document: doc,
  userRole,
  onClose,
  onProcess,
  onDelete,
}) => {
  const [activeTab, setActiveTab] = useState<"metadata" | "chunks">("metadata");
  const [copiedChecksum, setCopiedChecksum] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Chunk browser state
  const [chunks, setChunks] = useState<DocumentChunkResponse[]>([]);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [chunkLoading, setChunkLoading] = useState(false);
  const [chunkError, setChunkError] = useState<string | null>(null);
  const [chunkPage, setChunkPage] = useState(0);
  const CHUNK_PAGE_SIZE = 10;

  // Processing state
  const [isProcessing, setIsProcessing] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  // Load chunks when switching to chunks tab or changing page or switching document
  const loadChunks = useCallback(async (docId: string, page: number) => {
    setChunkLoading(true);
    setChunkError(null);
    try {
      const res = await DocumentsApi.getChunks(docId, CHUNK_PAGE_SIZE, page * CHUNK_PAGE_SIZE);
      setChunks(res.items || []);
      setChunkTotal(res.total || 0);
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setChunkError(apiErr.message || "Failed to load document chunks");
    } finally {
      setChunkLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen && doc && activeTab === "chunks") {
      void loadChunks(doc.id, chunkPage);
    }
  }, [isOpen, doc?.id, doc?.status, doc?.chunk_count, activeTab, chunkPage, loadChunks]);

  // Reset page and feedback when doc changes
  useEffect(() => {
    setChunkPage(0);
    setChunks([]);
    setChunkTotal(0);
    setActionFeedback(null);
  }, [doc?.id]);

  if (!isOpen || !doc) return null;

  const isDocProcessing = (() => {
    const s = doc.status?.toLowerCase();
    const es = doc.embedding_status?.toLowerCase();
    if (s === "failed" || s === "archived") return false;
    if (s === "ready" && es === "failed") return false;
    return s === "processing" || s === "uploading" || es === "processing" || es === "pending";
  })();

  const canViewStorageKey = (userRole === "OWNER" || userRole === "ADMIN") && !!doc.storage_key;

  const handleCopyChecksum = () => {
    if (!doc.checksum) return;
    void navigator.clipboard.writeText(doc.checksum);
    setCopiedChecksum(true);
    setTimeout(() => setCopiedChecksum(false), 2000);
  };

  const handleTriggerProcess = async (actionType: "full" | "embed" = "full") => {
    setIsProcessing(true);
    setActionFeedback(null);
    try {
      await onProcess(doc.id, actionType);
      setActionFeedback({
        type: "success",
        message:
          actionType === "embed"
            ? "Embeddings generated successfully."
            : "Document processed and indexed successfully.",
      });
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setActionFeedback({
        type: "error",
        message: apiErr.message || "Processing failed.",
      });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleTriggerDelete = async () => {
    if (!confirm(`Are you sure you want to delete "${doc.name}"?`)) return;
    setIsDeleting(true);
    setActionFeedback(null);
    try {
      const success = await onDelete(doc.id);
      if (success !== false) {
        onClose();
      } else {
        setActionFeedback({
          type: "error",
          message: "Failed to delete document. Ensure you have Admin or Owner permissions.",
        });
      }
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setActionFeedback({
        type: "error",
        message: apiErr.message || "Failed to delete document.",
      });
    } finally {
      setIsDeleting(false);
    }
  };

  const totalPages = Math.ceil(chunkTotal / CHUNK_PAGE_SIZE) || 1;

  return (
    <aside
      className="source-drawer"
      style={{
        width: "480px",
        minWidth: "480px",
        backgroundColor: "var(--bg-surface)",
        boxShadow: "var(--shadow-lg)",
      }}
    >
      {/* Header */}
      <div className="drawer-header" style={{ padding: "16px 20px" }}>
        <div className="drawer-title" style={{ gap: "10px", minWidth: 0 }}>
          <FileText size={18} className="text-accent" style={{ flexShrink: 0 }} />
          <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
            <span
              style={{
                fontSize: "0.95rem",
                fontWeight: 700,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: "340px",
              }}
              title={doc.original_filename || doc.name}
            >
              {doc.original_filename || doc.name}
            </span>
            <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
              Document ID: {doc.id.substring(0, 8)}...
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: "4px" }}
        >
          <X size={18} />
        </button>
      </div>

      {/* Navigation Tabs */}
      <div
        style={{
          display: "flex",
          borderBottom: "1px solid var(--border-subtle)",
          padding: "0 16px",
          background: "var(--bg-secondary)",
        }}
      >
        <button
          type="button"
          onClick={() => setActiveTab("metadata")}
          style={{
            padding: "10px 16px",
            background: "transparent",
            border: "none",
            borderBottom: activeTab === "metadata" ? "2px solid var(--accent-primary)" : "2px solid transparent",
            color: activeTab === "metadata" ? "var(--accent-primary)" : "var(--text-secondary)",
            fontWeight: activeTab === "metadata" ? 600 : 500,
            fontSize: "0.85rem",
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <FileCode size={14} /> Metadata
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("chunks")}
          style={{
            padding: "10px 16px",
            background: "transparent",
            border: "none",
            borderBottom: activeTab === "chunks" ? "2px solid var(--accent-primary)" : "2px solid transparent",
            color: activeTab === "chunks" ? "var(--accent-primary)" : "var(--text-secondary)",
            fontWeight: activeTab === "chunks" ? 600 : 500,
            fontSize: "0.85rem",
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <Layers size={14} /> Chunks
          <span
            style={{
              padding: "1px 6px",
              borderRadius: "999px",
              background: "var(--bg-tertiary)",
              fontSize: "0.7rem",
              fontWeight: 600,
            }}
          >
            {doc.chunk_count ?? chunkTotal}
          </span>
        </button>
      </div>

      {/* Body Content */}
      <div className="drawer-body" style={{ padding: "18px 20px" }}>
        {/* Action Feedback Banner */}
        {actionFeedback && (
          <div
            style={{
              padding: "10px 14px",
              backgroundColor: actionFeedback.type === "success" ? "rgba(16, 185, 129, 0.12)" : "var(--danger-bg)",
              border: `1px solid ${actionFeedback.type === "success" ? "var(--accent-emerald)" : "var(--danger-border)"}`,
              borderRadius: "var(--radius-md)",
              color: actionFeedback.type === "success" ? "var(--accent-emerald)" : "var(--danger-text)",
              fontSize: "0.8rem",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "8px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              {actionFeedback.type === "success" ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              <span>{actionFeedback.message}</span>
            </div>
            <button
              type="button"
              onClick={() => setActionFeedback(null)}
              style={{ background: "transparent", border: "none", color: "inherit", cursor: "pointer", padding: "2px" }}
            >
              <X size={14} />
            </button>
          </div>
        )}

        {/* Live Processing Indicator Banner */}
        {isDocProcessing && (
          <div
            style={{
              padding: "10px 14px",
              backgroundColor: "rgba(245, 158, 11, 0.12)",
              border: "1px solid rgba(245, 158, 11, 0.4)",
              borderRadius: "var(--radius-md)",
              color: "#f59e0b",
              fontSize: "0.8rem",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <Loader2 size={16} className="spin" />
            <span>Document is actively processing in background...</span>
          </div>
        )}

        {/* Error Banner if document failed */}
        {doc.error_message && (
          <div
            style={{
              padding: "10px 14px",
              backgroundColor: "var(--danger-bg)",
              border: "1px solid var(--danger-border)",
              borderRadius: "var(--radius-md)",
              color: "var(--danger-text)",
              fontSize: "0.8rem",
              display: "flex",
              alignItems: "flex-start",
              gap: "8px",
            }}
          >
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: "2px" }} />
            <div>
              <div style={{ fontWeight: 600, marginBottom: "2px" }}>Processing Failure</div>
              <div>{doc.error_message}</div>
            </div>
          </div>
        )}

        {activeTab === "metadata" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {/* Status Section */}
            <div
              style={{
                background: "var(--bg-secondary)",
                borderRadius: "var(--radius-md)",
                padding: "12px 14px",
                border: "1px solid var(--border-subtle)",
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "12px",
              }}
            >
              <div>
                <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginBottom: "4px" }}>Ingestion Status</div>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "5px",
                    padding: "3px 8px",
                    borderRadius: "999px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    background: `${statusColor(doc.status)}18`,
                    color: statusColor(doc.status),
                    border: `1px solid ${statusColor(doc.status)}40`,
                  }}
                >
                  {doc.status?.toLowerCase() === "ready" ? (
                    <CheckCircle2 size={12} />
                  ) : doc.status?.toLowerCase() === "failed" ? (
                    <XCircle size={12} />
                  ) : (
                    <Loader2 size={12} className={doc.status?.toLowerCase() === "processing" ? "spin" : ""} />
                  )}
                  {formatStatus(doc.status)}
                </span>
              </div>

              <div>
                <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginBottom: "4px" }}>Vector Indexing</div>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "5px",
                    padding: "3px 8px",
                    borderRadius: "999px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    background: `${statusColor(doc.embedding_status || "pending")}18`,
                    color: statusColor(doc.embedding_status || "pending"),
                    border: `1px solid ${statusColor(doc.embedding_status || "pending")}40`,
                  }}
                >
                  <Cpu size={12} />
                  {formatStatus(doc.embedding_status)}
                </span>
              </div>
            </div>

            {/* Metadata Table List */}
            <div
              style={{
                background: "var(--bg-surface)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
                overflow: "hidden",
              }}
            >
              <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem", fontWeight: 700, color: "var(--text-secondary)" }}>
                File Properties
              </div>

              <div style={{ display: "flex", flexDirection: "column" }}>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>Display Name</span>
                  <span style={{ fontWeight: 500, maxWidth: "260px", overflow: "hidden", textOverflow: "ellipsis" }}>{doc.name}</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>Original Filename</span>
                  <span style={{ fontWeight: 500, maxWidth: "260px", overflow: "hidden", textOverflow: "ellipsis" }}>{doc.original_filename}</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>File Size</span>
                  <span style={{ fontWeight: 500 }}>{formatBytes(doc.file_size)} ({doc.file_size.toLocaleString()} bytes)</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>Content Type</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>{doc.content_type || "application/octet-stream"}</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>Current Version</span>
                  <span style={{ fontWeight: 600 }}>v{doc.current_version}</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>Chunks Generated</span>
                  <span style={{ fontWeight: 600, color: "var(--accent-primary)" }}>{doc.chunk_count ?? "0"}</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>SHA-256 Checksum</span>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <code style={{ fontSize: "0.72rem", background: "var(--bg-secondary)", padding: "2px 6px", borderRadius: "var(--radius-sm)" }}>
                      {doc.checksum ? `${doc.checksum.substring(0, 12)}...` : "N/A"}
                    </code>
                    <button
                      type="button"
                      onClick={handleCopyChecksum}
                      title="Copy full checksum"
                      style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: "2px" }}
                    >
                      {copiedChecksum ? <Check size={13} color="var(--success-text)" /> : <Copy size={13} />}
                    </button>
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>Uploaded At</span>
                  <span style={{ fontSize: "0.78rem" }}>{formatDate(doc.created_at)}</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>Last Updated</span>
                  <span style={{ fontSize: "0.78rem" }}>{formatDate(doc.updated_at)}</span>
                </div>

                {canViewStorageKey && (
                  <div style={{ padding: "10px 14px", fontSize: "0.75rem", background: "var(--bg-secondary)" }}>
                    <div style={{ color: "var(--text-muted)", marginBottom: "4px" }}>Storage Key (Admin / Debug):</div>
                    <code style={{ wordBreak: "break-all", fontSize: "0.72rem", color: "var(--text-secondary)" }}>
                      {doc.storage_key}
                    </code>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* Chunks Tab */
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {chunkLoading ? (
              <div style={{ padding: "30px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
                <Loader2 size={20} className="spin" style={{ marginBottom: "8px" }} />
                <div>Loading text chunks...</div>
              </div>
            ) : chunkError ? (
              <div style={{ padding: "12px", background: "var(--danger-bg)", color: "var(--danger-text)", borderRadius: "var(--radius-md)", fontSize: "0.8rem" }}>
                {chunkError}
              </div>
            ) : chunks.length === 0 ? (
              <div style={{ padding: "32px 16px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
                <Layers size={24} style={{ marginBottom: "8px", opacity: 0.5 }} />
                <div style={{ fontWeight: 600 }}>No chunks found</div>
                <div style={{ fontSize: "0.75rem", marginTop: "4px" }}>
                  This document has not been chunked yet. Click "Re-process & Embed" below.
                </div>
              </div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "0.78rem", color: "var(--text-muted)" }}>
                  <span>
                    Showing {chunkPage * CHUNK_PAGE_SIZE + 1} - {Math.min((chunkPage + 1) * CHUNK_PAGE_SIZE, chunkTotal)} of {chunkTotal} chunks
                  </span>
                  <div style={{ display: "flex", gap: "4px" }}>
                    <button
                      type="button"
                      disabled={chunkPage === 0}
                      onClick={() => setChunkPage((p) => Math.max(0, p - 1))}
                      style={{
                        padding: "3px 8px",
                        background: "var(--bg-secondary)",
                        border: "1px solid var(--border-subtle)",
                        borderRadius: "var(--radius-sm)",
                        cursor: chunkPage === 0 ? "not-allowed" : "pointer",
                        opacity: chunkPage === 0 ? 0.4 : 1,
                      }}
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <span style={{ padding: "3px 8px" }}>
                      {chunkPage + 1} / {totalPages}
                    </span>
                    <button
                      type="button"
                      disabled={chunkPage >= totalPages - 1}
                      onClick={() => setChunkPage((p) => p + 1)}
                      style={{
                        padding: "3px 8px",
                        background: "var(--bg-secondary)",
                        border: "1px solid var(--border-subtle)",
                        borderRadius: "var(--radius-sm)",
                        cursor: chunkPage >= totalPages - 1 ? "not-allowed" : "pointer",
                        opacity: chunkPage >= totalPages - 1 ? 0.4 : 1,
                      }}
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                </div>

                {chunks.map((chk) => (
                  <div
                    key={chk.id}
                    style={{
                      background: "var(--bg-surface)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                      padding: "12px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "8px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "6px" }}>
                      <span
                        style={{
                          fontWeight: 700,
                          fontSize: "0.75rem",
                          color: "var(--accent-primary)",
                          background: "var(--accent-glow)",
                          padding: "2px 8px",
                          borderRadius: "var(--radius-sm)",
                        }}
                      >
                        #{chk.chunk_index}
                      </span>

                      <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.72rem", color: "var(--text-muted)" }}>
                        {chk.page_number && <span>Page {chk.page_number}</span>}
                        {chk.section_title && <span>· {chk.section_title}</span>}
                        <span>· {chk.character_count} chars</span>
                        <span>· {chk.word_count} words</span>
                      </div>
                    </div>

                    <div
                      style={{
                        fontSize: "0.78rem",
                        fontFamily: "var(--font-mono)",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        maxHeight: "180px",
                        overflowY: "auto",
                        background: "var(--bg-secondary)",
                        padding: "8px 10px",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--border-subtle)",
                        lineHeight: 1.45,
                      }}
                    >
                      {chk.content}
                    </div>

                    {chk.embedding_model && (
                      <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: "6px" }}>
                        <Cpu size={11} color="var(--accent-emerald)" />
                        <span>Vector: {chk.embedding_model} ({chk.embedding_dimension || 384}d)</span>
                      </div>
                    )}
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Action Footer */}
      <div
        style={{
          padding: "14px 20px",
          borderTop: "1px solid var(--border-subtle)",
          background: "var(--bg-secondary)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "10px",
        }}
      >
        <button
          type="button"
          onClick={handleTriggerDelete}
          disabled={isDeleting}
          style={{
            padding: "8px 12px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--danger-border)",
            background: "var(--danger-bg)",
            color: "var(--danger-text)",
            fontSize: "0.8rem",
            fontWeight: 600,
            cursor: isDeleting ? "not-allowed" : "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <Trash2 size={14} /> {isDeleting ? "Deleting..." : "Delete"}
        </button>

        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <button
            type="button"
            onClick={onClose}
            style={{
              padding: "8px 14px",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-subtle)",
              background: "var(--bg-surface)",
              color: "var(--text-secondary)",
              fontSize: "0.8rem",
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Close
          </button>

          {doc.status?.toLowerCase() === "ready" ? (
            <>
              <button
                type="button"
                onClick={() => void handleTriggerProcess("embed")}
                disabled={isProcessing || isDeleting || isDocProcessing}
                style={{
                  padding: "8px 12px",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border-subtle)",
                  background: "var(--bg-surface)",
                  color: "var(--text-primary)",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  cursor: isProcessing || isDeleting || isDocProcessing ? "not-allowed" : "pointer",
                }}
                title="Recompute vector embeddings for existing chunks"
              >
                <Cpu size={14} /> Re-embed Chunks
              </button>
              <button
                type="button"
                onClick={() => void handleTriggerProcess("full")}
                disabled={isProcessing || isDeleting || isDocProcessing}
                className="btn-primary"
                style={{
                  padding: "8px 12px",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  cursor: isProcessing || isDeleting || isDocProcessing ? "not-allowed" : "pointer",
                }}
                title="Re-extract and re-chunk from storage, then embed"
              >
                <RefreshCw size={14} className={isProcessing ? "spin" : ""} />
                {isProcessing ? "Processing..." : "Re-process & Embed"}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => void handleTriggerProcess("full")}
              disabled={isProcessing || isDeleting || isDocProcessing}
              className="btn-primary"
              style={{
                padding: "8px 14px",
                fontSize: "0.8rem",
                fontWeight: 600,
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                cursor: isProcessing || isDeleting || isDocProcessing ? "not-allowed" : "pointer",
              }}
              title="Extract, chunk, and embed document"
            >
              <RefreshCw size={14} className={isProcessing ? "spin" : ""} />
              {isProcessing ? "Processing..." : "Process & Embed"}
            </button>
          )}
        </div>
      </div>
    </aside>
  );
};
