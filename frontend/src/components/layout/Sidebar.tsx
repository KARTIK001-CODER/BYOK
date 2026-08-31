import React from "react";
import { Plus, Database, Bot, MessageSquare, Trash2, Settings2, Layers } from "lucide-react";
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
  activeView?: "chat" | "knowledge";
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  onDeleteConversation: (id: string, e: React.MouseEvent) => void;
  onSelectKnowledgeBase: (id: string | null) => void;
  onSelectProvider: (provider: string) => void;
  onSelectModel: (model: string) => void;
  onManageKnowledgeBases?: () => void;
  onViewChange?: (v: "chat" | "knowledge") => void;
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
  activeView,
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
          <div className="logo-icon">
            <Bot size={18} color="white" />
          </div>
          <span>RAGForge</span>
        </div>
      </div>

      {/* New Chat Button */}
      <button className="new-chat-btn" onClick={onNewChat}>
        <Plus size={18} />
        <span>New Chat</span>
      </button>

      {/* Selectors for KB and Model */}
      <div className="sidebar-controls">
        <div className="control-group">
          <label className="control-label" htmlFor="kb-select">
            <Database size={12} style={{ display: "inline", marginRight: "4px" }} />
            Knowledge Base
          </label>
          <div style={{ display: "flex", gap: "6px" }}>
            <select
              id="kb-select"
              className="custom-select"
              style={{ flex: 1 }}
              value={selectedKbId || ""}
              onChange={(e) => onSelectKnowledgeBase(e.target.value || null)}
            >
              <option value="">All Knowledge Bases</option>
              {knowledgeBases.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
            <button
              onClick={onManageKnowledgeBases}
              title="Manage Knowledge Bases"
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
            Model Provider
          </label>
          <div style={{ display: "flex", gap: "6px" }}>
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

      {/* View Toggle */}
      {onViewChange && (
        <div style={{ display: "flex", gap: "6px", padding: "8px 16px" }}>
          <button
            onClick={() => onViewChange("chat")}
            style={{
              flex: 1,
              padding: "7px",
              borderRadius: "var(--radius-md)",
              border: activeView === "chat" ? "1px solid var(--accent-primary)" : "1px solid var(--border-subtle)",
              background: activeView === "chat" ? "rgba(59,130,246,0.15)" : "var(--bg-surface)",
              color: activeView === "chat" ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: "0.8rem",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
            }}
          >
            <MessageSquare size={13} /> Chat
          </button>
          <button
            onClick={() => onViewChange("knowledge")}
            style={{
              flex: 1,
              padding: "7px",
              borderRadius: "var(--radius-md)",
              border: activeView === "knowledge" ? "1px solid var(--accent-primary)" : "1px solid var(--border-subtle)",
              background: activeView === "knowledge" ? "rgba(59,130,246,0.15)" : "var(--bg-surface)",
              color: activeView === "knowledge" ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: "0.8rem",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
            }}
          >
            <Layers size={13} /> Knowledge
          </button>
        </div>
      )}

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
            {user?.email ? user.email.substring(0, 2).toUpperCase() : "RF"}
          </div>
          <div className="user-meta">
            <span className="user-name">{user?.full_name || user?.email?.split("@")[0] || "User"}</span>
            <span className="user-org">{organization?.name || "RAGForge Workspace"}</span>
          </div>
        </div>
      </div>
    </aside>
  );
};
