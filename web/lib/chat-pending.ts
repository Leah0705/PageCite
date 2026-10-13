const KEY = "pagecite:pending_chat";

export interface PendingChat {
  sessionId: string;
  docName: string;
  messageCount: number;
  sentAt: string;
}

export function setPendingChat(p: PendingChat): void {
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch {}
}

export function clearPendingChat(): void {
  try { localStorage.removeItem(KEY); } catch {}
}

export function getPendingChat(): PendingChat | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as PendingChat) : null;
  } catch { return null; }
}
