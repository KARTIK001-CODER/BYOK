import React, { useRef, useEffect } from "react";
import { Sparkles, ArrowRight } from "lucide-react";
import { Message, CitationItem } from "../../types";
import { MessageItem } from "./MessageItem";
import { Composer } from "./Composer";

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
  loadingPhase: "searching" | "generating" | null;
  streamingMessage: Message | null;
  onSendMessage: (message: string) => void;
  onOpenSource: (citations: CitationItem[], selectedId?: number) => void;
  hasKnowledgeBase?: boolean;
}

const STARTER_QUESTIONS = [
  "Explain the JWT authentication and refresh token rotation architecture.",
  "What security practices and multi-tenancy safeguards are enforced?",
  "How does hybrid retrieval with pgvector and PostgreSQL FTS work?",
  "Summarize the main data storage and document ingestion pipelines.",
];

export const ChatWindow: React.FC<ChatWindowProps> = ({
  messages,
  isLoading,
  loadingPhase,
  streamingMessage,
  onSendMessage,
  onOpenSource,
  // hasKnowledgeBase is reserved for future inline warning banner
}) => {
  const scrollBottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingMessage, loadingPhase]);

  const isEmpty = messages.length === 0 && !streamingMessage;

  return (
    <div className="main-chat-area">
      <div className="messages-container">
        {isEmpty ? (
          <div className="empty-state">
            <div className="empty-icon">
              <Sparkles size={28} />
            </div>
            <h1 className="empty-title">Your knowledge, one conversation away.</h1>
            <p className="empty-subtitle">
              Ask questions across your documents, research faster, and get verifiable answers grounded with direct citations.
            </p>

            <div className="suggestions-grid">
              {STARTER_QUESTIONS.map((q, idx) => (
                <button
                  key={idx}
                  className="suggestion-card"
                  onClick={() => onSendMessage(q)}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span>{q}</span>
                    <ArrowRight size={14} style={{ opacity: 0.5, flexShrink: 0 }} />
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <MessageItem
                key={msg.id}
                message={msg}
                onOpenSource={onOpenSource}
              />
            ))}

            {streamingMessage && (
              <MessageItem
                key="streaming"
                message={streamingMessage}
                isStreaming={true}
                onOpenSource={onOpenSource}
              />
            )}

            {isLoading && loadingPhase && (
              <div className="message-wrapper">
                <div className="loading-indicator">
                  <div className="spinner" />
                  <span>
                    {loadingPhase === "searching"
                      ? "Searching your knowledge..."
                      : "Generating answer..."}
                  </span>
                </div>
              </div>
            )}
          </>
        )}
        <div ref={scrollBottomRef} />
      </div>

      <Composer
        onSendMessage={onSendMessage}
        isLoading={isLoading}
      />
    </div>
  );
};
