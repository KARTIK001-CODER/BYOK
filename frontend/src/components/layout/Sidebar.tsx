import { AlertOctagon, Plus, Database, Bot, MessageSquare, Trash2, Settings2, Layers, ShieldAlert } from "lucide-react";
import { Conversation, KnowledgeBase, ProviderInfo, User, Organization } from "../../types";

interface SidebarProps {
  user: User | null;
  organization: Organization | null;
  conversations: Conversation[];
  activeConversationId: string | null;
  knowledgeBases: KnowledgeBase[];
  selectedKbId: string | null;
  providers: ProviderInfo[];
  selectedProvider: string;
  selectedModel: string;
  activeView?: "incidents" | "remediations" | "knowledge" | "chat";
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  onDeleteConversation: (id: string, e: React.MouseEvent) => void;
  onSelectKnowledgeBase: (id: string | null) => void;
  onSelectProvider: (provider: string) => void;
  onSelectModel: (model: string) => void;
  onManageKnowledgeBases?: () => void;
  onViewChange?: (v: "incidents" | "remediations" | "knowledge" | "chat") => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  user,
  organization,
  conversations,
  activeConversationId,
  knowledgeBases,
  selectedKbId,
  providers,
  selectedProvider,
  selectedModel,
  activeView = "incidents",
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  onSelectKnowledgeBase,
  onSelectProvider,
  onSelectModel,
  onManageKnowledgeBases,
  onViewChange,
}) => {
  const currentProviderObj = providers.find((p) => p.id === selectedProvider) || providers[0];

  return (
    <aside className="sidebar">
      {/* Brand Header */}
      <div className="sidebar-header">
        <div className="logo-brand">
          <div className="logo-icon" style={{ background: "var(--accent-primary)" }}>
            <AlertOctagon size={18} color="white" />
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontWeight: 700, fontSize: "1rem", color: "var(--text-primary)" }}>TracePilot</span>
            <span style={{ fontSize: "0.68rem", color: "var(--text-muted)", letterSpacing: "0.02em" }}>SRE Investigation</span>
          </div>
        </div>
      </div>

      {/* View Toggle */}
      {onViewChange && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", padding: "10px 16px" }}>
          <button
            onClick={() => onViewChange("incidents")}
            style={{
              padding: "7px",
              borderRadius: "var(--radius-md)",
              border: activeView === "incidents" ? "1px solid var(--accent-primary)" : "1px solid var(--border-subtle)",
              background: activeView === "incidents" ? "rgba(59,130,246,0.15)" : "var(--bg-surface)",
              color: activeView === "incidents" ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
            }}
            data-testid="sidebar-incidents-button"
          >
            <AlertOctagon size={13} /> Incidents
          </button>
          <button
            onClick={() => onViewChange("remediations")}
            style={{
              padding: "7px",
              borderRadius: "var(--radius-md)",
              border: activeView === "remediations" ? "1px solid var(--accent-primary)" : "1px solid var(--border-subtle)",
              background: activeView === "remediations" ? "rgba(59,130,246,0.15)" : "var(--bg-surface)",
              color: activeView === "remediations" ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
            }}
            data-testid="sidebar-remediations-button"
          >
            <ShieldAlert size={13} /> Remediations
          </button>
          <button
            onClick={() => onViewChange("knowledge")}
            style={{
              padding: "7px",
              borderRadius: "var(--radius-md)",
              border: activeView === "knowledge" ? "1px solid var(--accent-primary)" : "1px solid var(--border-subtle)",
              background: activeView === "knowledge" ? "rgba(59,130,246,0.15)" : "var(--bg-surface)",
              color: activeView === "knowledge" ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
            }}
            data-testid="sidebar-knowledge-button"
          >
            <Layers size={13} /> Runbooks
          </button>
          <button
            onClick={() => onViewChange("chat")}
            style={{
              padding: "7px",
              borderRadius: "var(--radius-md)",
              border: activeView === "chat" ? "1px solid var(--accent-primary)" : "1px solid var(--border-subtle)",
              background: activeView === "chat" ? "rgba(59,130,246,0.15)" : "var(--bg-surface)",
              color: activeView === "chat" ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
            }}
            data-testid="sidebar-chat-button"
          >
            <MessageSquare size={13} /> Assistant
          </button>
        </div>
      )}

      {/* Action Button for Chat */}
      {activeView === "chat" && (
        <button className="new-chat-btn" onClick={onNewChat} style={{ margin: "0 16px 8px 16px" }}>
          <Plus size={16} />
          <span>New Thread</span>
        </button>
      )}

      {/* Selectors for KB and Model */}
      <div className="sidebar-controls">
        <div className="control-group">
          <label className="control-label" htmlFor="kb-select">
            <Database size={12} style={{ display: "inline", marginRight: "4px" }} />
            Runbook Context
          </label>
          <div style={{ display: "flex", gap: "6px" }}>
            <select
              id="kb-select"
              className="custom-select"
              style={{ flex: 1 }}
              value={selectedKbId || ""}
              onChange={(e) => onSelectKnowledgeBase(e.target.value || null)}
            >
              <option value="">All Service Runbooks</option>
              {knowledgeBases.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
            <button
              onClick={onManageKnowledgeBases}
              title="Manage Runbooks & Knowledge"
              style={{
                background: "var(--bg-surface)",
                border: "1px solid var(--border-subtle)",
                color: "var(--text-secondary)",
                padding: "6px 8px",
                borderRadius: "var(--radius-sm)",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
              }}
            >
              <Settings2 size={14} />
            </button>
          </div>
        </div>

        <div className="control-group">
          <label className="control-label" htmlFor="model-select">
            <Bot size={12} style={{ display: "inline", marginRight: "4px" }} />
            Investigation Model
          </label>
          <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
            <span
              className={`status-dot ${currentProviderObj?.is_configured ? "status-dot-online" : "status-dot-busy"}`}
              title={currentProviderObj?.is_configured ? "Provider configured" : "Provider not configured — check API key"}
            />
            <select
              id="provider-select"
              className="custom-select"
              style={{ width: "45%" }}
              value={selectedProvider}
              onChange={(e) => onSelectProvider(e.target.value)}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>

            <select
              id="model-select"
              className="custom-select"
              style={{ width: "55%" }}
              value={selectedModel}
              onChange={(e) => onSelectModel(e.target.value)}
            >
              {currentProviderObj?.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Conversation Thread History */}
      <div className="conversations-section">
        <div className="section-title">Recent Conversations</div>
        {conversations.length === 0 ? (
          <div style={{ padding: "16px 8px", fontSize: "0.8rem", color: "var(--text-muted)", textAlign: "center" }}>
            No conversations yet.
          </div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conv-item ${activeConversationId === conv.id ? "active" : ""}`}
              onClick={() => onSelectConversation(conv.id)}
            >
              <MessageSquare size={15} style={{ marginRight: "8px", flexShrink: 0 }} />
              <span className="conv-title">{conv.title}</span>
              <button
                className="conv-delete-btn"
                title="Delete conversation"
                onClick={(e) => onDeleteConversation(conv.id, e)}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>

      {/* User & Organization Footer */}
      <div className="sidebar-footer">
        <div className="user-profile">
          <div className="avatar">
            {user?.email ? user.email.substring(0, 2).toUpperCase() : "TP"}
          </div>
          <div className="user-meta">
            <span className="user-name">{user?.full_name || user?.email?.split("@")[0] || "User"}</span>
            <span className="user-org">{organization?.name || "TracePilot Workspace"}</span>
          </div>
        </div>
      </div>
    </aside>
  );
};
