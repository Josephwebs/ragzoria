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
  onConfirmation: (choice: "confirm" | "cancel") => void;
}

export function ChatWindow({ messages, input, loading, onInputChange, onSubmit, onConfirmation }: ChatWindowProps) {
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
              {message.response ? (
                <p className="tools-used">
                  <strong>Herramienta usada:</strong>{" "}
                  {message.response.tools_used.length
                    ? message.response.tools_used.join(", ")
                    : "Ninguna"}
                </p>
              ) : null}
              {message.response?.plan.length ? (
                <details className="plan">
                  <summary>Ver plan</summary>
                  <ol>{message.response.plan.map((step, stepIndex) => <li key={stepIndex}>{step}</li>)}</ol>
                </details>
              ) : null}
              {message.response?.used_rag ? <SourcesPanel sources={message.response.sources} /> : null}
              {message.response?.activity.length ? (
                <details className="activity">
                  <summary>Actividad</summary>
                  <ul>{message.response.activity.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul>
                </details>
              ) : null}
              {message.response?.needs_confirmation && index === messages.length - 1 ? (
                <div className="pending-card">
                  <strong>Accion pendiente</strong>
                  <span>{message.response.pending_action?.summary}</span>
                  <p>{message.response.pending_action?.details}</p>
                  <small>
                    Expira: {message.response.pending_action?.expires_at
                      ? new Date(message.response.pending_action.expires_at).toLocaleString()
                      : "sin fecha"}
                  </small>
                  <div className="confirmation-actions">
                    <button disabled={loading} onClick={() => onConfirmation("confirm")}>Confirmar ticket</button>
                    <button disabled={loading} onClick={() => onConfirmation("cancel")}>Cancelar</button>
                  </div>
                </div>
              ) : null}
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
