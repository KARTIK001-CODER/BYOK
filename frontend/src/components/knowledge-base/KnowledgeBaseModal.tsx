import React, { useState } from "react";
import { Database, Plus, Trash2, X, Pencil, Check } from "lucide-react";
import { KnowledgeBase } from "../../types";
import { KnowledgeBasesApi } from "../../api/knowledgeBases";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  knowledgeBases: KnowledgeBase[];
  onCreated: (kb: KnowledgeBase) => void;
  onUpdated?: (kb: KnowledgeBase) => void;
  onDeleted: (id: string) => void;
  onSelect: (id: string) => void;
  selectedId: string | null;
}

export const KnowledgeBaseModal: React.FC<Props> = ({
  isOpen,
  onClose,
  knowledgeBases,
  onCreated,
  onUpdated,
  onDeleted,
  onSelect,
  selectedId,
}) => {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  // Edit / Rename states
  const [editingKbId, setEditingKbId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

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

  const handleStartEdit = (kb: KnowledgeBase, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingKbId(kb.id);
    setEditName(kb.name);
    setEditDescription(kb.description || "");
    setEditError(null);
  };

  const handleCancelEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingKbId(null);
    setEditError(null);
  };

  const handleSaveEdit = async (kbId: string, e: React.MouseEvent | React.FormEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (!editName.trim() || savingEdit) return;
    setSavingEdit(true);
    setEditError(null);
    try {
      const updated = await KnowledgeBasesApi.update(kbId, {
        name: editName.trim(),
        description: editDescription.trim() || undefined,
      });
      if (onUpdated) {
        onUpdated(updated);
      }
      setEditingKbId(null);
    } catch (err: unknown) {
      const apiErr = err as { message?: string };
      setEditError(apiErr.message || "Failed to update knowledge base");
    } finally {
      setSavingEdit(false);
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

        <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "280px", overflowY: "auto" }}>
          {knowledgeBases.length === 0 ? (
            <div style={{ padding: "16px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>No knowledge bases yet. Create one to upload documents.</div>
          ) : (
            knowledgeBases.map((kb) => {
              if (editingKbId === kb.id) {
                return (
                  <form
                    key={kb.id}
                    onSubmit={(e) => void handleSaveEdit(kb.id, e)}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "8px",
                      padding: "10px 12px",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--accent-primary)",
                      background: "var(--bg-surface)",
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-primary)" }}>Rename Knowledge Base</span>
                      <button
                        type="button"
                        onClick={handleCancelEdit}
                        style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: "2px" }}
                      >
                        <X size={14} />
                      </button>
                    </div>

                    {editError && (
                      <div style={{ padding: "6px 10px", background: "var(--danger-bg)", border: "1px solid var(--danger-border)", borderRadius: "var(--radius-sm)", color: "var(--danger-text)", fontSize: "0.75rem" }}>
                        {editError}
                      </div>
                    )}

                    <input
                      className="form-input"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      placeholder="Knowledge base name"
                      style={{ padding: "6px 10px", fontSize: "0.85rem" }}
                      autoFocus
                      required
                    />
                    <input
                      className="form-input"
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      placeholder="Description (optional)"
                      style={{ padding: "6px 10px", fontSize: "0.8rem" }}
                    />
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: "6px" }}>
                      <button
                        type="button"
                        onClick={handleCancelEdit}
                        style={{ padding: "4px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-subtle)", background: "transparent", color: "var(--text-secondary)", fontSize: "0.8rem", cursor: "pointer" }}
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={savingEdit || !editName.trim()}
                        className="btn-primary"
                        style={{ padding: "4px 12px", fontSize: "0.8rem", display: "inline-flex", alignItems: "center", gap: "4px" }}
                      >
                        <Check size={13} /> {savingEdit ? "Saving..." : "Save"}
                      </button>
                    </div>
                  </form>
                );
              }

              return (
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
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: "0.9rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{kb.name}</div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{kb.description || kb.slug}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <button
                      onClick={(e) => handleStartEdit(kb, e)}
                      title="Rename knowledge base"
                      style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: "6px" }}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={(e) => handleDelete(kb.id, e)}
                      title="Delete knowledge base"
                      style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: "6px" }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

