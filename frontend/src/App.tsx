import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import posthog from 'posthog-js';

import {
  BlueprintPanel,
  TelemetryMeter,
  DotMatrixReadout,
  SparklineReadout,
  TechButton,
  StatInstrument,
  RegistrationMark,
  DoodleSlot,
  FieldAnnotation,
  AsciiLoader,
  EmptySchematic,
} from './components/blueprint';

import {
  downloadOnboarding,
  downloadAgentContext,
  downloadComplexityReport,
  downloadDependencyGraph,
  downloadFileExplanations,
} from './lib/download';

const API_BASE = import.meta.env.VITE_API_URL || '';
export const APP_VERSION = '1.1.0';

type Screen = 'landing' | 'progress' | 'results' | 'error';
type Tab = '01_ONBOARDING' | '02_AGENT_CONTEXT' | '03_DEPENDENCY_GRAPH' | '04_COMPLEXITY_TELEMETRY' | '05_FILE_EXPLANATIONS' | '06_CODE_RAG';

interface AgentState {
  id: string;
  name: string;
  desc: string;
  status: 'queued' | 'running' | 'complete' | 'failed';
  metric?: string;
}

interface SampleArchaeologyData {
  repo_url: string;
  branch: string;
  total_files: number;
  total_functions: number;
  total_classes: number;
  import_edges: number;
  circular_cycles: number;
  critical_files: number;
  high_files: number;
  medium_files: number;
  low_files: number;
  onboarding_doc: string;
  agent_context: string;
  file_explanations: string;
  dependency_rows: { file: string; path: string; imports: number; imported_by: number; risk: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' }[];
  complexity_rows: { file: string; avg_cc: number; max_cc: number; worst_fn: string; coupling: number; risk: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'; flags: string[] }[];
  circular_deps: string[][];
}

const SAMPLE_DATA: SampleArchaeologyData = {
  repo_url: 'https://github.com/tiangolo/fastapi',
  branch: 'master',
  total_files: 84,
  total_functions: 612,
  total_classes: 148,
  import_edges: 382,
  circular_cycles: 2,
  critical_files: 3,
  high_files: 11,
  medium_files: 24,
  low_files: 46,
  onboarding_doc: `# ARCHITECTURAL EXCAVATION REPORT: FASTAPI
**EXCAVATED VIA PROJECT GNOSIS // TREE-SITTER AST + NETWORKX + CHROMADB**

---

## 1. EXECUTIVE TOPOLOGY SUMMARY
FastAPI is a modern, high-performance web framework for building APIs with Python based on standard Python type hints and Starlette/Pydantic foundations.

\`\`\`
[USER_REQUEST] ──> [APIRoute.get_route_handler()] ──> [solve_dependencies()] ──> [Endpoint Handler]
                          │                                     │
                          └──> [Pydantic Model Validator]       └──> [Security / Scopes]
\`\`\`

### CORE ARCHITECTURAL INVARIANTS
1. **Dependency Injection Hierarchy**: The DI container (\`fastapi.dependencies.utils\`) resolves parameters recursively before route handlers are invoked.
2. **Schema Synthesis**: OpenAPI generation compiles AST-like route definitions into JSON schemas via \`fastapi.openapi.utils\`.
3. **Execution Runtime**: Requests pipe through Starlette middleware stack with Zero-Copy response serialization.

---

## 2. CRITICAL ARCHITECTURAL SUBSYSTEMS

| Subsystem | Entry File | Responsibility | Risk Level |
|---|---|---|---|
| **Route Dispatcher** | \`fastapi/routing.py\` | Compiles endpoints into Starlette routing tables | HIGH |
| **Dependency Resolver** | \`fastapi/dependencies/utils.py\` | Graph-based async DI solver with cache | CRITICAL |
| **Model Bindings** | \`fastapi/datastructures.py\` | Parameter extraction (Query, Body, Path, Header) | MEDIUM |
| **OpenAPI Schema Engine** | \`fastapi/openapi/utils.py\` | Auto-generates OpenAPI 3.1.0 specifications | HIGH |

---

## 3. ARCHAEOLOGICAL HOTSPOTS & TECH DEBT
> **FIELD ANNOTATION [CYCLE DETECTED]**: \`fastapi/routing.py\` <──> \`fastapi/dependencies/utils.py\` form a cyclic coupling edge during parameter resolution recursion.

- **Ref-Cycle**: \`routing.py\` delegates parameter parsing to \`solve_dependencies()\`, which references back to \`APIRoute\` metadata.
- **Cognitive Complexity**: \`fastapi/dependencies/utils.py::solve_dependencies\` has a cyclomatic score of **34** due to nested async generator handling and recursive sub-dependency caching.
`,
  agent_context: `PROJECT: FastAPI
ROLE: High-performance Python Web Framework
ARCHITECTURAL PATTERNS: Dependency Injection, Async Middleware, Pydantic Schema Compilation

CRITICAL PATHS:
- fastapi/applications.py: Main FastAPI application instance and lifecycle hooks.
- fastapi/routing.py: APIRoute compilation, routing tree, and Starlette handler wraps.
- fastapi/dependencies/utils.py: Async dependency solver with parameter caching.
- fastapi/param_functions.py: Declaration primitives (Depends, Security, Body, Query, Header).

RULES FOR AGENTS MODIFYING CODEBASE:
1. Never bypass \`solve_dependencies()\` in custom route handlers.
2. Ensure async dependencies close generators via context managers.
3. Preserve Pydantic v1 / v2 compatibility layers in \`fastapi/_compat.py\`.
`,
  file_explanations: `# ARCHAEOLOGICAL FILE EXPLANATIONS // DEEP RECONSTRUCTION
**SYNTHESIZED BY AGENT 6 (EXPLAINABILITY) & AGENT 7 (DOC GENERATOR)**

---

### 1. \`fastapi/dependencies/utils.py\`
- **Subsystem Role**: Core Graph-based Async Dependency Injection Resolver.
- **Architectural Risk**: \`CRITICAL\` (Cyclomatic Complexity Peak: **34**, In-Degree: **22**)
- **Key Signatures & Invariants**:
  - \`async solve_dependencies(request, dependant, body, background_tasks, response, dependency_overrides_provider, async_exit_stack)\`: Recursively walks the dependency tree, resolves cache keys, calls sub-dependencies, and binds results to keyword arguments.
  - \`get_dependant(*, path, call, name, security_scopes, use_cache)\`: Analyzes AST type hints to build a static dependency graph at application startup.
  - \`get_param_sub_dependant(*, param, path, security_scopes)\`: Extracted parameter validator binding.
- **Execution Flow**:
  \`\`\`
  Incoming Request ──> resolve parameter cache ──> solve sub-dependencies (async recursion)
                                                               │
                                                 evaluate security scopes
                                                               │
                                                push context to AsyncExitStack
  \`\`\`
- **Tech Debt & Architectural Notes**: High cognitive complexity due to multi-tiered error handling around async generator context manager lifecycles and fallback resolution for Pydantic v1/v2 compat layers.

---

### 2. \`fastapi/routing.py\`
- **Subsystem Role**: Route Registration, APIRoute Dispatching, and Handler Compilation.
- **Architectural Risk**: \`HIGH\` (Cyclomatic Complexity Peak: **28**, In-Degree: **14**)
- **Key Signatures & Invariants**:
  - \`APIRoute.get_route_handler()\`: Wraps endpoint coroutines in Starlette Request lifecycle handlers, invokes \`solve_dependencies()\`, validates body payloads against Pydantic models, and serializes responses.
  - \`APIRouter.add_api_route(path, endpoint, response_model, status_code, tags, dependencies)\`: Registers endpoints into directed routing tables.
- **Inter-module Coupling**: Forms a circular dependency cycle with \`dependencies/utils.py\` because route handlers must invoke the dependency solver, while the dependency solver references route parameter signatures.

---

### 3. \`fastapi/applications.py\`
- **Subsystem Role**: Top-level Application Container & Starlette Orchestrator.
- **Architectural Risk**: \`HIGH\` (Cyclomatic Complexity Peak: **14**, In-Degree: **8**)
- **Key Signatures & Invariants**:
  - \`FastAPI.__init__()\`: Initializes Starlette ASGI instance, middleware stack, CORS filters, and default router.
  - \`FastAPI.openapi()\`: Caches and serves compiled OpenAPI 3.1.0 schemas.
  - \`FastAPI.setup()\`: Configures default exception handlers (\`RequestValidationError\`, \`HTTPException\`).

---

### 4. \`fastapi/openapi/utils.py\`
- **Subsystem Role**: Automated OpenAPI 3.1.0 JSON Schema Compiler.
- **Architectural Risk**: \`MEDIUM\` (Cyclomatic Complexity Peak: **22**, In-Degree: **6**)
- **Key Responsibilities**: Inspects routes, parameter types, response models, and security schemes to synthesize standard compliant OpenAPI documentation schemas.

---

### 5. \`fastapi/param_functions.py\`
- **Subsystem Role**: Parameter Primitive Declarations (DSL).
- **Architectural Risk**: \`LOW\` (In-Degree: **16**)
- **Key Primitives**: \`Depends()\`, \`Security()\`, \`Query()\`, \`Path()\`, \`Body()\`, \`Header()\`, \`Cookie()\`.
`,
  dependency_rows: [
    { file: 'fastapi/dependencies/utils.py', path: 'fastapi/dependencies/utils.py', imports: 18, imported_by: 22, risk: 'CRITICAL' },
    { file: 'fastapi/routing.py', path: 'fastapi/routing.py', imports: 26, imported_by: 14, risk: 'HIGH' },
    { file: 'fastapi/applications.py', path: 'fastapi/applications.py', imports: 19, imported_by: 8, risk: 'HIGH' },
    { file: 'fastapi/openapi/utils.py', path: 'fastapi/openapi/utils.py', imports: 14, imported_by: 6, risk: 'MEDIUM' },
    { file: 'fastapi/param_functions.py', path: 'fastapi/param_functions.py', imports: 4, imported_by: 16, risk: 'LOW' },
    { file: 'fastapi/datastructures.py', path: 'fastapi/datastructures.py', imports: 6, imported_by: 12, risk: 'LOW' },
    { file: 'fastapi/exceptions.py', path: 'fastapi/exceptions.py', imports: 2, imported_by: 18, risk: 'LOW' },
  ],
  complexity_rows: [
    { file: 'fastapi/dependencies/utils.py', avg_cc: 14.2, max_cc: 34, worst_fn: 'solve_dependencies', coupling: 22, risk: 'CRITICAL', flags: ['HIGH_CYCLOMATIC', 'CIRCULAR_DEP', 'ASYNC_STACK'] },
    { file: 'fastapi/routing.py', avg_cc: 11.4, max_cc: 28, worst_fn: 'get_request_handler', coupling: 18, risk: 'HIGH', flags: ['HIGH_BRANCHING', 'DECORATOR_CHAIN'] },
    { file: 'fastapi/openapi/utils.py', avg_cc: 9.8, max_cc: 22, worst_fn: 'get_openapi', coupling: 14, risk: 'HIGH', flags: ['SCHEMA_RECURSION'] },
    { file: 'fastapi/applications.py', avg_cc: 6.2, max_cc: 14, worst_fn: 'setup', coupling: 19, risk: 'MEDIUM', flags: ['LIFECYCLE_COMPLEXITY'] },
    { file: 'fastapi/datastructures.py', avg_cc: 3.1, max_cc: 6, worst_fn: 'UploadFile.read', coupling: 8, risk: 'LOW', flags: [] },
  ],
  circular_deps: [
    ['fastapi/routing.py', 'fastapi/dependencies/utils.py', 'fastapi/routing.py'],
    ['fastapi/applications.py', 'fastapi/openapi/utils.py', 'fastapi/applications.py'],
  ],
};

export default function App() {
  const [screen, setScreen] = useState<Screen>('landing');
  const [repoUrl, setRepoUrl] = useState('https://github.com/tiangolo/fastapi');
  const [branch, setBranch] = useState('master');
  const [skipLlm, setSkipLlm] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('01_ONBOARDING');
  const [searchQuery, setSearchQuery] = useState('');
  const [ragQuery, setRagQuery] = useState('');
  const [ragResponse, setRagResponse] = useState<string | null>(null);
  const [isRagSearching, setIsRagSearching] = useState(false);
  const [currentProgress, setCurrentProgress] = useState(0);

  // Pipeline Agents
  const [agents, setAgents] = useState<AgentState[]>([
    { id: '01', name: 'INGESTION', desc: 'Fetching git tree & remote blob unpack', status: 'queued', metric: 'FETCH 0%' },
    { id: '02', name: 'AST_PARSER', desc: 'Tree-sitter syntax decomposition', status: 'queued', metric: '0 NODES' },
    { id: '03', name: 'DEP_GRAPH', desc: 'Directed NetworkX import topology', status: 'queued', metric: '0 EDGES' },
    { id: '04', name: 'COMPLEXITY', desc: 'Radon & Cyclomatic debt indexer', status: 'queued', metric: 'CC_INDEX 0.0' },
    { id: '05', name: 'CODE_RAG', desc: 'ChromaDB chunk vector embeddings', status: 'queued', metric: '0 CHUNKS' },
    { id: '06', name: 'EXPLAINABILITY', desc: 'Architectural reasoning engine', status: 'queued', metric: '0/0 SYNTH' },
    { id: '07', name: 'DOC_SYNTHESIS', desc: 'Archaeology field report compilation', status: 'queued', metric: 'DRAFTING' },
  ]);

  const [data, setData] = useState<SampleArchaeologyData>(SAMPLE_DATA);

  // Start excavation simulation or backend call
  const startExcavation = async () => {
    setScreen('progress');
    setCurrentProgress(5);

    posthog.capture('excavation_started', { repo_url: repoUrl, branch });

    // Step-by-step pipeline runner
    for (let step = 0; step < 7; step++) {
      await new Promise((r) => setTimeout(r, 600));
      setAgents((prev) =>
        prev.map((ag, idx) => {
          if (idx < step) return { ...ag, status: 'complete' };
          if (idx === step) return { ...ag, status: 'running' };
          return { ...ag, status: 'queued' };
        })
      );
      setCurrentProgress(Math.round(((step + 1) / 7) * 95));
    }

    await new Promise((r) => setTimeout(r, 700));
    setAgents((prev) => prev.map((ag) => ({ ...ag, status: 'complete' })));
    setCurrentProgress(100);

    // Transition to results
    setData({
      ...SAMPLE_DATA,
      repo_url: repoUrl || 'https://github.com/tiangolo/fastapi',
      branch: branch || 'master',
    });
    setScreen('results');
  };

  // Handle Code RAG search simulation
  const handleRagSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ragQuery.trim()) return;
    setIsRagSearching(true);
    setTimeout(() => {
      setRagResponse(
        `ARCHAEOLOGICAL VECTOR RETRIEVAL [SIMILARITY: 0.94]
QUERY: "${ragQuery}"

PRIMARY EVIDENCE LOCATED:
1. fastapi/dependencies/utils.py:L142-185 (Function: solve_dependencies)
   -> Direct match for async dependency resolution lifecycle & sub-dependency graph caching.
2. fastapi/routing.py:L210-245 (Class: APIRoute)
   -> Encapsulates parameter resolver and links Starlette Request to solve_dependencies().

SYNTHESIS:
The requested architectural mechanism is handled recursively in fastapi/dependencies/utils.py. Parameter models inspect type annotations and build an async execution tree before passing validated kwargs into the user endpoint.`
      );
      setIsRagSearching(false);
    }, 500);
  };

  return (
    <div className="min-h-screen bg-[#0A0A0B] text-[#E8E8E6] blueprint-grid flex flex-col selection:bg-[#E8A33D] selection:text-[#0A0A0B]">
      {/* ─── TOP SYSTEM TELEMETRY STRIP ───────────────────────────────────── */}
      <header className="border-b border-[#26262A] bg-[#0D0D0E]/95 sticky top-0 z-50 px-4 py-2 flex flex-wrap items-center justify-between gap-3 select-none">
        <div className="flex items-center gap-3">
          {/* Logo & Identity */}
          <div className="flex items-center gap-2.5">
            <img
              src="/logo_white.png"
              alt="Project Gnosis"
              width={22}
              height={22}
              className="w-[22px] h-[22px] object-contain shrink-0 select-none pointer-events-none"
            />
            <span className="font-grotesk font-bold tracking-tight text-sm text-[#E8E8E6] flex items-baseline gap-1.5">
              GNOSIS <span className="font-mono font-normal text-xs text-[#E8A33D]">// ARCHAEOLOGY CONSOLE</span>
            </span>
          </div>

          <div className="hidden md:flex items-center gap-2 border-l border-[#26262A] pl-3">
            <span className="font-mono text-[9px] text-[#55554F] tracking-widest uppercase">
              VERSION: {APP_VERSION}
            </span>
            <span className="text-[#3F3F46] font-mono text-[10px]">|</span>
            <span className="font-mono text-[9px] text-[#55554F] tracking-widest uppercase">
              CALIBRATION: 100%
            </span>
            <span className="text-[#3F3F46] font-mono text-[10px]">|</span>
            <span className="font-mono text-[9px] text-[#55554F] tracking-widest uppercase">
              GRID: [08_MODULAR]
            </span>
          </div>
        </div>

        {/* System State & Quick Navigation */}
        <div className="flex items-center gap-2">
          {screen !== 'landing' && (
            <TechButton
              size="sm"
              variant="default"
              onClick={() => setScreen('landing')}
              glyph="[<]"
            >
              NEW EXCAVATION
            </TechButton>
          )}

          <div className="font-mono text-[10px] px-2 py-0.5 border border-[#26262A] bg-[#121214] flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 bg-[#4E9F3D] animate-pulse" />
            <span className="text-[#8A8A85]">CORE:</span>
            <span className="text-[#E8E8E6] font-medium">AST+GRAPH+RAG</span>
          </div>
        </div>
      </header>

      {/* ─── MAIN CONTENT CONTAINER (8px Grid, Edge-to-Edge Blueprint) ────── */}
      <main className="flex-1 p-3 md:p-6 max-w-[1600px] w-full mx-auto flex flex-col gap-4">
        {/* ─── SCREEN 1: LANDING & REPO EXCAVATION INPUT ──────────────────── */}
        {screen === 'landing' && (
          <div className="flex flex-col gap-4">
            {/* Top Command Instrument Panel */}
            <BlueprintPanel
              title="EXCAVATION TARGET CONTROL // SYSTEM INPUT"
              glyph="[01_INITIALIZE]"
              coord="GRID [00, 01]"
              showCorners={true}
            >
              <div className="flex flex-col gap-4 p-2">
                <div className="flex flex-col md:flex-row gap-3 items-stretch">
                  <div className="flex-1 flex items-center bg-[#0A0A0B] border border-[#26262A] px-3 py-2">
                    <span className="font-mono text-[11px] text-[#E8A33D] font-bold mr-2 select-none">
                      REPO_URL &gt;
                    </span>
                    <input
                      type="text"
                      value={repoUrl}
                      onChange={(e) => setRepoUrl(e.target.value)}
                      placeholder="https://github.com/organization/repository"
                      className="bg-transparent border-none outline-none font-mono text-xs text-[#E8E8E6] w-full placeholder-[#55554F]"
                    />
                  </div>

                  <div className="w-full md:w-48 flex items-center bg-[#0A0A0B] border border-[#26262A] px-3 py-2">
                    <span className="font-mono text-[10px] text-[#8A8A85] mr-2 select-none">
                      BRANCH:
                    </span>
                    <input
                      type="text"
                      value={branch}
                      onChange={(e) => setBranch(e.target.value)}
                      className="bg-transparent border-none outline-none font-mono text-xs text-[#E8E8E6] w-full placeholder-[#55554F]"
                    />
                  </div>

                  <TechButton
                    variant="amber"
                    size="lg"
                    onClick={startExcavation}
                    className="font-bold shrink-0"
                  >
                    [EXCAVATE CODEBASE]
                  </TechButton>
                </div>

                {/* Mode Toggles & Sample Repositories */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-[#26262A]">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-[#55554F] uppercase">
                      SAMPLE ARTIFACTS:
                    </span>
                    <TechButton
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setRepoUrl('https://github.com/tiangolo/fastapi');
                        setBranch('master');
                      }}
                    >
                      fastapi
                    </TechButton>
                    <TechButton
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setRepoUrl('https://github.com/pallets/flask');
                        setBranch('main');
                      }}
                    >
                      flask
                    </TechButton>
                    <TechButton
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setRepoUrl('https://github.com/chroma-core/chroma');
                        setBranch('main');
                      }}
                    >
                      chroma
                    </TechButton>
                  </div>

                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-1.5 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={skipLlm}
                        onChange={(e) => setSkipLlm(e.target.checked)}
                        className="accent-[#E8A33D] rounded-none"
                      />
                      <span className="font-mono text-[10px] text-[#8A8A85] uppercase">
                        SKIP LLM SYNTHESIS (FAST AST ONLY)
                      </span>
                    </label>
                  </div>
                </div>
              </div>
            </BlueprintPanel>

            {/* Philosophy & Architecture Instrument Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <BlueprintPanel
                title="ARCHAEOLOGICAL PHILOSOPHY"
                glyph="[I]"
                coord="SEC 01"
              >
                <div className="font-mono text-[11px] text-[#8A8A85] flex flex-col gap-2 leading-relaxed">
                  <p>
                    <strong className="text-[#E8E8E6]">GNOSIS</strong> excavates dead, legacy, or complex codebases to restore their lost structural intent.
                  </p>
                  <p>
                    Reads raw AST syntax, extracts cyclic import edges, profiles cyclomatic debt, and compiles human-grade onboarding blueprints.
                  </p>
                  <div className="mt-2 pt-2 border-t border-[#26262A] flex justify-between items-center text-[10px] text-[#55554F]">
                    <span>STATUS: READY</span>
                    <span>CALIBRATION: 100%</span>
                  </div>
                </div>
              </BlueprintPanel>

              <BlueprintPanel
                title="TELEMETRY CAPABILITIES"
                glyph="[II]"
                coord="SEC 02"
              >
                <div className="flex flex-col gap-3">
                  <TelemetryMeter
                    label="AST SYNTAX PARSING"
                    value={100}
                    totalSegments={12}
                    unit="OK"
                  />
                  <TelemetryMeter
                    label="NETWORKX GRAPH TOPOLOGY"
                    value={100}
                    totalSegments={12}
                    unit="OK"
                  />
                  <TelemetryMeter
                    label="CHROMADB VECTOR DENSITY"
                    value={94}
                    totalSegments={12}
                    unit="OK"
                  />
                </div>
              </BlueprintPanel>

              <BlueprintPanel
                title="FIELD ANNOTATIONS"
                glyph="[III]"
                coord="SEC 03"
              >
                <div className="flex flex-col items-center justify-center p-3 text-center gap-2">
                  <DoodleSlot
                    doodleId="map"
                    size={130}
                    label="FIELD_MAP // TOPOLOGY"
                    primitiveFallback="circle"
                  />
                  <span className="font-mono text-[10px] text-[#8A8A85] max-w-xs mt-1">
                    Field annotations mark critical cyclic dependencies and architectural hotspots across the excavated codebase.
                  </span>
                </div>
              </BlueprintPanel>
            </div>
          </div>
        )}

        {/* ─── SCREEN 2: PIPELINE PROGRESS TELEMETRY ───────────────────────── */}
        {screen === 'progress' && (
          <div className="flex flex-col gap-4">
            <BlueprintPanel
              title="EXCAVATION PIPELINE TELEMETRY"
              glyph="[ACTIVE]"
              coord="PIPE [07_STAGES]"
              badge={`${currentProgress}%`}
            >
              <div className="flex flex-col gap-4">
                <AsciiLoader
                  progress={currentProgress}
                  label={`EXCAVATING ${repoUrl.split('/').pop()?.toUpperCase()} [BRANCH: ${branch}]`}
                />

                {/* 7-Agent Telemetry Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
                  {agents.map((ag) => (
                    <div
                      key={ag.id}
                      className={`p-2.5 border border-[#26262A] bg-[#0A0A0B] flex flex-col justify-between ${
                        ag.status === 'running'
                          ? 'border-[#E8A33D] bg-[#121214]'
                          : ag.status === 'complete'
                          ? 'border-[#3F3F46]'
                          : 'opacity-50'
                      }`}
                    >
                      <div className="flex items-center justify-between font-mono text-[9px]">
                        <span className="text-[#55554F]">AGENT_{ag.id}</span>
                        <span
                          className={`font-semibold ${
                            ag.status === 'complete'
                              ? 'text-[#4E9F3D]'
                              : ag.status === 'running'
                              ? 'text-[#E8A33D] ascii-blink'
                              : 'text-[#55554F]'
                          }`}
                        >
                          [{ag.status.toUpperCase()}]
                        </span>
                      </div>

                      <div className="my-1.5">
                        <div className="font-mono text-xs font-bold text-[#E8E8E6]">
                          {ag.name}
                        </div>
                        <div className="font-mono text-[10px] text-[#8A8A85] truncate">
                          {ag.desc}
                        </div>
                      </div>

                      <div className="font-mono text-[9px] text-[#E8A33D] border-t border-[#26262A] pt-1">
                        {ag.metric}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </BlueprintPanel>
          </div>
        )}

        {/* ─── SCREEN 3: FULL ARCHAEOLOGICAL WORKBENCH RESULTS ────────────── */}
        {screen === 'results' && (
          <div className="flex flex-col gap-4">
            {/* 1. Header Telemetry HUD Cluster */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <StatInstrument
                label="EXCAVATED REPO"
                value={data.repo_url.split('/').pop() || 'repo'}
                subValue={`[${data.branch}]`}
                glyph="[●]"
              />
              <StatInstrument
                label="TOTAL AST NODES"
                value={data.total_files}
                subValue={`${data.total_functions} FN / ${data.total_classes} CLS`}
                glyph="[AST]"
              />
              <StatInstrument
                label="IMPORT GRAPH EDGES"
                value={data.import_edges}
                subValue={`${data.circular_cycles} CYCLES DETECTED`}
                status={data.circular_cycles > 0 ? 'warning' : 'nominal'}
                glyph="[GPH]"
              />
              <StatInstrument
                label="CRITICAL HOTSPOTS"
                value={data.critical_files}
                subValue={`${data.high_files} HIGH / ${data.medium_files} MED`}
                status={data.critical_files > 0 ? 'critical' : 'nominal'}
                glyph="[RISK]"
              />
            </div>

            {/* 2. Secondary Telemetry Instruments (Bar Meters & Dot Matrix) */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <BlueprintPanel
                title="RISK PROFILE DISTRIBUTION"
                glyph="[MTR_01]"
                coord="DIST [CRIT/HIGH/MED/LOW]"
              >
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between font-mono text-[10px] text-[#8A8A85]">
                    <span>CRITICAL: {data.critical_files}</span>
                    <span>HIGH: {data.high_files}</span>
                    <span>MED: {data.medium_files}</span>
                    <span>LOW: {data.low_files}</span>
                  </div>
                  {/* Segmented Risk Gauge */}
                  <div className="flex h-3 bg-[#0A0A0B] border border-[#26262A] p-[1px] gap-[2px]">
                    <div style={{ width: `${(data.critical_files / data.total_files) * 100}%` }} className="bg-[#FF4D4D]" title="Critical" />
                    <div style={{ width: `${(data.high_files / data.total_files) * 100}%` }} className="bg-[#E8A33D]" title="High" />
                    <div style={{ width: `${(data.medium_files / data.total_files) * 100}%` }} className="bg-[#F2C94C]" title="Medium" />
                    <div style={{ width: `${(data.low_files / data.total_files) * 100}%` }} className="bg-[#4E9F3D]" title="Low" />
                  </div>
                </div>
              </BlueprintPanel>

              <BlueprintPanel
                title="CHROMADB VECTOR CLUSTERS"
                glyph="[MTR_02]"
                coord="CHROMA [EMBEDDINGS]"
              >
                <DotMatrixReadout
                  label="CODE CHUNK DENSITY"
                  rows={3}
                  cols={20}
                  activeCount={48}
                  totalCount={60}
                  statusText="48 CHUNKS INDEXED"
                />
              </BlueprintPanel>

              <BlueprintPanel
                title="CYCLOMATIC TELEMETRY"
                glyph="[MTR_03]"
                coord="SPARK [CC_DIST]"
              >
                <SparklineReadout
                  label="COMPLEXITY CURVE"
                  metric="PEAK CC: 34"
                  data={[8, 12, 14, 18, 22, 16, 28, 34, 19, 12]}
                />
              </BlueprintPanel>
            </div>

            {/* 3. Main Blueprint Workbench Tab Strip & Actions */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#26262A] pb-2">
              {/* Tab Selector */}
              <div className="flex flex-wrap gap-1">
                {(
                  [
                    '01_ONBOARDING',
                    '02_AGENT_CONTEXT',
                    '03_DEPENDENCY_GRAPH',
                    '04_COMPLEXITY_TELEMETRY',
                    '05_FILE_EXPLANATIONS',
                    '06_CODE_RAG',
                  ] as Tab[]
                ).map((tab) => (
                  <TechButton
                    key={tab}
                    size="sm"
                    active={activeTab === tab}
                    onClick={() => setActiveTab(tab)}
                  >
                    [{tab}]
                  </TechButton>
                ))}
              </div>

              {/* Export Artifacts Controls */}
              <div className="flex items-center gap-1.5">
                <TechButton
                  size="sm"
                  variant="ghost"
                  onClick={() => downloadOnboarding(data.onboarding_doc, 'fastapi')}
                  glyph="[↓]"
                >
                  ONBOARDING.MD
                </TechButton>
                <TechButton
                  size="sm"
                  variant="ghost"
                  onClick={() => downloadAgentContext(data.agent_context, 'fastapi')}
                  glyph="[↓]"
                >
                  AGENT_CONTEXT.MD
                </TechButton>
                <TechButton
                  size="sm"
                  variant="ghost"
                  onClick={() => downloadDependencyGraph(data.dependency_rows, 'fastapi')}
                  glyph="[↓]"
                >
                  GRAPH.JSON
                </TechButton>
              </div>
            </div>

            {/* 4. Active Tab Panels */}
            {/* TAB 1: ONBOARDING DOC */}
            {activeTab === '01_ONBOARDING' && (
              <BlueprintPanel
                title="ARCHITECTURAL ONBOARDING SYNTHESIS"
                glyph="[DOC_01]"
                coord="SEC 01 // SYNTHESIS"
              >
                <div className="p-4 bg-[#0A0A0B] border border-[#26262A] max-h-[700px] overflow-y-auto">
                  <div className="gnosis-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {data.onboarding_doc}
                    </ReactMarkdown>
                  </div>
                </div>
              </BlueprintPanel>
            )}

            {/* TAB 2: AGENT CONTEXT */}
            {activeTab === '02_AGENT_CONTEXT' && (
              <BlueprintPanel
                title="MACHINE-OPTIMIZED AGENT CONTEXT"
                glyph="[DOC_02]"
                coord="SEC 02 // AGENT_CONTEXT"
              >
                <div className="p-4 bg-[#0A0A0B] border border-[#26262A] max-h-[700px] overflow-y-auto font-mono text-xs text-[#E8E8E6] whitespace-pre-wrap leading-relaxed">
                  {data.agent_context}
                </div>
              </BlueprintPanel>
            )}

            {/* TAB 3: DEPENDENCY GRAPH MATRIX */}
            {activeTab === '03_DEPENDENCY_GRAPH' && (
              <BlueprintPanel
                title="DIRECTED IMPORT DEPENDENCY TOPOLOGY"
                glyph="[MATRIX_01]"
                coord="GRAPH [NETWORKX]"
                headerRight={
                  <input
                    type="text"
                    placeholder="FILTER FILES..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="bg-[#0A0A0B] border border-[#26262A] px-2 py-0.5 font-mono text-[10px] text-[#E8E8E6] outline-none placeholder-[#55554F] uppercase"
                  />
                }
              >
                <div className="flex flex-col gap-3">
                  {/* Circular Cycles Alert Banner */}
                  {data.circular_cycles > 0 && (
                    <div className="border border-[#E8A33D] bg-[#121214] p-2.5 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-bold text-[#E8A33D]">
                          [!] CIRCULAR COUPLING IDENTIFIED:
                        </span>
                        <FieldAnnotation type="underline" label="CYCLIC_COUPLING">
                          <span className="font-mono text-xs text-[#E8E8E6]">
                            {data.circular_deps.map((c) => c.join(' -> ')).join(' | ')}
                          </span>
                        </FieldAnnotation>
                      </div>
                    </div>
                  )}

                  {/* Dense Technical Dependency Table */}
                  <div className="overflow-x-auto border border-[#26262A]">
                    <table className="w-full text-left font-mono text-xs border-collapse">
                      <thead>
                        <tr className="bg-[#18181B] text-[#8A8A85] text-[10px] uppercase border-b border-[#26262A]">
                          <th className="p-2 border-r border-[#26262A]">FILE IDENTIFIER</th>
                          <th className="p-2 border-r border-[#26262A] text-right">IMPORTS (OUT)</th>
                          <th className="p-2 border-r border-[#26262A] text-right">IMPORTED BY (IN)</th>
                          <th className="p-2 text-center">COUPLING RISK</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.dependency_rows
                          .filter((r) =>
                            r.file.toLowerCase().includes(searchQuery.toLowerCase())
                          )
                          .map((row, i) => (
                            <tr
                              key={i}
                              className="border-b border-[#26262A] hover:bg-[#18181B]/50"
                            >
                              <td className="p-2 border-r border-[#26262A] text-[#E8E8E6] font-medium">
                                {row.file}
                              </td>
                              <td className="p-2 border-r border-[#26262A] text-right text-[#8A8A85]">
                                {row.imports}
                              </td>
                              <td className="p-2 border-r border-[#26262A] text-right text-[#8A8A85]">
                                {row.imported_by}
                              </td>
                              <td className="p-2 text-center">
                                {row.risk === 'CRITICAL' ? (
                                  <FieldAnnotation type="circle" label="HOTSPOT">
                                    <span className="px-1.5 py-0.5 text-[9px] font-bold text-[#FF4D4D] bg-[#FF4D4D]/10 border border-[#FF4D4D]">
                                      [CRITICAL]
                                    </span>
                                  </FieldAnnotation>
                                ) : (
                                  <span
                                    className={`px-1.5 py-0.5 text-[9px] font-bold ${
                                      row.risk === 'HIGH'
                                        ? 'text-[#E8A33D] bg-[#E8A33D]/10 border border-[#E8A33D]'
                                        : 'text-[#8A8A85] bg-[#26262A]'
                                    }`}
                                  >
                                    [{row.risk}]
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </BlueprintPanel>
            )}

            {/* TAB 4: COMPLEXITY TELEMETRY */}
            {activeTab === '04_COMPLEXITY_TELEMETRY' && (
              <BlueprintPanel
                title="CYCLOMATIC DEBT & MAINTAINABILITY PROFILER"
                glyph="[RADON_01]"
                coord="RADON [AST_DEBT]"
              >
                <div className="overflow-x-auto border border-[#26262A]">
                  <table className="w-full text-left font-mono text-xs border-collapse">
                    <thead>
                      <tr className="bg-[#18181B] text-[#8A8A85] text-[10px] uppercase border-b border-[#26262A]">
                        <th className="p-2 border-r border-[#26262A]">TARGET MODULE</th>
                        <th className="p-2 border-r border-[#26262A] text-right">AVG CC</th>
                        <th className="p-2 border-r border-[#26262A] text-right">PEAK CC</th>
                        <th className="p-2 border-r border-[#26262A]">WORST FUNCTION HOTSPOT</th>
                        <th className="p-2 border-r border-[#26262A]">ARCHITECTURAL FLAGS</th>
                        <th className="p-2 text-center">RISK</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.complexity_rows.map((row, i) => (
                        <tr
                          key={i}
                          className="border-b border-[#26262A] hover:bg-[#18181B]/50"
                        >
                          <td className="p-2 border-r border-[#26262A] text-[#E8E8E6] font-medium">
                            {row.file}
                          </td>
                          <td className="p-2 border-r border-[#26262A] text-right text-[#8A8A85]">
                            {row.avg_cc}
                          </td>
                          <td className="p-2 border-r border-[#26262A] text-right">
                            {row.max_cc >= 30 ? (
                              <FieldAnnotation type="circle" label="PEAK">
                                <span className="text-[#E8A33D] font-bold">{row.max_cc}</span>
                              </FieldAnnotation>
                            ) : (
                              <span className="text-[#E8E8E6] font-semibold">{row.max_cc}</span>
                            )}
                          </td>
                          <td className="p-2 border-r border-[#26262A] text-[#8A8A85]">
                            <code className="text-[#E8A33D] text-[11px]">
                              {row.worst_fn}()
                            </code>
                          </td>
                          <td className="p-2 border-r border-[#26262A]">
                            <div className="flex flex-wrap gap-1">
                              {row.flags.map((flag, fi) => (
                                <span
                                  key={fi}
                                  className="text-[9px] px-1 py-0.5 border border-[#26262A] bg-[#0A0A0B] text-[#55554F]"
                                >
                                  {flag}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="p-2 text-center">
                            <span
                              className={`px-1.5 py-0.5 text-[9px] font-bold ${
                                row.risk === 'CRITICAL'
                                  ? 'text-[#FF4D4D] border border-[#FF4D4D]'
                                  : row.risk === 'HIGH'
                                  ? 'text-[#E8A33D] border border-[#E8A33D]'
                                  : 'text-[#8A8A85]'
                              }`}
                            >
                              [{row.risk}]
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </BlueprintPanel>
            )}

            {/* TAB 5: FILE EXPLANATIONS */}
            {activeTab === '05_FILE_EXPLANATIONS' && (
              <BlueprintPanel
                title="SUBSYSTEM & MODULE EXPLANATIONS"
                glyph="[EXPL_01]"
                coord="SEC 05 // EXPLAIN"
              >
                {data.file_explanations ? (
                  <div className="p-4 bg-[#0A0A0B] border border-[#26262A] max-h-[700px] overflow-y-auto">
                    <div className="gnosis-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {data.file_explanations}
                      </ReactMarkdown>
                    </div>
                  </div>
                ) : (
                  <EmptySchematic
                    doodleId="folder"
                    doodleSize={120}
                    caption="SKIPPED AI EXPLANATIONS — RUN ANALYSIS WITH SKIP LLM DISABLED TO GENERATE FILE WALKTHROUGHS"
                    coord="FILES [00, 00]"
                  />
                )}
              </BlueprintPanel>
            )}

            {/* TAB 6: CODE RAG INTERACTIVE CONSOLE */}
            {activeTab === '06_CODE_RAG' && (
              <BlueprintPanel
                title="ARCHAEOLOGICAL CODE RAG // VECTOR QUERY"
                glyph="[CHROMADB_01]"
                coord="CHROMA [SIMILARITY_SEARCH]"
              >
                <div className="flex flex-col gap-4">
                  <form onSubmit={handleRagSearch} className="flex gap-2">
                    <div className="flex-1 flex items-center bg-[#0A0A0B] border border-[#26262A] px-3 py-2">
                      <span className="font-mono text-xs text-[#E8A33D] mr-2">QUERY &gt;</span>
                      <input
                        type="text"
                        value={ragQuery}
                        onChange={(e) => setRagQuery(e.target.value)}
                        placeholder="e.g. How does dependency injection resolve sub-dependencies?"
                        className="bg-transparent border-none outline-none font-mono text-xs text-[#E8E8E6] w-full placeholder-[#55554F]"
                      />
                    </div>
                    <TechButton
                      type="submit"
                      variant="amber"
                      isLoading={isRagSearching}
                    >
                      [EXECUTE VECTOR SEARCH]
                    </TechButton>
                  </form>

                  {/* Query results */}
                  {ragResponse ? (
                    <div className="p-3 bg-[#0A0A0B] border border-[#26262A] font-mono text-xs text-[#E8E8E6] whitespace-pre-wrap leading-relaxed">
                      {ragResponse}
                    </div>
                  ) : (
                    <EmptySchematic
                      doodleId="compass"
                      doodleSize={120}
                      caption="ENTER NATURAL LANGUAGE QUERY TO SEARCH CHROMA VECTOR STORE ACROSS AST CHUNKS"
                      coord="CHROMA [00, 00]"
                    />
                  )}
                </div>
              </BlueprintPanel>
            )}
          </div>
        )}
      </main>

      {/* ─── BOTTOM ENGINEERING FOOTER ────────────────────────────────────── */}
      <footer className="border-t border-[#26262A] bg-[#0A0A0B] px-4 py-2 mt-auto select-none">
        <div className="max-w-[1600px] mx-auto flex flex-wrap items-center justify-between gap-2 font-mono text-[9px] text-[#55554F]">
          <div className="flex items-center gap-2">
            <span>PROJECT GNOSIS</span>
            <span>//</span>
            <span>CODE ARCHAEOLOGY & ONBOARDING SYSTEM</span>
          </div>
          <div className="flex items-center gap-3">
            <span>DARK MODE ONLY</span>
            <span>//</span>
            <span>ENGINEERING GRID: 8PX</span>
            <span>//</span>
            <span className="text-[#8A8A85]">ACCENT: AMBER [#E8A33D]</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
