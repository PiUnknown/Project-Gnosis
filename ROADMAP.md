# Project Gnosis — Feature Roadmap & Idea Checklist

This document tracks upcoming features, architectural improvements, and experimental ideas planned for **Project Gnosis (Archaeon)**. Check items off with `- [x]` as they are completed.

---

## 🎯 High Priority / Next Up

- [ ] **Custom LLM / BYOK (Bring Your Own Key)**: Allow users to input their own OpenAI / Anthropic / Groq / NVIDIA API key in the UI for unlimited explanations.
- [ ] **Shareable Result Permalinks**: Enable public persistent URLs for completed analyses (e.g. `gnosis.piunknown.dev/r/pollen-robotics/microduck`) with caching.
- [ ] **Branch & Tag Selector**: Add a branch/tag dropdown selector on the landing page rather than defaulting only to `main`/`master`.
- [ ] **Interactive Repo Chat / Q&A**: Add a slide-out AI assistant to ask natural language questions about the analyzed codebase using the indexed ChromaDB vector embeddings.
- [ ] **PDF / Executive Report Export**: Generate downloadable high-resolution formatted PDF dossiers in addition to Markdown.

---

## 🏛️ Agent Pipeline & Analysis Enhancements

- [ ] **Private Repository Support**: Implement GitHub App / OAuth login so users can authenticate and analyze private company repositories.
- [ ] **Local Repository / ZIP Upload**: Allow uploading local directories or `.zip` archives directly without needing a public GitHub link.
- [ ] **Monorepo & Workspace Boundary Detection**: Detect nested packages in monorepos (Turborepo, Nx, Cargo workspaces, Lerna, Go workspaces) and provide per-package analysis breakdown.
- [ ] **PR & Diff Impact Analysis (Agent 8)**: Analyze a GitHub Pull Request URL to predict breaking changes, downstream affected modules, and risk score.
- [ ] **Test Coverage & Dead Code Detector**: Highlight orphan functions and modules with 0 incoming references across the AST graph.
- [ ] **Expanded Language Support**:
  - [ ] C# / .NET
  - [ ] Scala
  - [ ] Elixir
  - [ ] Dart / Flutter
  - [ ] Zig

---

## 💻 Frontend & UI/UX Improvements

- [ ] **Interactive 3D / WebGL Dependency Graph**: Upgrade graph rendering with Three.js / React Flow / 3d-force-graph with zoom, pan, node clustering, and filtering.
- [ ] **Syntax-Highlighted In-Browser Code Viewer**: Click any node or file explanation to view the actual source code with syntax highlighting side-by-side.
- [ ] **Dark / Light Classical Theme Toggle**: Add an ivory/marble light theme option honoring classical Greek aesthetics alongside the signature blue/dark mode.
- [ ] **Recent Searches & History**: Store recently analyzed repositories in `localStorage` for 1-click re-opening.
- [ ] **Batch Repository Comparison**: Compare two repositories side-by-side (architecture style, complexity metrics, dependency footprint).

---

## ⚡ Infrastructure, Performance & Scaling

- [ ] **Persistent Redis Caching Layer**: Pre-cache top 1,000 trending GitHub repositories so analysis opens instantly with 0 wait time.
- [ ] **Distributed RQ Workers**: Auto-scale background worker pods on Fly.io / Kubernetes based on queue backlog depth.
- [ ] **Email & Webhook Notifications**: Allow users to enter an email or Discord webhook to receive notification once a massive repository finishes analyzing.
- [ ] **Rate Limiting & Tiered Quotas**: Implement IP-based / account-based rate limiting on the FastAPI backend to protect serverless GPU endpoints.

---

## 📝 User Scratchpad & Quick Ideas

*Add quick thoughts, raw ideas, or bugs here:*

- [ ] 
- [ ] 
- [ ] 
