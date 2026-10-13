"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  SendIcon, Loader2Icon, BotIcon, UserIcon,
  PlusIcon, Trash2Icon, MessageSquareIcon, CopyIcon, CheckIcon,
  PanelRightOpenIcon, PanelRightCloseIcon, GlobeIcon, CalculatorIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useAuth, useUser } from "@clerk/nextjs";
import { toast } from "sonner";
import { chat, Citation, Doc, fetchConversation, getDocFileUrl, listDocs, type MetaEvent, type ToolUsage, type UsageEvent } from "@/lib/api";
import { clearPendingChat, setPendingChat } from "@/lib/chat-pending";
import {
  ChatSession,
  StoredMessage,
  createSession,
  deleteSession,
  loadSessions,
  upsertSession,
} from "@/lib/chat-storage";
import dynamic from "next/dynamic";

// Lazy-load PdfPane to avoid SSR issues with pdfjs
const PdfPane = dynamic(() => import("@/components/PdfPane"), { ssr: false });

interface LiveMessage extends StoredMessage {
  status?: string;
  streaming?: boolean;
}

interface ActivePdf {
  url: string;
  page: number;
  snippet: string;
  jumpKey: number;
  /** Pages to show. Undefined means all pages (full-doc mode). */
  limitToPages?: number[];
}


function uid() {
  return Math.random().toString(36).slice(2);
}

function hostnameOf(url?: string | null): string {
  if (!url) return "source";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 24);
  }
}

function isSafeHttpUrl(url?: string | null): boolean {
  if (!url) return false;
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function ChatClient() {
  const router = useRouter();
  const params = useSearchParams();
  const docParam = params.get("doc");
  const sessionParam = params.get("session");
  const { getToken, isLoaded, isSignedIn, userId } = useAuth();
  const { user } = useUser();
  const authTokenRef = useRef<string | undefined>(undefined);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [messages, setMessages] = useState<LiveMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [newChatOpen, setNewChatOpen] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [chatCost, setChatCost] = useState<number>(0);

  const [pdfOpen, setPdfOpen] = useState(false);
  const [activePdf, setActivePdf] = useState<ActivePdf | null>(null);

  const [webSourcesOpen, setWebSourcesOpen] = useState(false);
  const [webSources, setWebSources] = useState<ToolUsage["web_search"]["results"]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const cancelledRef = useRef(false);
  const isMountedRef = useRef(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeSessionRef = useRef<ChatSession | null>(null);
  const autoSaveRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Prevents duplicate session creation when docParam fires multiple effects
  const lastHandledDocParam = useRef<string | null>(null);

  // Track mount state so stream callbacks don't clear pendingChat on unmount
  // (the ChatWatcher needs to detect the answer and show the toast).
  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;

    const init = async () => {
      const t = await getToken();
      authTokenRef.current = t ?? undefined;

      const saved = loadSessions(userId ?? "");
      setSessions(saved);

      try {
        const data = await listDocs(authTokenRef.current);
        const indexed = data.filter((d) => d.indexed);
        setDocs(indexed);

        async function loadAndRecover(session: ChatSession) {
          setActiveId(session.id);
          activeSessionRef.current = session;
          let msgs: StoredMessage[] = session.messages;

          setMessages(msgs.map((m) => ({ ...m })));
          setChatCost(msgs.reduce((s, m) => s + (m.cost_usd ?? 0), 0));

          if (msgs.length > 0 && msgs[msgs.length - 1].role === "user") {
            setMessages((prev) => [
              ...prev,
              { id: uid(), role: "assistant" as const, content: "", streaming: true, status: "Recovering…" },
            ]);

            let lastDb = await fetchConversation(session.id, t ?? undefined).then((r) => r[r.length - 1]).catch(() => null);
            if (!lastDb || lastDb.role !== "assistant") {
              for (let i = 0; i < 8 && (!lastDb || lastDb.role !== "assistant"); i++) {
                await new Promise<void>((r) => setTimeout(r, 2000));
                const all = await fetchConversation(session.id, t ?? undefined).catch(() => []);
                lastDb = all[all.length - 1] ?? null;
              }
            }

            if (lastDb?.role === "assistant") {
              const recovered: StoredMessage = {
                id: uid(), role: "assistant",
                content: lastDb.content, citations: lastDb.citations, tool_usage: lastDb.tool_usage,
                tokens_in: lastDb.tokens_in, tokens_out: lastDb.tokens_out, cost_usd: lastDb.cost_usd,
              };
              msgs = [...msgs, recovered];
              const updated = { ...session, messages: msgs, updated_at: new Date().toISOString() };
              activeSessionRef.current = updated;
              setSessions((prev) => upsertSession(prev, updated, userId ?? ""));
              setMessages(msgs.map((m) => ({ ...m })));
              setChatCost(msgs.reduce((s, m) => s + (m.cost_usd ?? 0), 0));
              clearPendingChat();
            } else {
              setMessages(msgs.map((m) => ({ ...m })));
            }
          }
        }

        if (docParam) {
          const doc = indexed.find((d) => d.doc_id === docParam);
          if (doc) {
            lastHandledDocParam.current = docParam;
            const session = createSession(doc.doc_id, doc.filename);
            setSessions((prev) => {
              const next = [session, ...prev];
              upsertSession(prev, session, userId ?? "");
              return next;
            });
            setActiveId(session.id);
            activeSessionRef.current = session;
            setChatCost(0);
            router.replace(`/chat?session=${session.id}`);
          }
        } else if (sessionParam) {
          const session = saved.find((s) => s.id === sessionParam);
          if (session) {
            await loadAndRecover(session);
          }
        }
      } catch {}
    };

    init();
  }, [isLoaded, isSignedIn]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // Handle ?doc= param changes, including when user navigates from /docs to /chat
  // while already on the /chat page (init effect won't re-run in that case).
  useEffect(() => {
    if (!docParam) {
      lastHandledDocParam.current = null;
      return;
    }
    if (!isLoaded || !isSignedIn) return;
    if (lastHandledDocParam.current === docParam) return;
    if (!docs.length) return;

    lastHandledDocParam.current = docParam;
    const doc = docs.find((d) => d.doc_id === docParam);
    if (!doc) return;

    const session = createSession(doc.doc_id, doc.filename);
    setSessions((prev) => {
      upsertSession(prev, session, userId ?? "");
      return [session, ...prev];
    });
    setActiveId(session.id);
    activeSessionRef.current = session;
    setMessages([]);
    setChatCost(0);
    router.replace(`/chat?session=${session.id}`);
  }, [docParam, docs, isLoaded, isSignedIn]);

  const activeSession = sessions.find((s) => s.id === activeId) ?? null;

  // Poll DB until the assistant message lands (handles race where stream
  // completes just after the user navigates back to the chat page).
  async function pollForAnswer(sessionId: string, attempts = 8, delayMs = 2000) {
    for (let i = 0; i < attempts; i++) {
      if (i > 0) await new Promise<void>((r) => setTimeout(r, delayMs));
      const dbMsgs = await fetchConversation(sessionId, authTokenRef.current);
      const last = dbMsgs[dbMsgs.length - 1];
      if (last?.role === "assistant") return last;
    }
    return null;
  }

  async function openSession(session: ChatSession) {
    // Silence any in-flight stream callbacks but don't abort. Let the backend
    // finish so it writes to DB, recovery polling will find the response.
    cancelledRef.current = true;
    setStreaming(false);
    setPdfOpen(false);
    setActivePdf(null);
    setActiveId(session.id);
    activeSessionRef.current = session;
    let msgs: StoredMessage[] = session.messages;

    setMessages(msgs.map((m) => ({ ...m })));
    setChatCost(msgs.reduce((s, m) => s + (m.cost_usd ?? 0), 0));
    router.replace(`/chat?session=${session.id}`);

    if (msgs.length > 0 && msgs[msgs.length - 1].role === "user") {
      const placeholderId = uid();
      setMessages((prev) => [
        ...prev,
        { id: placeholderId, role: "assistant" as const, content: "", streaming: true, status: "Recovering…" },
      ]);

      const lastDb = await pollForAnswer(session.id);
      if (lastDb) {
        const recovered: StoredMessage = {
          id: uid(),
          role: "assistant",
          content: lastDb.content,
          citations: lastDb.citations,
          tool_usage: lastDb.tool_usage,
          tokens_in: lastDb.tokens_in,
          tokens_out: lastDb.tokens_out,
          cost_usd: lastDb.cost_usd,
        };
        msgs = [...msgs, recovered];
        const updated = { ...session, messages: msgs, updated_at: new Date().toISOString() };
        activeSessionRef.current = updated;
        setSessions((prev) => upsertSession(prev, updated, userId ?? ""));
        setMessages(msgs.map((m) => ({ ...m })));
        setChatCost(msgs.reduce((s, m) => s + (m.cost_usd ?? 0), 0));
      } else {
        setMessages(msgs.map((m) => ({ ...m })));
      }
    }
    cancelledRef.current = false;
  }

  function startNewChat(doc: Doc) {
    cancelledRef.current = true;
    setStreaming(false);
    setPdfOpen(false);
    setActivePdf(null);
    const session = createSession(doc.doc_id, doc.filename);
    setSessions((prev) => {
      const next = [session, ...prev];
      upsertSession(prev, session, userId ?? "");
      return next;
    });
    setActiveId(session.id);
    activeSessionRef.current = session;
    setMessages([]);
    setChatCost(0);
    setNewChatOpen(false);
    router.replace(`/chat?session=${session.id}`);
  }

  function removeSession(id: string, name: string) {
    if (!confirm(`Delete chat "${name}"? This cannot be undone.`)) return;
    setSessions((prev) => deleteSession(prev, id, userId ?? ""));
    if (activeId === id) {
      setActiveId(null);
      activeSessionRef.current = null;
      setMessages([]);
      router.replace("/chat");
    }
  }

  async function openCitation(citation: Citation, docId: string) {
    if (citation.source === "web" && isSafeHttpUrl(citation.url)) {
      window.open(citation.url!, "_blank", "noopener,noreferrer");
      return;
    }

    const rawUrl = getDocFileUrl(docId);
    const freshToken = await getToken();
    authTokenRef.current = freshToken ?? undefined;
    const token = authTokenRef.current;
    const load = token
      ? fetch(rawUrl, { headers: { Authorization: `Bearer ${token}` } })
          .then((r) => r.blob())
          .then((b) => URL.createObjectURL(b))
      : Promise.resolve(rawUrl);

    const citedPage = citation.page > 0 ? citation.page : 1;
    load.then((url) => {
      setActivePdf((prev) => ({
        url,
        page: citedPage,
        snippet: citation.text ?? "",
        jumpKey: (prev?.jumpKey ?? 0) + 1,
        limitToPages: [citedPage],
      }));
      setPdfOpen(true);
    });
  }

  const persistMessages = useCallback(
    (msgs: StoredMessage[]) => {
      const session = activeSessionRef.current;
      if (!session) return;
      const updated: ChatSession = {
        ...session,
        messages: msgs,
        updated_at: new Date().toISOString(),
      };
      activeSessionRef.current = updated;
      setSessions((prev) => upsertSession(prev, updated, userId ?? ""));
    },
    [userId]
  );

  const debouncedPersist = useCallback(
    (msgs: StoredMessage[]) => {
      if (autoSaveRef.current) clearTimeout(autoSaveRef.current);
      autoSaveRef.current = setTimeout(() => persistMessages(msgs), 600);
    },
    [persistMessages]
  );

  const updateLast = useCallback(
    (updater: (msg: LiveMessage) => LiveMessage) => {
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const next = [...prev];
        next[next.length - 1] = updater(next[next.length - 1]);
        return next;
      });
    },
    []
  );

  function toStored(msgs: LiveMessage[]): StoredMessage[] {
    return msgs.map(({ status: _s, streaming: _st, ...rest }) => rest);
  }

  function friendlyError(err: string): string {
    if (err.startsWith("429:")) {
      const secs = parseInt(err.slice(4), 10);
      const mins = Math.ceil(secs / 60);
      const label = secs >= 3600
        ? `${Math.ceil(secs / 3600)}h`
        : secs >= 60
          ? `${mins}m`
          : `${secs}s`;
      toast.warning(`Rate limit reached. Resets in ${label}.`, { duration: 10000 });
      return "Rate limit reached. Try again soon.";
    }
    if (err.includes("404") || err.toLowerCase().includes("not found"))
      return "Document not found. It may have been deleted.";
    if (err.includes("401") || err.includes("403"))
      return "Access denied. Check your API key.";
    if (err.includes("fetch") || err.includes("network"))
      return "Cannot reach the API. Is the backend running?";
    return err;
  }

  function stop() {
    cancelledRef.current = true;
    abortRef.current?.abort();
    if (autoSaveRef.current) clearTimeout(autoSaveRef.current);
    clearPendingChat();
    setStreaming(false);
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const next = [...prev];
      const last = next[next.length - 1];
      if (last.role === "assistant" && last.streaming) {
        next[next.length - 1] = { ...last, streaming: false, status: undefined, interrupted: true };
        persistMessages(toStored(next));
      }
      return next;
    });
  }

  function directReply(question: string): string | null {
    const q = question.toLowerCase().replace(/[?!.,]+$/, "").trim();
    const doc = activeSession?.doc_name ?? "this document";

    if (/^(hi|hello|hey|howdy|hiya|sup|yo|greetings|good\s*(morning|afternoon|evening))(\s|$)/.test(q))
      return `Hello! I'm PageCite, your AI assistant for ${doc}.\n\nAsk me anything about the document and I'll search it, verify my answer, and point you to the exact pages.`;

    if (/who are you|what are you|tell me about yourself|introduce yourself|what is pagecite/.test(q))
      return `I'm PageCite, a multi-agent assistant for your knowledge base.\n\nA LangGraph pipeline runs three agents in turn:\n- Researcher: hybrid search (pgvector + full-text + RRF), with web search and a calculator tool it calls when needed\n- Synthesizer: writes a cited answer from the retrieved chunks and tool results\n- Critic: checks the answer for hallucination, missing citations, and off-topic drift, sending it back for revision if needed\n\nCurrently loaded: ${doc}`;

    if (/what can you do|how can you help|what do you do|your capabilities|what can i ask|what kind of questions|what should i ask/.test(q))
      return `Here's what I can do with ${doc}:\n\n- Answer questions with page-level citations, click any badge to jump to the source\n- Search the web or run calculations when the document alone isn't enough (look for the Web or Calc badge)\n- Summarise sections, chapters, or the whole document\n- Extract specific data: tables, numbers, names, dates\n- Explain complex passages in plain language\n- Compare sections or identify contradictions\n- Find any topic, term, or concept mentioned in the document\n\nJust ask naturally and I'll figure out where to look.`;

    if (/^(help|how do i use (this|you)|how does this work|instructions|commands|getting started)/.test(q))
      return `How to use PageCite:\n\n1. Type your question in the box below and press Send or Enter\n2. I'll search the document, rerank results, generate an answer, and verify it\n3. Click the p.N citation badges under my answer to jump to that page in the PDF\n4. Use the panel icon (top right) to open the PDF side by side\n\nTips for better answers:\n- Be specific: "What does section 4 say about pricing?"\n- Ask for summaries: "Summarise the key findings"\n- Ask follow-ups: I remember the conversation context`;

    if (/^(thanks|thank you|thx|ty|cheers|great|awesome|perfect|nice)(\s|$)/.test(q))
      return `You're welcome! Feel free to ask anything else about ${doc}.`;

    return null;
  }

  async function send() {
    const question = input.trim();
    if (!question || !activeSession || streaming) return;

    const canned = directReply(question);
    if (canned) {
      setInput("");
      const userMsg: LiveMessage = { id: uid(), role: "user", content: question };
      const botMsg: LiveMessage = { id: uid(), role: "assistant", content: canned };
      setMessages((prev) => {
        const next = [...prev, userMsg, botMsg];
        persistMessages(toStored(next));
        return next;
      });
      return;
    }

    cancelledRef.current = false;
    setInput("");
    setStreaming(true);

    const freshToken = await getToken();
    authTokenRef.current = freshToken ?? undefined;

    const userMsg: LiveMessage = { id: uid(), role: "user", content: question };
    const assistantMsg: LiveMessage = {
      id: uid(), role: "assistant", content: "", streaming: true, status: "Thinking…",
    };

    let pendingMsgCount = 0;
    setMessages((prev) => {
      pendingMsgCount = prev.length;
      const next = [...prev, userMsg, assistantMsg];
      persistMessages(toStored(next.slice(0, -1)));
      return next;
    });
    setPendingChat({ sessionId: activeSession.id, docName: activeSession.doc_name, messageCount: pendingMsgCount, sentAt: new Date().toISOString() });

    abortRef.current = new AbortController();

    chat(
      { doc_id: activeSession.doc_id, question, session_id: activeSession.id },
      authTokenRef.current,
      (msg) => { if (!cancelledRef.current) updateLast((m) => ({ ...m, status: msg })); },
      (token) => {
        if (cancelledRef.current) return;
        setMessages((prev) => {
          if (prev.length === 0) return prev;
          const next = [...prev];
          next[next.length - 1] = {
            ...next[next.length - 1],
            content: next[next.length - 1].content + token,
            status: undefined,
          };
          debouncedPersist(toStored(next));
          return next;
        });
      },
      (citations) => { if (!cancelledRef.current) updateLast((m) => ({ ...m, citations })); },
      (duration_ms) => {
        if (cancelledRef.current) return;
        if (autoSaveRef.current) clearTimeout(autoSaveRef.current);
        // Only clear pending when still on the chat page. If the user navigated
        // away, leave it for ChatWatcher to detect and show a toast.
        if (isMountedRef.current) clearPendingChat();
        setMessages((prev) => {
          const next = prev.map((m, i) =>
            i === prev.length - 1
              ? { ...m, streaming: false, status: undefined, duration_ms }
              : m
          );
          persistMessages(toStored(next));
          return next;
        });
        setStreaming(false);
      },
      (err) => {
        if (cancelledRef.current) return;
        if (autoSaveRef.current) clearTimeout(autoSaveRef.current);
        if (isMountedRef.current) clearPendingChat();
        const msg = friendlyError(err);
        setMessages((prev) => {
          const next = prev.map((m, i) =>
            i === prev.length - 1
              ? { ...m, content: msg, streaming: false, status: undefined }
              : m
          );
          persistMessages(toStored(next));
          return next;
        });
        setStreaming(false);
      },
      abortRef.current.signal,
      (u: UsageEvent) => {
        if (cancelledRef.current) return;
        setChatCost((prev) => Math.round((prev + u.cost_usd) * 1e8) / 1e8);
        updateLast((m) => ({
          ...m,
          tokens_in: u.tokens_in,
          tokens_out: u.tokens_out,
          cost_usd: u.cost_usd,
        }));
      },
      (meta: MetaEvent) => {
        if (!cancelledRef.current && meta.from_cache)
          updateLast((m) => ({ ...m, from_cache: true }));
      },
      () => {
        if (!cancelledRef.current)
          toast.info("Personal information detected and redacted from your message.", { duration: 5000 });
      },
      (toolUsage: ToolUsage) => {
        if (cancelledRef.current) return;
        const used = toolUsage.web_search.used || toolUsage.calculator.used;
        if (!used) return;
        updateLast((m) => ({ ...m, tool_usage: toolUsage }));
      }
    );
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      <aside className="w-60 shrink-0 border-r border-border flex flex-col bg-background/50">
        <div className="p-3 border-b border-border">
          <Button size="sm" className="w-full gap-1.5" onClick={() => setNewChatOpen(true)}>
            <PlusIcon className="size-3.5" />
            New Chat
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {sessions.length === 0 ? (
            <p className="text-xs text-muted-foreground p-4 text-center">
              No chats yet. Start one above.
            </p>
          ) : (
            <div className="p-2 flex flex-col gap-0.5">
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className={`group relative rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
                    s.id === activeId
                      ? "bg-primary/15 text-foreground"
                      : "hover:bg-accent/50 text-muted-foreground hover:text-foreground"
                  }`}
                  onClick={() => void openSession(s)}
                >
                  <p className="text-xs font-medium truncate pr-5">{s.doc_name}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {s.messages.length > 0
                      ? s.messages[s.messages.length - 1].content.slice(0, 40) + "…"
                      : relativeTime(s.created_at)}
                  </p>
                  <button
                    className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                    onClick={(e) => { e.stopPropagation(); removeSession(s.id, s.doc_name); }}
                    title="Delete chat"
                  >
                    <Trash2Icon className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>

      <div className={`flex flex-col overflow-hidden transition-all duration-300 ${pdfOpen ? "flex-1" : "flex-1"}`}>
        {!activeSession ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-muted-foreground">
            <MessageSquareIcon className="size-10 opacity-20" />
            <p className="text-sm">Select a chat or start a new one.</p>
            <Button size="sm" onClick={() => setNewChatOpen(true)}>
              <PlusIcon className="size-3.5 mr-1.5" />
              New Chat
            </Button>
          </div>
        ) : (
          <>
            <div className="border-b border-border px-4 h-12 flex items-center gap-2 shrink-0 bg-background/80 backdrop-blur-sm">
              <span className="text-sm font-medium truncate flex-1">
                {activeSession.doc_name}
              </span>
              <span className="text-xs text-muted-foreground shrink-0">
                {messages.reduce((s, m) => s + (m.tokens_in ?? 0) + (m.tokens_out ?? 0), 0).toLocaleString()} tokens · ${(Math.round(chatCost * 10000) / 10000).toFixed(4)}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => {
                  setPdfOpen((o) => {
                    // Opening from the header button shows the full document.
                    if (!o) setActivePdf((prev) => prev ? { ...prev, limitToPages: undefined } : prev);
                    return !o;
                  });
                }}
                title={pdfOpen ? "Close document pane" : "Open document pane"}
              >
                {pdfOpen
                  ? <PanelRightCloseIcon className="size-4" />
                  : <PanelRightOpenIcon className="size-4" />
                }
              </Button>
            </div>

            <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6">
              {messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full min-h-[40vh] text-muted-foreground gap-2">
                  <p className="text-sm font-medium text-foreground">{activeSession.doc_name}</p>
                  <p className="text-xs">Ask anything about this document.</p>
                </div>
              ) : (
                <div className="max-w-3xl mx-auto flex flex-col gap-6">
                  <AnimatePresence initial={false}>
                    {messages.map((msg) => (
                      <motion.div
                        key={msg.id}
                        initial={{ opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.2, ease: "easeOut" as const }}
                        className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}
                      >
                        <Avatar className="size-7 shrink-0 mt-0.5">
                          {msg.role === "user" && user?.imageUrl && (
                            <AvatarImage src={user.imageUrl} alt="profile" />
                          )}
                          <AvatarFallback className={`text-[10px] ${msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-red-500/15 text-red-400"}`}>
                            {msg.role === "user"
                              ? <UserIcon className="size-3.5" />
                              : <BotIcon className="size-3.5" />
                            }
                          </AvatarFallback>
                        </Avatar>

                        <div className={`flex flex-col gap-1 max-w-[80%] ${msg.role === "user" ? "items-end" : "items-start"}`}>
                          <div className={`group/msg flex items-end gap-1.5 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}>
                            <div
                              className={`rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap break-words ${
                                msg.role === "user"
                                  ? "bg-primary text-primary-foreground rounded-tr-sm"
                                  : "bg-card border border-border rounded-tl-sm"
                              }`}
                            >
                              {msg.status && !msg.content ? (
                                <span className="flex items-center gap-2 text-muted-foreground italic text-xs">
                                  <Loader2Icon className="size-3 animate-spin shrink-0" />
                                  {msg.status}
                                </span>
                              ) : (
                                <>
                                  {msg.content}
                                  {msg.streaming && msg.content && (
                                    <span className="inline-block w-0.5 h-3.5 bg-current ml-0.5 animate-pulse rounded-full align-middle" />
                                  )}
                                  {msg.streaming && !msg.content && (
                                    <Loader2Icon className="size-3 animate-spin text-muted-foreground" />
                                  )}
                                  {/* Fallbacks for done state with no content */}
                                  {!msg.streaming && !msg.content && !msg.interrupted && (
                                    <span className="italic text-muted-foreground text-xs">No response was generated.</span>
                                  )}
                                  {!msg.streaming && !msg.content && msg.interrupted && (
                                    <span className="italic text-muted-foreground text-xs">Response interrupted. Try asking again.</span>
                                  )}
                                  {msg.interrupted && msg.content && !msg.streaming && (
                                    <span className="block text-xs text-muted-foreground mt-1 italic">(interrupted)</span>
                                  )}
                                </>
                              )}
                            </div>
                            {msg.content && !msg.streaming && (
                              <button
                                onClick={() => {
                                  navigator.clipboard.writeText(msg.content);
                                  setCopiedId(msg.id);
                                  setTimeout(() => setCopiedId((prev) => prev === msg.id ? null : prev), 2000);
                                }}
                                className="shrink-0 mb-1 opacity-0 group-hover/msg:opacity-100 transition-opacity p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent"
                                title="Copy"
                              >
                                {copiedId === msg.id
                                  ? <CheckIcon className="size-3 text-green-400" />
                                  : <CopyIcon className="size-3" />}
                              </button>
                            )}
                          </div>

                          {msg.citations && msg.citations.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 px-1">
                              {msg.citations.map((c: Citation, i: number) => (
                                <button
                                  key={i}
                                  title={c.source === "web" ? (c.url ?? "") : (c.text ?? `Page ${c.page}`)}
                                  onClick={() => void openCitation(c, activeSession.doc_id)}
                                  className="text-xs bg-primary/15 hover:bg-primary/30 text-primary px-2 py-0.5 rounded-full cursor-pointer border border-primary/20 hover:border-primary/50 transition-colors active:scale-95"
                                >
                                  {c.source === "web" ? hostnameOf(c.url) : `p.${c.page}`}
                                </button>
                              ))}
                            </div>
                          )}

                          {msg.tool_usage && (msg.tool_usage.web_search.used || msg.tool_usage.calculator.used) && (
                            <div className="flex flex-wrap gap-1.5 px-1">
                              {msg.tool_usage.web_search.used && (
                                <button
                                  onClick={() => {
                                    setWebSources(msg.tool_usage!.web_search.results);
                                    setWebSourcesOpen(true);
                                  }}
                                  title="View web sources"
                                  className="flex items-center gap-1 text-xs bg-accent/50 hover:bg-accent text-muted-foreground hover:text-foreground px-2 py-0.5 rounded-full cursor-pointer border border-border transition-colors active:scale-95"
                                >
                                  <GlobeIcon className="size-3" />
                                  Web ({msg.tool_usage.web_search.count})
                                </button>
                              )}
                              {msg.tool_usage.calculator.used && (
                                <span
                                  title={`${msg.tool_usage.calculator.expression} = ${msg.tool_usage.calculator.result}`}
                                  className="flex items-center gap-1 text-xs bg-accent/50 text-muted-foreground px-2 py-0.5 rounded-full border border-border"
                                >
                                  <CalculatorIcon className="size-3" />
                                  Calc
                                </span>
                              )}
                            </div>
                          )}

                          {(msg.duration_ms !== undefined || (msg.cost_usd !== undefined && msg.cost_usd > 0)) && (
                            <span className="text-xs text-muted-foreground px-1">
                              {msg.duration_ms !== undefined && (
                                <>
                                  {`Answered in ${(msg.duration_ms / 1000).toFixed(1)}s`}
                                  {msg.from_cache ? " from Cache" : ""}
                                </>
                              )}
                              {!msg.from_cache && msg.cost_usd !== undefined && msg.cost_usd > 0 && (
                                `${msg.duration_ms !== undefined ? " Costing " : ""}$${(Math.round(msg.cost_usd * 10000) / 10000).toFixed(4)} · ${((msg.tokens_in ?? 0) + (msg.tokens_out ?? 0)).toLocaleString()} tokens`
                              )}
                            </span>
                          )}
                        </div>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  <div ref={bottomRef} />
                </div>
              )}
            </div>

            <div className="border-t border-border px-4 py-3 shrink-0 bg-background/80 backdrop-blur-sm">
              <form
                className="max-w-3xl mx-auto flex gap-2"
                onSubmit={(e) => { e.preventDefault(); void send(); }}
              >
                <Input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={`Ask about ${activeSession.doc_name}…`}
                  disabled={streaming}
                  className="flex-1"
                />
                {streaming ? (
                  <Button
                    type="button"
                    size="icon-lg"
                    variant="destructive"
                    onClick={stop}
                    title="Stop generating"
                  >
                    <span className="block size-3 bg-current" />
                  </Button>
                ) : (
                  <Button type="submit" size="icon-lg" disabled={!input.trim()}>
                    <SendIcon />
                  </Button>
                )}
              </form>
            </div>
          </>
        )}
      </div>

      <AnimatePresence>
        {pdfOpen && (
          <motion.div
            key="pdf-pane"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: "50%", opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="shrink-0 border-l border-border flex flex-col overflow-hidden bg-background"
            style={{ minWidth: 0 }}
          >
            <PdfPane
              url={activePdf?.url ?? null}
              targetPage={activePdf?.page ?? 1}
              snippet={activePdf?.snippet ?? ""}
              jumpKey={activePdf?.jumpKey ?? 0}
              limitToPages={activePdf?.limitToPages}
              onClose={() => setPdfOpen(false)}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <Dialog open={newChatOpen} onOpenChange={setNewChatOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Choose a document</DialogTitle>
          </DialogHeader>
          {docs.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No indexed documents. Upload one in Documents first.
            </p>
          ) : (
            <div className="flex flex-col gap-1 max-h-72 overflow-y-auto">
              {docs.map((doc) => (
                <button
                  key={doc.doc_id}
                  className="text-left px-4 py-3 rounded-lg hover:bg-accent/50 transition-colors text-sm"
                  onClick={() => startNewChat(doc)}
                >
                  <p className="font-medium truncate">{doc.filename}</p>
                  <p className="text-xs text-muted-foreground font-mono break-all select-all">{doc.doc_id}</p>
                </button>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={webSourcesOpen} onOpenChange={setWebSourcesOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Web sources</DialogTitle>
          </DialogHeader>
          {webSources.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No sources recorded.</p>
          ) : (
            <div className="flex flex-col gap-1 max-h-72 overflow-y-auto">
              {webSources.map((r, i) =>
                isSafeHttpUrl(r.url) ? (
                  <a
                    key={i}
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-left px-4 py-3 rounded-lg hover:bg-accent/50 transition-colors text-sm"
                  >
                    <p className="font-medium truncate">{r.title || hostnameOf(r.url)}</p>
                    <p className="text-xs text-muted-foreground truncate">{r.url}</p>
                  </a>
                ) : (
                  <div key={i} className="px-4 py-3 rounded-lg text-sm opacity-60">
                    <p className="font-medium truncate">{r.title || hostnameOf(r.url)}</p>
                    <p className="text-xs text-muted-foreground truncate">{r.url}</p>
                  </div>
                )
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
