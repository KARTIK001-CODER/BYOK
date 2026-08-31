import React, { useState, useRef, useEffect } from "react";
import { ArrowUp } from "lucide-react";

interface ComposerProps {
  onSendMessage: (message: string) => void;
  isLoading: boolean;
  disabled?: boolean;
}

export const Composer: React.FC<ComposerProps> = ({
  onSendMessage,
  isLoading,
  disabled,
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
          <span className="composer-hints">Press Enter to send, Shift + Enter for new line</span>
          <button
            type="submit"
            className="send-btn"
            disabled={!input.trim() || isLoading || disabled}
            title="Send message"
          >
            <ArrowUp size={18} />
          </button>
        </div>
      </form>
    </div>
  );
};
