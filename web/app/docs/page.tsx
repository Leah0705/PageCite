"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import {
  UploadIcon,
  FileTextIcon,
  MessageSquareIcon,
  Loader2Icon,
  DatabaseIcon,
  Trash2Icon,
  CheckCircle2Icon,
  XCircleIcon,
  StopCircleIcon,
  RefreshCwIcon,
  CloudUploadIcon,
  CopyIcon,
  FileIcon,
  EyeIcon,
  XIcon,
  CoinsIcon,
  DownloadIcon,
} from "lucide-react";
import Nav from "@/components/nav";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@clerk/nextjs";
import { Doc, deleteDoc, getDocDownloadUrl, getDocFileUrl, listDocs, reindexDoc, stopDoc, uploadDoc } from "@/lib/api";
import { cn } from "@/lib/utils";
import dynamic from "next/dynamic";

const PdfPane = dynamic(() => import("@/components/PdfPane"), { ssr: false });

// Statuses that mean a background job is running or queued
const ACTIVE_STATUSES = new Set(["pending", "processing"]);

// Steps shown during ingestion, weights sum to 100 %
const PDF_STEPS = [
  { label: "Queued",     doneLabel: "Queued",     threshold: 0  },
  { label: "Parsing",    doneLabel: "Parsed",     threshold: 5  },
  { label: "Extracting", doneLabel: "Extracted",  threshold: 70 },
  { label: "Embedding",  doneLabel: "Embedded",   threshold: 80 },
  { label: "Finalizing", doneLabel: "Finalized",  threshold: 98 },
];

const DOCX_STEPS = [
  { label: "Queued",      doneLabel: "Queued",     threshold: 0  },
  { label: "Converting",  doneLabel: "Converted",  threshold: 5  },
  { label: "Parsing",     doneLabel: "Parsed",     threshold: 8  },
  { label: "Extracting",  doneLabel: "Extracted",  threshold: 70 },
  { label: "Embedding",   doneLabel: "Embedded",   threshold: 80 },
  { label: "Finalizing",  doneLabel: "Finalized",  threshold: 98 },
];

function getSteps(sourceType?: string) {
  return sourceType === "docx" ? DOCX_STEPS : PDF_STEPS;
}

function getCurrentStepIdx(pct: number, sourceType?: string): number {
  const steps = getSteps(sourceType);
  for (let i = steps.length - 1; i >= 0; i--) {
    if (pct >= steps[i].threshold) return i;
  }
  return 0;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric",
  });
}

// ── Source type badge ─────────────────────────────────────────────────────────

function SourceBadge({ sourceType }: { sourceType: string }) {
  if (sourceType === "docx") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-400/10 text-blue-400 text-[10px] font-medium uppercase tracking-wide">
        <FileIcon className="size-3" /> DOCX
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-red-400/10 text-red-400 text-[10px] font-medium uppercase tracking-wide">
      <FileTextIcon className="size-3" /> PDF
    </span>
  );
}

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case "indexed":
      return (
        <span className="inline-flex items-center gap-1 text-emerald-400 text-xs">
          <CheckCircle2Icon className="size-3" /> Ready
        </span>
      );
    case "failed":
      return (
        <span className="inline-flex items-center gap-1 text-destructive text-xs">
          <XCircleIcon className="size-3" /> Failed
        </span>
      );
    case "stopped":
      return (
        <span className="inline-flex items-center gap-1 text-orange-400 text-xs">
          <StopCircleIcon className="size-3" /> Stopped
        </span>
      );
    case "processing":
      return (
        <span className="inline-flex items-center gap-1 text-blue-400 text-xs">
          <Loader2Icon className="size-3 animate-spin" /> Processing
        </span>
      );
    case "uploading":
      return (
        <span className="inline-flex items-center gap-1 text-muted-foreground text-xs">
          <Loader2Icon className="size-3 animate-spin" /> Uploading
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 text-yellow-400 text-xs">
          <DatabaseIcon className="size-3" /> Queued
        </span>
      );
  }
}

// ── Smooth progress (bar + percentage counter share one animated value) ───────

function useSmoothedValue(real: number, sourceType?: string): number {
  const [display, setDisplay] = useState(real);
  const ref = useRef(real);

  useEffect(() => { ref.current = display; });

  useEffect(() => {
    const steps = getSteps(sourceType);
    const id = setInterval(() => {
      const cur = ref.current;
      if (cur < real) {
        const next = Math.min(cur + 0.5, real);
        ref.current = next;
        setDisplay(next);
        return;
      }
      // Creep toward next threshold - 1 while waiting for real progress
      const nextStep = steps.find(s => s.threshold > real);
      const cap = nextStep ? nextStep.threshold - 1 : real;
      if (cur < cap) {
        const next = Math.min(cur + 0.06, cap);
        ref.current = next;
        setDisplay(next);
      }
    }, 80);
    return () => clearInterval(id);
  }, [real, sourceType]);

  return display;
}

function StatusProgress({ status, value, sourceType }: { status: string; value: number; sourceType?: string }) {
  const display = useSmoothedValue(value, sourceType);
  const isUploading = status === "uploading";
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center w-full">
        <Loader2Icon className="size-3 animate-spin text-blue-400 shrink-0" />
        <span className="text-blue-400 text-xs ml-1">
          {isUploading ? "Uploading" : "Processing"}
        </span>
        {!isUploading && (
          <span className="text-xs text-muted-foreground tabular-nums ml-auto">
            {Math.floor(display)}%
          </span>
        )}
      </div>
      <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${display}%` }}
        />
      </div>
    </div>
  );
}

// ── Steps breakdown ──────────────────────────────────────────────────────────

function StepsBreakdown({ progress, status, sourceType }: { progress: number; status: string; sourceType?: string }) {
  const steps = getSteps(sourceType);
  const currentIdx = getCurrentStepIdx(progress, sourceType);
  const stopped = status === "stopped" || status === "failed";
  return (
    <div className="flex items-center flex-wrap gap-0.5 pt-0.5">
      {steps.map((s, i) => {
        const done = i < currentIdx;
        const active = i === currentIdx;
        const labelColor = done
          ? "text-emerald-400"
          : active && stopped
          ? "text-red-400"
          : active
          ? "text-yellow-400"
          : "text-muted-foreground/50";
        const arrowColor = done ? "text-emerald-500/70" : "text-muted-foreground/40";
        return (
          <span key={s.label} className="flex items-center gap-0.5">
            <span className={cn("text-xs leading-none font-medium", labelColor)}>
              {done ? `${s.doneLabel} ✓` : s.label}
            </span>
            {i < steps.length - 1 && (
              <span className={cn("text-xs leading-none", arrowColor)}>→</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

type FilterType = "all" | "pdf" | "docx";

// ── Page component ────────────────────────────────────────────────────────────

export default function DocsPage() {
  const router = useRouter();
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterType>("all");

  // File upload state
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  // Doc viewer state
  const [viewingDoc, setViewingDoc] = useState<Doc | null>(null);
  const [viewUrl, setViewUrl] = useState<string | null>(null);
  const [viewLoading, setViewLoading] = useState(false);

  const [optimisticDoc, setOptimisticDoc] = useState<Doc | null>(null);
  const [stopping, setStopping] = useState<Set<string>>(new Set());
  const [reindexing, setReindexing] = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);
  const prevStatusRef = useRef<Record<string, string>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchDocs(silent = false) {
    try {
      const token = (await getToken()) ?? undefined;
      const fetched = await listDocs(token);

      fetched.forEach((doc) => {
        const prev = prevStatusRef.current[doc.doc_id];
        if (prev && prev !== doc.status) {
          if (doc.status === "indexed") toast.success(`"${doc.filename}" is ready.`);
          else if (doc.status === "failed") toast.error(`"${doc.filename}" failed to process.`);
          else if (doc.status === "stopped") toast.info(`"${doc.filename}" was stopped.`);
        }
        prevStatusRef.current[doc.doc_id] = doc.status;
      });

      setDocs(fetched);
    } catch {
      if (!silent) toast.error("Could not reach the API. Is the backend running?");
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    const hasActive = docs.some((d) => ACTIVE_STATUSES.has(d.status));
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(() => fetchDocs(true), 2000);
    } else if (!hasActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {};
  }, [docs]);

  useEffect(() => {
    if (isLoaded && isSignedIn) fetchDocs();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isLoaded, isSignedIn]);

  async function handleViewDoc(doc: Doc) {
    setViewingDoc(doc);
    setViewUrl(null);
    setViewLoading(true);
    try {
      const token = (await getToken()) ?? undefined;
      const rawUrl = getDocFileUrl(doc.doc_id);
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(rawUrl, { headers });
      if (!res.ok) throw new Error("Failed to fetch");
      const blob = await res.blob();
      setViewUrl(URL.createObjectURL(blob));
    } catch {
      toast.error("Could not load document preview.");
      setViewingDoc(null);
    } finally {
      setViewLoading(false);
    }
  }

  async function handleDownload(doc: Doc) {
    try {
      const token = (await getToken()) ?? undefined;
      const rawUrl = getDocDownloadUrl(doc.doc_id);
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(rawUrl, { headers });
      if (!res.ok) throw new Error("Failed to fetch");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Download failed.");
    }
  }

  function closeViewer() {
    if (viewUrl) URL.revokeObjectURL(viewUrl);
    setViewingDoc(null);
    setViewUrl(null);
  }

  async function handleUpload() {
    if (!selectedFile) return;
    setUploading(true);

    const tempId = "__uploading__";
    setOptimisticDoc({
      doc_id: tempId,
      filename: selectedFile.name,
      uploaded_at: new Date().toISOString(),
      status: "uploading",
      indexed: false,
      source_type: selectedFile.name.toLowerCase().endsWith(".docx") ? "docx" : "pdf",
      progress_percent: 0,
    });
    setUploadOpen(false);
    setSelectedFile(null);

    try {
      const token = (await getToken()) ?? undefined;
      const uploaded = await uploadDoc(selectedFile, token);
      toast.success(`"${uploaded.filename}" queued for processing.`);
      await fetchDocs(true);
    } catch (err) {
      toast.error(String(err));
    } finally {
      setOptimisticDoc(null);
      setUploading(false);
    }
  }

  async function handleStop(doc: Doc) {
    setStopping((s) => new Set(s).add(doc.doc_id));
    try {
      const token = (await getToken()) ?? undefined;
      await stopDoc(doc.doc_id, token);
      await fetchDocs(true);
      toast.info(`"${doc.filename}" stopped.`);
    } catch (err) {
      toast.error(String(err));
    } finally {
      setStopping((s) => { const n = new Set(s); n.delete(doc.doc_id); return n; });
    }
  }

  async function handleReindex(doc: Doc) {
    setReindexing((s) => new Set(s).add(doc.doc_id));
    try {
      const token = (await getToken()) ?? undefined;
      await reindexDoc(doc.doc_id, token);
      await fetchDocs(true);
      toast.success(`"${doc.filename}" queued for reprocessing.`);
    } catch (err) {
      toast.error(String(err));
    } finally {
      setReindexing((s) => { const n = new Set(s); n.delete(doc.doc_id); return n; });
    }
  }

  async function handleDelete(doc: Doc) {
    if (!confirm(`Delete "${doc.filename}"? This cannot be undone.`)) return;
    try {
      const token = (await getToken()) ?? undefined;
      await deleteDoc(doc.doc_id, token);
      delete prevStatusRef.current[doc.doc_id];
      setDocs((prev) => prev.filter((d) => d.doc_id !== doc.doc_id));
      toast.success(`"${doc.filename}" deleted.`);
    } catch (err) {
      toast.error(String(err));
    }
  }

  const allDocs = optimisticDoc ? [optimisticDoc, ...docs] : docs;
  const displayDocs = filter === "all"
    ? allDocs
    : allDocs.filter((d) => (d.source_type ?? "pdf") === filter);

  return (
    <div className="flex flex-col min-h-screen">
      <Nav />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 60% 40% at 50% -5%, oklch(0.62 0.22 264 / 0.08), transparent)",
        }}
      />

      <main className="flex-1 max-w-6xl mx-auto w-full px-4 py-10">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold">Document Library</h1>
          <div className="flex items-center gap-2">
            <Button onClick={() => setUploadOpen(true)}>
              <UploadIcon />
              Upload File
            </Button>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex items-center justify-between mb-6">
          <div className="inline-flex rounded-lg border border-border p-1 gap-1">
            {(["all", "pdf", "docx"] as FilterType[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
                  filter === f
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted"
                )}
              >
                {f === "all" ? "All" : f.toUpperCase()}
              </button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {displayDocs.length} {displayDocs.length === 1 ? "Document" : "Documents"}
          </span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24 text-muted-foreground gap-2">
            <Loader2Icon className="animate-spin size-4" />
            Loading…
          </div>
        ) : displayDocs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-3">
            <FileTextIcon className="size-10 opacity-30" />
            <p className="text-sm">
              {filter === "all"
                ? "No documents yet. Upload a PDF or DOCX file to get started."
                : `No ${filter.toUpperCase()} documents yet.`}
            </p>
            {filter === "all" && (
              <Button variant="outline" onClick={() => setUploadOpen(true)}>
                Upload File
              </Button>
            )}
          </div>
        ) : (
          <motion.div
            initial="hidden"
            animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.07 } } }}
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
          >
            <AnimatePresence>
              {displayDocs.map((doc) => {
                const isActive = ACTIVE_STATUSES.has(doc.status);
                const isUploading = doc.status === "uploading";
                const canRecover = doc.status === "stopped" || doc.status === "failed";

                return (
                  <motion.div
                    key={doc.doc_id}
                    variants={{
                      hidden: { opacity: 0, y: 16 },
                      show: { opacity: 1, y: 0, transition: { duration: 0.25 } },
                    }}
                  >
                    <Card className="card-glow flex flex-col h-full">
                      <CardHeader className="pb-3">
                        <div className="flex items-start justify-between gap-2">
                          <CardTitle
                            className={cn(
                              "text-sm font-semibold leading-snug break-all",
                              doc.indexed && "cursor-pointer hover:text-primary transition-colors"
                            )}
                            title={doc.indexed ? "Click to preview" : doc.filename}
                            onClick={() => doc.indexed && handleViewDoc(doc)}
                          >
                            {doc.filename}
                          </CardTitle>
                          <SourceBadge sourceType={doc.source_type ?? "pdf"} />
                        </div>
                      </CardHeader>

                      <CardContent className="flex-1 pb-3 space-y-3">
                        <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs">
                          <dt className="text-muted-foreground font-medium">Added</dt>
                          <dd className="text-foreground">{formatDate(doc.uploaded_at)}</dd>
                          <dt className="text-muted-foreground font-medium">Doc ID</dt>
                          <dd>
                            {doc.doc_id === "__uploading__" ? (
                              <span className="text-muted-foreground font-mono">-</span>
                            ) : (
                              <button
                                className="group inline-flex items-center gap-1 text-muted-foreground font-mono break-all text-left hover:text-foreground transition-colors cursor-pointer"
                                onClick={() => {
                                  navigator.clipboard.writeText(doc.doc_id);
                                  toast.success("Doc ID copied.");
                                }}
                                title="Click to copy"
                              >
                                {doc.doc_id}
                                <CopyIcon className="size-2.5 shrink-0 opacity-0 group-hover:opacity-60 transition-opacity" />
                              </button>
                            )}
                          </dd>
                          {doc.page_count != null && (
                            <>
                              <dt className="text-muted-foreground font-medium">Pages</dt>
                              <dd className="text-foreground">{doc.page_count}</dd>
                            </>
                          )}
                          {doc.index_time_s != null && (
                            <>
                              <dt className="text-muted-foreground font-medium">Indexed in</dt>
                              <dd className="text-foreground">{doc.index_time_s}s</dd>
                            </>
                          )}
                          {doc.ingestion_cost_usd != null && doc.ingestion_cost_usd > 0 && (
                            <>
                              <dt className="text-muted-foreground font-medium flex items-center gap-1">
                                <CoinsIcon className="size-2.5" /> Ingest cost
                              </dt>
                              <dd className="text-foreground">
                                ${(Math.round(doc.ingestion_cost_usd * 10000) / 10000).toFixed(4)}
                                {doc.ingestion_tokens != null && (
                                  <span className="text-muted-foreground ml-1">
                                    ({doc.ingestion_tokens.toLocaleString()} tokens)
                                  </span>
                                )}
                              </dd>
                            </>
                          )}
                        </dl>

                        {/* Status: one line with bar+% when processing/uploading */}
                        {(doc.status === "processing" || isUploading) ? (
                          <StatusProgress
                            status={doc.status}
                            value={isUploading ? 0 : doc.progress_percent}
                            sourceType={doc.source_type}
                          />
                        ) : (
                          <StatusBadge status={doc.status} />
                        )}

                        {/* Step breakdown: active or stopped/failed */}
                        {(doc.status === "processing" || doc.status === "stopped" || doc.status === "failed") && (
                          <StepsBreakdown progress={doc.progress_percent} status={doc.status} sourceType={doc.source_type} />
                        )}
                      </CardContent>

                      <CardFooter className="gap-2">
                        {isUploading ? (
                          <Button size="sm" className="flex-1" disabled>
                            <CloudUploadIcon className="size-3.5" />
                            Uploading…
                          </Button>
                        ) : isActive ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="flex-1 text-destructive hover:text-destructive"
                            onClick={() => handleStop(doc)}
                            disabled={stopping.has(doc.doc_id)}
                          >
                            {stopping.has(doc.doc_id) ? (
                              <Loader2Icon className="size-3.5 animate-spin" />
                            ) : (
                              <StopCircleIcon className="size-3.5" />
                            )}
                            Stop
                          </Button>
                        ) : canRecover ? (
                          <>
                            <Button
                              size="sm"
                              className="flex-1"
                              onClick={() => handleReindex(doc)}
                              disabled={reindexing.has(doc.doc_id)}
                            >
                              {reindexing.has(doc.doc_id) ? (
                                <Loader2Icon className="size-3.5 animate-spin" />
                              ) : (
                                <RefreshCwIcon className="size-3.5" />
                              )}
                              Reindex
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="shrink-0 text-destructive hover:text-destructive"
                              onClick={() => handleDelete(doc)}
                              title="Delete document"
                            >
                              <Trash2Icon className="size-3.5" />
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              className="shrink-0"
                              disabled={!doc.indexed}
                              onClick={() => handleViewDoc(doc)}
                              title="Preview document"
                            >
                              <EyeIcon className="size-3.5 text-purple-400" />
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="shrink-0"
                              onClick={() => void handleDownload(doc)}
                              title="Download document"
                            >
                              <DownloadIcon className="size-3.5 text-blue-400" />
                            </Button>
                            <Button
                              size="sm"
                              className="flex-1"
                              disabled={!doc.indexed}
                              onClick={() => router.push(`/chat?doc=${doc.doc_id}&t=${Date.now()}`)}
                            >
                              <MessageSquareIcon />
                              Chat
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="shrink-0 text-destructive hover:text-destructive"
                              onClick={() => handleDelete(doc)}
                              title="Delete document"
                            >
                              <Trash2Icon className="size-3.5" />
                            </Button>
                          </>
                        )}
                      </CardFooter>
                    </Card>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </motion.div>
        )}
      </main>

      <footer className="border-t border-border py-6 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} PageCite
      </footer>

      {/* ── Document Viewer ────────────────────────────────────────────────── */}
      <AnimatePresence>
        {viewingDoc && (
          <motion.div
            key="doc-viewer"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex"
          >
            {/* Backdrop */}
            <div
              className="absolute inset-0 bg-black/60 backdrop-blur-sm"
              onClick={closeViewer}
            />
            {/* Panel */}
            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ duration: 0.25, ease: "easeInOut" }}
              className="relative ml-auto w-full max-w-3xl h-full bg-background border-l border-border flex flex-col shadow-2xl"
            >
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                  {(viewingDoc.source_type ?? "pdf") === "docx" ? (
                    <FileIcon className="size-4 text-blue-400 shrink-0" />
                  ) : (
                    <FileTextIcon className="size-4 text-red-400 shrink-0" />
                  )}
                  <span className="text-sm font-medium truncate">{viewingDoc.filename}</span>
                </div>
                <Button size="icon" variant="ghost" className="size-7 shrink-0" onClick={closeViewer}>
                  <XIcon className="size-3.5" />
                </Button>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-hidden">
                {viewLoading ? (
                  <div className="flex items-center justify-center h-full gap-2 text-muted-foreground">
                    <Loader2Icon className="animate-spin size-4" />
                    Loading…
                  </div>
                ) : viewUrl ? (
                  <PdfPane
                    url={viewUrl}
                    targetPage={1}
                    snippet=""
                    jumpKey={0}
                    onClose={closeViewer}
                    hideClose
                  />
                ) : null}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Upload File Dialog ─────────────────────────────────────────────── */}
      <Dialog
        open={uploadOpen}
        onOpenChange={(open) => {
          if (!uploading) { setUploadOpen(open); setSelectedFile(null); }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload a Document</DialogTitle>
            <DialogDescription>
              Supports PDF and DOCX files. The document will be queued for background processing.
            </DialogDescription>
          </DialogHeader>

          <div
            className="border-2 border-dashed border-border rounded-xl p-8 text-center cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors"
            onClick={() => !uploading && fileRef.current?.click()}
          >
            {selectedFile ? (
              <p className="text-sm font-medium">{selectedFile.name}</p>
            ) : (
              <>
                <FileTextIcon className="mx-auto size-8 text-muted-foreground mb-2 opacity-50" />
                <p className="text-sm text-muted-foreground">Click to select a PDF or DOCX file</p>
              </>
            )}
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx"
              className="hidden"
              onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
            />
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => { setUploadOpen(false); setSelectedFile(null); }}
              disabled={uploading}
            >
              Cancel
            </Button>
            <Button onClick={handleUpload} disabled={!selectedFile || uploading}>
              {uploading ? (
                <><Loader2Icon className="size-4 animate-spin mr-1" /> Uploading…</>
              ) : (
                "Upload"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  );
}
