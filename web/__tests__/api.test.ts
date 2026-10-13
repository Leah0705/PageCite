import { chat, createApiKey, fetchConversation, getDocStatus, getMyUsage, listApiKeys, listDocs, parseSseFrame, revokeApiKey, uploadDoc } from "@/lib/api";

function mockFetch(body: unknown, ok = true, status = 200) {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
    body: null,
  });
}

describe("listDocs", () => {
  it("returns parsed JSON on success", async () => {
    const docs = [
      {
        doc_id: "abc",
        filename: "test.pdf",
        uploaded_at: "2024-01-01T00:00:00Z",
        status: "indexed",
        indexed: true,
        progress_percent: 100,
      },
    ];
    mockFetch(docs);
    const result = await listDocs();
    expect(result).toEqual(docs);
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain("/documents");
  });

  it("throws on non-ok response", async () => {
    mockFetch({}, false, 500);
    await expect(listDocs()).rejects.toThrow("Failed to fetch documents");
  });
});

describe("uploadDoc", () => {
  it("posts a multipart form and returns upload response with status", async () => {
    const resp = { doc_id: "xyz", filename: "paper.pdf", status: "pending" };
    mockFetch(resp);
    const file = new File(["content"], "paper.pdf", { type: "application/pdf" });
    const result = await uploadDoc(file);
    expect(result.doc_id).toBe("xyz");
    expect(result.status).toBe("pending");
    const call = (global.fetch as jest.Mock).mock.calls[0];
    expect(call[1].method).toBe("POST");
    expect(call[1].body).toBeInstanceOf(FormData);
  });

  it("throws on failure", async () => {
    mockFetch({}, false, 422);
    const file = new File(["x"], "x.pdf", { type: "application/pdf" });
    await expect(uploadDoc(file)).rejects.toThrow("Upload failed");
  });
});

describe("getDocStatus", () => {
  it("returns status response for a doc", async () => {
    const resp = { status: "processing", progress_percent: 42, page_count: null };
    mockFetch(resp);
    const result = await getDocStatus("doc-123");
    expect(result.status).toBe("processing");
    expect(result.progress_percent).toBe(42);
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain("/documents/doc-123/status");
  });

  it("sends auth header when token provided", async () => {
    mockFetch({ status: "indexed", progress_percent: 100, page_count: 5 });
    await getDocStatus("doc-abc", "tok_123");
    const call = (global.fetch as jest.Mock).mock.calls[0];
    expect(call[1].headers).toMatchObject({ Authorization: "Bearer tok_123" });
  });

  it("throws on non-ok response", async () => {
    mockFetch({}, false, 404);
    await expect(getDocStatus("missing")).rejects.toThrow("Failed to fetch document status");
  });
});

describe("chat", () => {
  it("posts to /query/stream with correct body", () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500, body: null });
    const ctrl = new AbortController();
    chat(
      { doc_id: "abc", question: "What is this?", session_id: "sess1" },
      undefined,
      () => {}, () => {}, () => {}, () => {},
      () => {},
      ctrl.signal
    );
    const call = (global.fetch as jest.Mock).mock.calls[0];
    expect(call[0]).toContain("/query/stream");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toMatchObject({
      doc_id: "abc",
      question: "What is this?",
      session_id: "sess1",
    });
  });

  it("calls onError with 429 sentinel when rate limited", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 429,
      headers: { get: (h: string) => (h === "Retry-After" ? "3600" : null) },
      body: null,
    });
    const onError = jest.fn();
    chat(
      { doc_id: "abc", question: "hi" },
      undefined,
      () => {}, () => {}, () => {}, () => {},
      onError,
      undefined
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(onError).toHaveBeenCalledWith("429:3600");
  });
});

describe("getMyUsage", () => {
  it("returns usage summary", async () => {
    const summary = { total_cost_usd: 0.0042, total_tokens: 1234 };
    mockFetch(summary);
    const result = await getMyUsage("tok_abc");
    expect(result.total_cost_usd).toBeCloseTo(0.0042);
    expect(result.total_tokens).toBe(1234);
    const call = (global.fetch as jest.Mock).mock.calls[0];
    expect(call[0]).toContain("/usage/me");
    expect(call[1].headers).toMatchObject({ Authorization: "Bearer tok_abc" });
  });

  it("throws on non-ok response", async () => {
    mockFetch({}, false, 500);
    await expect(getMyUsage()).rejects.toThrow("Failed to fetch usage");
  });
});

describe("fetchConversation", () => {
  it("returns messages on success", async () => {
    const msgs = [
      { role: "user", content: "hi", tokens_in: 5, tokens_out: 0, cost_usd: 0 },
      { role: "assistant", content: "hello", tokens_in: 0, tokens_out: 8, cost_usd: 0.001 },
    ];
    mockFetch(msgs);
    const result = await fetchConversation("sess-1", "tok_abc");
    expect(result).toHaveLength(2);
    expect(result[1].role).toBe("assistant");
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain("/conversations/sess-1");
  });

  it("returns empty array on non-ok response", async () => {
    mockFetch({}, false, 404);
    const result = await fetchConversation("missing");
    expect(result).toEqual([]);
  });

  it("returns empty array on network error", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("Network error"));
    const result = await fetchConversation("sess-x");
    expect(result).toEqual([]);
  });
});

describe("listApiKeys", () => {
  it("returns key records on success", async () => {
    const keys = [{ id: "k1", name: "Claude Desktop", created_at: "2026-01-01T00:00:00Z", last_used_at: null }];
    mockFetch(keys);
    const result = await listApiKeys("tok");
    expect(result).toEqual(keys);
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain("/api-keys");
  });

  it("throws on non-ok response", async () => {
    mockFetch({}, false, 401);
    await expect(listApiKeys()).rejects.toThrow("Failed to fetch API keys");
  });
});

describe("createApiKey", () => {
  it("posts name and returns created record with key", async () => {
    const created = { id: "k2", name: "Cursor", key: "pc_abc123", created_at: "2026-01-01T00:00:00Z" };
    mockFetch(created);
    const result = await createApiKey("Cursor", "tok");
    expect(result.key).toBe("pc_abc123");
    const call = (global.fetch as jest.Mock).mock.calls[0];
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toMatchObject({ name: "Cursor" });
  });

  it("throws on failure", async () => {
    mockFetch({}, false, 422);
    await expect(createApiKey("x")).rejects.toThrow("Failed to create API key");
  });
});

describe("revokeApiKey", () => {
  it("sends DELETE to the correct URL", async () => {
    mockFetch({});
    await revokeApiKey("k1", "tok");
    const call = (global.fetch as jest.Mock).mock.calls[0];
    expect(call[0]).toContain("/api-keys/k1");
    expect(call[1].method).toBe("DELETE");
  });

  it("throws on failure", async () => {
    mockFetch({}, false, 404);
    await expect(revokeApiKey("missing")).rejects.toThrow("Failed to revoke API key");
  });
});

describe("chat SSE stream", () => {
  /** Build a mock body with a getReader() that feeds chunks then signals done. */
  function makeBody(chunks: string[]) {
    const encoder = new TextEncoder();
    let idx = 0;
    return {
      getReader: () => ({
        read: async () => {
          if (idx < chunks.length) {
            return { done: false, value: encoder.encode(chunks[idx++]) };
          }
          return { done: true, value: undefined };
        },
      }),
    };
  }

  it("fires onDone via explicit done event", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200,
      body: makeBody(["event: token\ndata: Hello\n\n", "event: done\ndata: {}\n\n"]),
    });
    const onToken = jest.fn();
    const onDone = jest.fn();
    chat({ doc_id: "d", question: "q" }, undefined, () => {}, onToken, () => {}, onDone, () => {});
    await new Promise((r) => setTimeout(r, 50));
    expect(onToken).toHaveBeenCalledWith("Hello");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("parses the tool_usage event and calls onToolUsage", async () => {
    const toolUsage = {
      web_search: { used: true, count: 2, results: [{ title: "A", url: "https://a.com", snippet: "s" }] },
      calculator: { used: false, expression: "", result: "" },
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200,
      body: makeBody([
        `event: tool_usage\ndata: ${JSON.stringify(toolUsage)}\n\n`,
        "event: done\ndata: {}\n\n",
      ]),
    });
    const onToolUsage = jest.fn();
    chat(
      { doc_id: "d", question: "q" }, undefined,
      () => {}, () => {}, () => {}, () => {}, () => {},
      undefined, undefined, undefined, undefined,
      onToolUsage
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(onToolUsage).toHaveBeenCalledWith(toolUsage);
  });

  it("fires onDone fallback when done event lacks trailing \\n\\n", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200,
      body: makeBody(["event: token\ndata: Hi\n\n", "event: done\ndata: {}"]),
    });
    const onToken = jest.fn();
    const onDone = jest.fn();
    chat({ doc_id: "d", question: "q" }, undefined, () => {}, onToken, () => {}, onDone, () => {});
    await new Promise((r) => setTimeout(r, 50));
    expect(onToken).toHaveBeenCalledWith("Hi");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("fires onDone fallback when stream closes with no done event", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200,
      body: makeBody(["event: token\ndata: World\n\n"]),
    });
    const onToken = jest.fn();
    const onDone = jest.fn();
    chat({ doc_id: "d", question: "q" }, undefined, () => {}, onToken, () => {}, onDone, () => {});
    await new Promise((r) => setTimeout(r, 50));
    expect(onToken).toHaveBeenCalledWith("World");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("keeps blank lines inside a token instead of cutting the frame", async () => {
    // Frames exactly as app.main._sse() emits a token that contains a paragraph break.
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200,
      body: makeBody([
        "event: token\ndata: First\n\n",
        "event: token\ndata:  paragraph.\ndata: \ndata: Second\n\n",
        "event: token\ndata:  paragraph.\n\n",
        "event: done\ndata: \n\n",
      ]),
    });
    const tokens: string[] = [];
    const onDone = jest.fn();
    chat({ doc_id: "d", question: "q" }, undefined, () => {}, (t) => tokens.push(t), () => {}, onDone, () => {});
    await new Promise((r) => setTimeout(r, 50));
    expect(tokens.join("")).toBe("First paragraph.\n\nSecond paragraph.");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("does not fire onDone twice when explicit done event is received", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200,
      body: makeBody(["event: done\ndata: {}\n\n"]),
    });
    const onDone = jest.fn();
    chat({ doc_id: "d", question: "q" }, undefined, () => {}, () => {}, () => {}, onDone, () => {});
    await new Promise((r) => setTimeout(r, 50));
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});

describe("parseSseFrame", () => {
  it("joins multiple data lines with a newline", () => {
    expect(parseSseFrame("event: token\ndata: a\ndata: \ndata: b")).toEqual({ event: "token", data: "a\n\nb" });
  });

  it("keeps leading spaces after the single separator space", () => {
    expect(parseSseFrame("event: token\ndata:  word")).toEqual({ event: "token", data: " word" });
  });

  it("returns null when the event name or data is missing", () => {
    expect(parseSseFrame("data: orphan")).toBeNull();
    expect(parseSseFrame("event: done")).toBeNull();
    expect(parseSseFrame("")).toBeNull();
  });
});
