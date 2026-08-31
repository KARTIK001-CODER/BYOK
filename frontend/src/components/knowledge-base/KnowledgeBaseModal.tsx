import React, { useState } from "react";
import { Database, Plus, Trash2, X } from "lucide-react";
import { KnowledgeBase } from "../../types";
import { KnowledgeBasesApi } from "../../api/knowledgeBases";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  knowledgeBases: KnowledgeBase[];
  onCreated: (kb: KnowledgeBase) => void;
  onDeleted: (id: string) => void;
  onSelect: (id: string) => void;
  selectedId: string | null;
}

export const KnowledgeBaseModal: React.FC<Props> = ({ isOpen, onClose, knowledgeBases, onCreated, onDeleted, onSelect, selectedId }) => {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  if (!isOpen) return null;

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const kb = await KnowledgeBasesApi.create({ name: name.trim(), description: description.trim() || undefined });
      onCreated(kb);
      setName("");
      setDescription("");
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setError(apiErr.message || "Failed to create knowledge base");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Delete this knowledge base? Documents will be removed.")) return;
    try {
      await KnowledgeBasesApi.delete(id);
      onDeleted(id);
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setError(apiErr.message || "Failed to delete");
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" style={{ maxWidth: "560px" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Database size={18} color="white" />
            <h2 style={{ fontSize: "1.05rem", fontWeight: 700 }}>Knowledge Bases</h2>
          </div>
          <button onClick={onClose} style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer" }}>
            <X size={18} />
          </button>
        </div>

        {error && (
          <div style={{ padding: "10px 14px", backgroundColor: "var(--danger-bg)", border: "1px solid var(--danger-border)", borderRadius: "var(--radius-md)", color: "var(--danger-text)", fontSize: "0.85rem" }}>
            {error}
          </div>
        )}

        <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: "10px", background: "var(--bg-surface)", padding: "14px", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
          <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>Create new knowledge base</div>
          <input className="form-input" placeholder="e.g. Engineering Docs" value={name} onChange={(e) => setName(e.target.value)} required />
          <input className="form-input" placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
          <button type="submit" className="btn-primary" disabled={creating} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
            <Plus size={14} /> {creating ? "Creating..." : "Create"}
          </button>
        </form>

        <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "260px", overflowY: "auto" }}>
          {knowledgeBases.length === 0 ? (
            <div style={{ padding: "16px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>No knowledge bases yet. Create one to upload documents.</div>
          ) : (
            knowledgeBases.map((kb) => (
              <div
                key={kb.id}
                onClick={() => onSelect(kb.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "10px 12px",
                  borderRadius: "var(--radius-md)",
                  border: selectedId === kb.id ? "1px solid var(--accent-primary)" : "1px solid var(--border-subtle)",
                  background: selectedId === kb.id ? "rgba(59,130,246,0.08)" : "var(--bg-surface)",
                  cursor: "pointer",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{kb.name}</div>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{kb.description || kb.slug}</div>
                </div>
                <button onClick={(e) => handleDelete(kb.id, e)} style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: "6px" }}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
