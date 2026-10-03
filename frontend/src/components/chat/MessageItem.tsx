import React, { useMemo, useState } from "react";
import { Bot, FileText, Cpu, Clock, Layers, Copy, Check, ShieldCheck, OctagonX, Zap } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
  const citations = message.message_metadata?.citations || [];
  const meta = message.message_metadata;
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
    } catch {
      // Clipboard API unavailable (permissions/HTTP) — fallback via selection
      const ta = document.createElement("textarea");
      ta.value = message.content;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  // Turn [1] / [1, 2] into markdown links so ReactMarkdown renders them
  // and our custom <a> turns them back into interactive pills.
  const markdownContent = useMemo(() => {
    if (isUser) return message.content;
    return message.content.replace(
      /\[(\d+(?:\s*,\s*\d+)*)\]/g,
      (_m, ids: string) =>
        ids
          .split(",")
          .map((s) => `[${s.trim()}](#citation-${s.trim()})`)
          .join(" ")
    );
  }, [message.content, isUser]);

  if (isUser) {
    return (
      <div className="message-wrapper">
        <div className="user-message">{message.content}</div>
      </div>
    );
  }

  return (
    <div className="message-wrapper">
      <div className="assistant-message">
        <div className="assistant-header">
          <div className="assistant-avatar">
            <Bot size={16} />
          </div>
          <span className="assistant-name">RAGForge</span>
          {meta?.groundedness !== undefined && meta?.groundedness !== null && (
            <span className="grounded-badge" title="Answer verified against retrieved sources">
              <ShieldCheck size={12} /> Grounded
            </span>
          )}
          {meta?.stopped && (
            <span className="stopped-badge" title="Generation was stopped early">
              <OctagonX size={12} /> Stopped
            </span>
          )}
          {meta?.model && (
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginLeft: "auto" }}>
              {meta.provider?.toUpperCase()} · {meta.model}
            </span>
          )}
        </div>

        <div className="message-content markdown-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => {
                const m = href?.match(/^#citation-(\d+)$/);
                if (m) {
                  const num = parseInt(m[1], 10);
                  return (
                    <button
                      className="citation-pill"
                      title={`View Source [${num}]`}
                      onClick={() => onOpenSource(citations, num)}
                    >
                      {children}
                    </button>
                  );
                }
                return (
                  <a href={href} target="_blank" rel="noreferrer">
                    {children}
                  </a>
                );
              },
            }}
          >
            {markdownContent}
          </ReactMarkdown>
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
            {meta.time_to_first_token_ms != null && (
              <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <Zap size={12} />
                {(meta.time_to_first_token_ms / 1000).toFixed(1)}s to first token
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

        {/* Message actions */}
        {!isStreaming && (
          <div className="message-actions">
            <button className="msg-action-btn" onClick={handleCopy} title="Copy answer">
              {copied ? <Check size={13} /> : <Copy size={13} />}
              <span>{copied ? "Copied" : "Copy"}</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
