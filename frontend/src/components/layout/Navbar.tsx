import React from "react";
import { AlertOctagon, Layers, LogOut, Database, MessageSquare, ShieldAlert } from "lucide-react";
import { User, Organization } from "../../types";

interface NavbarProps {
  user: User | null;
  organization: Organization | null;
  selectedProvider: string;
  selectedModel: string;
  onLogout: () => void;
  onManageKnowledgeBases?: () => void;
  activeView?: "incidents" | "remediations" | "knowledge" | "chat";
  onViewChange?: (v: "incidents" | "remediations" | "knowledge" | "chat") => void;
  knowledgeBaseName?: string | null;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  organization,
  selectedProvider,
  selectedModel,
  onLogout,
  onManageKnowledgeBases,
  activeView = "incidents",
  onViewChange,
  knowledgeBaseName,
}) => {
  return (
    <header className="chat-header">
      <div className="chat-header-title">
        {activeView === "remediations" ? (
          <ShieldAlert size={18} className="text-accent" />
        ) : activeView === "knowledge" ? (
          <Database size={18} className="text-accent" />
        ) : activeView === "chat" ? (
          <MessageSquare size={18} className="text-accent" />
        ) : (
          <AlertOctagon size={18} className="text-accent" />
        )}
        <span>
          {activeView === "incidents"
            ? "TracePilot — Incident Management"
            : activeView === "remediations"
            ? "TracePilot — Remediation Review"
            : activeView === "knowledge"
            ? "TracePilot — Runbooks & Knowledge"
            : "TracePilot — Operational Assistant"}
        </span>
        {knowledgeBaseName && activeView === "knowledge" && (
          <span style={{ fontWeight: 400, color: "var(--text-muted)", fontSize: "0.85rem" }}>
            · {knowledgeBaseName}
          </span>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        {onViewChange && (
          <div
            style={{
              display: "flex",
              background: "var(--bg-surface)",
              borderRadius: "var(--radius-full)",
              padding: "2px",
              border: "1px solid var(--border-subtle)",
            }}
          >
            <button
              onClick={() => onViewChange("incidents")}
              style={{
                padding: "4px 12px",
                borderRadius: "999px",
                border: "none",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: "pointer",
                background: activeView === "incidents" ? "var(--accent-primary)" : "transparent",
                color: activeView === "incidents" ? "white" : "var(--text-muted)",
              }}
              data-testid="navbar-incidents-button"
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                <AlertOctagon size={12} /> Incidents
              </span>
            </button>
            <button
              onClick={() => onViewChange("remediations")}
              style={{
                padding: "4px 12px",
                borderRadius: "999px",
                border: "none",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: "pointer",
                background: activeView === "remediations" ? "var(--accent-primary)" : "transparent",
                color: activeView === "remediations" ? "white" : "var(--text-muted)",
              }}
              data-testid="navbar-remediations-button"
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                <ShieldAlert size={12} /> Remediations
              </span>
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
              data-testid="navbar-knowledge-button"
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                <Database size={12} /> Runbooks
              </span>
            </button>
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
              data-testid="navbar-chat-button"
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                <MessageSquare size={12} /> Assistant
              </span>
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
          <span className="status-dot status-dot-online" aria-hidden />
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
