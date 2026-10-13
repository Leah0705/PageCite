"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import { Key, Plus, Trash2, Copy, Eye, EyeOff, Check, Terminal, Globe } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  listApiKeys,
  createApiKey,
  revokeApiKey,
  type ApiKeyRecord,
  type ApiKeyCreated,
} from "@/lib/api";

const CLAUDE_CONFIG = `{
  "mcpServers": {
    "pagecite": {
      "command": "/absolute/path/to/pagecite/.venv/bin/python3",
      "args": ["-m", "mcp_server"],
      "env": {
        "PAGECITE_API_KEY": "pc_YOUR_KEY_HERE",
        "DATABASE_URL": "postgresql://pagecite:pagecite@localhost:5432/pagecite",
        "PYTHONPATH": "/absolute/path/to/pagecite"
      }
    }
  }
}`;

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function CopyBlock({ content, label }: { content: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="relative group">
      {label && <p className="text-xs font-medium text-muted-foreground mb-1">{label}</p>}
      <pre className="bg-muted rounded-md p-3 text-xs overflow-x-auto pr-10 whitespace-pre-wrap break-all">{content}</pre>
      <button
        onClick={copy}
        className="absolute top-2 right-2 p-1.5 rounded-md bg-muted-foreground/10 hover:bg-muted-foreground/20 transition-colors text-muted-foreground hover:text-foreground"
        title="Copy"
      >
        {copied ? <Check className="size-3.5 text-green-500" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}

export default function ApiKeysClient() {
  const { getToken } = useAuth();
  const [keys, setKeys] = useState<ApiKeyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<ApiKeyCreated | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [keyCopied, setKeyCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      setKeys(await listApiKeys(token ?? undefined));
    } catch {
      toast.error("Failed to load API keys");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  async function handleCreate(e: { preventDefault(): void }) {
    e.preventDefault();
    const name = newName.trim() || "Default";
    setCreating(true);
    try {
      const token = await getToken();
      const created = await createApiKey(name, token ?? undefined);
      setNewKey(created);
      setNewName("");
      setRevealed(false);
      setKeyCopied(false);
      await load();
    } catch {
      toast.error("Failed to create API key");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(keyId: string, keyName: string) {
    if (!confirm(`Revoke "${keyName}"? This cannot be undone.`)) return;
    try {
      const token = await getToken();
      await revokeApiKey(keyId, token ?? undefined);
      toast.success("Key revoked");
      await load();
    } catch {
      toast.error("Failed to revoke key");
    }
  }

  function copyKey(key: string) {
    navigator.clipboard.writeText(key);
    setKeyCopied(true);
    setTimeout(() => setKeyCopied(false), 2000);
    toast.success("Copied to clipboard");
  }

  function closeDialog() {
    setNewKey(null);
    setRevealed(false);
    setKeyCopied(false);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">API Keys</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Generate keys to connect Claude Desktop or Cursor to your PageCite library via the MCP server.
        </p>
      </div>

      {/* Generate form */}
      <Card className="p-5">
        <form onSubmit={handleCreate} className="flex gap-3">
          <Input
            placeholder="Key name (e.g. Claude Desktop)"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="flex-1"
            maxLength={80}
          />
          <Button type="submit" disabled={creating} className="shrink-0">
            <Plus className="size-4 mr-1.5" />
            {creating ? "Generating…" : "Generate key"}
          </Button>
        </form>
      </Card>

      {/* Keys list */}
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : keys.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
          <Key className="size-10 opacity-30" />
          <p className="text-sm">No API keys yet. Generate one above.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {keys.map((k) => (
            <Card key={k.id} className="px-4 py-3 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="font-medium text-sm truncate">{k.name}</p>
                <p className="text-xs text-muted-foreground">
                  Created {formatDate(k.created_at)}
                  {k.last_used_at ? ` · Last used ${formatDate(k.last_used_at)}` : " · Never used"}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="text-destructive hover:text-destructive hover:bg-destructive/10 shrink-0"
                onClick={() => handleRevoke(k.id, k.name)}
              >
                <Trash2 className="size-4" />
              </Button>
            </Card>
          ))}
        </div>
      )}

      {/* MCP Setup Guide */}
      <div className="space-y-5">
        <h2 className="text-base font-semibold">MCP Setup Guide</h2>

        <div className="space-y-6">
          {/* Step 1 */}
          <div className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-xs font-bold mt-0.5">1</span>
            <div className="space-y-1.5 flex-1">
              <p className="text-sm font-medium">Start PageCite</p>
              <CopyBlock content="docker compose up --build" />
            </div>
          </div>

          {/* Step 2 */}
          <div className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-xs font-bold mt-0.5">2</span>
            <div className="space-y-1 flex-1">
              <p className="text-sm font-medium">Generate an API key</p>
              <p className="text-xs text-muted-foreground">Use the form above. The key is shown only once, copy it immediately after generation.</p>
            </div>
          </div>

          {/* Step 3: Claude Desktop */}
          <div className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-xs font-bold mt-0.5">3</span>
            <div className="space-y-2 flex-1">
              <div className="flex items-center gap-2">
                <Terminal className="size-4 text-primary" />
                <p className="text-sm font-medium">Configure Claude Desktop</p>
              </div>
              <ol className="text-xs text-muted-foreground space-y-1 list-decimal list-inside">
                <li>Click the Claude menu in your menu bar (macOS) or system tray (Windows) and select <strong className="text-foreground">Settings</strong>.</li>
                <li>Navigate to the <strong className="text-foreground">Developer</strong> tab and click <strong className="text-foreground">Edit Config</strong>.</li>
                <li>Add the following under the <code className="bg-muted px-1 rounded">mcpServers</code> key and save:</li>
              </ol>
              <CopyBlock content={CLAUDE_CONFIG} />
              <div className="rounded-md border border-amber-500/25 bg-amber-500/5 px-3 py-2.5 text-xs text-muted-foreground space-y-1.5">
                <p>
                  Replace every <code className="bg-muted px-1 rounded">/absolute/path/to/pagecite</code> with your
                  actual repo path, e.g. <code className="bg-muted px-1 rounded">/Users/you/projects/pagecite</code>.
                  Both <code className="bg-muted px-1 rounded">command</code> and <code className="bg-muted px-1 rounded">PYTHONPATH</code> need it.
                </p>
                <p>
                  Use the project&apos;s <strong className="text-foreground">venv Python</strong>{" "}
                  (<code className="bg-muted px-1 rounded">.venv/bin/python3</code>). Claude Desktop runs processes
                  with a minimal PATH, a bare <code className="bg-muted px-1 rounded">python</code> won&apos;t be found.
                </p>
                <p>Replace <code className="bg-muted px-1 rounded">pc_YOUR_KEY_HERE</code> with the key from step 2.</p>
              </div>
              <p className="text-xs text-muted-foreground">
                <strong className="text-foreground">Completely restart</strong> Claude Desktop to apply the changes.
                The <code className="bg-muted px-1 rounded">search_documents</code>,{" "}
                <code className="bg-muted px-1 rounded">list_documents</code>, and{" "}
                <code className="bg-muted px-1 rounded">get_document</code> tools will appear automatically.
              </p>
            </div>
          </div>

          {/* Step 4: Cursor */}
          <div className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-xs font-bold mt-0.5">4</span>
            <div className="space-y-2 flex-1">
              <div className="flex items-center gap-2">
                <Globe className="size-4 text-primary" />
                <p className="text-sm font-medium">Cursor (HTTP/SSE, optional)</p>
              </div>
              <p className="text-xs text-muted-foreground">In Cursor Settings → MCP, add a new server:</p>
              <div className="space-y-2">
                <CopyBlock label="Server URL" content="http://localhost:8000/mcp/sse" />
                <CopyBlock label="Header (X-API-Key)" content="pc_YOUR_KEY_HERE" />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* New key dialog */}
      <Dialog open={!!newKey} onOpenChange={(open) => { if (!open) closeDialog(); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Key className="size-4 text-primary" />
              Your new API key
            </DialogTitle>
          </DialogHeader>

          <p className="text-sm text-muted-foreground -mt-1">
            Copy it now, it won&apos;t be shown again.
          </p>

          <div className="rounded-lg border border-border bg-muted/40 p-3">
            <div className="flex items-start gap-2">
              <code className="flex-1 font-mono text-xs text-foreground break-all leading-relaxed">
                {revealed
                  ? newKey?.key
                  : "pc_" + "•".repeat(Math.max(0, (newKey?.key?.length ?? 46) - 3))}
              </code>
              <div className="flex shrink-0 flex-col gap-0.5">
                <button
                  onClick={() => setRevealed((v) => !v)}
                  className="p-1.5 rounded-md hover:bg-muted-foreground/15 transition-colors text-muted-foreground hover:text-foreground"
                  title={revealed ? "Hide" : "Reveal"}
                >
                  {revealed ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                </button>
                <button
                  onClick={() => newKey && copyKey(newKey.key)}
                  className="p-1.5 rounded-md hover:bg-muted-foreground/15 transition-colors text-muted-foreground hover:text-foreground"
                  title="Copy"
                >
                  {keyCopied ? <Check className="size-3.5 text-green-500" /> : <Copy className="size-3.5" />}
                </button>
              </div>
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            Use this as <code className="bg-muted px-1 rounded">PAGECITE_API_KEY</code> in your Claude Desktop config.
          </p>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => newKey && copyKey(newKey.key)}>
              {keyCopied
                ? <><Check className="size-4 mr-1.5 text-green-500" />Copied!</>
                : <><Copy className="size-4 mr-1.5" />Copy key</>}
            </Button>
            <Button className="flex-1" onClick={closeDialog}>
              Done
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
