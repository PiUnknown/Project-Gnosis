# Code Archaeology Agent

> Give it a GitHub URL. Get back a complete architectural map of the codebase.

**Status:** In Development  
**Author:** Om Kumar Jha  
**GitHub:** [github.com/PiUnknown](https://github.com/PiUnknown)  
**LinkedIn:** [linkedin.com/in/omkumarjha043](https://linkedin.com/in/omkumarjha043)

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
  |  NVIDIA NIM inference  |
  |  Per-component prose  |
  +-----------------------+
            |
            v
  +-----------------------+
  |  Agent 7: Doc Gen     |
  |  Synthesize all output|
  |  Write onboarding.md  |
  |  Complexity JSON      |
  |  Graph HTML           |
  +-----------------------+
            |
            v
Output: onboarding.md + complexity_report.json + dependency_graph.html
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
```

This pattern makes each agent independently testable: mock the state, test the agent, verify state after.

---

## Tech Stack

### Core Pipeline

**tree-sitter**  
Language-agnostic AST parser. Parses Python, JavaScript, TypeScript, Go (and 50+ others) using the same Python API. Handles broken code gracefully: produces partial ASTs instead of throwing. Used in production by GitHub Copilot, Neovim, and VS Code. The only serious option for multi-language AST parsing in Python.

**NetworkX**  
Python graph library. Used to construct the directed dependency graph: nodes are file paths, edges are import relationships. Provides `simple_cycles()` for circular dependency detection and centrality algorithms for identifying core files.

**radon**  
Python-specific code metrics library. Computes cyclomatic complexity per function, raw LOC metrics, and maintainability index. For JS/TS/Go, cyclomatic complexity is computed by walking the tree-sitter AST and counting branch nodes.

**ChromaDB**  
Embedded vector database. Stores code chunks as embeddings with metadata (file path, symbol name, language, complexity score). Runs as a Python library with no server. Persistent client mode saves the collection to disk between runs.

**sentence-transformers (all-MiniLM-L6-v2)**  
Embedding model that runs locally. Generates 384-dimensional vectors for code chunks. Free, no API required, fast on CPU. Upgrade path: `nomic-embed-code` for code-specialized embeddings in v2.

**NVIDIA NIM (meta/llama-3.3-70b-instruct)**  
LLM inference provider. Exposes an OpenAI-compatible REST API. Used only in Agent 6 for generating natural language explanations. Free tier with generous rate limits. Temperature set to 0.1 for consistent, accurate explanations.

### Infrastructure

**FastAPI**  
Async Python web framework. Exposes a POST endpoint `/analyze` that accepts `{ "repo_url": str, "options": {} }` and returns the generated document. Runs the agent pipeline as a background task.

**GitPython**  
Used to clone repositories programmatically for private repos or when the full file tree is needed. For public repos, the GitHub REST API is preferred (no disk I/O, faster).

**GitHub REST API**  
For public repositories: fetches the complete file tree and individual file contents via HTTP. No cloning required. Rate limit: 60 requests/hour unauthenticated, 5000/hour with a PAT.

**Frontend Design & Implementation (Figma Make → React 18 + TypeScript + Tailwind + shadcn/ui)**  
Professional SPA; Figma-first workflow; dark blue/white palette; 0px border-radius aesthetic.

**pyvis**  
Renders the NetworkX dependency graph as an interactive HTML file using D3.js. Users can zoom, pan, and click nodes to see file details. Zero frontend code required.

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
| Backend Engineering | FastAPI async pipeline, stateful multi-step request processing, background tasks |
| Systems Design | Pipeline decomposition, shared state pattern, interface design between agents |

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
│   ├── utils/
│   │   ├── github_api.py        # GitHub REST API client
│   │   ├── tree_sitter_utils.py # Language parser initialization
│   │   ├── nvidia_client.py     # NVIDIA NIM API wrapper with retry logic
│   │   └── filters.py           # File exclusion logic
│   │
│   └── api/
│       └── main.py              # FastAPI application
│
├── frontend/
│   └── app.py                   # Streamlit frontend
│
├── tests/
│   ├── test_ingestion.py
│   ├── test_ast_parser.py
│   ├── test_dependency_graph.py
│   ├── test_complexity_scorer.py
│   ├── test_code_rag.py
│   └── fixtures/
│       └── sample_repo/         # Tiny synthetic repo for testing
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

Each phase has a concrete deliverable that can be demonstrated independently.

**Phase 1: Ingestion Agent**  
Given a GitHub URL, print a JSON file manifest with file paths, languages, and line counts.  
Deliverable: `python -m src.agents.ingestion --url https://github.com/X/Y`

**Phase 2: AST Parser Agent**  
Given the file manifest, print symbol tables for every Python and JS file.  
Deliverable: symbol_tables.json showing functions, classes, and imports per file.

**Phase 3: Dependency Graph Agent**  
Given the symbol tables, print the dependency graph and any circular dependencies.  
Deliverable: dependency_graph.html that renders in a browser.

**Phase 4: Complexity Scorer Agent**  
Given symbol tables and file contents, print a ranked complexity report.  
Deliverable: complexity_report.json with risk levels per file.

**Phase 5: Code RAG Agent**  
Populate ChromaDB. Test retrieval: `query_code("where does authentication happen?")` should return relevant chunks.  
Deliverable: interactive terminal to test retrieval queries.

**Phase 6: Explainability Agent**  
Given a file path, print a natural language explanation of that file.  
Deliverable: readable, accurate explanation of a file Om has not read before.

**Phase 7: Doc Generator Agent**  
Full pipeline run: URL in, onboarding.md out.  
Deliverable: a complete onboarding doc for a real open-source repo.

**Phase 8: FastAPI Backend**  
Wrap the pipeline in an API. POST `/analyze` → returns the doc as JSON.

**Phase 9: React Frontend (designed via Figma Make)**
Production-quality web UI. Design system built in Figma using Figma Make, 
implemented in React 18 + TypeScript + Tailwind CSS + shadcn/ui.

Visual direction: deep electric blue (#1400FF) primary palette, IBM Plex Mono 
for all UI chrome, Playfair Display serif for hero type, classical Athena figure 
as background motif. Inspired by the Nous Research Hermes Agent site. Sharp corners 
everywhere, no gradients, no gray, no green.

Three screens:
  1. Landing     — URL input, options, classical split-screen composition
  2. Job Progress — live pipeline visualizer, large serif progress percentage
  3. Results     — four-tab output viewer (doc, graph, complexity, JSON) 
                    with sticky download bar

Deliverables:
  - Complete Figma design system (colors, typography, all component states)
  - Figma prototypes for all three screens at 1440px
  - React implementation built from the Figma design
  - Demo video: full pipeline run from URL input to onboarding doc

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
  ...

## Core Components

### fastapi_users/router/__init__.py
**Responsibility:** The central routing hub. Assembles all sub-routers
(auth, register, verify, reset) and exposes them as a single FastAPI
APIRouter. New engineers should read this file after understanding the
authentication module.

**Depends on:** authentication, db, schemas
**Depended on by:** 12 files
**Risk level:** HIGH (avg complexity: 8.2, coupling: 6)

...

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

## Environment Setup

```bash
git clone https://github.com/PiUnknown/code-archaeology-agent
cd code-archaeology-agent
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Add NVIDIA_API_KEY to .env
# Optionally add GITHUB_TOKEN for higher rate limits
```

**Running a full analysis:**
```bash
python -m src.orchestrator --url https://github.com/tiangolo/fastapi --output ./outputs
```

**Running the Streamlit UI:**
```bash
streamlit run frontend/app.py
```

**Running the FastAPI server:**
```bash
uvicorn src.api.main:app --reload
```

---

## Design Decisions and Tradeoffs

**Sequential pipeline vs parallel DAG**  
v1 runs agents sequentially. Agents 3, 4, and 5 could run in parallel (all depend on Agent 2's output but not on each other). Sequential is simpler to debug and the total runtime is acceptable for repos under 500 files. Parallel execution is a v2 optimization.

**Local embeddings vs API embeddings**  
`all-MiniLM-L6-v2` runs locally, no API cost, no rate limits, works offline. OpenAI's `text-embedding-3-small` produces better code embeddings but costs money and requires network access. The local model is accurate enough for v1. Swap-in is one line of code.

**ChromaDB vs FAISS**  
ChromaDB: persistent, metadata filtering, easier API. FAISS: faster at scale, no metadata filtering. For repos under 50k chunks, ChromaDB is fine. FAISS becomes relevant at 500k+ chunks (very large monorepos).

**NVIDIA NIM vs Groq/Local LLMs**  
NVIDIA NIM hosts state-of-the-art open models like `meta/llama-3.3-70b-instruct` and exposes them via an OpenAI-compatible REST API. By pointing the standard `openai` library to NVIDIA's serverless endpoint, we avoid proprietary vendor SDKs. It provides the same llama-3.3-70b model family quality as the previous Groq setup but with more lenient rate limits (40 RPM vs Groq's 30 RPM) and no daily token cap on the free tier.

**Design philosophy: classical academic instrument, not startup SaaS**
The Nous Research Hermes Agent site (nousr.com/hermes) is the direct visual 
reference. The #1400FF electric blue, Playfair Display serif headlines in all-caps, 
IBM Plex Mono for all UI text, sharp-corner components, and the Athena classical 
figure are all deliberate. The aesthetic says: this tool takes code seriously. It does 
not borrow from Vercel's minimalist gray or Tailwind's green accent defaults. 
The visual identity matches the project's name — Gnosis, knowledge — and its 
subject matter: excavating understanding from undocumented codebases.

The Figma-first workflow (design in Figma Make, then implement) is correct for 
a portfolio project. It produces a design system that can be presented independently 
of the code — useful in interviews where you want to show both the engineering 
architecture and the product design thinking.
  
---

## Limitations (v1)

- Public GitHub repos only (private repo support requires GitHub PAT, in v2)
- Repos above 10,000 files use a sampling strategy (top 200 by centrality)
- Languages supported in v1: Python, JavaScript, TypeScript, Go
- Explanation quality degrades for deeply obfuscated or minified code
- NVIDIA NIM free tier supports 40 requests/minute per model, capping runs to 20 files by default to avoid rate limits
- The generated document is a snapshot: it does not update when the repo changes

---

## Roadmap

**v1.0 — Core pipeline**  
All 7 agents working end-to-end. Streamlit demo. Supports Python and JS repos.

**v1.1 — Language expansion**  
Add Rust, Java, C++ via tree-sitter grammars.

**v2.0 — Product features**  
Private repo support, GitHub Action integration (auto-generate docs on push), changelog-aware analysis (what changed since last run), team collaboration (annotate the generated doc).

**v3.0 — Agent loop**  
Replace sequential pipeline with an agent loop: the explainability agent notices gaps in its understanding, re-queries ChromaDB, and iterates until it has sufficient context. True agentic behavior.

---

## Why This Exists

This is a portfolio project built to demonstrate production-level AI engineering skills: not just calling an LLM API, but designing a system where multiple specialized agents work together, each with clear interfaces, testable in isolation, grounded by retrieval, and producing output that is genuinely useful to a real user.

The problem is real. The architecture reflects how a senior engineer would actually approach it. Every design decision has a documented rationale. Every component can be explained in an interview.
