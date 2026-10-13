# PageCite Evaluation

This directory contains the golden dataset and RAGAS evaluation scripts for measuring PageCite's RAG pipeline quality.

---

## Golden Dataset: `golden.jsonl`

Each line is a JSON object with the following fields:

| Field | Type | Description |
|---|---|---|
| `question` | `str` | The user question to ask the pipeline |
| `expected_answer` | `str` | Ground-truth reference answer |
| `source_doc` | `str` | Human-readable name of the source document |
| `source_page` | `int` | Approximate page number in the source PDF (`-1` for out-of-scope) |
| `category` | `str` | One of `factual`, `reasoning`, `multi_hop`, `out_of_scope` |

### Category definitions

| Category | Description | Count |
|---|---|---|
| `factual` | Direct lookup of a specific fact stated in the document | 15 |
| `reasoning` | Requires understanding cause-and-effect or the "why" behind a design choice | 8 |
| `multi_hop` | Answer requires connecting information from two or more parts of the document | 5 |
| `out_of_scope` | Question is unrelated to the document, the system should refuse gracefully | 2 |

The current dataset is built from **"Attention Is All You Need"** (Vaswani et al., 2017).

---

## Adding new entries

1. Open `eval/golden.jsonl` in any text editor.
2. Append one JSON object per line (no trailing commas, each line is independent).
3. Use an existing entry as a template:

```jsonl
{"question": "...", "expected_answer": "...", "source_doc": "...", "source_page": N, "category": "factual"}
```

4. Keep `expected_answer` concise and factually accurate. It is used as the RAGAS `reference` string.
5. For out-of-scope questions set `source_page` to `-1`.

---

## Running the evaluation: `run.py`

### Prerequisites

1. The PDF must be uploaded and indexed via the API. Note the `doc_id` returned by `POST /documents/{doc_id}/index`. The server does **not** need to be running during evaluation, `run.py` calls the pipeline directly.
2. `GOOGLE_API_KEY` must be set in your environment (used as the RAGAS judge LLM).
3. `run.py` calls the pipeline with `use_tools=False`, so the Researcher's web search / calculator
   step is skipped entirely, so scores measure document-grounded retrieval + synthesis only, and runs
   stay reproducible instead of depending on live web search results.

### Usage

```bash
# Basic run (requires --doc-id)
python eval/run.py --doc-id <your_doc_id>

# Limit to a subset of entries (useful for quick smoke tests)
python eval/run.py --doc-id <your_doc_id> --limit 5

# Filter by category
python eval/run.py --doc-id <your_doc_id> --category factual

# Override the golden dataset path
python eval/run.py --doc-id <your_doc_id> --golden path/to/custom.jsonl

# Save results to a custom directory
python eval/run.py --doc-id <your_doc_id> --results-dir eval/results
```

Or via Make:

```bash
DOC_ID=<your_doc_id> make eval
```

To refresh the root README scores from the latest saved result without re-running evaluation:

```bash
make update-readme
# or directly:
python eval/run.py --update-readme
```

### Output

- **Console:** per-question table showing question, RAGAS scores, and pass/fail, followed by aggregate means.
- **File:** `eval/results/<UTC-timestamp>.json` with full per-question and aggregate data.
- **README.md:** the `Latest results` table in the root README is automatically updated with the new scores.

### Expected runtime and cost

| Dataset size | Approximate wall time | Approximate Gemini API cost |
|---|---|---|
| 5 questions | ~2 min | < $0.02 |
| 30 questions (full) | ~10–15 min | ~$0.05–$0.15 |

Cost depends on answer and context length. Each question triggers:
- 1 PageCite agent run through Researcher → Synthesizer → Critic (tools disabled,
  one Synthesizer + one Critic call per revision, up to 2 revisions)
- 4–8 Gemini calls for RAGAS metrics (faithfulness, answer relevancy, context precision, context recall)

---

## Metrics

| Metric | What it measures | Ideal |
|---|---|---|
| `faithfulness` | Are all claims in the answer supported by retrieved contexts? | → 1.0 |
| `answer_relevancy` | Is the answer relevant to the question (not off-topic)? | → 1.0 |
| `context_precision` | Are retrieved chunks ranked with the most relevant ones first? | → 1.0 |
| `context_recall` | Does the retrieved context cover all the information needed for the reference answer? | → 1.0 |

---

## Results directory

`eval/results/` stores one JSON file per evaluation run, named by UTC timestamp. Each file contains:

```json
{
  "timestamp": "2025-...",
  "doc_id": "...",
  "golden_file": "eval/golden.jsonl",
  "n_total": 30,
  "n_evaluated": 30,
  "per_question": [...],
  "means": {
    "faithfulness": 0.92,
    "answer_relevancy": 0.88,
    "context_precision": 0.85,
    "context_recall": 0.79
  }
}
```
