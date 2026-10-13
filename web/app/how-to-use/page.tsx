import Nav from "@/components/nav";
import { LogInIcon, UploadIcon, DatabaseIcon, MessageSquareIcon, LightbulbIcon, AlertCircleIcon, BarChart2Icon, PlugIcon } from "lucide-react";

const steps = [
  {
    number: "01",
    icon: LogInIcon,
    title: "Sign in",
    desc: "Click Sign in from the nav bar or visit /login. Create an account or sign in with an existing one.",
    detail: "PageCite uses Clerk for authentication. Your documents, chats, and usage data are private, and no other user can see them.",
  },
  {
    number: "02",
    icon: UploadIcon,
    title: "Add a document",
    desc: "Go to Documents and click Upload File to add a policy, manual, report, or any other PDF or DOCX file to your knowledge base.",
    detail: "Files are stored securely on the server and associated with your account. DOCX files are automatically converted to PDF on upload so they go through the same OCR and embedding pipeline as native PDFs.",
  },
  {
    number: "03",
    icon: DatabaseIcon,
    title: "Wait for indexing",
    desc: "After upload the document is queued for background processing. The card shows a smooth progress bar and a step breakdown: Queued → Parsing → Extracting → Embedding → Finalizing.",
    detail: "Indexing takes 1-3 minutes depending on file size. You can leave the page and come back, the card polls every 2 seconds. Use Stop to cancel at any time, the card remembers which step it was on. Use Reindex to retry a failed or stopped document. Chat activates once indexing completes.",
  },
  {
    number: "04",
    icon: MessageSquareIcon,
    title: "Start chatting",
    desc: "Click Chat on any indexed document. Progress updates stream in while the agents work, and the checked answer arrives with page-level citations you can click to jump to the exact passage.",
    detail: "Behind the scenes, a Researcher agent retrieves chunks (and optionally calls web search or a calculator), a Synthesizer writes the answer, and a Critic reviews it for hallucination and missing citations before it reaches you, revising up to twice if needed. Conversation history is saved per session and per account. Each message shows its estimated cost in US dollars and its token count. If PII masking is enabled, a notice appears when an email address, phone number, US SSN, or card number is detected in your message and masked before it reaches the model.",
  },
  {
    number: "05",
    icon: LightbulbIcon,
    title: "Read citations & tool badges",
    desc: "Every answer includes page badges beneath the response. Click a badge to open the PDF at the exact source passage.",
    detail: "If the Researcher used web search or the calculator, a Web (N) or Calc badge appears next to the citations. Click Web to see the source URLs, or hover Calc to see the expression and result. If the model cannot find relevant context, it says so rather than hallucinating.",
  },
  {
    number: "06",
    icon: BarChart2Icon,
    title: "Track usage",
    desc: "Visit the Usage page to see your spend in US dollars and your token count. Switch between Hourly, Daily, Weekly, Monthly, and All Time views.",
    detail: "Cost is estimated from the per-token rates configured on the server. The chat header also shows the running cost of the current chat.",
  },
  {
    number: "07",
    icon: PlugIcon,
    title: "Use with Claude Desktop or Cursor (MCP)",
    desc: "Go to Settings → API Keys, generate a key, then add the MCP server config to Claude Desktop. Your knowledge base becomes a searchable tool inside any MCP client.",
    detail: "For Claude Desktop, add the mcpServers entry to claude_desktop_config.json with your PAGECITE_API_KEY and restart. For Cursor, point it at http://localhost:8000/mcp/sse with the X-API-Key header. The API Keys page shows the exact config snippet.",
  },
];

const tips = [
  "Ask specific questions, the retrieval pipeline works best with focused queries.",
  "If the Critic isn't satisfied with a draft answer, it's automatically revised (up to twice) before you see it.",
  "Ask something needing current events or a calculation and watch for the Web or Calc badge. The model decides on its own whether to use those tools.",
  "Repeated or near-identical questions hit the semantic cache and return instantly.",
  "Both PDF and DOCX files use the same inline viewer. Click any page citation badge to jump directly to the source passage.",
  "Your documents are private, only you can see and chat with files you've uploaded.",
  "Session memory persists across logins, your chat history is saved to your account.",
  "Rate limits are 30 requests per hour and 200 per day. A countdown toast appears when you hit the limit.",
];

export default function HowToUsePage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Nav />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 60% 40% at 50% -5%, oklch(0.62 0.22 264 / 0.1), transparent)",
        }}
      />

      <main className="flex-1 max-w-4xl mx-auto w-full px-4 py-16">
        <h1 className="text-3xl font-bold tracking-tight mb-2">How to use PageCite</h1>
        <p className="text-muted-foreground mb-14">
          From upload to conversation in six steps.
        </p>

        {/* Steps */}
        <div className="flex flex-col gap-6 mb-16">
          {steps.map(({ number, icon: Icon, title, desc, detail }) => (
            <div key={number} className="card-glow flex gap-5 rounded-xl border border-border bg-card p-6">
              <div className="shrink-0 flex flex-col items-center gap-2">
                <span className="text-xs font-mono text-primary font-bold">{number}</span>
                <span className="flex items-center justify-center size-9 rounded-lg bg-primary/15 text-primary">
                  <Icon className="size-4" />
                </span>
              </div>
              <div>
                <h3 className="font-semibold mb-1">{title}</h3>
                <p className="text-sm text-foreground/80 mb-2 text-justify">{desc}</p>
                <p className="text-xs text-muted-foreground leading-relaxed text-justify">{detail}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Tips */}
        <div className="rounded-xl border border-primary/20 bg-primary/5 p-6">
          <div className="flex items-center gap-2 mb-4 text-primary font-medium text-sm">
            <AlertCircleIcon className="size-4" />
            Tips for best results
          </div>
          <ul className="flex flex-col gap-2">
            {tips.map((tip) => (
              <li key={tip} className="flex items-start gap-2 text-sm text-muted-foreground text-justify">
                <span className="mt-1.5 size-1.5 rounded-full bg-primary/60 shrink-0" />
                {tip}
              </li>
            ))}
          </ul>
        </div>

        {/* Build time note */}
        <div className="mt-6 rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
          <strong className="text-foreground">First Docker build takes longer.</strong>{" "}
          The initial{" "}
          <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">docker compose up --build</code>{" "}
          downloads Python ML models (~1 GB) and compiles the Next.js app. Subsequent
          builds use Docker layer cache and are significantly faster.
        </div>
      </main>

      <footer className="border-t border-border py-6 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} PageCite
      </footer>
    </div>
  );
}
