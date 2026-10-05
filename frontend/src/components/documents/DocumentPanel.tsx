import React, { useEffect, useState, useCallback } from "react";
import {
  Upload,
  FileText,
  Trash2,
  Cpu,
  Layers,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
  Clock,
  HardDrive,
} from "lucide-react";
import { DocumentsApi, DocumentResponse } from "../../api/documents";
import { KnowledgeBasesApi, KnowledgeBaseStats } from "../../api/knowledgeBases";
import {
  formatBytes,
  isDocumentProcessing,
  statusColor,
  statusLabel,
} from "../../utils/documents";
import { DocumentInspectorDrawer } from "./DocumentInspectorDrawer";

interface Props {
  kbId: string | null;
  kbName?: string | null;
  userRole?: string | null;
}

export const DocumentPanel: React.FC<Props> = ({ kbId, kbName, userRole }) => {
  const [docs, setDocs] = useState<DocumentResponse[]>([]);
  const [stats, setStats] = useState<KnowledgeBaseStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<DocumentResponse | null>(null);

  const load = useCallback(async () => {
    if (!kbId) {
      setDocs([]);
      setStats(null);
      setSelectedDoc(null);
      return;
    }
    setLoading(true);
    setStatsLoading(true);
    setStatsError(null);
    setError(null);
    try {
      const [{ items }, kbStats] = await Promise.all([
        DocumentsApi.list(kbId),
        KnowledgeBasesApi.getStats(kbId).catch((err) => {
          console.warn("Failed to load KB stats:", err);
          return null;
        }),
      ]);
      setDocs(items);
      if (kbStats) {
        setStats(kbStats);
      } else {
        setStatsError("Failed to load statistics");
      }
      setSelectedDoc((prev) => {
        if (!prev) return null;
        const matching = items.find((d) => d.id === prev.id);
        return matching || null;
      });
    } catch {
      setError("Failed to load documents");
    } finally {
      setLoading(false);
      setStatsLoading(false);
    }
  }, [kbId]);

  useEffect(() => {
    load();
  }, [load]);

  // Live polling: poll every 3 seconds only while at least one document is actively processing
  const hasActiveProcessing = docs.some(isDocumentProcessing);

  useEffect(() => {
    if (!kbId || !hasActiveProcessing) return;

    let isMounted = true;
    let inFlight = false;
    let timerId: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      if (!isMounted || inFlight) return;
      inFlight = true;
      try {
        const [{ items }, kbStats] = await Promise.all([
          DocumentsApi.list(kbId),
          KnowledgeBasesApi.getStats(kbId).catch(() => null),
        ]);
        if (!isMounted) return;
        setDocs(items);
        if (kbStats) setStats(kbStats);
        setSelectedDoc((prev) => {
          if (!prev) return null;
          const matching = items.find((d) => d.id === prev.id);
          return matching || prev;
        });
      } catch (err) {
        if (isMounted) {
          console.warn("Polling documents failed:", err);
        }
      } finally {
        inFlight = false;
        if (isMounted) {
          timerId = setTimeout(poll, 3000);
        }
      }
    };

    timerId = setTimeout(poll, 3000);

    return () => {
      isMounted = false;
      if (timerId) clearTimeout(timerId);
    };
  }, [kbId, hasActiveProcessing]);

  const handleUpload = async (files: FileList | null) => {
    if (!files || !kbId) return;
    setError(null);
    setUploading(true);
    for (const file of Array.from(files)) {
      try {
        const uploadRes = await DocumentsApi.upload(kbId, file);
        // Auto-trigger processing pipeline (ingest + embed).
        // Members can upload but only Admins can process — surface 403 clearly.
        try {
          await DocumentsApi.process(uploadRes.document.id);
        } catch (procErr) {
          const msg = (procErr as { message?: string; code?: string })?.message || "";
          const isForbidden =
            (procErr as { code?: string })?.code === "FORBIDDEN" ||
            /permission|admin|forbidden/i.test(msg);
          console.warn("Auto-process failed, document uploaded but needs manual processing", procErr);
          setError(
            isForbidden
              ? `Uploaded ${file.name}, but processing needs an Admin role. Ask a workspace admin to click “Re-process & Embed”.`
              : `Uploaded ${file.name}, but auto-processing failed: ${msg || "try Re-process manually."}`
          );
        }
      } catch (err: unknown) {
        const apiErr = err as { message?: string };
        setError(apiErr.message || `Failed to upload ${file.name}`);
      }
    }
    setUploading(false);
    await load();
  };

  const handleDelete = async (docId: string): Promise<boolean> => {
    try {
      await DocumentsApi.delete(docId);
      setDocs((prev) => prev.filter((d) => d.id !== docId));
      if (selectedDoc?.id === docId) {
        setSelectedDoc(null);
      }
      if (kbId) {
        void KnowledgeBasesApi.getStats(kbId).then(setStats).catch(() => {});
      }
      return true;
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      const msg = apiErr.message || "Delete failed";
      setError(msg);
      return false;
    }
  };

  const handleProcess = async (docId: string, actionType: "full" | "embed" = "full"): Promise<void> => {
    try {
      if (actionType === "embed") {
        await DocumentsApi.embed(docId);
      } else {
        await DocumentsApi.process(docId);
      }
      await load();
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      const msg = apiErr.message || "Processing failed";
      setError(msg);
      throw err;
    }
  };

  if (!kbId) {
    return (
      <div style={{ padding: "32px 24px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
        Select a knowledge base to manage documents. Create one via “Manage Knowledge Bases”.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "row", height: "100%", overflow: "hidden" }}>
      {/* Main List Area */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          gap: "14px",
          padding: "16px 20px",
          overflowY: "auto",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700, fontSize: "0.95rem" }}>
            <FileText size={18} className="text-accent" />
            <span>{kbName || "Documents"}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {hasActiveProcessing && (
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  fontSize: "0.75rem",
                  color: "var(--warning-text)",
                  background: "var(--warning-bg)",
                  padding: "3px 10px",
                  borderRadius: "999px",
                  border: "1px solid var(--warning-border)",
                }}
              >
                <Loader2 size={12} className="spin" /> Processing active...
              </span>
            )}
            <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
              {docs.length} {docs.length === 1 ? "file" : "files"}
            </span>
          </div>
        </div>

        {/* Knowledge Base Statistics Overview */}
        {statsLoading && !stats ? (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
              gap: "10px",
            }}
          >
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div
                key={i}
                style={{
                  background: "var(--bg-secondary)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border-subtle)",
                  padding: "10px 14px",
                  height: "64px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Loader2 size={16} className="spin" style={{ color: "var(--text-muted)" }} />
              </div>
            ))}
          </div>
        ) : stats ? (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
              gap: "10px",
            }}
          >
            {/* Total Documents */}
            <div
              style={{
                background: "var(--bg-secondary)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
                padding: "10px 14px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", color: "var(--text-muted)", fontSize: "0.72rem" }}>
                <span>Documents</span>
                <FileText size={13} />
              </div>
              <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }}>
                {stats.total_documents}
              </div>
              <div style={{ fontSize: "0.68rem", color: "var(--text-muted)" }}>
                Active in library
              </div>
            </div>

            {/* Total Chunks */}
            <div
              style={{
                background: "var(--bg-secondary)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
                padding: "10px 14px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", color: "var(--text-muted)", fontSize: "0.72rem" }}>
                <span>Chunks</span>
                <Layers size={13} color="var(--accent-primary)" />
              </div>
              <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }}>
                {stats.total_chunks}
              </div>
              <div style={{ fontSize: "0.68rem", color: "var(--text-muted)" }}>
                Current versions
              </div>
            </div>

            {/* Storage Size */}
            <div
              style={{
                background: "var(--bg-secondary)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
                padding: "10px 14px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", color: "var(--text-muted)", fontSize: "0.72rem" }}>
                <span>Storage</span>
                <HardDrive size={13} />
              </div>
              <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }}>
                {formatBytes(stats.total_file_size_bytes)}
              </div>
              <div style={{ fontSize: "0.68rem", color: "var(--text-muted)" }}>
                Total raw size
              </div>
            </div>

            {/* Ready Documents */}
            <div
              style={{
                background: "var(--bg-secondary)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
                padding: "10px 14px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", color: "var(--accent-emerald)", fontSize: "0.72rem" }}>
                <span>Ready</span>
                <CheckCircle2 size={13} />
              </div>
              <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--accent-emerald)" }}>
                {stats.ready_documents}
              </div>
              <div style={{ fontSize: "0.68rem", color: "var(--text-muted)" }}>
                {stats.pending_embeddings > 0 ? `${stats.pending_embeddings} pending vector` : "Fully indexed"}
              </div>
            </div>

            {/* Processing Documents */}
            <div
              style={{
                background: stats.processing_documents > 0 ? "rgba(245, 158, 11, 0.08)" : "var(--bg-secondary)",
                borderRadius: "var(--radius-md)",
                border: stats.processing_documents > 0 ? "1px solid rgba(245, 158, 11, 0.3)" : "1px solid var(--border-subtle)",
                padding: "10px 14px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", color: stats.processing_documents > 0 ? "#f59e0b" : "var(--text-muted)", fontSize: "0.72rem" }}>
                <span>Processing</span>
                <Loader2 size={13} className={stats.processing_documents > 0 ? "spin" : ""} />
              </div>
              <div style={{ fontSize: "1.25rem", fontWeight: 700, color: stats.processing_documents > 0 ? "#f59e0b" : "var(--text-primary)" }}>
                {stats.processing_documents}
              </div>
              <div style={{ fontSize: "0.68rem", color: stats.processing_documents > 0 ? "#f59e0b" : "var(--text-muted)" }}>
                {stats.processing_documents > 0 ? "In pipeline" : "Idle"}
              </div>
            </div>

            {/* Failed Documents & Embeddings */}
            <div
              style={{
                background: stats.failed_documents + stats.failed_embeddings > 0 ? "var(--danger-bg)" : "var(--bg-secondary)",
                borderRadius: "var(--radius-md)",
                border: stats.failed_documents + stats.failed_embeddings > 0 ? "1px solid var(--danger-border)" : "1px solid var(--border-subtle)",
                padding: "10px 14px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", color: stats.failed_documents + stats.failed_embeddings > 0 ? "var(--danger-text)" : "var(--text-muted)", fontSize: "0.72rem" }}>
                <span>Failed</span>
                <AlertTriangle size={13} />
              </div>
              <div style={{ fontSize: "1.25rem", fontWeight: 700, color: stats.failed_documents + stats.failed_embeddings > 0 ? "var(--danger-text)" : "var(--text-primary)" }}>
                {stats.failed_documents + stats.failed_embeddings}
              </div>
              <div style={{ fontSize: "0.68rem", color: stats.failed_documents + stats.failed_embeddings > 0 ? "var(--danger-text)" : "var(--text-muted)" }}>
                {stats.failed_documents > 0
                  ? `${stats.failed_documents} ingest failed`
                  : stats.failed_embeddings > 0
                  ? `${stats.failed_embeddings} embed failed`
                  : "0 errors"}
              </div>
            </div>
          </div>
        ) : statsError ? (
          <div
            style={{
              padding: "8px 12px",
              background: "var(--bg-secondary)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-md)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontSize: "0.75rem",
              color: "var(--text-muted)",
            }}
          >
            <span>Could not load knowledge base metrics.</span>
            <button
              type="button"
              onClick={() => void load()}
              style={{ background: "transparent", border: "none", color: "var(--accent-primary)", cursor: "pointer", fontWeight: 600, fontSize: "0.75rem" }}
            >
              Retry
            </button>
          </div>
        ) : null}

        {error && (
          <div
            style={{
              padding: "10px 14px",
              background: "var(--danger-bg)",
              border: "1px solid var(--danger-border)",
              borderRadius: "var(--radius-md)",
              color: "var(--danger-text)",
              fontSize: "0.82rem",
            }}
          >
            {error}
          </div>
        )}

        {/* Dropzone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleUpload(e.dataTransfer.files);
          }}
          style={{
            border: `1px dashed ${dragOver ? "var(--accent-primary)" : "var(--border-strong)"}`,
            background: dragOver ? "rgba(59,130,246,0.08)" : "var(--bg-surface)",
            borderRadius: "var(--radius-md)",
            padding: "20px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "8px",
            cursor: "pointer",
            transition: "all 0.15s",
          }}
          onClick={() => document.getElementById("doc-file-input")?.click()}
        >
          <Upload size={22} color="var(--accent-primary)" />
          <span style={{ fontSize: "0.85rem", color: "var(--text-secondary)", fontWeight: 500 }}>
            {uploading ? "Uploading files..." : "Drag & drop files or click to browse"}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>PDF, DOCX, TXT, MD · Max 25MB</span>
          <input
            id="doc-file-input"
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md"
            style={{ display: "none" }}
            onChange={(e) => handleUpload(e.target.files)}
          />
          {uploading && <Loader2 size={16} className="spin" style={{ animation: "spin 1s linear infinite" }} />}
        </div>

        {/* Document Cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {loading && docs.length === 0 ? (
            <div style={{ padding: "24px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
              <Loader2 size={18} className="spin" style={{ marginBottom: "6px" }} />
              <div>Loading documents...</div>
            </div>
          ) : docs.length === 0 ? (
            <div style={{ padding: "24px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.82rem" }}>
              No documents yet. Upload your first file above.
            </div>
          ) : (
            docs.map((d) => {
              const isSelected = selectedDoc?.id === d.id;
              const isProc = isDocumentProcessing(d);

              return (
                <div
                  key={d.id}
                  onClick={() => setSelectedDoc(d)}
                  style={{
                    background: isSelected ? "rgba(59,130,246,0.06)" : "var(--bg-surface)",
                    border: `1px solid ${isSelected ? "var(--accent-primary)" : "var(--border-subtle)"}`,
                    borderRadius: "var(--radius-md)",
                    padding: "12px 14px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "8px",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                    boxShadow: isSelected ? "0 0 10px var(--accent-glow)" : "none",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
                      <FileText size={16} style={{ flexShrink: 0, color: "var(--accent-primary)" }} />
                      <span
                        title={d.original_filename || d.name}
                        style={{
                          fontSize: "0.88rem",
                          fontWeight: 600,
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          color: "var(--text-primary)",
                        }}
                      >
                        {d.original_filename || d.name}
                      </span>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedDoc(d);
                        }}
                        title="Inspect details and chunks"
                        style={{
                          background: "var(--bg-secondary)",
                          border: "1px solid var(--border-subtle)",
                          color: "var(--text-secondary)",
                          cursor: "pointer",
                          padding: "4px 8px",
                          borderRadius: "var(--radius-sm)",
                          fontSize: "0.75rem",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        <Info size={12} /> Inspect
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (confirm(`Delete "${d.original_filename || d.name}"?`)) {
                            void handleDelete(d.id);
                          }
                        }}
                        title="Delete document"
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "var(--text-muted)",
                          cursor: "pointer",
                          padding: "5px",
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "8px", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "4px",
                        padding: "2px 8px",
                        borderRadius: "999px",
                        background: `${statusColor(d.status)}18`,
                        color: statusColor(d.status),
                        border: `1px solid ${statusColor(d.status)}40`,
                        fontWeight: 600,
                      }}
                    >
                      {d.status?.toLowerCase() === "ready" ? (
                        <CheckCircle2 size={10} />
                      ) : d.status?.toLowerCase() === "failed" ? (
                        <XCircle size={10} />
                      ) : (
                        <Loader2 size={10} className={isProc ? "spin" : ""} />
                      )}
                      {statusLabel(d.status)}
                    </span>

                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "4px",
                        padding: "2px 8px",
                        borderRadius: "999px",
                        background: `${statusColor(d.embedding_status || "pending")}18`,
                        color: statusColor(d.embedding_status || "pending"),
                        border: `1px solid ${statusColor(d.embedding_status || "pending")}40`,
                        fontWeight: 500,
                      }}
                    >
                      <Cpu size={10} /> {statusLabel(d.embedding_status || "not_embedded")}
                    </span>

                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                      <Layers size={10} /> {(d.file_size / 1024).toFixed(1)} KB
                    </span>

                    {typeof d.chunk_count === "number" && d.chunk_count > 0 && (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", color: "var(--accent-primary)", fontWeight: 500 }}>
                        · {d.chunk_count} {d.chunk_count === 1 ? "chunk" : "chunks"}
                      </span>
                    )}

                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                      <Clock size={10} /> v{d.current_version}
                    </span>
                  </div>

                  {/* Surface Error Banner on Card if Failed */}
                  {d.error_message && (
                    <div
                      style={{
                        padding: "6px 10px",
                        background: "var(--danger-bg)",
                        border: "1px solid var(--danger-border)",
                        borderRadius: "var(--radius-sm)",
                        color: "var(--danger-text)",
                        fontSize: "0.72rem",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                      }}
                    >
                      <AlertTriangle size={12} style={{ flexShrink: 0 }} />
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {d.error_message}
                      </span>
                    </div>
                  )}

                  {/* Process Buttons */}
                  {(d.status?.toLowerCase() !== "ready" || d.embedding_status?.toLowerCase() !== "completed") && (
                    <div style={{ display: "flex", gap: "8px", marginTop: "2px" }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleProcess(d.id);
                        }}
                        style={{
                          padding: "5px 10px",
                          borderRadius: "var(--radius-sm)",
                          border: "1px solid var(--border-subtle)",
                          background: "var(--bg-secondary)",
                          color: "var(--text-primary)",
                          fontSize: "0.78rem",
                          fontWeight: 500,
                          cursor: "pointer",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "5px",
                        }}
                      >
                        {isProc ? (
                          <>
                            <Loader2 size={12} className="spin" /> Processing...
                          </>
                        ) : d.status?.toLowerCase() !== "ready" ? (
                          "Re-process & Embed"
                        ) : (
                          "Embed Vectors"
                        )}
                      </button>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Document Inspector Drawer */}
      <DocumentInspectorDrawer
        isOpen={!!selectedDoc}
        document={selectedDoc}
        userRole={userRole}
        onClose={() => setSelectedDoc(null)}
        onProcess={handleProcess}
        onDelete={handleDelete}
      />
    </div>
  );
};
