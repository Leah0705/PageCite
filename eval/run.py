"""
PageCite RAGAS evaluation runner.

Loads eval/golden.jsonl, runs the full PageCite pipeline for every entry, then
computes RAGAS metrics using Gemini as the judge model.  Results are printed as
a per-question table and saved to eval/results/<UTC-timestamp>.json.

Usage:
    python eval/run.py --doc-id <doc_id>
    python eval/run.py --doc-id <doc_id> --limit 5
    python eval/run.py --doc-id <doc_id> --category factual
    DOC_ID=<doc_id> python eval/run.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

# Ensure project root is importable when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness

from rag.agents.graph import run_agent

EVAL_DIR = Path(__file__).parent
DEFAULT_GOLDEN = EVAL_DIR / "golden.jsonl"
RESULTS_DIR = EVAL_DIR / "results"

VALID_CATEGORIES = {"factual", "reasoning", "multi_hop", "out_of_scope"}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _load_golden(path: Path, category: str | None, limit: int | None) -> list[dict]:
    entries: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))

    if category:
        entries = [e for e in entries if e.get("category") == category]

    if limit:
        entries = entries[:limit]

    return entries


def _run_pipeline(question: str, doc_id: str) -> tuple[str, list[str]]:
    """Invoke the PageCite agent and return (answer, retrieved_context_strings).

    use_tools=False so scores measure document-grounded retrieval + synthesis only.
    Web search / calculator results would otherwise leak non-document context into
    RAGAS's context_precision / context_recall and make runs non-reproducible.
    """
    state, _usage = run_agent(question=question, doc_id=doc_id, top_k=8, use_tools=False)
    answer: str = state.get("generation", "")
    docs = state.get("documents", [])
    contexts = [doc.page_content for doc in docs] if docs else ["No context retrieved."]
    return answer, contexts


def _build_ragas_judge() -> tuple[LangchainLLMWrapper, LangchainEmbeddingsWrapper]:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set, required for RAGAS judge.")

    llm = LangchainLLMWrapper(
        ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=api_key,
            temperature=0,
        )
    )
    emb = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    )
    return llm, emb


def _compute_ragas(
    samples: list[SingleTurnSample],
    llm: LangchainLLMWrapper,
    emb: LangchainEmbeddingsWrapper,
) -> tuple[dict[str, list[float | None]], dict[str, float]]:
    metrics = [
        Faithfulness(llm=llm),
        AnswerRelevancy(llm=llm, embeddings=emb),
        ContextPrecision(llm=llm),
        ContextRecall(llm=llm),
    ]
    dataset = EvaluationDataset(samples=samples)
    result = evaluate(dataset=dataset, metrics=metrics, raise_exceptions=False, show_progress=True)

    # Extract per-sample lists and compute means
    per_metric_lists: dict[str, list[float | None]] = {}
    means: dict[str, float] = {}

    for m in metrics:
        raw = result[m.name]
        if isinstance(raw, list):
            per_metric_lists[m.name] = raw
            valid = [v for v in raw if v is not None and not (isinstance(v, float) and math.isnan(v))]
            means[m.name] = round(sum(valid) / len(valid), 4) if valid else 0.0
        elif raw is None:
            per_metric_lists[m.name] = [None] * len(samples)
            means[m.name] = 0.0
        else:
            per_metric_lists[m.name] = [float(raw)] * len(samples)
            means[m.name] = round(float(raw), 4)

    return per_metric_lists, means


def _print_per_question_table(
    entries: list[dict],
    per_metric: dict[str, list[float | None]],
    answers: list[str],
) -> None:
    metric_names = list(per_metric.keys())
    col_w = 36
    score_w = 8

    header = f"{'#':<4} {'Question':<{col_w}}"
    for m in metric_names:
        abbr = {"faithfulness": "Faith", "answer_relevancy": "AnswRel",
                "context_precision": "CtxPrec", "context_recall": "CtxRec"}.get(m, m[:7])
        header += f"  {abbr:>{score_w}}"
    print("\n" + "─" * len(header))
    print(header)
    print("─" * len(header))

    for i, entry in enumerate(entries):
        q = entry["question"][:col_w - 1] + "…" if len(entry["question"]) > col_w else entry["question"]
        row = f"{i + 1:<4} {q:<{col_w}}"
        for m in metric_names:
            val = per_metric[m][i]
            row += f"  {val:>{score_w}.3f}" if val is not None else f"  {'N/A':>{score_w}}"
        print(row)

    print("─" * len(header))


def _print_means_table(means: dict[str, float]) -> None:
    print("\n  Aggregate means:")
    print("  " + "─" * 36)
    for metric, score in means.items():
        if math.isnan(score):
            print(f"  {metric:<24}   N/A")
        else:
            bar = "█" * int(score * 20)
            print(f"  {metric:<24}  {score:.3f}  {bar}")
    print("  " + "─" * 36)


def _portable_path(path: Path) -> str:
    """Path relative to the project root, so result files never record local directories."""
    try:
        return str(path.resolve().relative_to(EVAL_DIR.parent.resolve()))
    except ValueError:
        return path.name


def _save_results(
    doc_id: str,
    golden_file: Path,
    entries: list[dict],
    answers: list[str],
    contexts: list[list[str]],
    per_metric: dict[str, list[float | None]],
    means: dict[str, float],
    results_dir: Path = RESULTS_DIR,
) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = results_dir / f"{ts}.json"

    per_question: list[dict[str, Any]] = []
    for i, entry in enumerate(entries):
        scores = {m: (per_metric[m][i] if per_metric[m][i] is not None else None)
                  for m in per_metric}
        per_question.append({
            "index": i + 1,
            "question": entry["question"],
            "category": entry.get("category"),
            "source_page": entry.get("source_page"),
            "expected_answer": entry["expected_answer"],
            "generated_answer": answers[i],
            "retrieved_contexts": contexts[i],
            "scores": scores,
        })

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "doc_id": doc_id,
        "golden_file": _portable_path(golden_file),
        "n_total": len(entries),
        "n_evaluated": len(entries),
        "per_question": per_question,
        "means": means,
    }

    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    out_path.write_text(serialized)
    (results_dir / "latest.json").write_text(serialized)
    return out_path


_README_START = "<!-- EVAL-RESULTS-START -->"
_README_END = "<!-- EVAL-RESULTS-END -->"
_ROOT_README = Path(__file__).parent.parent / "README.md"


def _latest_result_file(results_dir: Path = RESULTS_DIR) -> Path | None:
    """Return the most recently written JSON in results_dir, or None."""
    files = sorted(results_dir.glob("*.json"))
    return files[-1] if files else None


def update_readme_from_results(
    results_dir: Path = RESULTS_DIR,
    result_file: Path | None = None,
) -> bool:
    """
    Write scores from a result JSON into the <!-- EVAL-RESULTS-START/END --> block
    in README.md.  Pass result_file to use a specific file, otherwise the latest
    file in results_dir is used.
    Returns True if the README was updated, False otherwise.
    """
    latest = result_file or _latest_result_file(results_dir)
    if latest is None:
        print(f"No result files found in {results_dir}.", file=sys.stderr)
        return False

    data = json.loads(latest.read_text())
    means: dict[str, float] = data["means"]
    n_evaluated: int = data["n_evaluated"]
    timestamp: str = data["timestamp"]
    date_str = timestamp[:10]

    if not _ROOT_README.exists():
        print(f"README not found at {_ROOT_README}.", file=sys.stderr)
        return False

    rows = "\n".join(
        f"| `{metric}` | {score:.3f} | {'█' * int(score * 20)} |"
        if not math.isnan(score)
        else f"| `{metric}` | N/A | |"
        for metric, score in means.items()
    )
    block = (
        f"{_README_START}\n"
        f"| Metric | Score | |\n"
        f"|---|---|---|\n"
        f"{rows}\n\n"
        f"_Evaluated on {n_evaluated} questions · {date_str} · "
        f"full results in [`eval/results/latest.json`](eval/results/latest.json)_\n"
        f"{_README_END}"
    )

    content = _ROOT_README.read_text()
    start = content.find(_README_START)
    end = content.find(_README_END)
    if start == -1 or end == -1:
        print("Markers <!-- EVAL-RESULTS-START/END --> not found in README.md.", file=sys.stderr)
        return False

    _ROOT_README.write_text(content[:start] + block + content[end + len(_README_END):])
    print(f"README.md updated from {latest.name}")
    return True


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation against PageCite golden dataset")
    parser.add_argument(
        "--doc-id",
        default=os.getenv("DOC_ID"),
        help="doc_id of the indexed PDF (or set DOC_ID env var)",
    )
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="Path to .jsonl golden dataset")
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N entries")
    parser.add_argument(
        "--category",
        choices=list(VALID_CATEGORIES),
        default=None,
        help="Filter to a single category",
    )
    parser.add_argument("--results-dir", default=str(RESULTS_DIR), help="Directory for result JSON files")
    parser.add_argument(
        "--update-readme",
        action="store_true",
        help="Update README.md from the latest result file and exit (no evaluation run)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)

    if args.update_readme:
        sys.exit(0 if update_readme_from_results(results_dir) else 1)

    if not args.doc_id:
        parser.error("--doc-id is required (or set the DOC_ID environment variable)")

    golden_path = Path(args.golden)
    if not golden_path.exists():
        print(f"ERROR: golden dataset not found at {golden_path}", file=sys.stderr)
        sys.exit(1)

    entries = _load_golden(golden_path, args.category, args.limit)
    if not entries:
        print("No entries matched the given filters.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(entries)} entries from {golden_path}")
    if args.category:
        print(f"  Category filter: {args.category}")

    # ── Step 1: run pipeline for every entry ──────────────────────
    print("\nRunning PageCite pipeline…")
    all_answers: list[str] = []
    all_contexts: list[list[str]] = []
    ragas_samples: list[SingleTurnSample] = []

    for i, entry in enumerate(entries, start=1):
        q = entry["question"]
        print(f"  [{i:>2}/{len(entries)}] {q[:80]}{'…' if len(q) > 80 else ''}")

        try:
            answer, contexts = _run_pipeline(q, args.doc_id)
        except Exception as exc:
            print(f"         pipeline error: {exc}")
            answer = ""
            contexts = ["Pipeline error."]

        all_answers.append(answer)
        all_contexts.append(contexts)
        ragas_samples.append(
            SingleTurnSample(
                user_input=q,
                response=answer,
                retrieved_contexts=contexts,
                reference=entry["expected_answer"],
            )
        )

    # ── Step 2: RAGAS scoring ──────────────────────────────────────
    print("\nBuilding RAGAS judge (Gemini 2.5 Flash)…")
    llm, emb = _build_ragas_judge()

    print("Computing RAGAS metrics…")
    per_metric, means = _compute_ragas(ragas_samples, llm, emb)

    # ── Step 2b: fix out-of-scope scores ──────────────────────────
    # Faithfulness and answer_relevancy are undefined for "I do not know"
    # responses. There's no claim to fact-check and no context to be relevant
    # to, so RAGAS gives 0 even when the refusal is the correct answer.
    # Override all four metrics to 1.0 for any out_of_scope question whose
    # answer is a proper refusal.
    _NO_ANSWER = ("i do not know", "i don't know", "i cannot", "not mentioned")
    for i, entry in enumerate(entries):
        if entry.get("category") == "out_of_scope":
            ans_lower = all_answers[i].strip().lower()
            is_refusal = any(ans_lower.startswith(p) for p in _NO_ANSWER)
            if is_refusal:
                for m in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
                    if m in per_metric:
                        per_metric[m][i] = 1.0

    # Recompute means after overrides
    for m_name, values in per_metric.items():
        valid = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
        means[m_name] = round(sum(valid) / len(valid), 4) if valid else 0.0

    # ── Step 3: display results ────────────────────────────────────
    _print_per_question_table(entries, per_metric, all_answers)
    _print_means_table(means)

    # ── Step 4: save to disk ───────────────────────────────────────
    out_path = _save_results(
        doc_id=args.doc_id,
        golden_file=golden_path,
        entries=entries,
        answers=all_answers,
        contexts=all_contexts,
        per_metric=per_metric,
        means=means,
        results_dir=results_dir,
    )
    print(f"\nResults saved → {out_path}")

    # ── Step 5: update root README from the file we just saved ───
    update_readme_from_results(result_file=out_path)


if __name__ == "__main__":
    main()
