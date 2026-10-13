import { Suspense } from "react";
import Nav from "@/components/nav";
import ChatClient from "./ChatClient";

export default function ChatPage() {
  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Nav />
      <div className="flex flex-1 overflow-hidden">
        <Suspense fallback={<div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>}>
          <ChatClient />
        </Suspense>
      </div>
    </div>
  );
}
