"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  GitBranch, Search, Zap, Lightbulb,
  Brain, Plug, Wrench, FlaskConical,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import Nav from "@/components/nav";

const features = [
  { icon: GitBranch,    title: "Multi-Agent Pipeline",   desc: "A LangGraph graph runs Researcher, Synthesizer, and Critic agents in turn. The Critic checks each draft for hallucination, missing citations, and off-topic drift, and sends it back for up to 2 revisions." },
  { icon: Wrench,       title: "Researcher Tools",       desc: "The Researcher agent can call Tavily web search and a safe calculator through Gemini function calling. The model decides when a tool is needed." },
  { icon: FlaskConical, title: "RAGAS Evaluation",       desc: "Faithfulness, answer relevancy, context precision, and recall, scored on a 30-question golden dataset with a one-command eval runner." },
  { icon: Brain,        title: "Contextual Retrieval",   desc: "Gemini adds a one-sentence context to every chunk before embedding, so a short passage still carries the document context it needs to be found." },
  { icon: Search,       title: "Hybrid Search",          desc: "Fuses dense pgvector HNSW search with PostgreSQL full-text search (ts_rank) through Reciprocal Rank Fusion, then re-scores the candidates with a cross-encoder reranker." },
  { icon: Lightbulb,    title: "HyDE Fallback",          desc: "When the reranker score falls below threshold, generates a hypothetical answer passage and re-retrieves using its embedding to rescue ambiguous queries." },
  { icon: Plug,         title: "MCP Server",             desc: "Exposes search, list, and get tools over the Model Context Protocol, so Claude Desktop and Cursor can query your knowledge base as native tools." },
  { icon: Zap,          title: "Semantic Cache",         desc: "A Redis vector cache answers near-identical questions in milliseconds without rerunning retrieval or generation, and is cleared when a document is reindexed or deleted." },
];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

const item = {
  hidden: { opacity: 0, y: 16 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.3, ease: "easeOut" as const } },
};

export default function LandingPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Nav />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 70% 50% at 50% -5%, oklch(0.62 0.22 264 / 0.12), transparent)",
        }}
      />

      <main className="flex-1">
        <section className="max-w-6xl mx-auto px-4 pt-16 pb-12 text-center">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-primary/30 bg-primary/10 text-primary text-xs font-medium mb-4"
          >
            <Brain className="size-3.5" />
            Powered by LangGraph + Gemini 2.5 Flash
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="text-4xl sm:text-5xl font-bold tracking-tight mb-4 leading-[1.1]"
          >
            <span className="gradient-heading">A Knowledge Base That Cites Its Sources</span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="text-base text-muted-foreground max-w-xl mx-auto mb-7"
          >
            Upload policies, manuals, reports, and specs as PDF or DOCX files to build a private knowledge base. Ask questions in English and get answers that are checked against the source and linked to the exact page.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.3 }}
            className="flex items-center justify-center gap-3"
          >
            <Link href="/docs" className={buttonVariants({ size: "lg" })}>
              Get started
            </Link>
            <Link href="/how-to-use" className={buttonVariants({ variant: "outline", size: "lg" })}>
              How it works
            </Link>
          </motion.div>
        </section>

        <section className="max-w-6xl mx-auto px-4 pb-14">
          <motion.div
            variants={container}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, amount: 0.2 }}
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
          >
            {features.map(({ icon: Icon, title, desc }) => (
              <motion.div
                key={title}
                variants={item}
                className="card-glow rounded-xl border border-border bg-card p-5 cursor-default"
              >
                <div className="flex items-center gap-2.5 mb-2">
                  <span className="flex items-center justify-center size-7 rounded-md bg-primary/15 text-primary">
                    <Icon className="size-3.5" />
                  </span>
                  <h3 className="font-medium text-sm">{title}</h3>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed text-justify">{desc}</p>
              </motion.div>
            ))}
          </motion.div>
        </section>
      </main>

      <footer className="border-t border-border py-6 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} PageCite
      </footer>
    </div>
  );
}
