import { RefreshCcw } from "lucide-react";
import { useState } from "react";
import { sendChat } from "./api/client";
import { ChatMessage, ChatWindow } from "./components/ChatWindow";

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit() {
    const message = input.trim();
    if (!message || loading) return;
    const history = messages.slice(-6).map(({ role, content }) => ({ role, content }));
    setInput("");
    setError("");
    setMessages(current => [...current, { role: "user", content: message }]);
    setLoading(true);
    try {
      const response = await sendChat(message, history);
      setMessages(current => [...current, { role: "assistant", content: response.answer, response }]);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Error desconocido");
      setMessages(current => current.slice(0, -1));
      setInput(message);
    } finally { setLoading(false); }
  }

  return <main className="app-layout">
    <header className="topbar">
      <h1>Ragzor Assistant</h1>
      <div className="topbar-actions">
        <span role="status">{loading ? "Consultando..." : "Listo"}</span>
        <button disabled={loading} title="Nueva conversacion" aria-label="Nueva conversacion"
          onClick={() => { setMessages([]); setError(""); setInput(""); }}>
          <RefreshCcw size={17} />
        </button>
      </div>
    </header>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="workspace">
      <ChatWindow messages={messages} input={input} loading={loading}
        onInputChange={setInput} onSubmit={handleSubmit} />
    </div>
  </main>;
}
