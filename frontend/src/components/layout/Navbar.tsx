import React from "react";
import { Sparkles, Layers, LogOut, Database, MessageSquare } from "lucide-react";
import { User, Organization } from "../../types";

interface NavbarProps {
  user: User | null;
  organization: Organization | null;
  selectedProvider: string;
  selectedModel: string;
  onLogout: () => void;
  onManageKnowledgeBases?: () => void;
  activeView?: "chat" | "knowledge";
  onViewChange?: (v: "chat" | "knowledge") => void;
  knowledgeBaseName?: string | null;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  organization,
  selectedProvider,
  selectedModel,
  onLogout,
  onManageKnowledgeBases,
  activeView,
  onViewChange,
  knowledgeBaseName,
}) => {
  return (
    <header className="chat-header">
      <div className="chat-header-title">
        <Sparkles size={18} className="text-accent" />
        <span>{activeView === "knowledge" ? "Knowledge Base" : "RAGForge Assistant"}</span>
        {knowledgeBaseName && <span style={{ fontWeight: 400, color: "var(--text-muted)", fontSize: "0.85rem" }}>· {knowledgeBaseName}</span>}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        {onViewChange && (
          <div style={{ display: "flex", background: "var(--bg-surface)", borderRadius: "var(--radius-full)", padding: "2px", border: "1px solid var(--border-subtle)" }}>
            <button
              onClick={() => onViewChange("chat")}
              style={{
                padding: "4px 12px",
                borderRadius: "999px",
                border: "none",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: "pointer",
                background: activeView === "chat" ? "var(--accent-primary)" : "transparent",
                color: activeView === "chat" ? "white" : "var(--text-muted)",
              }}
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}><MessageSquare size={12} /> Chat</span>
            </button>
            <button
              onClick={() => onViewChange("knowledge")}
              style={{
                padding: "4px 12px",
                borderRadius: "999px",
                border: "none",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: "pointer",
                background: activeView === "knowledge" ? "var(--accent-primary)" : "transparent",
                color: activeView === "knowledge" ? "white" : "var(--text-muted)",
              }}
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}><Database size={12} /> Knowledge</span>
            </button>
          </div>
        )}

        {onManageKnowledgeBases && (
          <button
            onClick={onManageKnowledgeBases}
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-secondary)", padding: "6px 10px", borderRadius: "var(--radius-md)", fontSize: "0.8rem", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "6px" }}
          >
            <Database size={14} /> Manage
          </button>
        )}

        <div className="model-badge">
          <Layers size={14} />
          <span>{selectedProvider.toUpperCase()} · {selectedModel}</span>
        </div>

        {user && (
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              {organization?.name || "Workspace"}
            </span>
            <button
              onClick={onLogout}
              title="Logout"
              style={{
                background: "transparent",
                border: "none",
                color: "var(--text-muted)",
                cursor: "pointer",
                padding: "4px",
                display: "flex",
                alignItems: "center",
              }}
            >
              <LogOut size={16} />
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
