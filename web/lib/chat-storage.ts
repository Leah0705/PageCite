import type { Citation, ToolUsage } from "./api";

export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  tool_usage?: ToolUsage | null;
  duration_ms?: number;
  interrupted?: boolean;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
  from_cache?: boolean;
}

export interface ChatSession {
  id: string;
  doc_id: string;
  doc_name: string;
  messages: StoredMessage[];
  created_at: string;
  updated_at: string;
}

function storageKey(userId: string) {
  return userId ? `pagecite_chats_${userId}` : "pagecite_chats";
}

function sortByRecent(sessions: ChatSession[]): ChatSession[] {
  return [...sessions].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  );
}

export function loadSessions(userId: string): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw: ChatSession[] = JSON.parse(localStorage.getItem(storageKey(userId)) ?? "[]");
    return sortByRecent(raw);
  } catch {
    return [];
  }
}

export function saveSessions(sessions: ChatSession[], userId: string): void {
  localStorage.setItem(storageKey(userId), JSON.stringify(sessions));
}

export function createSession(doc_id: string, doc_name: string): ChatSession {
  return {
    id: crypto.randomUUID(),
    doc_id,
    doc_name,
    messages: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

export function upsertSession(
  sessions: ChatSession[],
  updated: ChatSession,
  userId: string
): ChatSession[] {
  const idx = sessions.findIndex((s) => s.id === updated.id);
  const merged = idx >= 0
    ? sessions.map((s, i) => (i === idx ? updated : s))
    : [updated, ...sessions];
  const next = sortByRecent(merged);
  saveSessions(next, userId);
  return next;
}

export function deleteSession(
  sessions: ChatSession[],
  id: string,
  userId: string
): ChatSession[] {
  const next = sessions.filter((s) => s.id !== id);
  saveSessions(next, userId);
  return next;
}
