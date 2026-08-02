# 📓 Gnosis Project Scratchpad

> **Project Goal:** Automated code archaeology and explanation pipeline.

---

## ⚡ Current Status
- [x] **Ingestion** — API tree-fetching & Git clone fallback
- [x] **AST Parsing** — Tree-sitter parser (Py/JS/TS/Go)
- [x] **Dependency Graph** — NetworkX mapping (Centrality + circular import checks)
- [x] **Complexity Scorer** — Radon metrics & custom AST branch node counting
- [x] **Code RAG** — Chromadb vector database with local embedding models
- [x] **Explainability** — NVIDIA NIM LLM inference and context engineering
- [x] **Doc Generator** — Compiler formatting output as `onboarding.md`
- [x] **Interactive Frontend** — React + TypeScript SPA (Aesthetic dark blue/white)
- [x] **Docker Deployment** — Containerized FastAPI backend + docker-compose ready

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

---

## 🚀 Future Roadmap

### Performance
- [ ] **Parallel Execution** — Run independent agents (AST, complexity) concurrently.
- [ ] **Incremental Updates** — Compute diffs between runs; update only changed files in existing doc.

### Core Features
- [ ] **Private Repos** — Support user authentication via GitHub Personal Access Tokens (PAT).
- [ ] **Language Expansion** — Add Rust, Java, and C++ grammars.
- [ ] **CI/CD Integration** — Run Gnosis as a GitHub Action on commit/PR.
- [ ] **Interactive Visuals** — D3 graph rendering directly in the React frontend.
