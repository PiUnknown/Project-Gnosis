# 📓 Gnosis Project Scratchpad

> **Project Goal:** Automated code archaeology and explanation pipeline.

---

## ⚡ Current Status
- [x] **Ingestion** — API tree-fetching, concurrent content fetching (ThreadPoolExecutor, 15 threads), and dynamic repository analysis tiers
- [x] **AST Parsing** — Tree-sitter parser (Py/JS/TS/Go/Rust/Java/C/C++)
- [x] **Dependency Graph** — NetworkX mapping (Centrality + circular import checks)
- [x] **Complexity Scorer** — Radon metrics & custom AST branch node counting
- [x] **Code RAG** — Chromadb vector database with local embedding models
- [x] **Explainability** — NVIDIA NIM LLM inference and context engineering
- [x] **Doc Generator** — Compiler formatting output as `onboarding.md`
- [x] **Interactive Frontend** — React + TypeScript SPA (Aesthetic dark blue/white)
- [x] **Docker & Cloud Deployment** — Containerized FastAPI backend on Microsoft Azure App Service + React frontend on Vercel

---

## 🛠️ Resolved Obstacles

### 1. LLM Provider Transition
* **Obstacle:** Groq free-tier rate limits (30 RPM, daily caps) stalled runs on medium codebases.
* **Fix:** Migrated to NVIDIA NIM serverless (`meta/llama-3.3-70b-instruct`). Exposes OpenAI-compatible endpoints with a more generous 40 RPM limit.

### 2. Redundant API Costs
* **Obstacle:** Running pipelines repeatedly on the same repo wasted time and tokens.
* **Fix:** Disk-based **Explanation Cache** in `./explanation_cache/` keyed by file Git SHA. Cache hits use 0 tokens.

### 3. Production Endpoint CORS
* **Obstacle:** Deployed frontend failed to connect to local backend endpoints.
* **Fix:** Parameterized frontend calls with dynamic `API_BASE` (`VITE_API_URL`) environment variable.

### 4. Language Expansion
* **Obstacle:** Originally restricted to Python, JS, TS, and Go.
* **Fix:** Added AST grammars and parsing support for Rust, Java, C, and C++ to `tree_sitter_utils.py` and `generic_parser.py`.

### 5. Repository Size & Token Limits
* **Obstacle:** Large codebases crashed backend workers or exceeded rate limits.
* **Fix:** Implemented dynamic **Repository Analysis Tiers**:
  * *Full Mode* ($\le 300$ files): Full analysis.
  * *Warning Mode* ($301 - 1000$ files): Full analysis with UI token warnings.
  * *Sampled Mode* ($1001 - 3000$ files): Ingests all files but runs detailed AST, complexity, and LLM explanation on the most important subset.
  * *Rejection Mode* ($> 3000$ files): Rejects analysis with a `400 Bad Request`.

### 6. Slow Ingestion
* **Obstacle:** Sequential file downloading took several minutes for medium repos.
* **Fix:** Implemented multi-threaded concurrent ingestion using a `ThreadPoolExecutor` (capped at 15 workers), fetching raw content from `raw.githubusercontent.com`.

---

## 🚀 Future Roadmap

### Performance
- [ ] **Parallel Execution** — Run independent agents (AST, complexity) concurrently.
- [ ] **Incremental Updates** — Compute diffs between runs; update only changed files in existing doc.

### Core Features
- [ ] **Private Repos** — Support user authentication via GitHub Personal Access Tokens (PAT).
- [ ] **CI/CD Integration** — Run Gnosis as a GitHub Action on commit/PR.
- [ ] **Interactive Visuals** — D3 graph rendering directly in the React frontend.
