import { Send, ShieldCheck } from "lucide-react";
import { FormEvent, useRef } from "react";
import type { ChatResponse } from "../api/client";
import { SourcesPanel } from "./SourcesPanel";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
}

interface ChatWindowProps {
  messages: ChatMessage[];
  input: string;
  loading: boolean;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
}

export function ChatWindow({ messages, input, loading, onInputChange, onSubmit }: ChatWindowProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
    inputRef.current?.focus();
  }

  return (
    <section className="chat-shell">
      <div className="message-list">
        {messages.length === 0 ? (
          <div className="empty-state">
            <ShieldCheck size={32} aria-hidden="true" />
            <h2>Ragzor Assistant</h2>
          </div>
        ) : (
          messages.map((message, index) => (
            <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
              <div className="message-author">{message.role === "user" ? "Usuario" : "Ragzor"}</div>
              <p>{message.content}</p>
              {message.response?.used_rag ? <SourcesPanel sources={message.response.sources} /> : null}
            </article>
          ))
        )}
      </div>

      <form className="chat-input-row" onSubmit={handleSubmit}>
        <input
          ref={inputRef}
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder="Escribe tu consulta..."
          maxLength={1500}
          disabled={loading}
        />
        <button type="submit" disabled={loading || input.trim().length === 0} title="Enviar consulta">
          <Send size={17} aria-hidden="true" />
          <span>Enviar</span>
        </button>
      </form>
    </section>
  );
}
