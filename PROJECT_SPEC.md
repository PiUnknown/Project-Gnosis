# PROJECT SPEC: Code Archaeology Agent

**Codename:** Archaeon / Project Gnosis
**Version:** 0.1.0
**Status:** In Development (Agents 1–7 production-stable; all pipeline stages operational)
**Author:** Om Kumar Jha
**GitHub:** github.com/PiUnknown
**Production URL:** gnosis.piunknown.dev
**Last Updated:** August 2026

---

## What We Are Building

A multi-agent system that accepts a GitHub repository URL and produces a structured, human-readable onboarding document for that codebase. No manual reading required. The agent reads the repo, understands its architecture, identifies risks, and writes the documentation a senior engineer would have written if they had the time.

The target audience for the output is an engineer joining a project with zero context.

---

## The Core Problem

Undocumented codebases are the norm, not the exception. When an engineer joins a project:

- They spend 2 to 4 weeks exploring files with no map
- There is no answer to "where does X happen?"
- Senior engineers repeat the same onboarding explanations every cycle
- PRs from new engineers break things they did not know existed

Code Archaeology automates the construction of that mental model. It does what a senior engineer does when they explore an unfamiliar codebase, and it writes it down.

---

## Deployment Architecture

### Production Stack

```
User
  ↓
Vercel
React Frontend (gnosis.piunknown.dev)
  ↓
Azure App Service (eastasia region)
FastAPI Backend
  ↓
Pipeline Agents 1–7
  ↓
GitHub API → tree-sitter → NetworkX → radon → ChromaDB → sentence-transformers → NVIDIA NIM
  ↓
Generated onboarding document
```

### Services

| Component | Service | URL / Identifier |
|---|---|---|
| Frontend | Vercel | gnosis.piunknown.dev |
| Backend | Azure App Service (eastasia) | project-gnosis-api-xxxxxxxx.eastasia-01.azurewebsites.net |
| CI/CD | GitHub Actions | Deploys to Azure on push to master |
| LLM Inference | NVIDIA NIM Serverless | meta/llama-3.1-8b-instruct |

### Deprecated Services
- **Render** — previously hosted the backend. No longer used. Fully migrated to Azure App Service.

### CORS Configuration
Production CORS allows `https://gnosis.piunknown.dev`.
Local development CORS allows `http://localhost:3000` and `http://localhost:5173`.

---

## Agent Architecture

The system uses a sequential multi-agent pipeline. Each agent has a single responsibility. All agents share one state object. No agent calls another agent directly. The orchestrator manages the sequence.

```
GitHub URL
    |
    v
[Agent 1: Ingestion Agent]
    - Clone repo or fetch via GitHub API
    - Detect languages
    - Build file manifest
    |
    v
[Agent 2: AST Parser Agent]
    - Parse every file via tree-sitter
    - Extract symbol tables (functions, classes, imports)
    |
    v
[Agent 3: Dependency Graph Agent]
    - Cross-reference imports across files
    - Build directed dependency graph (NetworkX DiGraph)
    - Detect circular dependencies
    |
    v
[Agent 4: Complexity Scorer Agent]
    - Cyclomatic complexity per function
    - Coupling metrics per file
    - Tech debt flagging
    |
    v
[Agent 5: Code RAG Agent]
    - Chunk code at AST boundaries (not token boundaries)
    - Embed chunks using sentence-transformers (all-MiniLM-L6-v2)
    - Store in ChromaDB with metadata
    |
    v
[Agent 6: Explainability Agent]
    - For each major component: retrieve context from ChromaDB
    - Build explanation prompt with dependency context
    - Call NVIDIA NIM LLM (meta/llama-3.1-8b-instruct)
    - Generate natural language explanation per component
    |
    v
[Agent 7: Doc Generator Agent]
    - Synthesize all outputs into structured Markdown
    - Output: onboarding doc (onboarding.md), agent context doc (agent_context.md), complexity report, dependency map
    |
    v
Final Output: onboarding.md
```

---

## Shared State Object

Every agent reads from and writes to this. It is a Python dataclass passed through the pipeline.

```python
@dataclass
class ArchaeonState:
    # Input
    repo_url: str
    repo_path: str = None

    # Agent 1 output
    file_manifest: list = field(default_factory=list)
    # Each entry: {path, language, line_count, size_bytes}

    # Agent 2 output
    symbol_tables: dict = field(default_factory=dict)
    # key: file_path, value: {functions, classes, imports, docstrings}

    # Agent 3 output
    dependency_graph: Any = None    # nx.DiGraph
    circular_deps: list = field(default_factory=list)
    circular_nodes: set = field(default_factory=set)
    graph_stats: dict = field(default_factory=dict)
    topological_order: list = field(default_factory=list)

    # Agent 4 output
    complexity_scores: dict = field(default_factory=dict)
    # key: file_path, value: ComplexityScore dataclass

    # Agent 5 output
    chroma_collection_name: str = None

    # Agent 6 output
    explanations: dict = field(default_factory=dict)
    # key: file_path, value: explanation string

    # Agent 7 output
    final_doc: str = None
    complexity_report_json: str = None

    # --- Repository Analysis Tiers ---
    analysis_mode: str = "Full"
    files_discovered: int = 0
    files_analyzed: int = 0
    analyzed_paths: Optional[set] = None
```

---

## Agent Specifications

### Agent 1: Ingestion Agent

**Input:** GitHub URL (public repo)
**Output:** file_manifest, repo_path written to state

**Responsibilities:**
- Clone using GitPython or raw GitHub API (API preferred for speed)
- **Concurrent Content Ingestion:** Fetch raw file contents concurrently using a `ThreadPoolExecutor` (max 15 threads) from `raw.githubusercontent.com` to speed up ingestion.
- Walk the file tree, collect path, extension, size, line count
- Detect language per file using extension mapping + tree-sitter fallback
- Filter out: node_modules, .git, __pycache__, dist, build, .lock files, binary files

**Repository Analysis Tiers (Dynamic Mode):**
- **Full Mode:** $\le 300$ files. Full analysis pipeline.
- **Full (Warning) Mode:** $301 - 1000$ files. Runs full analysis but triggers a UI warning for high token usage.
- **Sampled Mode:** $1001 - 3000$ files. Ingests all files but limits parsing, complexity scoring, and LLM explanation to a selected subset of the most critical files (ranked by centrality, functions, and classes) to stay within token budgets.
- **Rejection Mode:** $> 3000$ files. Request is rejected with a `400 Bad Request` to protect resource usage.

---

### Agent 2: AST Parser Agent

**Input:** file_manifest, raw file contents
**Output:** symbol_tables written to state

**Responsibilities:**
- Initialize tree-sitter parser for each detected language
- Parse each file into an AST
- Walk the AST and extract functions, classes, imports, docstrings
- Flag files that fail to parse (syntax error signal)

**Supported languages in v1:** Python, JavaScript, TypeScript, Go, Rust, Java, C, C++

---

### Agent 3: Dependency Graph Agent

**Input:** symbol_tables
**Output:** dependency_graph, circular_deps, graph_stats, topological_order

**Responsibilities:**
- For each file, read its import statements
- Map imports to internal files using the file manifest
- Build a directed edge: if A imports B, edge goes A → B
- Detect circular dependencies using `nx.simple_cycles()`
- Compute PageRank centrality for identifying core files
- Compute topological sort for suggested reading order

---

### Agent 4: Complexity Scorer Agent

**Input:** file_manifest, symbol_tables
**Output:** complexity_scores written to state

**Metrics per file:**
- Avg and max cyclomatic complexity across all functions
- Number of functions and average function length
- Coupling score: sourced from graph_stats['out_degree'] (unique internal imports)
- Risk level: LOW / MEDIUM / HIGH / CRITICAL based on composite OR-logic scoring

**For Python:** radon library (`radon.complexity.cc_visit`)
**For JS/TS:** custom tree-sitter AST branch counter

**Risk thresholds:**
- Max complexity >= 21: CRITICAL
- Max complexity >= 11: HIGH
- Avg complexity >= 10: HIGH
- Parse failure: CRITICAL
- Circular dependency involvement: CRITICAL
- Coupling >= 8 unique internal modules: HIGH

---

### Agent 5: Code RAG Agent

**Input:** file_manifest, symbol_tables, complexity_scores
**Output:** populated ChromaDB collection, collection_name written to state

**Chunking strategy:**
- Chunk at function level: each function is one chunk
- Chunk at class level: class definition + docstring (methods separate)
- File-level chunk: imports + module docstring per file
- Do NOT chunk by token count. Semantic unit chunking only.

**Metadata per chunk:**
```python
{
    "file_path": str,
    "symbol_name": str,
    "symbol_type": str,        # "function", "class", "module"
    "language": str,
    "line_start": int,
    "line_end": int,
    "complexity": float,       # -1.0 sentinel for None
    "risk_level": str          # "UNKNOWN" sentinel for None
}
```

**Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, runs locally)
**Vector store:** ChromaDB, persistent client, cosine similarity

**Azure SQLite fix (required):**
ChromaDB requires SQLite >= 3.35. Azure App Service ships with 3.31.
Apply at top of `src/api/main.py` BEFORE any ChromaDB import:
```python
__import__("pysqlite3")
import sys
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
```
And add `pysqlite3-binary` to `requirements.txt`.

**Resolved (August 2026):**
Agent 5 previously stalled during the embedding phase on Azure due to memory limits/timeouts.
This was resolved by processing chunks in streaming batches (`STREAM_BATCH_SIZE = 128`) and running garbage collection (`gc.collect()`) after loading and embedding each batch to reduce peak memory pressure.

---

### Agent 6: Explainability Agent

**Input:** dependency_graph, ChromaDB collection, complexity_scores
**Output:** explanations dict written to state

**LLM Provider:** NVIDIA NIM Serverless (migrated from Groq, August 2026)
**Model:** `meta/llama-3.1-8b-instruct` (default)
**Client:** OpenAI-compatible client pointed at NVIDIA NIM endpoint
**Temperature:** 0.1

**File selection:** Priority tiers by risk level and graph in-degree.
- Tier 0: CRITICAL risk files
- Tier 1: In-degree >= 5 (structurally critical)
- Tier 2: HIGH risk files
- Tier 3: In-degree >= 2
- Tier 4: MEDIUM risk files
Cap: 20 files per run (configurable via `max_explanations` parameter).

**Context budget:**
- System prompt: ~500 tokens
- Retrieved code chunks: ~2000 tokens (8000 characters)
- Dependency context: ~500 tokens
- Response: 800 tokens max

**Rate limiting:** 2.5 seconds between NVIDIA NIM calls. Exponential backoff (1s, 2s, 4s, 8s) on 429 responses.

---

### Agent 7: Doc Generator Agent

**Input:** full state object
**Output:** final_doc (onboarding.md), agent_context_md (agent_context.md)

**Generated document sections:**
1. Header — repo name, generation date, GitHub URL, branch
2. Project Summary — synthesized opening + language stats + risk summary
3. Repository Statistics — Markdown table of key metrics
4. Architecture Map — ASCII bar chart of top 15 files by in-degree
5. Core Components — per-file explanations with dependency context
6. Tech Debt Report — circular deps, CRITICAL files, complex functions, parse failures
7. Suggested Reading Order — topological sort, or cycle warning if cycles exist
8. Footer — generation timestamp, pipeline summary

Each section is built by an independent function wrapped in try/except. One section failing never prevents the rest from rendering.

---

## FastAPI Backend

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | /analyze | Submit repo URL for analysis. Returns job_id. |
| GET | /jobs/{job_id} | Poll job status, current phase, progress %. |
| GET | /jobs/{job_id}/result | Fetch complete result when status == "complete". |
| DELETE | /jobs/{job_id} | Delete a job from the store. |
| GET | /jobs | List all jobs (lightweight summaries). |
| GET | /health | Health check. |
| GET | / | API info and endpoint list. |

**Job status values:** queued → running → complete / failed

**Progress phases (in order):**
metadata → ingestion → ast_parser → dependency_graph → complexity_scorer →
code_rag → explainability → doc_generator

**Thread pool:** `concurrent.futures.ThreadPoolExecutor(max_workers=2)`
Pipeline tasks are CPU/IO bound and run in worker threads, keeping the async event loop free for status polling.

**Job store:** In-memory dict with `threading.Lock`. Jobs are lost on server restart. Redis upgrade path in v2.

---

## Frontend Architecture

### Design System

**Colors:**
- Primary background: #1400FF (electric blue — Nous Research reference)
- Secondary/panel: #0F00CC
- Content area (light tabs): #F0F0FF
- Text / accent: #FFFFFF
- Input fill: #FFFFFF (white field, blue text inside)
- No gray, no black, no green in the palette

**Typography:**
- Playfair Display — hero headings and progress display number. Weight 400. ALL CAPS.
- IBM Plex Mono — all UI chrome: labels, buttons, nav, tabs, file paths, agent names, status, metadata.
- Inter — body copy, descriptions, markdown prose.

**Components:**
- Border-radius: 0px everywhere. Sharp corners. No exceptions.
- Borders: 1px solid rgba(255,255,255,0.25) on blue backgrounds.
- No drop shadows. No gradients. No glassmorphism.

**Classical figure:**
- Athena SVG engraving on right half of Landing and Progress pages.
- Rendered in #3D28FF (lighter blue) at 0.28 opacity. Monochromatic.

### Screens

**Landing ("/")**
Split layout: left content column (URL input, options, CTA), right Athena figure.
Submit: POST /analyze → navigate to /jobs/:jobId.
Validation: URL must contain github.com with owner/repo structure.

**Job Progress ("/jobs/:jobId")**
Left column: 7-agent pipeline list (step number, name, status: QUEUED / RUNNING··· / COMPLETE ✓).
Right column: large Playfair Display percentage ("67%"), 1px progress bar, current phase name.
Polling: GET /jobs/:jobId every 2000ms via setInterval stored in useRef (not useState). Cleanup on unmount.
Auto-navigate to results after 1500ms delay once status === "complete".

**Results ("/jobs/:jobId/results")**
Header: repo name, branch, stats row, risk distribution pills.
Four tabs (IBM Plex Mono uppercase, white underline on active):
- ONBOARDING DOC — react-markdown on #F0F0FF, blue headings, Playfair h1
- DEPENDENCY GRAPH — top files table (in-degree, risk), reading order list
- COMPLEXITY REPORT — sortable/filterable table, risk badges
- RAW OUTPUT — collapsible JSON panels with copy buttons
Sticky download bar: three outlined-white buttons (onboarding.md, complexity_report.json, dependency_graph.json).

### Tech Stack

| Component | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Styling | Tailwind CSS |
| Components | shadcn/ui |
| Routing | react-router-dom v6 |
| Markdown | react-markdown + remark-gfm |
| Typography | @tailwindcss/typography |
| HTTP | Fetch API (no axios) |
| State | useState + useRef (no Redux/Zustand) |
| Hosting | Vercel |
| Domain | gnosis.piunknown.dev |

---

## Tech Stack Summary

| Component | Library | Reason |
|---|---|---|
| Repo ingestion | GitPython + GitHub REST API | GitPython for clones, API for speed on public repos |
| AST parsing | tree-sitter | Language-agnostic, 50+ languages, fast, handles broken code |
| Graph construction | NetworkX | Standard Python graph library, DiGraph + PageRank support |
| Complexity analysis | radon (Python), custom AST walker (JS/TS) | radon is the standard for Python metrics |
| Vector store | ChromaDB + pysqlite3-binary | Lightweight, local; pysqlite3-binary required on Azure |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Free, runs locally, no API cost |
| LLM inference | NVIDIA NIM (meta/llama-3.1-8b-instruct) | OpenAI-compatible API, responds faster on free tier than 70b |
| Backend | FastAPI + Azure App Service | Async, clean; Azure for production reliability |
| CI/CD | GitHub Actions | Auto-deploys to Azure on push to master |
| Frontend | React 18 + Tailwind + shadcn/ui | Production SPA; Figma Make designed |
| Frontend hosting | Vercel | Auto-deploys; custom domain support |
| Graph visualization | pyvis | Renders interactive HTML graph |
| Testing | pytest | All agents have independent test suites |

---

## Build Phases

| Phase | Scope | Deliverable | Status |
|---|---|---|---|
| 1 | Ingestion Agent | File manifest from GitHub API | ✅ Complete |
| 2 | AST Parser Agent | Symbol tables for Python + JS/TS | ✅ Complete |
| 3 | Dependency Graph Agent | NetworkX DiGraph + cycle detection | ✅ Complete |
| 4 | Complexity Scorer Agent | Risk-scored complexity report | ✅ Complete |
| 5 | Code RAG Agent | ChromaDB collection + retrieval interface | ✅ Complete |
| 6 | Explainability Agent | Per-file prose via NVIDIA NIM | ✅ Complete |
| 7 | Doc Generator Agent | Full onboarding.md synthesis | ✅ Complete |
| 8 | FastAPI Backend | Async job queue, polling, results API | ✅ Complete (Azure) |
| 9 | React Frontend | Three-screen SPA, Figma Make design | ✅ Complete (Vercel) |

---

## Inputs and Outputs

**Primary input:** GitHub repository URL (public)
**Optional inputs:**
- GitHub personal access token (for private repos or higher rate limits)
- `max_explanations` (int, 0–100): cap on LLM calls per run
- `skip_llm` (bool): skip Agent 6 entirely, produce doc without prose explanations

**Primary output:** `onboarding.md`
**Secondary outputs:**
- `complexity_report.json`
- `dependency_graph.html` (interactive pyvis visualization)
- `symbol_tables.json`
- `graph_data.json`
- `explanations.json`

---

## Constraints and Risk Factors

| Constraint | Status | Mitigation |
|---|---|---|
| Large repos (10k+ files) | Known limitation | Sampling: analyze top 200 by in-degree centrality |
| LLM context window | Handled | RAG ensures only relevant chunks go into each LLM call |
| NVIDIA NIM rate limits | Managed | 2.5s sleep between calls + exponential backoff on 429 |
| tree-sitter language coverage | Known gap | Graceful fallback: skip, treat as blob, use filename heuristics |
| Private repos | Not supported in v1 | GitHub PAT support in v2 |
| Generated code (minified JS) | Filtered | Skip by file size and extension |
| Azure SQLite too old for ChromaDB | **Fixed** | pysqlite3-binary + sys.modules swap in main.py |
| Agent 5 embedding stall on Azure | **Fixed** | Switch to streaming batches of 128 and garbage collection to reduce memory pressure |
| In-memory job store lost on restart | Known limitation | Redis upgrade in v2 |

---

## LLM Provider Migration History

| Period | Provider | Model | Notes |
|---|---|---|---|
| Original | Groq | llama-3.3-70b-versatile | Free tier, OpenAI-compatible |
| August 2026 | NVIDIA NIM | meta/llama-3.3-70b-instruct | Same OpenAI-compatible client, new endpoint + key |

**Migration approach:** The utility client was updated to point the OpenAI client at the NVIDIA NIM endpoint, implemented as `nvidia_client.py`. The default model was set to `meta/llama-3.1-8b-instruct` to avoid cold-start delays. No other changes to the agent prompts, temperature, or retry logic were required.

---

## Success Criteria

- Running against a repo Om has not read before produces a document that accurately describes what the codebase does
- Dependency graph matches actual import relationships when manually spot-checked
- Complexity scores flag files that are actually complex when Om reads them
- Agent 5 completes embedding without stalling on Azure App Service
- End-to-end runtime under 8 minutes for a repo with 200–500 files
- Demo accessible at gnosis.piunknown.dev for live demonstration in interviews

---

## What This Project Demonstrates (Interview Signal)

1. **Agentic AI** — Multi-agent pipeline with shared state, sequential orchestration, agent design patterns
2. **RAG** — AST-based semantic chunking (not naive token chunking), code embeddings, ChromaDB retrieval
3. **Context Engineering** — Selective context construction, hierarchical summarization, managing repos exceeding context windows
4. **Graph Engineering** — Dependency graph construction, cycle detection, centrality analysis, graph traversal
5. **Static Code Analysis** — tree-sitter AST parsing, cyclomatic complexity, coupling metrics, tech debt detection
6. **LLM Orchestration** — NVIDIA NIM API integration, prompt construction, temperature tuning, batching, provider migration
7. **Backend Engineering** — FastAPI async pipeline, stateful request handling, job queuing, thread pool execution
8. **Systems Design** — Pipeline decomposition, shared state pattern, interface design between agents
9. **DevOps / Cloud** — Azure App Service deployment, GitHub Actions CI/CD, Vercel frontend hosting, custom domain, CORS, SQLite compatibility fix

Every architectural decision in this project has a documented "why" that Om can explain in an interview. The project is live at gnosis.piunknown.dev.