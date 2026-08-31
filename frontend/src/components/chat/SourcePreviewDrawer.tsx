import React from "react";
import { X, FileText, BookOpen, Hash } from "lucide-react";
import { CitationItem } from "../../types";

interface SourcePreviewDrawerProps {
  isOpen: boolean;
  citations: CitationItem[];
  selectedCitationId: number | null;
  onClose: () => void;
  onSelectCitation: (id: number) => void;
}

export const SourcePreviewDrawer: React.FC<SourcePreviewDrawerProps> = ({
  isOpen,
  citations,
  selectedCitationId,
  onClose,
  onSelectCitation,
}) => {
  if (!isOpen) return null;

  return (
    <aside className="source-drawer">
      <div className="drawer-header">
        <div className="drawer-title">
          <BookOpen size={18} className="text-accent" />
          <span>Retrieved Sources ({citations.length})</span>
        </div>
        <button
          onClick={onClose}
          style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer" }}
        >
          <X size={18} />
        </button>
      </div>

      <div className="drawer-body">
        {citations.map((cit) => (
          <div
            key={cit.id}
            className="source-detail-card"
            style={{
              borderColor: selectedCitationId === cit.id ? "var(--accent-primary)" : "var(--border-subtle)",
              boxShadow: selectedCitationId === cit.id ? "0 0 12px var(--accent-glow)" : "none",
            }}
            onClick={() => onSelectCitation(cit.id)}
          >
            <div className="source-meta-row">
              <span style={{ fontWeight: 700, color: "var(--accent-primary)", display: "flex", alignItems: "center", gap: "4px" }}>
                <Hash size={12} />
                Source [{cit.id}]
              </span>
              {cit.page_number && <span>Page {cit.page_number}</span>}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.85rem", fontWeight: 600, color: "var(--text-primary)" }}>
              <FileText size={15} color="var(--accent-primary)" />
              <span>{cit.document_name}</span>
            </div>

            {cit.section_title && (
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                Section: <span style={{ color: "var(--text-secondary)" }}>{cit.section_title}</span>
              </div>
            )}

            <div className="source-content-box">
              {cit.content_preview || "Document text excerpt..."}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
};
