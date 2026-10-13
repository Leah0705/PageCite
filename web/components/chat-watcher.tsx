"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import { fetchConversation } from "@/lib/api";
import { clearPendingChat, getPendingChat } from "@/lib/chat-pending";

const POLL_MS = 3000;

export default function ChatWatcher() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const pathname = usePathname();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const router = useRouter();

  useEffect(() => {
    // If user is on /chat they see results directly, no toast needed
    if (!isLoaded || !isSignedIn || pathname.startsWith("/chat")) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }

    async function check() {
      const pending = getPendingChat();
      if (!pending) {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        return;
      }

      try {
        const token = (await getToken()) ?? undefined;
        const msgs = await fetchConversation(pending.sessionId, token);
        const hasNewAnswer = msgs.some(
          (m) =>
            m.role === "assistant" &&
            m.created_at &&
            m.created_at > pending.sentAt
        );
        if (hasNewAnswer) {
          clearPendingChat();
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          toast.success(`Answer ready for "${pending.docName}"`, {
            duration: 10000,
            action: {
              label: "View",
              onClick: () => router.push(`/chat?session=${pending.sessionId}`),
            },
          });
        }
      } catch {
        // network errors are silent, watcher is best-effort
      }
    }

    check();
    if (!pollRef.current) {
      pollRef.current = setInterval(check, POLL_MS);
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [isLoaded, isSignedIn, pathname]);

  return null;
}
