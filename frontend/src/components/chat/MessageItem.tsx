import React from "react";
import { Bot, FileText, Cpu, Clock, Layers } from "lucide-react";
import { Message, CitationItem } from "../../types";

interface MessageItemProps {
  message: Message;
  isStreaming?: boolean;
  onOpenSource: (citations: CitationItem[], selectedId?: number) => void;
}

export const MessageItem: React.FC<MessageItemProps> = ({
  message,
  isStreaming,
  onOpenSource,
}) => {
  const isUser = message.role === "user";

  // Helper to render text with interactive [1], [2] citation badges
  const renderFormattedContent = (content: string, citations?: CitationItem[]) => {
    const parts = content.split(/(\[\d+(?:\s*,\s*\d+)*\])/g);

    return parts.map((part, index) => {
      const citationMatch = part.match(/\[(\d+(?:\s*,\s*\d+)*)\]/);
      if (citationMatch) {
        const idStrings = citationMatch[1].split(",");
        return (
          <span key={index} style={{ display: "inline-flex", gap: "2px" }}>
            {idStrings.map((idStr, subIdx) => {
              const num = parseInt(idStr.trim(), 10);
              return (
                <button
                  key={subIdx}
                  className="citation-pill"
                  title={`View Source [${num}]`}
                  onClick={() => citations && onOpenSource(citations, num)}
                >
                  {num}
                </button>
              );
            })}
          </span>
        );
      }
      return <span key={index}>{part}</span>;
    });
  };

  if (isUser) {
    return (
      <div className="message-wrapper">
        <div className="user-message">{message.content}</div>
      </div>
    );
  }

  const citations = message.message_metadata?.citations || [];
  const meta = message.message_metadata;

  return (
    <div className="message-wrapper">
      <div className="assistant-message">
        <div className="assistant-header">
          <div className="assistant-avatar">
            <Bot size={16} />
          </div>
          <span className="assistant-name">RAGForge</span>
          {meta?.model && (
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginLeft: "auto" }}>
              {meta.provider?.toUpperCase()} · {meta.model}
            </span>
          )}
        </div>

        <div className="message-content">
          {renderFormattedContent(message.content, citations)}
          {isStreaming && <span className="streaming-cursor" />}
        </div>

        {/* Sources Box */}
        {citations.length > 0 && (
          <div className="sources-card">
            <div className="sources-header">
              <FileText size={13} />
              <span>Grounded Sources ({citations.length})</span>
            </div>
            <div className="sources-list">
              {citations.map((cit) => (
                <button
                  key={cit.id}
                  className="source-item-btn"
                  onClick={() => onOpenSource(citations, cit.id)}
                >
                  <span className="source-item-id">[{cit.id}]</span>
                  <span style={{ fontWeight: 500 }}>{cit.document_name}</span>
                  {cit.page_number && (
                    <span style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>
                      p. {cit.page_number}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Telemetry Footer */}
        {meta && (
          <div className="telemetry-footer">
            {meta.retrieval && (
              <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <Layers size={12} />
                {meta.retrieval.result_count} chunks ({meta.retrieval.search_mode})
              </span>
            )}
            {meta.latency_ms && (
              <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <Clock size={12} />
                {Math.round(meta.latency_ms)}ms total
              </span>
            )}
            {meta.usage?.total_tokens && (
              <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <Cpu size={12} />
                {meta.usage.total_tokens} tokens
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
