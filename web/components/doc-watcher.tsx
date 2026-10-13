"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import { listDocs } from "@/lib/api";

const ACTIVE = new Set(["pending", "processing"]);
const POLL_MS = 3000;

export default function DocWatcher() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const pathname = usePathname();
  const prevStatuses = useRef<Record<string, string>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // DocsPage handles its own toasts, skip on that route
    if (!isLoaded || !isSignedIn || pathname.startsWith("/docs")) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }

    async function check() {
      try {
        const token = (await getToken()) ?? undefined;
        const docs = await listDocs(token);

        docs.forEach((doc) => {
          const prev = prevStatuses.current[doc.doc_id];
          if (prev && prev !== doc.status) {
            if (doc.status === "indexed") {
              toast.success(`"${doc.filename}" is ready to chat.`);
            } else if (doc.status === "failed") {
              toast.error(`"${doc.filename}" failed to process.`);
            } else if (doc.status === "stopped") {
              toast.info(`"${doc.filename}" indexing was stopped.`);
            }
          }
          prevStatuses.current[doc.doc_id] = doc.status;
        });

        const hasActive = docs.some((d) => ACTIVE.has(d.status));
        if (!hasActive && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
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
