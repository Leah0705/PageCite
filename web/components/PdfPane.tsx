"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { ChevronLeftIcon, ChevronRightIcon, XIcon, FileTextIcon, AlertCircleIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

export interface PdfPaneProps {
  url: string | null;
  targetPage: number;
  snippet: string;
  /** Incremented by parent to force a jump even when page hasn't changed. */
  jumpKey: number;
  onClose: () => void;
  /** Hide the built-in toolbar close button when the parent provides its own. */
  hideClose?: boolean;
  /**
   * When set, only these page numbers are rendered (citation mode).
   * The toolbar hides prev/next arrows and shows a simplified label.
   */
  limitToPages?: number[];
}

const HIGHLIGHT_STYLE =
  'background:#FFE600;color:#1a1a1a;border-radius:2px;padding:0 2px;font-weight:inherit';

const norm = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();

// Trigram highlight: fires when any 3-word sequence from the snippet is found
// in a rolling window of recent text items. Highlights that item + ~N more.
function buildTextRenderer(snippet: string) {
  if (!snippet) return ({ str }: { str: string }) => str;

  const snWords = norm(snippet).split(' ').filter(Boolean);
  if (snWords.length < 3) return ({ str }: { str: string }) => str;

  const trigrams = new Set<string>();
  for (let i = 0; i < snWords.length - 2; i++) {
    trigrams.add(`${snWords[i]} ${snWords[i + 1]} ${snWords[i + 2]}`);
  }

  const buf: string[] = [];
  let runLeft = 0;

  return function customTextRenderer({ str }: { str: string }): string {
    if (!str.trim()) return str;
    const words = norm(str.trim()).split(' ').filter(Boolean);
    if (!words.length) return str;

    if (runLeft > 0) {
      runLeft--;
      buf.push(...words);
      if (buf.length > 8) buf.splice(0, buf.length - 8);
      return `<mark style="${HIGHLIGHT_STYLE}">${str}</mark>`;
    }

    const combined = [...buf.slice(-4), ...words];
    let hit = false;
    for (let i = 0; i <= combined.length - 3; i++) {
      if (trigrams.has(`${combined[i]} ${combined[i + 1]} ${combined[i + 2]}`)) {
        hit = true;
        break;
      }
    }

    buf.push(...words);
    if (buf.length > 8) buf.splice(0, buf.length - 8);

    if (hit) {
      runLeft = Math.max(3, Math.ceil(snWords.length / 5));
      return `<mark style="${HIGHLIGHT_STYLE}">${str}</mark>`;
    }

    return str;
  };
}

export default function PdfPane({ url, targetPage, snippet, jumpKey, onClose, hideClose = false, limitToPages }: PdfPaneProps) {
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(targetPage > 0 ? targetPage : 1);
  const [containerWidth, setContainerWidth] = useState(0);
  const [loadError, setLoadError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w > 0) setContainerWidth(w);
    });
    ro.observe(el);
    if (el.clientWidth > 0) setContainerWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    observerRef.current?.disconnect();
    if (!numPages || !scrollAreaRef.current) return;
    const root = scrollAreaRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        let best: { page: number; ratio: number } | null = null;
        for (const e of entries) {
          if (e.isIntersecting) {
            const page = Number((e.target as HTMLElement).dataset.page);
            if (page > 0 && (!best || e.intersectionRatio > best.ratio)) {
              best = { page, ratio: e.intersectionRatio };
            }
          }
        }
        if (best) setCurrentPage(best.page);
      },
      { root, threshold: [0.1, 0.5, 1.0] }
    );
    pageRefs.current.forEach((el) => { if (el) observer.observe(el); });
    observerRef.current = observer;
    return () => observer.disconnect();
  }, [numPages]);

  useEffect(() => {
    if (targetPage > 0 && numPages > 0) {
      const el = pageRefs.current[targetPage - 1];
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [targetPage, jumpKey, numPages]);

  useEffect(() => {
    setLoadError(false);
    setNumPages(0);
    pageRefs.current = [];
    observerRef.current?.disconnect();
  }, [url]);

  function scrollToPage(page: number) {
    if (!numPages) return;
    const p = Math.max(1, Math.min(numPages, page));
    const el = pageRefs.current[p - 1];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); scrollToPage(currentPage + 1); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); scrollToPage(currentPage - 1); }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [currentPage, numPages],
  );

  // Rebuild renderer when snippet or target page changes to reset highlight state
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const customTextRenderer = useCallback(buildTextRenderer(snippet), [snippet, targetPage]);

  function onLoadSuccess({ numPages: n }: { numPages: number }) {
    setNumPages(n);
    setLoadError(false);
    pageRefs.current = new Array(n).fill(null);
    const targetP = targetPage > 0 ? Math.min(targetPage, n) : 1;
    setCurrentPage(targetP);
    // Retry scrolling until the page element is in the DOM (converted PDFs
    // render more slowly than native PDFs).
    let attempts = 0;
    function tryScroll() {
      const el = pageRefs.current[targetP - 1];
      if (el) {
        el.scrollIntoView({ behavior: "auto", block: "start" });
      } else if (attempts++ < 8) {
        setTimeout(tryScroll, 150);
      }
    }
    setTimeout(tryScroll, 150);
  }

  if (!url) {
    return (
      <div className="flex flex-col h-full">
        <PdfToolbar currentPage={0} numPages={0} onPrev={() => {}} onNext={() => {}} onClose={onClose} hideClose={hideClose} citationMode={!!limitToPages} />
        <div className="flex flex-col items-center justify-center flex-1 gap-3 text-muted-foreground">
          <FileTextIcon className="size-10 opacity-20" />
          <p className="text-sm text-center px-6">Click any citation to view the source</p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex flex-col h-full outline-none focus-visible:ring-0"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <PdfToolbar
        currentPage={currentPage}
        numPages={numPages}
        onPrev={() => scrollToPage(currentPage - 1)}
        onNext={() => scrollToPage(currentPage + 1)}
        onClose={onClose}
        hideClose={hideClose}
        citationMode={!!limitToPages}
      />

      <div
        ref={scrollAreaRef}
        className="flex-1 overflow-y-auto bg-muted/30 flex flex-col items-center py-4 px-2 gap-4"
      >
        <Document
          key={url}
          file={url}
          onLoadSuccess={onLoadSuccess}
          onLoadError={() => setLoadError(true)}
          loading={
            <div className="flex items-center justify-center h-40 text-muted-foreground text-sm gap-2">
              <span className="animate-pulse">Loading PDF…</span>
            </div>
          }
          error={null}
        >
          {loadError ? (
            <div className="flex flex-col items-center gap-2 text-muted-foreground py-10 px-4 text-center">
              <AlertCircleIcon className="size-8 opacity-40" />
              <p className="text-sm">Could not load this PDF.</p>
              <p className="text-xs opacity-60">The document may have been deleted or re-uploaded.</p>
            </div>
          ) : numPages > 0 ? (
            Array.from({ length: numPages }, (_, i) => i + 1)
              .filter((pageNum) => !limitToPages || limitToPages.includes(pageNum))
              .map((pageNum) => (
                <div
                  key={pageNum}
                  ref={(el) => { pageRefs.current[pageNum - 1] = el; }}
                  data-page={pageNum}
                  className="shadow-lg ring-1 ring-border/30 shrink-0"
                >
                  <Page
                    pageNumber={pageNum}
                    width={containerWidth > 32 ? containerWidth - 32 : undefined}
                    renderTextLayer
                    renderAnnotationLayer
                    customTextRenderer={pageNum === targetPage ? customTextRenderer : undefined}
                    loading={
                      <div
                        style={{ width: containerWidth > 32 ? containerWidth - 32 : 400, height: 560 }}
                        className="flex items-center justify-center text-muted-foreground text-sm animate-pulse"
                      >
                        Rendering page {pageNum}…
                      </div>
                    }
                  />
                </div>
              ))
          ) : null}
        </Document>
      </div>
    </div>
  );
}

interface PdfToolbarProps {
  currentPage: number;
  numPages: number;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
  hideClose?: boolean;
  /** Hides prev/next navigation when showing only the cited page(s). */
  citationMode?: boolean;
}

function PdfToolbar({ currentPage, numPages, onPrev, onNext, onClose, hideClose = false, citationMode = false }: PdfToolbarProps) {
  return (
    <div className="shrink-0 h-10 border-b border-border flex items-center px-2 gap-1 bg-background/80 backdrop-blur-sm">
      {!citationMode && (
        <Button variant="ghost" size="icon" className="size-7" onClick={onPrev}
          disabled={currentPage <= 1} title="Previous page (←)">
          <ChevronLeftIcon className="size-4" />
        </Button>
      )}
      <span className="text-xs text-muted-foreground tabular-nums select-none min-w-[4rem] text-center">
        {currentPage > 0 ? (citationMode ? `p.${currentPage}` : `${currentPage} / ${numPages || "-"}`) : "-"}
      </span>
      {!citationMode && (
        <Button variant="ghost" size="icon" className="size-7" onClick={onNext}
          disabled={!numPages || currentPage >= numPages} title="Next page (→)">
          <ChevronRightIcon className="size-4" />
        </Button>
      )}
      <div className="flex-1" />
      {!hideClose && (
        <Button variant="ghost" size="icon" className="size-7" onClick={onClose} title="Close PDF pane">
          <XIcon className="size-4" />
        </Button>
      )}
    </div>
  );
}
