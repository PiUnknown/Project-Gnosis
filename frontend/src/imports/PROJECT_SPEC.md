# PROJECT SPEC: Code Archaeology Agent

**Codename:** Archaeon  
**Version:** 1.0.4 (spec)  
**Status:** Pre-build  
**Author:** Om Kumar Jha  
**GitHub:** github.com/PiUnknown  

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

## Agent Architecture

The system uses a sequential multi-agent pipeline. Each agent has a single responsibility. All agents share one state object. No agent calls another agent directly. The orchestrator manages the sequence.

```
GitHub URL
    |
    v
[Agent 1: Ingestion Agent]
    - Clone repo
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
    - Embed chunks using code embedding model
    - Store in ChromaDB with metadata
    |
    v
[Agent 6: Explainability Agent]
    - For each major component: retrieve context from ChromaDB
    - Build explanation prompt with dependency context
    - Call Groq LLM to generate natural language explanation
    |
    v
[Agent 7: Doc Generator Agent]
    - Synthesize all outputs into structured Markdown
    - Output: onboarding doc, complexity report, dependency map
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
    repo_path: str = None           # local clone path

    # Agent 1 output
    file_manifest: list = field(default_factory=list)
    # Each entry: {path, language, line_count, size_bytes}

    # Agent 2 output
    symbol_tables: dict = field(default_factory=dict)
    # key: file_path, value: {functions, classes, imports, docstrings}

    # Agent 3 output
    dependency_graph: Any = None    # nx.DiGraph
    circular_deps: list = field(default_factory=list)

    # Agent 4 output
    complexity_scores: dict = field(default_factory=dict)
    # key: file_path, value: {avg_complexity, max_complexity, coupling, risk_level}

    # Agent 5 output
    chroma_collection_name: str = None

    # Agent 6 output
    explanations: dict = field(default_factory=dict)
    # key: file_path, value: explanation string

    # Agent 7 output
    final_doc: str = None
    complexity_report_json: str = None
```

---

## Agent Specifications

### Agent 1: Ingestion Agent

**Input:** GitHub URL (public repo)  
**Output:** file_manifest, repo_path written to state

**Responsibilities:**
- Clone using GitPython or raw GitHub API (API preferred for speed, avoids full clone)
- Walk the file tree, collect path, extension, size, line count
- Detect language per file using extension mapping + tree-sitter fallback
- Filter out: node_modules, .git, __pycache__, dist, build, .lock files, binary files, images

**Design decision:** GitHub API over full clone for public repos. Avoids disk I/O overhead. Fetches file list via `/repos/{owner}/{repo}/git/trees?recursive=1` then fetches individual file contents lazily.

**Size limit:** Skip files above 100KB (usually generated code). Warn user about repos above 10,000 files.

---

### Agent 2: AST Parser Agent

**Input:** file_manifest, raw file contents  
**Output:** symbol_tables written to state

**Responsibilities:**
- Initialize tree-sitter parser for each detected language
- Parse each file into an AST
- Walk the AST and extract:
  - Function names + signatures + line numbers
  - Class names + methods
  - Import statements (what is imported, from where)
  - Module-level docstrings
- Flag files that fail to parse (syntax error signal, goes into tech debt report)

**Supported languages in v1:** Python, JavaScript, TypeScript, Go  
**Languages to add in v2:** Rust, Java, C++

**Design note:** tree-sitter is language-agnostic at the API level. Adding a new language means adding its grammar. The parsing logic stays the same.

---

### Agent 3: Dependency Graph Agent

**Input:** symbol_tables  
**Output:** dependency_graph, circular_deps written to state

**Responsibilities:**
- For each file, read its import statements
- Map imports to internal files using the file manifest
- Build a directed edge: if A imports B, edge goes A → B
- Identify circular dependencies using NetworkX cycle detection (nx.simple_cycles)
- Compute per-node:
  - in-degree: how many files import this file (high = critical file)
  - out-degree: how many files this file imports (high = hub file)

**Output graph:** nx.DiGraph where each node is a file path, each edge is an import relationship

**Visualization:** Export to JSON for pyvis or D3.js rendering in frontend

---

### Agent 4: Complexity Scorer Agent

**Input:** file_manifest, symbol_tables (function bodies)  
**Output:** complexity_scores written to state

**Metrics per file:**
- Avg cyclomatic complexity across all functions
- Max cyclomatic complexity (worst function in the file)
- Number of functions
- Average function length in lines
- Coupling score: number of unique internal imports
- Risk level: LOW / MEDIUM / HIGH / CRITICAL based on composite score

**For Python:** use radon library (radon.complexity.cc_visit)  
**For JS/TS:** implement cyclomatic complexity counter on the AST (count if/for/while/switch/catch/ternary nodes)  
**For Go:** count select/case/if/for nodes in AST

**Risk thresholds (to be tuned):**
- Avg complexity > 10: HIGH
- Max complexity > 20: CRITICAL
- Parse failure: CRITICAL
- Circular dependency involvement: CRITICAL

---

### Agent 5: Code RAG Agent

**Input:** file_manifest, symbol_tables  
**Output:** populated ChromaDB collection, collection name written to state

**Chunking strategy:**
- Chunk at function level: each function is one chunk
- Chunk at class level: class definition + its docstring is one chunk (methods are separate)
- File-level chunk: imports + module docstring for each file
- Do NOT chunk by token count. Semantic unit chunking only.

**Metadata per chunk:**
```python
{
    "file_path": str,
    "symbol_name": str,        # function name, class name, or "module"
    "symbol_type": str,        # "function", "class", "module"
    "language": str,
    "line_start": int,
    "line_end": int,
    "complexity": float,       # from Agent 4 output
    "risk_level": str
}
```

**Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` for v1 (consistent with Om's existing projects). Upgrade to `nomic-embed-code` or `text-embedding-3-small` in v2.

**Vector store:** ChromaDB, local persistent client

**Retrieval interface exposed:** `query_code(natural_language_query, n_results=5) -> list[chunks]`

---

### Agent 6: Explainability Agent

**Input:** dependency_graph, ChromaDB collection, complexity_scores  
**Output:** explanations dict written to state

**For each file with risk level MEDIUM or above (plus all top-10 by in-degree):**

1. Query ChromaDB for that file's chunks: get its functions and classes as context
2. Query dependency graph: get what this file imports and what imports it
3. Build explanation prompt:

```
You are analyzing a codebase. Here is the code from {file_path}:

[retrieved code chunks]

This file imports: {list of internal dependencies}
These files import this file: {list of dependents}
Cyclomatic complexity: {score} ({risk_level})

Explain:
1. What this file's primary responsibility is
2. How it fits into the broader architecture
3. What a new engineer must understand before modifying it
4. Any risks or areas of concern

Be specific. Refer to actual function names. Max 300 words.
```

4. Call Groq API (llama-3.3-70b-versatile, temperature=0.1)
5. Store explanation in state.explanations[file_path]

**Batching:** Process explanations with a small delay between Groq calls to avoid rate limits. Target: 20 files max in v1.

---

### Agent 7: Doc Generator Agent

**Input:** full state object  
**Output:** final_doc (Markdown string), complexity_report_json written to state

**Generated document sections:**

```
# [Repo Name] - Architecture Overview
> Generated by Code Archaeology Agent

## 1. Project Summary
[Synthesized from top-level README if present + LLM summary of entry points]

## 2. Repository Statistics
- Total files analyzed: N
- Languages: Python (40%), JS (30%), ...
- Total functions: N
- High-risk files: N

## 3. Architecture Map
[Text-based dependency tree, top 15 most-connected files]

## 4. Core Components
[For each major file: name, responsibility, dependencies, explanation]

## 5. Tech Debt Report
[Circular deps, high complexity files, parse failures, undocumented functions]

## 6. Suggested Reading Order
[For a new engineer: start here, then here, then here]

## 7. Dependency Graph
[ASCII representation or pyvis HTML embed]
```
---

## Frontend Architecture

### Design System

**Colors:**
  Primary background: #1400FF (electric blue)
  Secondary/panel:    #0F00CC
  Content area:       #F0F0FF (light, for readable text on result tabs)
  Accent/text:        #FFFFFF
  Input fill:         #FFFFFF (white field, blue text inside)
  No gray, no black, no green anywhere in the palette.

**Typography:**
  Playfair Display — hero headings, progress display number. 400 weight. ALL CAPS.
  IBM Plex Mono    — all UI chrome: labels, buttons, nav, tabs, file paths, 
                     agent names, status badges, metadata.
  Inter            — body copy, descriptions, markdown prose.

**Components:**
  Border-radius: 0px everywhere (sharp corners, no exceptions).
  Borders: 1px solid rgba(255,255,255,0.25) on blue, rgba(20,0,255,0.15) on light.
  No drop shadows. No gradients. No glassmorphism.

**Classical figure:**
  Athena SVG engraving placed in right half of Landing and Progress pages.
  Rendered in #3D28FF (lighter blue) at 0.28 opacity.
  Bleeds off right and bottom edge. Monochromatic — no outline color difference.

### Screen: Landing ("/")
Split layout: left content column (600px), right figure column (840px).
Form: URL input (white field, blue text), max_explanations number, skip_llm toggle.
CTA: "ANALYZE REPOSITORY →" — white fill, blue text, full column width, 0px radius.
Submit flow: validate → POST /analyze → navigate to /jobs/:jobId.

### Screen: Job Progress ("/jobs/:jobId")
Left column: 7-agent pipeline list with step numbers and status states 
  (QUEUED / RUNNING with animated dots / COMPLETE ✓).
Right column: Large Playfair Display percentage (e.g. "67%"), thin 1px progress bar, 
  current phase in IBM Plex Mono uppercase.
Polling: GET /jobs/:jobId every 2 seconds via setInterval with useRef cleanup.
Auto-navigate to results after 1500ms delay once status === "complete".

### Screen: Results ("/jobs/:jobId/results")
Header: repo name, branch, stats, risk distribution pills, circular dep warning.
Four tabs (IBM Plex Mono uppercase, white underline on active):
  ONBOARDING DOC — react-markdown on #F0F0FF background, blue headings, 
                    Playfair Display h1, IBM Plex Mono h3.
  DEPENDENCY GRAPH — top files table (in-degree, out-degree, risk), 
                      reading order numbered list.
  COMPLEXITY REPORT — sortable/filterable table, risk badges 
                       (CRITICAL: white-on-blue, HIGH: blue-outline, 
                        MEDIUM: light-blue-fill, LOW: muted).
  RAW OUTPUT — four collapsible sections with copy buttons, 
                JSON syntax coloring in blue palette.
Sticky download bar: three outlined-white buttons, blue background, 
  IBM Plex Mono uppercase text.

### Frontend Tech Decisions

**Figma Make for design first:**
  Produces a complete design system (color, typography, all component states) 
  before a line of React is written. The Figma file is a standalone deliverable 
  for portfolio presentation. The design is the specification — not a rough mockup.

**React over Streamlit:**
  Streamlit is a data science notebook. The blue/white classical aesthetic of 
  Project Gnosis cannot be achieved in Streamlit without fighting its component 
  defaults at every step. React with Tailwind implements the Figma design faithfully.

**IBM Plex Mono for UI chrome:**
  Every non-prose element (labels, buttons, nav, file paths, agent names, status 
  text, tab labels) uses IBM Plex Mono. This is a design system decision, not 
  a font preference. It creates visual consistency between the UI chrome and the 
  code content the tool analyzes.

**No state management library:**
  Three pages, eight pieces of page-level state. useState + useRef is sufficient. 
  Redux or Zustand would be over-engineering for this scope.

---

## Tech Stack

| Component | Library | Reason |
|---|---|---|
| Repo ingestion | GitPython + GitHub REST API | GitPython for clones, API for speed on public repos |
| AST parsing | tree-sitter | Language-agnostic, 50+ languages, fast |
| Graph construction | NetworkX | Standard Python graph library, DiGraph support |
| Complexity analysis | radon (Python), custom AST walker (others) | radon is the standard for Python metrics |
| Vector store | ChromaDB | Lightweight, local, no infra needed |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Already in Om's stack, free, runs locally |
| LLM inference | Groq API (llama-3.3-70b-versatile) | Fast, free tier, Om's standard inference provider |
| Backend | FastAPI | Async, clean, Om's stack |
| Frontend Design | Figma Make | Design-first workflow; produces Figma component library before any React code is written |
| Frontend Implementation | React 18 + TypeScript + Tailwind CSS + shadcn/ui | Standard production React stack implemented from Figma specs |
| Visualization | pyvis (graph), matplotlib (charts) | pyvis renders interactive HTML graph |

---

## Build Phases

| Phase | Scope | Deliverable |
|---|---|---|
| 1 | Ingestion Agent | Given a GitHub URL, return a file manifest as JSON |
| 2 | AST Parser Agent | Given file manifest, return symbol tables as JSON |
| 3 | Dependency Graph Agent | Given symbol tables, return dependency graph + circular dep list |
| 4 | Complexity Scorer Agent | Given symbol tables + file contents, return complexity scores |
| 5 | Code RAG Agent | Given symbol tables, populate ChromaDB, test retrieval queries |
| 6 | Explainability Agent | Given full state, generate explanations for top 5 files |
| 7 | Doc Generator Agent | Generate full onboarding Markdown from full state |
| 8 | FastAPI backend | Wrap pipeline in API, accept GitHub URL, return doc |
| 9 | React Frontend (Figma Make → React) | Design system in Figma. Three-screen SPA: Landing, Progress, Results. Blue/white palette, Playfair Display + IBM Plex Mono typography, classical Athena motif, 0px radius everywhere. |

---

## Inputs and Outputs

**Primary input:** GitHub repository URL (public)  
**Optional inputs:**
- GitHub personal access token (for private repos or higher rate limits)
- Directory filter (analyze only `/src` or `/backend`)
- Target audience: intern / engineer / external contributor (affects explanation tone)
- Exclude patterns: custom file/folder exclusions beyond defaults

**Primary output:** `onboarding.md` (downloadable Markdown)  
**Secondary outputs:**
- `complexity_report.json`
- `dependency_graph.html` (interactive pyvis visualization)
- `symbol_table.json` (structured data for downstream tooling)

---

## Constraints and Risk Factors

| Constraint | Mitigation |
|---|---|
| Large repos (10k+ files) | Sampling strategy: analyze top 200 files by in-degree centrality |
| LLM context window | RAG ensures only relevant chunks go into each LLM call |
| Groq rate limits | Batch explanations with exponential backoff, limit to 20 files in v1 |
| tree-sitter language coverage | Graceful fallback: skip parsing, treat file as blob, use filename heuristics |
| Private repos | GitHub PAT support in v2 |
| Generated code (minified JS, proto files) | Filter by file size and extension |

---

## Success Criteria

- Running against a repo Om has not read before produces a document that accurately describes what the codebase does
- Dependency graph matches actual import relationships when manually spot-checked
- Complexity scores flag files that are actually complex when Om reads them
- End-to-end runtime under 5 minutes for a repo with 200-500 files
- Demo video of the tool analyzing a real open-source repo is shareable on Twitter/LinkedIn

---

## What This Project Demonstrates (Interview Signal)

This project covers the following domains simultaneously:

1. **Agentic AI** - Multi-agent pipeline with shared state, sequential orchestration, agent design patterns
2. **RAG** - AST-based semantic chunking (not naive token chunking), code embeddings, ChromaDB retrieval
3. **Context Engineering** - Selective context construction for LLM prompts, hierarchical summarization, managing repos that exceed context windows
4. **Graph Engineering** - Dependency graph construction, cycle detection, centrality analysis, graph traversal
5. **Static Code Analysis** - tree-sitter AST parsing, cyclomatic complexity, coupling metrics, tech debt detection
6. **LLM Orchestration** - Groq API integration, prompt construction, temperature tuning, batching
7. **Backend Engineering** - FastAPI async pipeline, stateful request handling
8. **Systems Design** - How to decompose a complex task into independent, composable agents

Every architectural decision in this project has a "why" that Om can explain in an interview.
