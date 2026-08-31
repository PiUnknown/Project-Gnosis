# Project Gnosis

> Give it a GitHub URL. Get back a complete architectural map of the codebase.

**Version:** 1.0.1 (Public Release)
**Status:** Live (Agents 1–7 production-stable; all pipeline stages operational)
**Codename:** Project Gnosis
**Author:** Om Kumar Jha
**GitHub:** [github.com/PiUnknown](https://github.com/PiUnknown)
**LinkedIn:** [linkedin.com/in/omkumarjha043](https://linkedin.com/in/omkumarjha043)
**Production URL:** [gnosis.piunknown.dev](https://gnosis.piunknown.dev)

---

## What It Does

Code Archaeology is a multi-agent system that takes any GitHub repository URL and produces a structured, human-readable onboarding document for that codebase.

It reads every file, parses the syntax tree, maps dependencies between modules, scores complexity and tech debt, embeds code semantically, and then uses an LLM to generate natural language explanations of every major component. The final output is a Markdown document a senior engineer would have written if they had two weeks and the patience.

The tool does not require any configuration, API keys for the target repo (public repos only in v1), or prior knowledge of the codebase. You give it a URL. It figures out the rest.

---

## The Problem It Solves

**Undocumented codebases are the default, not the exception.**

When an engineer joins a project with no documentation:
- They spend 2 to 4 weeks exploring files without a map
- Senior engineers repeat the same onboarding explanations every hiring cycle
- New PRs break things that the new engineer did not know existed
- Questions like "where does X happen?" have no fast answer

The standard solutions: write docs (nobody does it), record loom videos (go stale), hold 1:1 walkthroughs (does not scale). None of these are maintainable.

Code Archaeology automates the mental model construction that every senior engineer performs when they explore an unfamiliar codebase. It reads what they would read, maps what they would map, and writes down what they would have explained verbally.

---

## Use Cases

**1. New engineer onboarding**
An engineering manager runs Code Archaeology on the codebase before a new hire starts. The new hire gets a structured document: what each module does, which files are critical, where to start reading, what to avoid touching without understanding first.

**2. Open-source contribution**
A developer wants to contribute to an open-source project but the repo has no architecture doc. They run the tool, get a component map in 3 minutes, and know exactly which files are relevant to the issue they want to fix.

**3. Code review due diligence**
A senior engineer is reviewing a large PR that touches files they are not familiar with. They run the tool scoped to those specific files to quickly understand the dependency surface before reviewing.

**4. Technical debt audit**
A tech lead wants to know which files are highest risk before a refactor. The complexity report surfaces: cyclomatic complexity per function, coupling scores, circular dependencies, parse failures, and a ranked list of files by risk level.

**5. Acquisition or integration due diligence**
A startup is integrating a third-party codebase or being acquired. Their engineers have days, not weeks, to understand the foreign codebase. Code Archaeology produces a structural map in minutes.

**6. Self-documentation**
A solo developer runs it on their own project after 6 months away. The tool reconstructs what they built and why, faster than reading their own code.

---

## Architecture

The system is a sequential multi-agent pipeline. Seven specialized agents share one state object. Each agent reads from state, performs one job, and writes its output back. No agent calls another agent. The orchestrator drives the sequence.

```
Input: GitHub Repository URL
            |
            v
  +-----------------------+
  |  Agent 1: Ingestion   |
  |  Clone / API fetch    |
  |  Detect languages     |
  |  Build file manifest  |
  +-----------------------+
            |
            v
  +-----------------------+
  |  Agent 2: AST Parser  |
  |  tree-sitter parsing  |
  |  Extract symbol tables|
  |  Functions/classes/   |
  |  imports/docstrings   |
  +-----------------------+
            |
            v
  +-----------------------+
  |  Agent 3: Dep Graph   |
  |  Cross-ref imports    |
  |  NetworkX DiGraph     |
  |  Detect cycles        |
  |  Compute centrality   |
  +-----------------------+
            |
            v
  +-----------------------+
  |  Agent 4: Complexity  |
  |  Cyclomatic complexity|
  |  Coupling metrics     |
  |  Tech debt flagging   |
  |  Risk level per file  |
  +-----------------------+
            |
            v
  +-----------------------+
  |  Agent 5: Code RAG    |
  |  AST-based chunking   |
  |  Code embeddings      |
  |  ChromaDB ingestion   |
  |  Retrieval interface  |
  +-----------------------+
            |
            v
  +-----------------------+
  |  Agent 6: Explain     |
  |  RAG retrieval        |
  |  Dependency context   |
  |  NVIDIA NIM inference |
  |  Per-component prose  |
  +-----------------------+
            |
            v
  +-----------------------+
  |  Agent 7: Doc Gen     |
  |  Synthesize all output|
  |  Write onboarding.md  |
  |  Write agent_context.md|
  |  Complexity JSON      |
  |  Graph HTML           |
  +-----------------------+
            |
            v
Output: onboarding.md + agent_context.md + complexity_report.json + dependency_graph.html
```

### Shared State

All agents communicate through a single dataclass that is initialized at pipeline start and passed through each agent:

```python
@dataclass
class ArchaeonState:
    repo_url: str
    repo_path: str = None
    file_manifest: list = field(default_factory=list)
    symbol_tables: dict = field(default_factory=dict)
    dependency_graph: Any = None       # nx.DiGraph
    circular_deps: list = field(default_factory=list)
    complexity_scores: dict = field(default_factory=dict)
    chroma_collection_name: str = None
    explanations: dict = field(default_factory=dict)
    final_doc: str = None
    complexity_report_json: str = None
    
    # --- Repository Analysis Tiers ---
    analysis_mode: str = "Full"
    files_discovered: int = 0
    files_analyzed: int = 0
    analyzed_paths: set = None
```

This pattern makes each agent independently testable: mock the state, test the agent, verify state after.

---

## Tech Stack

### Core Pipeline

**tree-sitter**
Language-agnostic AST parser. Parses Python, JavaScript, TypeScript, Go, Rust, Java, C, and C++ using the same Python API. Handles broken code gracefully: produces partial ASTs instead of throwing. Used in production by GitHub Copilot, Neovim, and VS Code. The only serious option for multi-language AST parsing in Python.

**NetworkX**
Python graph library. Used to construct the directed dependency graph: nodes are file paths, edges are import relationships. Provides `simple_cycles()` for circular dependency detection and centrality algorithms for identifying core files.

**radon**
Python-specific code metrics library. Computes cyclomatic complexity per function, raw LOC metrics, and maintainability index. For JS/TS/Go, cyclomatic complexity is computed by walking the tree-sitter AST and counting branch nodes.

**ChromaDB**
Embedded vector database. Stores code chunks as embeddings with metadata (file path, symbol name, language, complexity score). Requires SQLite >= 3.35 — on Azure, the system SQLite is too old and must be patched with `pysqlite3-binary` (see Deployment section).

**sentence-transformers (all-MiniLM-L6-v2)**
Embedding model that runs locally. Generates 384-dimensional vectors for code chunks. Free, no API required, fast on CPU. Upgrade path: `nomic-embed-code` for code-specialized embeddings in v2.

**NVIDIA NIM (meta/llama-3.1-8b-instruct)**
LLM inference via NVIDIA's serverless NIM API. Accessed through an OpenAI-compatible client pointed at the NVIDIA endpoint. Replaced Groq in August 2026. Default Model: `meta/llama-3.1-8b-instruct` (responds in 5-15s on the free tier; `meta/llama-3.3-70b-instruct` is supported via runtime environment override). Temperature set to 0.1 for consistent, accurate explanations.

### Infrastructure

**FastAPI & Distributed Task Queue (Redis + RQ)**
Async Python web framework. Exposes a POST endpoint `/analyze` that accepts `{ "repo_url": str, "options": {} }`, enqueues the job to Redis Queue (RQ), and returns a `job_id` for asynchronous status polling (`GET /jobs/{id}`). Heavy multi-agent pipeline workloads (AST parsing, vector embeddings, LLM calls) are executed out-of-process by dedicated background workers.

**GitPython**
Used to clone repositories programmatically. For public repos, the GitHub REST API is preferred (no disk I/O, faster).

**GitHub REST API & Concurrent Ingestion**
For public repositories: fetches the complete file tree and downloads file contents concurrently via a `ThreadPoolExecutor` (max 15 threads) pointing to `raw.githubusercontent.com`. This cuts down the time required to ingest a medium-sized codebase from minutes to seconds. Rate limit: 60 requests/hour unauthenticated, 5000/hour with a PAT.

**pyvis**
Renders the NetworkX dependency graph as an interactive HTML file using D3.js. Users can zoom, pan, and click nodes to see file details. Zero frontend code required.

### Frontend

**React 18 + TypeScript + Tailwind CSS + shadcn/ui**
Production SPA hosted on Vercel at [gnosis.piunknown.dev](https://gnosis.piunknown.dev).
Designed via Figma Make with the Nous Research Hermes Agent site as visual reference.
Deep electric blue (#1400FF) primary palette, IBM Plex Mono for UI chrome, Playfair Display serif for hero type, 0px border-radius everywhere.
Three screens: Landing → Job Progress (live polling) → Results (four-tab output viewer).

### Deployment

| Layer | Service | Details |
|---|---|---|
| Frontend | Vercel | Production SPA auto-deployed from GitHub on push to master |
| Web API | Azure App Service | FastAPI backend (eastasia region), auto-deployed via GitHub Actions |
| Queue & Store | Upstash Redis | Serverless persistent job store & RQ message broker (TLS) |
| Background Worker | Render | Dedicated worker service (`python -m src.api.worker`) pulling and executing analysis jobs |
| Domain | gnosis.piunknown.dev | Points to Vercel; API calls routed to Azure App Service |
| CI/CD | GitHub Actions | Automated build, test suite (407 tests), and deployment on push to master |

### Domain Coverage

This project spans the following AI and engineering domains:

| Domain | What This Project Covers |
|---|---|
| Agentic AI | Multi-agent pipeline, shared state orchestration, agent design patterns, deterministic vs non-deterministic agents |
| RAG | AST-based semantic chunking, code embeddings, ChromaDB semantic retrieval, context-augmented generation |
| Context Engineering | Context window management for large repos, hierarchical summarization via symbol tables, prompt construction and budgeting |
| Graph Engineering | Dependency graph construction, cycle detection, centrality analysis, topological sort |
| Static Code Analysis | tree-sitter AST parsing, cyclomatic complexity, coupling metrics, multi-language support |
| LLM Orchestration | NVIDIA NIM API, prompt design, temperature control, batching, rate limit handling with exponential backoff |
| Backend Engineering | FastAPI async pipeline, distributed task queue with Redis & RQ, dual-backend job store, persistent state management |
| Systems Design | Pipeline decomposition, shared state pattern, interface design between agents |
| DevOps | Azure App Service, Upstash Redis, Render worker, GitHub Actions CI/CD, Vercel hosting, custom domain, CORS |

---

## Chunking Strategy: Why Not Token-Based

Most RAG systems chunk documents every 512 or 1024 tokens. For code, this is wrong.

A 512-token cut might land in the middle of a function:

```python
def process_payment(user_id, amount, currency):
    # validate
    user = get_user(user_id)          # chunk ends here
    if not user.is_active:            # chunk starts here
        raise PaymentError(...)
```

The first chunk looks like a retrieval function. The second looks like a validation function. Neither is retrievable by a query about payment processing. The semantic unit was destroyed.

AST-based chunking preserves semantic units:

- One function = one chunk
- One class definition = one chunk (methods are separate chunks)
- Module-level imports + docstring = one chunk per file

tree-sitter makes this exact: it knows where every function starts and ends in every language. The chunk boundaries are precise, not approximate.

---

## Dependency Graph: What It Reveals

The dependency graph answers questions that are impossible to answer by reading files:

| Question | How the Graph Answers It |
|---|---|
| Which files are most critical? | High in-degree: many files import this one |
| What breaks if I change file X? | All files with a path to X in the graph |
| What does file X depend on? | Out-edges of X |
| Are there circular dependencies? | Cycles in the graph |
| What order should I read files in? | Topological sort of the graph |
| Which files are isolated? | Nodes with in-degree 0 and out-degree 0 |

This is structural knowledge that cannot be extracted by reading files one by one.

---

## Complexity Scoring: What Gets Flagged

The tool flags files and functions based on composite risk scores.

**Signals that increase risk:**

- Cyclomatic complexity above 10 for any function
- Average complexity above 6 across all functions in a file
- Parse failure (syntax error in the source)
- Circular dependency involvement
- Coupling score above threshold (too many unique imports)
- Very high line count with low comment ratio
- Functions with zero docstrings

**Output:** A ranked list of files by risk level (CRITICAL / HIGH / MEDIUM / LOW) with specific reasons for each rating.

---

## Project Structure

```
code-archaeology-agent/
├── README.md
├── PROJECT_SPEC.md
├── GLOSSARY.md
│
├── src/
│   ├── orchestrator.py          # Main pipeline runner
│   ├── state.py                 # ArchaeonState dataclass
│   │
│   ├── agents/
│   │   ├── ingestion.py         # Agent 1
│   │   ├── ast_parser.py        # Agent 2
│   │   ├── dependency_graph.py  # Agent 3
│   │   ├── complexity_scorer.py # Agent 4
│   │   ├── code_rag.py          # Agent 5
│   │   ├── explainability.py    # Agent 6
│   │   └── doc_generator.py     # Agent 7
│   │
│   ├── parsers/
│   │   ├── base.py              # Shared data models
│   │   ├── python_parser.py     # Python AST extraction
│   │   ├── js_parser.py         # JS/TS AST extraction
│   │   └── complexity.py        # Complexity computation
│   │
│   ├── utils/
│   │   ├── github_api.py        # GitHub REST API client
│   │   ├── tree_sitter_utils.py # Language parser initialization
│   │   ├── nvidia_client.py     # NVIDIA NIM API client wrapper with retry logic
│   │   ├── chunker.py           # AST-based code chunker
│   │   ├── embedder.py          # sentence-transformers wrapper
│   │   ├── retriever.py         # ChromaDB retrieval interface
│   │   ├── graph_utils.py       # Import resolution + pyvis rendering
│   │   └── filters.py           # File exclusion logic
│   │
│   └── api/
│       ├── main.py              # FastAPI web application
│       ├── models.py            # Pydantic request/response models
│       ├── job_store.py         # Dual-backend job store (Redis + memory fallback)
│       ├── queue.py             # RQ task queue manager & executor fallback
│       ├── worker.py            # Standalone distributed background worker
│       └── pipeline_runner.py   # API-specific pipeline runner
│
├── frontend/                    # React 18 + TypeScript + Tailwind
│   ├── src/
│   │   ├── pages/               # LandingPage, JobProgressPage, ResultsPage
│   │   ├── components/          # TopBar, RiskBadge, LoadingSpinner, ErrorBanner
│   │   ├── lib/                 # api.ts, download.ts
│   │   └── types/               # api.ts (TypeScript interfaces)
│   └── ...
│
├── tests/
│   ├── test_ingestion.py
│   ├── test_ast_parser.py
│   ├── test_dependency_graph.py
│   ├── test_complexity_scorer.py
│   ├── test_code_rag.py
│   ├── test_explainability.py
│   ├── test_doc_generator.py
│   ├── test_api.py
│   └── fixtures/
│       └── sample_repo/
│
├── .github/
│   └── workflows/
│       └── azure-deploy.yml     # GitHub Actions → Azure App Service
│
├── outputs/                     # Generated docs (gitignored)
│   ├── onboarding.md
│   ├── complexity_report.json
│   └── dependency_graph.html
│
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Build Order

Each phase has a concrete deliverable. Current production status is shown.

| Phase | Description | Status |
|---|---|---|
| 1 | Ingestion Agent — file manifest from GitHub API | ✅ Production |
| 2 | AST Parser Agent — symbol tables via tree-sitter | ✅ Production |
| 3 | Dependency Graph Agent — NetworkX DiGraph, cycle detection | ✅ Production |
| 4 | Complexity Scorer Agent — radon, risk levels | ✅ Production |
| 5 | Code RAG Agent — ChromaDB + sentence-transformers | ✅ Production |
| 6 | Explainability Agent — NVIDIA NIM LLM inference | ✅ Production |
| 7 | Doc Generator Agent — synthesizes all output | ✅ Production |
| 8 | Distributed Backend & Queue — FastAPI (Azure) + Redis Queue (Upstash) + Worker (Render) | ✅ Production |
| 9 | React Frontend — three-screen SPA (Figma Make design) | ✅ Production (Vercel) |

---

## Deployment

### Production Architecture

```
User
  ↓
Vercel (gnosis.piunknown.dev)
React Frontend
  ↓ (POST /analyze)
Azure App Service (eastasia)
FastAPI Web API
  ↓ (Enqueues job & writes initial state)
Upstash Redis (Serverless TLS)
Persistent Job Store & RQ Queue
  ↓ (Pulls & processes job out-of-process)
Render Background Worker
Pipeline Agents 1–7 (GitHub API → AST → Graph → Radon → ChromaDB → NVIDIA NIM)
  ↓ (Writes progress & final results)
Upstash Redis
  ↓ (Polled by FastAPI via GET /jobs/:id)
Vercel Frontend Visualization
```

### Environment Setup (Local Development)

```bash
git clone https://github.com/PiUnknown/Project-Gnosis
cd code-archaeology-agent
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Add NVIDIA_API_KEY to .env       ← NVIDIA NIM API key
# Add GITHUB_TOKEN for higher rate limits (optional)
```

**Running the FastAPI server locally:**
```bash
uvicorn src.api.main:app --reload --port 8000
```

**Running the frontend locally:**
```bash
cd frontend
npm install
npm run dev                     # Runs on localhost:5173
```

**Running a full CLI analysis:**
```bash
python run.py --url https://github.com/tiangolo/fastapi --output ./outputs
```

### Azure App Service Deployment

The backend deploys automatically via GitHub Actions on every push to `master`.

The workflow in `.github/workflows/azure-deploy.yml`:
1. Checks out the repository
2. Sets up Python environment
3. Installs dependencies
4. Deploys to Azure App Service

Manual deployment if needed:
```bash
az webapp up --name project-gnosis-api --resource-group gnosis-rg --runtime PYTHON:3.11
```

### Critical Azure Fix: SQLite for ChromaDB

Azure App Service ships with SQLite 3.31, but ChromaDB requires SQLite >= 3.35. The fix is applied at the top of `src/api/main.py` before any ChromaDB import:

```python
# Must run before any chromadb import — Azure SQLite is too old
__import__("pysqlite3")
import sys
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
```

And in `requirements.txt`:
```
pysqlite3-binary
```

Without this fix, Agent 5 crashes immediately with `unsupported sqlite3 version`. With the fix, Agent 5 reaches the embedding stage.

### Environment Variables

| Variable | Required For | Description |
|---|---|---|
| `NVIDIA_API_KEY` | Agent 6 (Explainability) | NVIDIA NIM serverless API key |
| `GITHUB_TOKEN` | All agents (higher rate limit) | GitHub PAT for 5000 req/hr vs 60 |

For production on Azure, these are set via Azure App Service Application Settings, not `.env` files.

---

## Resolved Investigations: Agent 5 Embedding Stall

**Observed behavior:** The pipeline previously progressed cleanly through Agents 1–4, but Agent 5 stalled during the embedding phase on Azure App Service with no further output (e.g., when embedding ~700 chunks from 41 files).

**Root Cause:** sentence-transformers' CPU-based embedding of all chunks in a single large batch ran into memory limits and request timeouts on constrained App Service plans due to large numpy allocations.

**Resolution:**
- Configured chunk processing in streaming batches (`STREAM_BATCH_SIZE = 128` in `code_rag.py`) to reduce peak memory pressure.
- Added explicit garbage collection (`gc.collect()`) after loading and embedding each batch of chunks to release memory immediately.
- Added per-batch logging in `embedder.py` to trace progress and ensure consistent throughput.

---

## Output Example

Running on a mid-sized FastAPI project produces a document with this structure:

```markdown
# fastapi-users — Architecture Overview
Generated by Code Archaeology Agent | 2024-01-15

## Project Summary
fastapi-users is an authentication library for FastAPI applications.
It provides user management, OAuth2, and JWT handling out of the box.

## Repository Statistics
- Total files analyzed: 87
- Languages: Python (94%), TOML (4%), Markdown (2%)
- Total functions: 312
- High-risk files: 4
- Circular dependencies: 0

## Architecture Map
fastapi_users/
  router/         ← imported by 12 files (CRITICAL)
  db/             ← imported by 8 files
  authentication/ ← imports 6 modules, imported by 9

## Core Components

### fastapi_users/router/__init__.py
**Responsibility:** The central routing hub. Assembles all sub-routers
(auth, register, verify, reset) and exposes them as a single FastAPI
APIRouter. New engineers should read this file after understanding the
authentication module.

**Depends on:** authentication, db, schemas
**Depended on by:** 12 files
**Risk level:** HIGH (avg complexity: 8.2, coupling: 6)

## Tech Debt Report
- fastapi_users/db/sqlalchemy.py: cyclomatic complexity 23 in `get_user`
- fastapi_users/router/oauth.py: circular import with oauth_client.py

## Suggested Reading Order
1. fastapi_users/schemas.py       — data models, understand the domain
2. fastapi_users/db/__init__.py   — database abstraction
3. fastapi_users/authentication/  — core logic
4. fastapi_users/router/          — how it all connects
```

---

## Design Decisions and Tradeoffs

**Sequential pipeline vs parallel DAG**
v1 runs agents sequentially. Agents 3, 4, and 5 could run in parallel (all depend on Agent 2's output but not on each other). Sequential is simpler to debug and the total runtime is acceptable for repos under 500 files. Parallel execution is a v2 optimization.

**Local embeddings vs API embeddings**
`all-MiniLM-L6-v2` runs locally, no API cost, no rate limits, works offline. OpenAI's `text-embedding-3-small` produces better code embeddings but costs money and requires network access. The local model is accurate enough for v1. A swap to the NVIDIA NIM embedding endpoint is the natural v2 path given the existing NVIDIA integration.

**ChromaDB vs FAISS**
ChromaDB: persistent, metadata filtering, easier API. FAISS: faster at scale, no metadata filtering. For repos under 50k chunks, ChromaDB is fine. FAISS becomes relevant at 500k+ chunks (very large monorepos).

**NVIDIA NIM over Groq**
Groq was the original inference provider (free tier, llama-3.3-70b-versatile). Migrated to NVIDIA NIM in August 2026. NVIDIA NIM provides the same OpenAI-compatible API surface, the same model family, and integrates cleanly with the existing OpenAI client pointed at the NVIDIA endpoint. To optimize performance and avoid cold-start delays on the free tier, the default model is configured as `meta/llama-3.1-8b-instruct` (5-15s response), with the option to use `meta/llama-3.3-70b-instruct` via runtime environment variables.

**Azure App Service over Render**
Render was the original deployment target. Migrated to Azure App Service in August 2026. Azure provides GitHub Actions integration, better uptime SLAs, and is the correct choice for a project targeting enterprise engineering teams. The main operational complexity introduced was the SQLite version issue (fixed with pysqlite3-binary).

**React via Figma Make over Streamlit**
Streamlit produces a working demo in 30 minutes but looks like a data science notebook. Project Gnosis is a developer tool being presented in interviews and on LinkedIn. A React frontend with the Nous Research Hermes Agent site as visual reference signals production intent. The Figma-first workflow (design in Figma Make, implement in React) also produces a standalone design deliverable.

**In-memory job store over Redis**
All job state lives in a module-level dict with a threading lock. Jobs are lost on server restart. This is acceptable for v1 (single-server, development tool with short-lived jobs). A Redis-backed store is the v2 upgrade path and a one-file change.

---

## Limitations (v1)

- Public GitHub repos only (private repo support requires GitHub PAT, in v2)
- **Repository Size Limits (Dynamic Tiers):**
  - Repositories are dynamically classified based on file count into four tiers: *Full* ($\le 300$ files), *Full (Warning)* ($301 - 1000$ files), *Sampled* ($1001 - 3000$ files), or *Rejected* ($> 3000$ files).
  - Under *Sampled* mode, analysis is restricted to a selected subset of the most critical files to respect LLM contexts and rate ceilings.
- **Languages supported:** Python, JavaScript, TypeScript, Go, Rust, Java, C, C++
- Explanation quality degrades for deeply obfuscated or minified code
- The generated document is a snapshot: it does not update when the repo changes

---

## Roadmap

**v1.0 — Distributed Production Release**
*Current status: Completed & Live.*
- All 7 archaeology agents working end-to-end.
- Multi-language AST parsing support: Python, JavaScript, TypeScript, Go, Rust, Java, C, and C++ via Tree-Sitter grammars.
- Dynamic repository sizing tiers (Full, Warning, Sampled, and Rejection modes).
- Multi-threaded concurrent file ingestion (15 concurrent threads).
- Streaming batch embeddings (SentenceTransformers + ChromaDB) with active memory cleanup.
- Distributed Task Queue with Redis (Upstash) and dedicated background worker processes (Render).
- Full-stack production deployment: React SPA on Vercel, FastAPI Web API on Azure App Service.

**v2.0 — Product & Integration Features**
- Private repository support via GitHub App / OAuth authentication.
- GitHub Action integration (auto-generate or update onboarding docs on PR or push).
- Changelog-aware incremental analysis (analyzing only diffs since the last run).
- Interactive Codebase Chat (asking follow-up questions to the RAG vector store).
- Team collaboration (annotating and exporting generated documentation).

**v3.0 — Autonomous Agent Loop**
- Replace the linear pipeline with an autonomous agent loop: the explainability agent detects gaps in its understanding, re-queries ChromaDB, and iterates until high confidence is achieved.

---

## Why This Exists

This is a portfolio project built to demonstrate production-level AI engineering skills: not just calling an LLM API, but designing a system where multiple specialized agents work together, each with clear interfaces, testable in isolation, grounded by retrieval, and producing output that is genuinely useful to a real user.

The problem is real. The architecture reflects how a senior engineer would actually approach it. Every design decision has a documented rationale. Every component can be explained in an interview. The project is deployed, publicly accessible at [gnosis.piunknown.dev](https://gnosis.piunknown.dev), with the backend hosted on **Microsoft Azure App Service** and the frontend hosted on **Vercel**.

---

## License

This project is **Dual-Licensed**:

1. **Open Source (AGPL-3.0)**: For open-source developers, researchers, and hobbyists, the project is licensed under the [GNU Affero General Public License v3.0](LICENSE). Anyone is free to use, modify, and distribute this software, provided that any network service built on it also publishes its full source code.
2. **Commercial License**: For companies and commercial entities who want to integrate Project Gnosis into closed-source commercial applications or run it without copyleft restrictions, commercial licenses are available. 

To inquire about commercial licensing, please contact the author.

