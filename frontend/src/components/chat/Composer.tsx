import React, { useState, useRef, useEffect } from "react";
import { ArrowUp, Square, Database } from "lucide-react";

interface ComposerProps {
  onSendMessage: (message: string) => void;
  onStop: () => void;
  isLoading: boolean;
  disabled?: boolean;
  kbName?: string | null;
}

export const Composer: React.FC<ComposerProps> = ({
  onSendMessage,
  onStop,
  isLoading,
  disabled,
  kbName,
}) => {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [input]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading || disabled) return;
    if (input.trim().length > 2000) return;
    onSendMessage(input.trim());
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="composer-container">
      <form onSubmit={handleSubmit} className="composer-box">
        {kbName && (
          <div className="composer-scope">
            <Database size={12} />
            <span>Asking {kbName}</span>
            <span className="composer-scope-note">grounded answers only</span>
          </div>
        )}
        <textarea
          ref={textareaRef}
          className="composer-textarea"
          placeholder="Ask anything about your knowledge base..."
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || isLoading}
        />
        <div className="composer-actions">
          <span className="composer-hints">
            <span className="kbd">Enter</span> send · <span className="kbd">Shift+Enter</span> newline · {input.length}/2000
          </span>
          {isLoading ? (
            <button
              type="button"
              className="stop-btn"
              onClick={onStop}
              title="Stop generating"
            >
              <Square size={14} />
            </button>
          ) : (
            <button
              type="submit"
              className="send-btn"
              disabled={!input.trim() || input.trim().length > 2000 || disabled}
              title="Send message"
            >
              <ArrowUp size={18} />
            </button>
          )}
        </div>
      </form>
    </div>
  );
};
