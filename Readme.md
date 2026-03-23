# SEBI Circular Knowledge Graph Agent

> An AI-powered agent that reads any SEBI circular PDF and automatically extracts every reference to other regulatory documents — circulars, regulations, acts, master circulars — structured into a queryable knowledge graph.

---

## Table of Contents

- [What It Does](#what-it-does)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Running the Agent](#running-the-agent)
- [Understanding the Output](#understanding-the-output)
- [Evaluation](#evaluation)
- [Automatic Evaluation (No Ground Truth)](#automatic-evaluation-no-ground-truth)
- [Running Tests](#running-tests)
- [Models and Providers](#models-and-providers)
- [Limitations](#limitations)
- [Scaling to All SEBI Circulars](#scaling-to-all-sebi-circulars)

---

## What It Does

SEBI circulars constantly reference older circulars, regulations, and acts. Compliance officers need to trace these references manually across hundreds of PDFs — a slow, error-prone process.

This agent automates that by:

1. Parsing any SEBI circular PDF page by page
2. Using an LLM to extract every reference to an external document from each page
3. Deduplicating references found across multiple pages
4. Running a second verification pass to catch missed clause-level references
5. Building a directed knowledge graph: **source circular → referenced documents**
6. Exporting results as JSON, GraphML, and a Mermaid diagram

**Example output for a 3-page SEBI circular:**
```
Total unique references: 8
  - SEBI (Mutual Funds) Regulations, 2026   [Regulation 42(1), 42(2)]   Pages: 1, 2
  - SEBI Master Circular for Mutual Funds   [para 10.9, para 16.8]      Pages: 2
  - SEBI Circular HO/47/11/...             []                           Pages: 2, 3
  - Securities and Exchange Board of India Act, 1992  [Section 11(1)]  Pages: 3
  - SEBI (Mutual Funds) Regulations, 1996  [Regulation 77]              Pages: 3
```

---

## Architecture

```
PDF File
   │
   ▼
┌─────────────────┐
│  pdf_parser.py  │  pdfplumber extracts text page-by-page
│                 │  Also extracts: circular number, subject,
│                 │  date, addressees from page 1
└────────┬────────┘
         │  List[PageContent] + DocumentMetadata
         ▼
┌──────────────────────────┐
│  reference_extractor.py  │  For each page → LLM call → JSON array of references
│                          │  Second pass: verify Master Circular clause references
│                          │  Deduplication: 3-tier matching (key / date+type / fuzzy)
└────────┬─────────────────┘
         │  List[DocumentReference]
         ▼
┌──────────────────────────┐
│  knowledge_graph.py      │  networkx DiGraph
│                          │  source circular → referenced documents
│                          │  Export: JSON + GraphML + Mermaid
└──────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  output/                            │
│    circular_references.json         │  Structured reference list
│    circular_graph.graphml           │  Opens in Gephi / yEd
│    circular_diagram.mmd             │  Paste at mermaid.live
└─────────────────────────────────────┘
```

---

## Project Structure

```
sebi-kg-agent/
│
├── agent/
│   ├── __init__.py
│   ├── pdf_parser.py          # PDF text extraction + metadata (subject, addressees, circular number)
│   ├── reference_extractor.py # LLM prompting, JSON parsing, dedup, verification pass
│   └── knowledge_graph.py     # Graph construction and multi-format export
│
├── evals/
│   ├── __init__.py
│   ├── evaluator.py           # Precision / Recall / F1 against manual ground truth
│   ├── improve.py             # Side-by-side V1 vs V2 prompt comparison
│   ├── llm_judge.py           # Automatic evaluation without ground truth
│   ├── regex_check.py         # Zero-cost field verification against PDF text
│   └── ground_truth/
│       └── example_ground_truth.json
│
├── tests/
│   └── test_agent.py          # 13 unit tests (dedup logic + evaluator math)
│
├── output/                    # Generated files (gitignored)
├── main.py                    # CLI entrypoint
├── conftest.py                # pytest path configuration
└── requirements.txt
```

---

## Setup

### Prerequisites

- Python 3.11+
- A HuggingFace account with a free API token (or Anthropic / Gemini key)

### Step 1 — Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/sebi-kg-agent
cd sebi-kg-agent
```

### Step 2 — Create and activate a virtual environment

```bash
python3.11 -m venv venv
source venv/bin/activate        # Mac / Linux
# venv\Scripts\activate         # Windows
```

### Step 3 — Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4 — Set your API key

Pick one provider and export its key:

```bash
# Option A — HuggingFace (free tier, recommended)
export HF_TOKEN="hf_..."

# Option B — Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-..."

# Option C — Google Gemini
export GEMINI_API_KEY="AIza..."
```

> **Get a free HuggingFace token:** Go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → New token → Read access is enough.

---

## Running the Agent

### Basic usage

```bash
python3 main.py path/to/circular.pdf
```

### With options

```bash
# Use a specific provider
python3 main.py circular.pdf --provider huggingface

# Show progress per page
python3 main.py circular.pdf --provider huggingface --verbose

# Custom output directory
python3 main.py circular.pdf --output-dir ./results

# Skip GraphML or Mermaid export
python3 main.py circular.pdf --no-graphml --no-mermaid
```

### All options

```
Arguments:
  pdf                   Path to SEBI circular PDF (required)

Options:
  --provider            anthropic | gemini | huggingface  (default: anthropic)
  --output-dir DIR      Where to write output files       (default: ./output)
  --verbose             Print progress per page
  --no-graphml          Skip GraphML export
  --no-mermaid          Skip Mermaid diagram export
```

### Example run

```
============================================================
  SEBI Knowledge Graph Agent
  Provider : huggingface
  File     : sebi_circular.pdf
============================================================

[ 1/4 ] Parsing PDF …
        3 pages extracted.
        Detected circular: HO/(92)2026-IMD-POD-2/I/6961/2026

[ 2/4 ] Extracting references (3 pages) …
        Page   1 / 3 … 2 ref(s) found.
        Page   2 / 3 … 5 ref(s) found.
        Page   3 / 3 … 3 ref(s) found.
        Raw references extracted: 10
        Running verification pass for Master Circular clauses ...
        Verification pass found 2 additional clause ref(s).

[ 3/4 ] Deduplicating and structuring …
        Unique references: 8

[ 4/4 ] Building knowledge graph and exporting …
        ✓ JSON    → output/sebi_circular_references.json
        ✓ GraphML → output/sebi_circular_graph.graphml
        ✓ Mermaid → output/sebi_circular_diagram.mmd
```

---

## Understanding the Output

### `*_references.json`

The primary output. Contains:

```json
{
  "source_document": {
    "title": "Borrowing by Mutual Funds",
    "circular_number": "HO/(92)2026-IMD-POD-2/I/6961/2026",
    "date": "March 13, 2026",
    "issuing_authority": "Securities and Exchange Board of India (SEBI)",
    "addressees": [
      "All Mutual Funds",
      "All Asset Management Companies (AMCs)",
      "All Trustee Companies/ Board of Trustees of Mutual Funds",
      "Association of Mutual Funds in India (AMFI)"
    ],
    "total_pages": 3
  },
  "total_references": 8,
  "references_by_type": {
    "regulation": [...],
    "master_circular": [...],
    "circular": [...],
    "act": [...]
  },
  "references": [
    {
      "document_type": "master_circular",
      "title": "SEBI Master Circular for Mutual Funds",
      "circular_number": "",
      "date": "June 27, 2024",
      "clause": "para 16.8",
      "context": "AMCs shall ensure compliance of...",
      "found_on_pages": [2]
    }
  ],
  "graph": { "nodes": 9, "edges": 8 }
}
```

### `*_graph.graphml`

Open in **Gephi** (free at gephi.org) or **yEd** to visualise the knowledge graph. Each node is a document, each edge is a reference relationship labelled with the clause.

### `*_diagram.mmd`

Mermaid diagram — paste at [mermaid.live](https://mermaid.live) to see an instant visual:

```
graph LR
    N0["Borrowing by Mutual Funds"]  ← source (blue)
    N1["SEBI (MF) Regulations 2026"] ← regulation (purple)
    N2["SEBI Master Circular 2024"]  ← master circular (orange)
    N0 -->|Regulation 42(1)| N1
    N0 -->|para 16.8| N2
```

**Colour coding:**

| Colour | Document Type |
|--------|--------------|
| 🔵 Blue | Source circular (the PDF you analysed) |
| 🟢 Green | Other SEBI circulars |
| 🟣 Purple | Regulations |
| 🟡 Yellow | Acts of Parliament |
| 🟠 Orange | Master Circulars |
| 🔷 Light Blue | Notifications |

---

## Evaluation

Evaluation measures how accurately the agent extracted references compared to a hand-annotated ground truth file.

### Step 1 — Create a ground truth file

Copy the example and annotate it by reading your PDF manually:

```bash
cp evals/ground_truth/example_ground_truth.json evals/ground_truth/my_circular.json
```

Edit `my_circular.json`:

```json
{
  "source_circular": "HO/(92)2026-IMD-POD-2/I/6961/2026",
  "references": [
    {
      "document_type": "master_circular",
      "title": "SEBI Master Circular for Mutual Funds",
      "circular_number": "",
      "date": "June 27, 2024",
      "clause": "para 16.8",
      "found_on_pages": [2]
    }
  ]
}
```

### Step 2 — Run the evaluator

```bash
python3 -m evals.evaluator \
  --predicted output/sebi_circular_references.json \
  --ground-truth evals/ground_truth/my_circular.json \
  --save evals/results/eval_v1.json
```

**Sample output:**

```
Overall Reference Detection
┌──────────────┬───────────┐
│ Precision    │     92.3% │
│ Recall       │    100.0% │
│ F1 Score     │     96.0% │
│ TP / FP / FN │ 8 / 1 / 0 │
└──────────────┴───────────┘

Per-field Accuracy (matched pairs)
┌─────────────────┬───────────┬────────┬───────┐
│ document_type   │    100.0% │ 100.0% │ 100.0%│
│ title           │     93.8% │  93.8% │ 93.8% │
│ circular_number │     87.5% │  87.5% │ 87.5% │
│ date            │     87.5% │  87.5% │ 87.5% │
│ clause          │     81.2% │  81.2% │ 81.2% │
└─────────────────┴───────────┴────────┴───────┘
```

### Step 3 — Compare V1 vs V2 prompts

```bash
python3 -m evals.improve \
  --pdf sebi_circular.pdf \
  --ground-truth evals/ground_truth/my_circular.json \
  --provider huggingface
```

This runs the agent with both the basic and improved prompt and prints a delta table showing the improvement.

---

## Automatic Evaluation (No Ground Truth)

Three methods that require no manual annotation:

### LLM-as-Judge

Asks the LLM to verify each extracted reference against the original PDF text. Also detects duplicates and validates source metadata.

```bash
python3 -m evals.llm_judge \
  --predicted output/sebi_circular_references.json \
  --pdf sebi_circular.pdf \
  --provider huggingface \
  --save evals/results/llm_judge.json
```

Checks performed:
- **Reference accuracy** — is each reference genuinely in the PDF?
- **Field accuracy** — are title, date, clause, circular_number correct?
- **Duplicate detection** — are any references extracted twice?
- **Source metadata** — is the circular number, subject, addressees correctly extracted?

### Regex Cross-Check

Zero-cost verification that extracted field values appear verbatim in the PDF:

```bash
python3 -m evals.regex_check \
  --predicted output/sebi_circular_references.json \
  --pdf sebi_circular.pdf
```

### When to use each

| Method | Catches | Cost |
|--------|---------|------|
| Manual ground truth | Everything including missed refs | High — manual work |
| LLM-as-Judge | Hallucinations, field errors, duplicates, metadata | 1 API call per reference |
| Regex check | Wrong circular numbers, dates, clauses | Free |

---

## Running Tests

Unit tests cover deduplication logic and evaluator math — no API key needed:

```bash
pytest tests/ -v
```

Expected output:

```
tests/test_agent.py::TestDeduplication::test_same_circular_number_merged PASSED
tests/test_agent.py::TestDeduplication::test_different_circulars_not_merged PASSED
tests/test_agent.py::TestDeduplication::test_title_based_dedup PASSED
tests/test_agent.py::TestDeduplication::test_longer_title_wins PASSED
tests/test_agent.py::TestDeduplication::test_empty_refs_ignored PASSED
tests/test_agent.py::TestEvaluator::test_perfect_match PASSED
tests/test_agent.py::TestEvaluator::test_no_predictions PASSED
tests/test_agent.py::TestEvaluator::test_extra_prediction_is_fp PASSED
tests/test_agent.py::TestEvaluator::test_title_fuzzy_match PASSED
tests/test_agent.py::TestNormHelpers::test_norm_strips_special_chars PASSED
tests/test_agent.py::TestNormHelpers::test_title_match_substring PASSED
tests/test_agent.py::TestNormHelpers::test_circnum_match PASSED
tests/test_agent.py::TestNormHelpers::test_circnum_no_match PASSED

13 passed in 0.13s
```

---

## Models and Providers

| Provider | Model | Setup | Notes |
|----------|-------|-------|-------|
| HuggingFace (default) | Qwen/Qwen2.5-72B-Instruct | `HF_TOKEN` env var | Free tier via serverless inference |
| Anthropic | claude-3-5-sonnet-20240620 | `ANTHROPIC_API_KEY` env var | Best accuracy |
| Google Gemini | gemini-2.0-flash | `GEMINI_API_KEY` env var | Generous free tier |

### Other models you can use on HuggingFace

Just change the model string in `agent/reference_extractor.py`:

```python
model="meta-llama/Llama-3.3-70B-Instruct"   # Best instruction following
model="Qwen/Qwen3-72B-Instruct"              # Latest Qwen
model="mistralai/Mistral-Small-3.1-24B-Instruct"  # Faster / cheaper
```

---

## Limitations

**v1 known issues:**

- **Scanned PDFs** — pdfplumber cannot extract text from image-only pages. Run the PDF through OCR (e.g. Adobe Acrobat, Tesseract) before passing to the agent
- **Long dense pages** — pages over 5,000 characters are truncated before being sent to the LLM. References in the truncated portion will be missed
- **Non-standard circular numbers** — the regex covers all known SEBI formats but may miss unusual patterns
- **Recall not 100%** — the LLM occasionally collapses multiple clause references into one. The verification pass mitigates this but doesn't eliminate it entirely
- **Evaluation needs manual effort** — the LLM judge catches hallucinations and duplicates automatically but cannot detect missed references without a ground truth file

---

## Scaling to All SEBI Circulars

To build a full knowledge graph across all SEBI circulars:

1. **Bulk ingestion** — scrape [sebi.gov.in](https://sebi.gov.in/legal/circulars.html) circular archive using their public listing. Store PDFs in S3 or GCS.

2. **Parallel processing** — process each circular concurrently using `asyncio` and the HuggingFace batch inference API. A 3-page circular takes ~15 seconds — 1,000 circulars would take ~4 hours single-threaded but under 30 minutes with 10 workers.

3. **Graph database** — migrate from in-memory `networkx` to **Neo4j** or **Amazon Neptune** for persistent, queryable storage. A Cypher query like `MATCH (a)-[:REFERENCES]->(b) WHERE b.title CONTAINS 'LODR' RETURN a` instantly finds all circulars referencing LODR regulations.

4. **Incremental updates** — monitor SEBI's circular RSS feed. Trigger the agent automatically on new PDFs so the graph stays current.

5. **Search layer** — index all document titles and circular numbers in **Elasticsearch** or **pgvector** for semantic search across the graph.

6. **Compliance dashboard** — build a UI where compliance officers can:
   - Enter a regulation name and see every circular that references it
   - Click a circular and trace its full dependency tree
   - Get alerts when a new circular modifies a document they are tracking

---

## License

MIT