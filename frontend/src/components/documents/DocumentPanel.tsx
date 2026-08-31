import React, { useEffect, useState, useCallback } from "react";
import { Upload, FileText, Trash2, Cpu, Layers, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { DocumentsApi, DocumentResponse } from "../../api/documents";

interface Props {
  kbId: string | null;
  kbName?: string;
}

const statusColor = (status: string) => {
  switch (status?.toLowerCase()) {
    case "ready":
      return "#10b981";
    case "processing":
      return "#f59e0b";
    case "failed":
      return "#ef4444";
    default:
      return "#94a3b8";
  }
};

const statusLabel = (status: string) => status?.replaceAll("_", " ") ?? "Unknown";

export const DocumentPanel: React.FC<Props> = ({ kbId, kbName }) => {
  const [docs, setDocs] = useState<DocumentResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const load = useCallback(async () => {
    if (!kbId) {
      setDocs([]);
      return;
    }
    setLoading(true);
    try {
      const { items } = await DocumentsApi.list(kbId);
      setDocs(items);
    } catch {
      setError("Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [kbId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleUpload = async (files: FileList | null) => {
    if (!files || !kbId) return;
    setError(null);
    setUploading(true);
    for (const file of Array.from(files)) {
      try {
        const uploadRes = await DocumentsApi.upload(kbId, file);
        // Auto-trigger processing pipeline
        try {
          await DocumentsApi.process(uploadRes.document.id);
        } catch (procErr) {
          console.warn("Auto-process failed, document uploaded but needs manual processing", procErr);
        }
      } catch (err: unknown) {
        const apiErr = err as { message?: string };
        setError(apiErr.message || `Failed to upload ${file.name}`);
      }
    }
    setUploading(false);
    await load();
  };

  const handleDelete = async (docId: string) => {
    if (!confirm("Delete this document?")) return;
    try {
      await DocumentsApi.delete(docId);
      await load();
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setError(apiErr.message || "Delete failed");
    }
  };

  const handleProcess = async (docId: string) => {
    try {
      await DocumentsApi.process(docId);
      await load();
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setError(apiErr.message || "Processing failed");
    }
  };

  if (!kbId) {
    return (
      <div style={{ padding: "24px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
        Select a knowledge base to manage documents. Create one via “Manage Knowledge Bases”.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "14px", padding: "16px", overflowY: "auto", flex: 1 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 600, fontSize: "0.9rem" }}>
          <FileText size={16} /> {kbName || "Documents"}
        </div>
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{docs.length} files</span>
      </div>

      {error && (
        <div style={{ padding: "8px 12px", background: "var(--danger-bg)", border: "1px solid var(--danger-border)", borderRadius: "var(--radius-md)", color: "var(--danger-text)", fontSize: "0.8rem" }}>
          {error}
        </div>
      )}

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); handleUpload(e.dataTransfer.files); }}
        style={{
          border: `1px dashed ${dragOver ? "var(--accent-primary)" : "var(--border-strong)"}`,
          background: dragOver ? "rgba(59,130,246,0.08)" : "var(--bg-surface)",
          borderRadius: "var(--radius-md)",
          padding: "18px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "8px",
          cursor: "pointer",
          transition: "all 0.15s",
        }}
        onClick={() => document.getElementById("doc-file-input")?.click()}
      >
        <Upload size={20} color="var(--text-muted)" />
        <span style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
          {uploading ? "Uploading..." : "Drag & drop files or click to browse"}
        </span>
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>PDF, DOCX, TXT, MD, CSV · Max 25MB</span>
        <input id="doc-file-input" type="file" multiple accept=".pdf,.docx,.txt,.md,.csv" style={{ display: "none" }} onChange={(e) => handleUpload(e.target.files)} />
        {uploading && <Loader2 size={16} className="spin" style={{ animation: "spin 1s linear infinite" }} />}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {loading ? (
          <div style={{ padding: "12px", textAlign: "center", color: "var(--text-muted)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Loading...</div>
        ) : docs.length === 0 ? (
          <div style={{ padding: "12px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.8rem" }}>No documents yet. Upload your first file above.</div>
        ) : (
          docs.map((d) => (
            <div key={d.id} style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", padding: "10px 12px", display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
                  <FileText size={14} style={{ flexShrink: 0, color: "var(--text-muted)" }} />
                  <span title={d.original_filename} style={{ fontSize: "0.85rem", fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.original_filename || d.name}</span>
                </div>
                <button onClick={() => handleDelete(d.id)} style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer" }}><Trash2 size={14} /></button>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", padding: "2px 6px", borderRadius: "999px", background: `${statusColor(d.status)}18`, color: statusColor(d.status), border: `1px solid ${statusColor(d.status)}40` }}>
                  {d.status === "ready" ? <CheckCircle2 size={10} /> : d.status === "failed" ? <XCircle size={10} /> : <Loader2 size={10} style={d.status === "processing" ? { animation: "spin 1s linear infinite" } : {}} />}
                  {statusLabel(d.status)}
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}><Cpu size={10} /> {statusLabel(d.embedding_status || "not_embedded")}</span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}><Layers size={10} /> {(d.file_size / 1024).toFixed(1)} KB</span>
              </div>
              {(d.status !== "ready" || d.embedding_status !== "completed") && (
                <button onClick={() => handleProcess(d.id)} style={{ marginTop: "4px", padding: "6px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-subtle)", background: "var(--bg-secondary)", color: "var(--text-primary)", fontSize: "0.8rem", cursor: "pointer" }}>
                  {d.status !== "ready" ? "Re-process & Embed" : "Embed vectors"}
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};
