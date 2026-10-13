import {
  ChatSession,
  createSession,
  deleteSession,
  loadSessions,
  saveSessions,
  upsertSession,
} from "@/lib/chat-storage";
import { clearPendingChat, getPendingChat, setPendingChat } from "@/lib/chat-pending";

function makeSession(overrides: Partial<ChatSession> = {}): ChatSession {
  return {
    id: crypto.randomUUID(),
    doc_id: "doc-1",
    doc_name: "test.pdf",
    messages: [],
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

beforeEach(() => localStorage.clear());

describe("chat-storage", () => {
  it("createSession returns a session with a unique id and empty messages", () => {
    const a = createSession("doc-1", "a.pdf");
    const b = createSession("doc-1", "a.pdf");
    expect(a.id).not.toBe(b.id);
    expect(a.doc_name).toBe("a.pdf");
    expect(a.messages).toEqual([]);
  });

  it("loadSessions returns [] when nothing is stored", () => {
    expect(loadSessions("user-1")).toEqual([]);
  });

  it("loadSessions returns [] on corrupted storage", () => {
    localStorage.setItem("pagecite_chats_user-1", "not-json{");
    expect(loadSessions("user-1")).toEqual([]);
  });

  it("saveSessions/loadSessions round-trips and sorts by most recent", () => {
    const older = makeSession({ updated_at: "2026-01-01T00:00:00.000Z" });
    const newer = makeSession({ updated_at: "2026-02-01T00:00:00.000Z" });
    saveSessions([older, newer], "user-1");
    const loaded = loadSessions("user-1");
    expect(loaded.map((s) => s.id)).toEqual([newer.id, older.id]);
  });

  it("sessions are isolated per user", () => {
    saveSessions([makeSession()], "user-1");
    expect(loadSessions("user-2")).toEqual([]);
  });

  it("upsertSession inserts a new session at the front", () => {
    const existing = makeSession({ updated_at: "2026-01-01T00:00:00.000Z" });
    const added = makeSession({ updated_at: "2026-03-01T00:00:00.000Z" });
    const next = upsertSession([existing], added, "user-1");
    expect(next.map((s) => s.id)).toEqual([added.id, existing.id]);
    expect(loadSessions("user-1")).toHaveLength(2);
  });

  it("upsertSession replaces an existing session by id", () => {
    const session = makeSession();
    const updated = { ...session, doc_name: "renamed.pdf" };
    const next = upsertSession([session], updated, "user-1");
    expect(next).toHaveLength(1);
    expect(next[0].doc_name).toBe("renamed.pdf");
  });

  it("deleteSession removes the session and persists the change", () => {
    const keep = makeSession();
    const drop = makeSession();
    saveSessions([keep, drop], "user-1");
    const next = deleteSession([keep, drop], drop.id, "user-1");
    expect(next.map((s) => s.id)).toEqual([keep.id]);
    expect(loadSessions("user-1").map((s) => s.id)).toEqual([keep.id]);
  });
});

describe("chat-pending", () => {
  const pending = {
    sessionId: "s-1",
    docName: "test.pdf",
    messageCount: 2,
    sentAt: "2026-01-01T00:00:00.000Z",
  };

  it("returns null when nothing is pending", () => {
    expect(getPendingChat()).toBeNull();
  });

  it("set/get round-trips a pending chat", () => {
    setPendingChat(pending);
    expect(getPendingChat()).toEqual(pending);
  });

  it("clearPendingChat removes the entry", () => {
    setPendingChat(pending);
    clearPendingChat();
    expect(getPendingChat()).toBeNull();
  });

  it("returns null on corrupted storage", () => {
    localStorage.setItem("pagecite:pending_chat", "{broken");
    expect(getPendingChat()).toBeNull();
  });
});
