export interface Source {
  source: string; tipo_fuente: string; categoria: string; seccion: string; fragment: string;
}
export interface PendingAction {
  id: string;
  type: "create_ticket";
  summary: string;
  details: string;
  expires_at: string;
  status: "pending";
}
export interface ChatResponse {
  answer: string;
  thread_id: string;
  used_rag: boolean;
  plan: string[];
  sources: Source[];
  needs_confirmation: boolean;
  pending_action: PendingAction | null;
  activity: string[];
  tools_used: string[];
}
const API = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export async function sendChat(
  message: string,
  threadId: string,
  userId: string,
  confirmation?: "confirm" | "cancel"
): Promise<ChatResponse> {
  const response = await fetch(API + "/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId, user_id: userId, confirmation })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo procesar el mensaje.");
  return data;
}
