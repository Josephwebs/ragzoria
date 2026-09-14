export interface Message { role: "user" | "assistant"; content: string }
export interface Source {
  source: string; tipo_fuente: string; categoria: string; seccion: string; fragment: string;
}
export interface ChatResponse { answer: string; used_rag: boolean; sources: Source[] }
const API = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export async function sendChat(message: string, history: Message[]): Promise<ChatResponse> {
  const response = await fetch(API + "/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history: history.slice(-6) })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo procesar el mensaje.");
  return data;
}
