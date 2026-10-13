import Nav from "@/components/nav";
import ApiKeysClient from "./ApiKeysClient";

export default function ApiKeysPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Nav />
      <main className="flex-1 max-w-3xl mx-auto w-full px-4 py-10">
        <ApiKeysClient />
      </main>
      <footer className="border-t border-border py-6 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} PageCite
      </footer>
    </div>
  );
}
