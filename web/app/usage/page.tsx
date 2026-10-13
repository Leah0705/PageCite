import { Suspense } from "react";
import Nav from "@/components/nav";
import UsageClient from "./UsageClient";

export default function UsagePage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Nav />
      <main className="flex-1 max-w-3xl mx-auto w-full px-4 py-10">
        <Suspense fallback={<p className="text-muted-foreground text-sm">Loading…</p>}>
          <UsageClient />
        </Suspense>
      </main>
      <footer className="border-t border-border py-6 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} PageCite
      </footer>
    </div>
  );
}
