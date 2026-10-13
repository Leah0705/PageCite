/**
 * Tests for /docs page: background ingestion UX:
 *   - Document cards render with correct status badges
 *   - Progress bar shown only for pending/processing docs
 *   - Chat button disabled while doc is not indexed
 *   - Simplified upload dialog (no SSE spinner, just Upload button)
 *   - Polling starts when active docs are present
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DocsPage from "@/app/docs/page";
import * as api from "@/lib/api";

// ── global mocks ─────────────────────────────────────────────────────────────

jest.mock("@clerk/nextjs", () => ({
  useAuth: () => ({
    getToken: async () => "test-token",
    isLoaded: true,
    isSignedIn: true,
  }),
}));

jest.mock("@/lib/api", () => ({
  listDocs: jest.fn(),
  uploadDoc: jest.fn(),
  deleteDoc: jest.fn(),
  indexDocStream: jest.fn(),
  getDocStatus: jest.fn(),
  stopDoc: jest.fn(),
  reindexDoc: jest.fn(),
}));

jest.mock("@/components/nav", () => () => <nav data-testid="nav" />);

// navigator.clipboard is not available in JSDOM
Object.defineProperty(navigator, "clipboard", {
  value: { writeText: jest.fn().mockResolvedValue(undefined) },
  writable: true,
});

// ── helpers ──────────────────────────────────────────────────────────────────

function makeDoc(overrides: Partial<api.Doc> = {}): api.Doc {
  return {
    doc_id: "doc-1",
    filename: "report.pdf",
    uploaded_at: "2025-01-15T10:00:00Z",
    status: "indexed",
    indexed: true,
    progress_percent: 100,
    ...overrides,
  };
}

// ── tests ────────────────────────────────────────────────────────────────────

describe("DocsPage: document card rendering", () => {
  beforeEach(() => jest.clearAllMocks());

  it("shows 'Ready' badge for an indexed document", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([makeDoc()]);
    await act(async () => { render(<DocsPage />); });
    expect(await screen.findByText("Ready")).toBeInTheDocument();
  });

  it("shows 'Queued' badge for a pending document", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "pending", indexed: false, progress_percent: 0 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    expect(await screen.findByText("Queued")).toBeInTheDocument();
  });

  it("shows 'Processing' badge for a processing document", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "processing", indexed: false, progress_percent: 45 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    expect(await screen.findByText("Processing")).toBeInTheDocument();
  });

  it("shows 'Failed' badge for a failed document", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "failed", indexed: false, progress_percent: 0 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    expect(await screen.findByText("Failed")).toBeInTheDocument();
  });

  it("shows progress percent for a processing doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "processing", indexed: false, progress_percent: 67 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    expect(await screen.findByText("67%")).toBeInTheDocument();
  });

  it("does not show progress percent for an indexed doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([makeDoc()]);
    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Ready");
    expect(screen.queryByText("100%")).not.toBeInTheDocument();
  });
});

describe("DocsPage: Chat button state", () => {
  beforeEach(() => jest.clearAllMocks());

  it("enables Chat for an indexed doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([makeDoc()]);
    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Ready");
    const chatBtn = screen.getByRole("button", { name: /chat/i });
    expect(chatBtn).not.toBeDisabled();
  });

  it("shows Stop button (not Chat) for a pending doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "pending", indexed: false, progress_percent: 0 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Queued");
    expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /chat/i })).not.toBeInTheDocument();
  });
});

describe("DocsPage: upload dialog", () => {
  beforeEach(() => jest.clearAllMocks());

  // Render with an existing doc so only the header "Upload File" button is present
  // (the empty-state button is hidden when docs.length > 0).

  it("opens upload dialog when Upload File button clicked", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([makeDoc()]);
    await act(async () => { render(<DocsPage />); });
    const uploadBtn = await screen.findByRole("button", { name: /upload file/i });
    await userEvent.click(uploadBtn);
    expect(screen.getByText(/upload a document/i)).toBeInTheDocument();
  });

  it("Upload button in dialog is disabled when no file selected", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([makeDoc()]);
    await act(async () => { render(<DocsPage />); });
    await userEvent.click(await screen.findByRole("button", { name: /upload file/i }));
    const submitBtn = screen.getByRole("button", { name: /^upload$/i });
    expect(submitBtn).toBeDisabled();
  });

  it("upload enqueues task and closes dialog without SSE streaming", async () => {
    (api.listDocs as jest.Mock)
      .mockResolvedValueOnce([makeDoc()])
      .mockResolvedValue([
        makeDoc(),
        makeDoc({ doc_id: "doc-new", status: "pending", indexed: false, progress_percent: 0 }),
      ]);
    (api.uploadDoc as jest.Mock).mockResolvedValue({
      doc_id: "doc-new",
      filename: "paper.pdf",
      status: "pending",
    });

    await act(async () => { render(<DocsPage />); });
    await userEvent.click(await screen.findByRole("button", { name: /upload file/i }));

    const file = new File(["content"], "paper.pdf", { type: "application/pdf" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);

    await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));

    await waitFor(() => {
      expect(api.uploadDoc).toHaveBeenCalledTimes(1);
    });

    // indexDocStream must NOT be called, ingestion is background now
    expect(api.indexDocStream).not.toHaveBeenCalled();
  });
});

describe("DocsPage: polling", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });
  afterEach(() => jest.useRealTimers());

  it("re-fetches docs every 2 s while a doc is pending", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "pending", indexed: false, progress_percent: 0 }),
    ]);

    await act(async () => { render(<DocsPage />); });
    await act(async () => { await Promise.resolve(); }); // flush initial fetch

    const callsBefore = (api.listDocs as jest.Mock).mock.calls.length;

    await act(async () => { jest.advanceTimersByTime(2000); });
    await act(async () => { await Promise.resolve(); });

    expect((api.listDocs as jest.Mock).mock.calls.length).toBeGreaterThan(callsBefore);
  });

  it("stops polling once all docs are indexed", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([makeDoc()]);

    await act(async () => { render(<DocsPage />); });
    await act(async () => { await Promise.resolve(); });

    const callsAfterFirstFetch = (api.listDocs as jest.Mock).mock.calls.length;

    await act(async () => { jest.advanceTimersByTime(6000); });
    await act(async () => { await Promise.resolve(); });

    // No additional polls, all docs already indexed
    expect((api.listDocs as jest.Mock).mock.calls.length).toBe(callsAfterFirstFetch);
  });
});

describe("DocsPage: Stop button", () => {
  beforeEach(() => jest.clearAllMocks());

  it("shows Stop button for a pending doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "pending", indexed: false, progress_percent: 0 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Queued");
    expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument();
  });

  it("shows Stop button for a processing doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "processing", indexed: false, progress_percent: 45 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Processing");
    expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument();
  });

  it("calls stopDoc and refreshes list when Stop is clicked", async () => {
    (api.listDocs as jest.Mock)
      .mockResolvedValueOnce([makeDoc({ status: "processing", indexed: false, progress_percent: 45 })])
      .mockResolvedValue([makeDoc({ status: "stopped", indexed: false, progress_percent: 0 })]);
    (api.stopDoc as jest.Mock).mockResolvedValue(undefined);

    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Processing");

    await userEvent.click(screen.getByRole("button", { name: /stop/i }));

    await waitFor(() => expect(api.stopDoc).toHaveBeenCalledTimes(1));
    await screen.findByText("Stopped");
  });

  it("does not show Stop button for an indexed doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([makeDoc()]);
    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Ready");
    expect(screen.queryByRole("button", { name: /stop/i })).not.toBeInTheDocument();
  });
});

describe("DocsPage: Reindex button", () => {
  beforeEach(() => jest.clearAllMocks());

  it("shows Reindex button for a stopped doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "stopped", indexed: false, progress_percent: 0 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Stopped");
    expect(screen.getByRole("button", { name: /reindex/i })).toBeInTheDocument();
  });

  it("shows Reindex button for a failed doc", async () => {
    (api.listDocs as jest.Mock).mockResolvedValue([
      makeDoc({ status: "failed", indexed: false, progress_percent: 0 }),
    ]);
    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Failed");
    expect(screen.getByRole("button", { name: /reindex/i })).toBeInTheDocument();
  });

  it("calls reindexDoc when Reindex is clicked", async () => {
    (api.listDocs as jest.Mock)
      .mockResolvedValueOnce([makeDoc({ status: "stopped", indexed: false, progress_percent: 0 })])
      .mockResolvedValue([makeDoc({ status: "pending", indexed: false, progress_percent: 0 })]);
    (api.reindexDoc as jest.Mock).mockResolvedValue(undefined);

    await act(async () => { render(<DocsPage />); });
    await screen.findByText("Stopped");

    await userEvent.click(screen.getByRole("button", { name: /reindex/i }));

    await waitFor(() => expect(api.reindexDoc).toHaveBeenCalledTimes(1));
    await screen.findByText("Queued");
  });
});
