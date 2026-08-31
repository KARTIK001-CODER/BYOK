import React, { useState, useEffect, useCallback } from "react";
import { Navbar } from "./components/layout/Navbar";
import { Sidebar } from "./components/layout/Sidebar";
import { ChatWindow } from "./components/chat/ChatWindow";
import { SourcePreviewDrawer } from "./components/chat/SourcePreviewDrawer";
import { AuthModal } from "./components/auth/AuthModal";
import { KnowledgeBaseModal } from "./components/knowledge-base/KnowledgeBaseModal";
import { DocumentPanel } from "./components/documents/DocumentPanel";
import { AuthApi } from "./api/auth";
import { ChatApi } from "./api/chat";
import { ConversationsApi } from "./api/conversations";
import { KnowledgeBasesApi } from "./api/knowledgeBases";
import { ApiClient } from "./api/client";
import {
  User,
  Organization,
  Conversation,
  KnowledgeBase,
  ProviderInfo,
  Message,
  CitationItem,
  RAGChatRequest,
} from "./types";

export const App: React.FC = () => {
  const [user, setUser] = useState<User | null>(null);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [showAuthModal, setShowAuthModal] = useState<boolean>(false);

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<string | null>(null);
  const [showKbModal, setShowKbModal] = useState(false);
  const [activeView, setActiveView] = useState<"chat" | "knowledge">("chat");

  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("groq");
  const [selectedModel, setSelectedModel] = useState<string>("qwen/qwen3.8-27b");

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [loadingPhase, setLoadingPhase] = useState<"searching" | "generating" | null>(null);
  const [streamingMessage, setStreamingMessage] = useState<Message | null>(null);

  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [activeCitations, setActiveCitations] = useState<CitationItem[]>([]);
  const [selectedCitationId, setSelectedCitationId] = useState<number | null>(null);

  // Load initial models catalog
  useEffect(() => {
    ChatApi.getModels()
      .then((provs) => {
        setProviders(provs);
        if (provs.length > 0) {
          // Prefer configured provider first
          const configured = provs.find((p) => p.is_configured) || provs[0];
          setSelectedProvider(configured.id);
          setSelectedModel(configured.default_model);
        }
      })
      .catch(() => {
        setProviders([
          {
            id: "groq",
            name: "Groq",
            description: "Ultra-fast inference",
            is_configured: true,
            default_model: "qwen/qwen3.8-27b",
            models: [
              {
                id: "qwen/qwen3.8-27b",
                name: "Qwen 3.8 27B",
                provider: "groq",
                capabilities: { streaming: true, context_window: 128000, max_output_tokens: 8192 },
                is_default: true,
              },
            ],
          },
        ]);
      });
  }, []);

  const loadUserData = useCallback(async () => {
    try {
      const u = await AuthApi.getCurrentUser();
      setUser(u);
      const memberships = await AuthApi.getUserOrganizations();
      const primaryOrg = memberships[0]?.organization || (memberships[0] ? {
        id: memberships[0].organization_id,
        name: "Workspace",
        slug: "workspace",
      } : null);
      setOrganization(primaryOrg);
      if (primaryOrg) {
        ApiClient.setOrganizationId(primaryOrg.id);
      }
      const [kbs, convs] = await Promise.all([
        KnowledgeBasesApi.list().catch(() => []),
        ConversationsApi.list().catch(() => []),
      ]);
      setKnowledgeBases(kbs);
      setConversations(convs);
      if (kbs.length > 0 && !selectedKbId) {
        setSelectedKbId(kbs[0].id);
      }
      setShowAuthModal(false);
    } catch {
      setShowAuthModal(true);
    }
  }, [selectedKbId]);

  useEffect(() => {
    if (ApiClient.getToken()) {
      loadUserData();
    } else {
      setShowAuthModal(true);
    }
  }, [loadUserData]);

  const handleSelectConversation = async (id: string) => {
    setActiveConversationId(id);
    setActiveView("chat");
    try {
      const fullConv = await ConversationsApi.get(id);
      setMessages(fullConv.messages || []);
      if (fullConv.knowledge_base_ids && fullConv.knowledge_base_ids.length > 0) {
        setSelectedKbId(fullConv.knowledge_base_ids[0]);
      }
    } catch (err) {
      console.error("Failed to load conversation:", err);
    }
  };

  const handleNewChat = () => {
    setActiveConversationId(null);
    setMessages([]);
    setStreamingMessage(null);
    setDrawerOpen(false);
    setActiveView("chat");
  };

  const handleDeleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await ConversationsApi.delete(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeConversationId === id) {
        handleNewChat();
      }
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    }
  };

  const handleSelectProvider = (prov: string) => {
    setSelectedProvider(prov);
    const p = providers.find((x) => x.id === prov);
    if (p) {
      setSelectedModel(p.default_model);
    }
  };

  const handleOpenSource = (citations: CitationItem[], selectedId?: number) => {
    setActiveCitations(citations);
    setSelectedCitationId(selectedId || (citations[0]?.id ?? null));
    setDrawerOpen(true);
  };

  const handleKbCreated = (kb: KnowledgeBase) => {
    setKnowledgeBases((prev) => [...prev, kb]);
    setSelectedKbId(kb.id);
    setShowKbModal(false);
  };

  const handleKbDeleted = (id: string) => {
    setKnowledgeBases((prev) => prev.filter((k) => k.id !== id));
    if (selectedKbId === id) setSelectedKbId(null);
  };

  const handleSendMessage = async (queryText: string) => {
    if (!queryText.trim() || isLoading) return;

    const userMsg: Message = {
      id: `temp-${Date.now()}`,
      conversation_id: activeConversationId || "new",
      role: "user",
      content: queryText,
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setLoadingPhase("searching");

    let currentAnswerText = "";
    const currentCitations: CitationItem[] = [];
    let currentConvId = activeConversationId;
    let retrievalSummary: { search_mode: string; result_count: number; latency_ms: number } | undefined;

    const requestPayload: RAGChatRequest = {
      message: queryText,
      conversation_id: activeConversationId,
      knowledge_base_ids: selectedKbId ? [selectedKbId] : null,
      provider: selectedProvider,
      model: selectedModel,
      search_mode: "hybrid",
      top_k: 8,
    };

    await ChatApi.streamChat(requestPayload, {
      onStart: (data) => {
        currentConvId = data.conversation_id;
        if (!activeConversationId) {
          setActiveConversationId(data.conversation_id);
          ConversationsApi.list().then(setConversations).catch(() => {});
        }
      },
      onRetrieval: (data) => {
        retrievalSummary = data;
        setLoadingPhase("generating");
      },
      onToken: (data) => {
        setLoadingPhase(null);
        currentAnswerText += data.delta;
        setStreamingMessage({
          id: "streaming-msg",
          conversation_id: currentConvId || "active",
          role: "assistant",
          content: currentAnswerText,
          created_at: new Date().toISOString(),
          message_metadata: {
            provider: selectedProvider,
            model: selectedModel,
            citations: currentCitations,
            retrieval: retrievalSummary,
          },
        });
      },
      onCitation: (data) => {
        currentCitations.push(data);
        setStreamingMessage((prev) =>
          prev
            ? {
                ...prev,
                message_metadata: {
                  ...prev.message_metadata,
                  citations: [...currentCitations],
                },
              }
            : null
        );
      },
      onDone: (data) => {
        const finalAssistantMsg: Message = {
          id: data.message_id,
          conversation_id: data.conversation_id,
          role: "assistant",
          content: currentAnswerText,
          created_at: new Date().toISOString(),
          message_metadata: {
            provider: selectedProvider,
            model: selectedModel,
            citations: currentCitations,
            retrieval: retrievalSummary,
            latency_ms: data.latency_ms,
            time_to_first_token_ms: data.time_to_first_token_ms,
            usage: data.usage,
          },
        };

        setMessages((prev) => [...prev, finalAssistantMsg]);
        setStreamingMessage(null);
        setIsLoading(false);
        setLoadingPhase(null);
      },
      onError: (err) => {
        const errorMsg: Message = {
          id: `err-${Date.now()}`,
          conversation_id: currentConvId || "active",
          role: "assistant",
          content: `We couldn't generate an answer: ${err.message}`,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errorMsg]);
        setStreamingMessage(null);
        setIsLoading(false);
        setLoadingPhase(null);
      },
      onComplete: () => {
        setIsLoading(false);
        setLoadingPhase(null);
      },
    });
  };

  const handleLogout = () => {
    ApiClient.setToken(null);
    ApiClient.setOrganizationId(null);
    setUser(null);
    setOrganization(null);
    setConversations([]);
    setMessages([]);
    setShowAuthModal(true);
  };

  const selectedKb = knowledgeBases.find((k) => k.id === selectedKbId) || null;

  return (
    <div className="app-container">
      <Sidebar
        user={user}
        organization={organization}
        conversations={conversations}
        activeConversationId={activeConversationId}
        knowledgeBases={knowledgeBases}
        selectedKbId={selectedKbId}
        providers={providers}
        selectedProvider={selectedProvider}
        selectedModel={selectedModel}
        activeView={activeView}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
        onSelectKnowledgeBase={setSelectedKbId}
        onSelectProvider={handleSelectProvider}
        onSelectModel={setSelectedModel}
        onManageKnowledgeBases={() => setShowKbModal(true)}
        onViewChange={setActiveView}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
        <Navbar
          user={user}
          organization={organization}
          selectedProvider={selectedProvider}
          selectedModel={selectedModel}
          onLogout={handleLogout}
          onManageKnowledgeBases={() => setShowKbModal(true)}
          activeView={activeView}
          onViewChange={setActiveView}
          knowledgeBaseName={selectedKb?.name}
        />

        <div style={{ flex: 1, display: "flex", height: "calc(100% - 56px)", overflow: "hidden" }}>
          {activeView === "knowledge" ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--bg-primary)", overflow: "hidden" }}>
              <DocumentPanel kbId={selectedKbId} kbName={selectedKb?.name} />
            </div>
          ) : (
            <ChatWindow
              messages={messages}
              isLoading={isLoading}
              loadingPhase={loadingPhase}
              streamingMessage={streamingMessage}
              onSendMessage={handleSendMessage}
              onOpenSource={handleOpenSource}
              hasKnowledgeBase={!!selectedKbId || knowledgeBases.length > 0}
            />
          )}

          <SourcePreviewDrawer
            isOpen={drawerOpen}
            citations={activeCitations}
            selectedCitationId={selectedCitationId}
            onClose={() => setDrawerOpen(false)}
            onSelectCitation={setSelectedCitationId}
          />
        </div>
      </div>

      <KnowledgeBaseModal
        isOpen={showKbModal}
        onClose={() => setShowKbModal(false)}
        knowledgeBases={knowledgeBases}
        onCreated={handleKbCreated}
        onDeleted={handleKbDeleted}
        onSelect={(id) => { setSelectedKbId(id); setShowKbModal(false); }}
        selectedId={selectedKbId}
      />

      <AuthModal
        isOpen={showAuthModal}
        onSuccess={(u, org) => {
          setUser(u);
          setOrganization(org);
          setShowAuthModal(false);
          loadUserData();
        }}
      />
    </div>
  );
};
