import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'

type Screen = 'landing' | 'progress' | 'results'
type AgentStatus = 'queued' | 'running' | 'complete' | 'failed'
type ResultsTab = 'onboarding' | 'dependency' | 'complexity' | 'raw'

interface AgentState {
  id: string
  name: string
  status: AgentStatus
}

interface JobState {
  status: 'running' | 'complete' | 'failed'
  agents: AgentState[]
  error: string | null
}

interface ResultSummary {
  repo_url: string
  total_files: number
  total_functions: number
  total_classes: number
  import_edges: number
  circular_cycles: number
  explained: number
  risk_distribution: Record<string, number>
}

interface DepRow {
  file: string
  path: string
  imported_by: number
  imports: number
  risk: RiskLevel
}

interface ComplexityRow {
  file: string
  path: string
  risk: RiskLevel
  avg_cc: number
  max_cc: number
  worst_fn: string
  coupling: number
  flags: string[]
}

interface AnalysisResult {
  summary: ResultSummary
  onboarding_doc: string
  dependency_rows: DepRow[]
  reading_order: string[]
  complexity_rows: ComplexityRow[]
  explanations: Record<string, string>
  complexity_report_json: string
  circular_deps: string[][]
}

type RiskLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

const AGENT_DESCS = [
  'Fetching repository file tree from GitHub API',
  'Parsing syntax trees with tree-sitter',
  'Building directed import graph with NetworkX',
  'Scoring cyclomatic complexity and tech debt',
  'Embedding code chunks into ChromaDB',
  'Generating explanations via Groq LLM',
  'Synthesizing all outputs into onboarding.md',
]

// ─── GnosisLogo ───────────────────────────────────────────────────────────────
function GnosisLogo() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      style={{ display: 'block', flexShrink: 0 }}
    >
      <line x1="1" y1="4"  x2="17" y2="4"  stroke="white" strokeWidth="1.2" />
      <line x1="1" y1="9"  x2="17" y2="9"  stroke="white" strokeWidth="1.2" />
      <line x1="1" y1="14" x2="17" y2="14" stroke="white" strokeWidth="1.2" />
      <line x1="9" y1="1"  x2="9"  y2="17" stroke="white" strokeWidth="1.2" />
      <rect x="1"    y="1"    width="2.5" height="2.5" fill="white" />
      <rect x="14.5" y="1"    width="2.5" height="2.5" fill="white" />
      <rect x="1"    y="14.5" width="2.5" height="2.5" fill="white" />
      <rect x="14.5" y="14.5" width="2.5" height="2.5" fill="white" />
      <rect x="7.5"  y="7.5"  width="3"   height="3"   fill="white" />
    </svg>
  )
}

// ─── NavBar ───────────────────────────────────────────────────────────────────
function NavBar({ onLogoClick }: { onLogoClick: () => void }) {
  return (
    <nav
      style={{
        height: 72,
        background: '#1400FF',
        borderBottom: '1px solid rgba(255,255,255,0.15)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 96px',
        flexShrink: 0,
      }}
    >
      <button
        onClick={onLogoClick}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: 0,
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: 14,
          fontWeight: 500,
          letterSpacing: '0.12em',
          color: '#FFFFFF',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <GnosisLogo />
        GNOSIS
      </button>
      <span
        style={{
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: 11,
          fontWeight: 400,
          letterSpacing: '0.14em',
          color: 'rgba(255,255,255,0.50)',
        }}
      >
        CODE ARCHAEOLOGY AGENT
      </span>
    </nav>
  )
}

// ─── Athena Figure ────────────────────────────────────────────────────────────
function AthenaFigure({ brightness = 0.88 }: { brightness?: number }) {
  return (
    <div
      style={{
        position: 'absolute',
        right: -60,
        top: 0,
        bottom: 0,
        width: 700,
        pointerEvents: 'none',
        overflow: 'hidden',
      }}
    >
      <img
        src="https://images.unsplash.com/photo-1670813885725-e3c5391dcd31?w=900&h=1200&fit=crop&auto=format"
        alt="Classical goddess figure"
        style={{
          position: 'absolute',
          right: -40,
          top: 0,
          height: '100%',
          width: 'auto',
          objectFit: 'cover',
          objectPosition: 'center top',
          filter: `grayscale(1) contrast(1.35) brightness(${brightness})`,
          mixBlendMode: 'screen',
          opacity: 0.82,
        }}
      />
    </div>
  )
}

// ─── RiskBadge ────────────────────────────────────────────────────────────────
function RiskBadge({ level, onLight = false }: { level: RiskLevel; onLight?: boolean }) {
  const styles: Record<RiskLevel, React.CSSProperties> = {
    CRITICAL: onLight
      ? { background: '#1400FF', color: '#FFFFFF', border: 'none' }
      : { background: '#FFFFFF', color: '#1400FF', border: 'none' },
    HIGH: onLight
      ? { background: 'transparent', color: '#1400FF', border: '1px solid #1400FF' }
      : { background: 'transparent', color: '#FFFFFF', border: '1px solid #FFFFFF' },
    MEDIUM: onLight
      ? { background: 'rgba(20,0,255,0.08)', color: 'rgba(20,0,255,0.70)', border: '1px solid rgba(20,0,255,0.20)' }
      : { background: 'transparent', color: 'rgba(255,255,255,0.65)', border: '1px solid rgba(255,255,255,0.40)' },
    LOW: onLight
      ? { background: 'transparent', color: 'rgba(10,10,26,0.35)', border: 'none' }
      : { background: 'transparent', color: 'rgba(255,255,255,0.40)', border: 'none' },
  }
  return (
    <span
      style={{
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 9,
        fontWeight: 500,
        letterSpacing: '0.12em',
        padding: '3px 8px',
        display: 'inline-block',
        ...styles[level],
      }}
    >
      {level}
    </span>
  )
}

// ─── Toggle ───────────────────────────────────────────────────────────────────
function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!on)}
      style={{
        width: 44,
        height: 24,
        background: on ? '#FFFFFF' : 'transparent',
        border: on ? '1px solid #FFFFFF' : '1px solid rgba(255,255,255,0.40)',
        cursor: 'pointer',
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        transition: 'background 0.15s, border 0.15s',
        flexShrink: 0,
      }}
    >
      <div
        style={{
          width: 16,
          height: 16,
          background: on ? '#1400FF' : 'rgba(255,255,255,0.60)',
          position: 'absolute',
          left: on ? 24 : 2,
          transition: 'left 0.15s, background 0.15s',
        }}
      />
    </button>
  )
}

// ─── Screen 1: Landing ────────────────────────────────────────────────────────
function LandingPage({ onSubmit }: { onSubmit: (url: string, jobId: string) => void }) {
  const [url, setUrl] = useState('')
  const [maxExplanations, setMaxExplanations] = useState(20)
  const [skipLlm, setSkipLlm] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [focused, setFocused] = useState(false)
  const [hoverSubmit, setHoverSubmit] = useState(false)
  const [showTooltip, setShowTooltip] = useState(false)

  const validate = (val: string) => /^https?:\/\/github\.com\/[^/]+\/[^/]+/.test(val)

  const handleSubmit = async () => {
    if (!validate(url)) {
      setError('INVALID GITHUB URL — MUST MATCH github.com/owner/repo')
      return
    }
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_url: url,
          max_explanations: maxExplanations,
          skip_llm: skipLlm,
        }),
      })
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      const { job_id } = await res.json()
      onSubmit(url, job_id)
    } catch (err) {
      setError(`CONNECTION FAILED — IS THE SERVER RUNNING? (${err instanceof Error ? err.message : 'unknown error'})`)
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: '#1400FF' }}>
      <NavBar onLogoClick={() => {}} />
      <div style={{ display: 'flex', flex: 1, position: 'relative', overflow: 'hidden' }}>
        {/* Left column */}
        <div
          style={{
            width: 600,
            flexShrink: 0,
            padding: '0 0 0 96px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
          }}
        >
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 58, fontWeight: 400, color: '#FFFFFF', lineHeight: 0.95, letterSpacing: '-0.01em', textTransform: 'uppercase' }}>
              UNDERSTAND
            </div>
            <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 58, fontWeight: 400, color: '#FFFFFF', lineHeight: 0.95, letterSpacing: '-0.01em', textTransform: 'uppercase' }}>
              ANY CODEBASE
            </div>
          </div>

          <p style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: 16, fontWeight: 400, color: 'rgba(255,255,255,0.65)', maxWidth: 420, lineHeight: 1.6, margin: '0 0 32px 0' }}>
            Enter a public GitHub URL. Gnosis maps every import, scores every function, and writes the onboarding document your team never did.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(255,255,255,0.65)', marginBottom: 8 }}>
              REPOSITORY URL
            </div>

            <input
              type="text"
              value={url}
              onChange={(e) => { setUrl(e.target.value); setError('') }}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              placeholder="https://github.com/owner/repo"
              style={{
                width: 480,
                height: 56,
                background: '#FFFFFF',
                border: error ? '1px solid #FF3B3B' : focused ? '1px solid #FFFFFF' : '1px solid rgba(255,255,255,0.30)',
                padding: '0 20px',
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 14,
                fontWeight: 400,
                color: '#1400FF',
                outline: 'none',
                boxSizing: 'border-box',
              }}
              onKeyDown={(e) => e.key === 'Enter' && !loading && handleSubmit()}
            />
            <style>{`input::placeholder { color: rgba(20,0,255,0.35) !important; }`}</style>

            {error && (
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, letterSpacing: '0.1em', color: '#FF3B3B', marginTop: 6, maxWidth: 480 }}>
                {error}
              </div>
            )}

            <div style={{ display: 'flex', gap: 32, marginTop: 16, alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, letterSpacing: '0.14em', color: 'rgba(255,255,255,0.65)', marginBottom: 8 }}>
                  MAX EXPLANATIONS
                </div>
                <input
                  type="number"
                  value={maxExplanations}
                  onChange={(e) => setMaxExplanations(Number(e.target.value))}
                  style={{ width: 72, height: 40, background: '#FFFFFF', border: '1px solid rgba(255,255,255,0.30)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 500, color: '#1400FF', textAlign: 'center', outline: 'none' }}
                />
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, letterSpacing: '0.14em', color: 'rgba(255,255,255,0.65)' }}>
                    SKIP LLM
                  </div>
                  <div style={{ position: 'relative' }}>
                    <button
                      onMouseEnter={() => setShowTooltip(true)}
                      onMouseLeave={() => setShowTooltip(false)}
                      style={{ width: 16, height: 16, background: 'transparent', border: '1px solid rgba(255,255,255,0.40)', color: 'rgba(255,255,255,0.65)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, cursor: 'default', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0 }}
                    >
                      ?
                    </button>
                    {showTooltip && (
                      <div style={{ position: 'absolute', left: 24, top: -8, width: 220, background: '#0F00CC', border: '1px solid #FFFFFF', padding: '10px 14px', fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: '#FFFFFF', lineHeight: 1.5, zIndex: 10 }}>
                        Skips Groq LLM calls. Pipeline completes faster but without per-file explanations.
                      </div>
                    )}
                  </div>
                </div>
                <Toggle on={skipLlm} onChange={setSkipLlm} />
              </div>
            </div>

            <button
              onClick={handleSubmit}
              disabled={loading}
              onMouseEnter={() => !loading && setHoverSubmit(true)}
              onMouseLeave={() => setHoverSubmit(false)}
              style={{
                width: 480,
                height: 56,
                marginTop: 16,
                background: loading ? 'rgba(255,255,255,0.30)' : hoverSubmit ? 'transparent' : '#FFFFFF',
                border: loading ? 'none' : hoverSubmit ? '1px solid #FFFFFF' : 'none',
                color: loading ? 'rgba(255,255,255,0.60)' : hoverSubmit ? '#FFFFFF' : '#1400FF',
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 13,
                fontWeight: 500,
                letterSpacing: '0.14em',
                cursor: loading ? 'not-allowed' : 'pointer',
                transition: 'all 0.15s',
              }}
            >
              {loading ? 'SUBMITTING ···' : 'ANALYZE REPOSITORY →'}
            </button>
          </div>

          <div style={{ position: 'fixed', bottom: 32, right: 96, fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.35)' }}>
            v0.1.0 · PiUnknown · Project Gnosis
          </div>
        </div>

        <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          <AthenaFigure brightness={0.88} />
        </div>
      </div>
    </div>
  )
}

// ─── Screen 2: Progress ───────────────────────────────────────────────────────
function ProgressPage({ repoUrl, jobId, onComplete }: { repoUrl: string; jobId: string; onComplete: () => void }) {
  const [agentStatuses, setAgentStatuses] = useState<AgentStatus[]>(
    Array(7).fill('queued' as AgentStatus)
  )
  const [agentNames, setAgentNames] = useState<string[]>(
    ['INGESTION','AST PARSER','DEPENDENCY GRAPH','COMPLEXITY SCORER','CODE RAG','EXPLAINABILITY','DOC GENERATOR']
  )
  const [jobStatus, setJobStatus] = useState<'running' | 'complete' | 'failed'>('running')
  const [errorMsg, setErrorMsg] = useState('')
  const [hoverBtn, setHoverBtn] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    // If no real jobId (demo mode), simulate with timers
    if (!jobId) {
      let idx = 0
      setAgentStatuses(prev => { const n = [...prev]; n[0] = 'running'; return n })
      const t = setInterval(() => {
        setAgentStatuses(prev => {
          const n = [...prev]
          const running = n.findIndex(s => s === 'running')
          if (running === -1) { clearInterval(t); return n }
          n[running] = 'complete'
          if (running + 1 < 7) n[running + 1] = 'running'
          else { setJobStatus('complete'); clearInterval(t) }
          return n
        })
        idx++
      }, 2200)
      return () => clearInterval(t)
    }

    // Real polling against FastAPI
    const poll = async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`)
        if (!res.ok) return
        const data: JobState = await res.json()
        const names = data.agents.map(a => a.name)
        const statuses = data.agents.map(a => a.status)
        setAgentNames(names)
        setAgentStatuses(statuses)
        if (data.status === 'complete') {
          setJobStatus('complete')
          clearInterval(intervalRef.current!)
        }
        if (data.status === 'failed') {
          setJobStatus('failed')
          setErrorMsg(data.error || 'Unknown error')
          clearInterval(intervalRef.current!)
        }
      } catch {
        // network blip — keep polling
      }
    }

    poll() // immediate first call
    intervalRef.current = setInterval(poll, 1500)
    return () => clearInterval(intervalRef.current!)
  }, [jobId])

  const completeCount = agentStatuses.filter(s => s === 'complete').length
  const runningIdx = agentStatuses.findIndex(s => s === 'running')
  const progress = Math.round(((completeCount + (runningIdx !== -1 ? 0.5 : 0)) / 7) * 100)
  const currentName = runningIdx !== -1 ? agentNames[runningIdx] : agentNames[Math.min(completeCount, 6)]
  const displayRepo = repoUrl.replace(/^https?:\/\//, '') || 'github.com/owner/repo'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', background: '#1400FF', position: 'relative', overflow: 'hidden' }}>
      <AthenaFigure brightness={0.55} />
      <NavBar onLogoClick={() => {}} />

      {/* Repo context bar */}
      <div style={{ height: 48, borderBottom: '1px solid rgba(255,255,255,0.15)', padding: '0 120px', display: 'flex', alignItems: 'center', gap: 16, position: 'relative', zIndex: 1, flexShrink: 0 }}>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(255,255,255,0.50)' }}>ANALYZING</span>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 400, color: '#FFFFFF' }}>{displayRepo}</span>
        <div style={{ marginLeft: 'auto' }}>
          {jobStatus === 'running' && (
            <span className="pulse-border" style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: '#FFFFFF', border: '1px solid #FFFFFF', padding: '4px 12px' }}>
              RUNNING
            </span>
          )}
          {jobStatus === 'complete' && (
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: '#FFFFFF', border: '1px solid #FFFFFF', padding: '4px 12px' }}>
              COMPLETE ✓
            </span>
          )}
          {jobStatus === 'failed' && (
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: '#FF3B3B', border: '1px solid #FF3B3B', padding: '4px 12px' }}>
              FAILED
            </span>
          )}
        </div>
      </div>

      {/* Main content */}
      <div style={{ display: 'flex', flex: 1, maxWidth: 1200, margin: '0 auto', width: '100%', padding: '0 120px', boxSizing: 'border-box', position: 'relative', zIndex: 1 }}>
        {/* Left: Pipeline */}
        <div style={{ width: 500, flexShrink: 0, paddingTop: 64 }}>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.16em', color: 'rgba(255,255,255,0.50)', marginBottom: 32 }}>
            PIPELINE STATUS
          </div>
          {agentNames.map((name, idx) => {
            const status = agentStatuses[idx]
            const isRunning = status === 'running'
            const isComplete = status === 'complete'
            const isQueued = status === 'queued'
            return (
              <div
                key={idx}
                style={{
                  height: 72,
                  borderBottom: '1px solid rgba(255,255,255,0.10)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  paddingRight: 16,
                  opacity: isQueued ? 0.35 : 1,
                  borderLeft: isRunning ? '2px solid #FFFFFF' : '2px solid transparent',
                  paddingLeft: isRunning ? 14 : 0,
                  transition: 'opacity 0.3s, border-left 0.3s',
                }}
              >
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 400, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.30)', width: 28, flexShrink: 0 }}>
                  {String(idx + 1).padStart(2, '0')}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 500, letterSpacing: '0.10em', color: '#FFFFFF' }}>{name}</div>
                  <div style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: 12, color: 'rgba(255,255,255,0.45)', marginTop: 3 }}>{AGENT_DESCS[idx]}</div>
                </div>
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: isComplete ? 500 : 400, letterSpacing: '0.08em', color: isComplete ? '#FFFFFF' : isRunning ? '#FFFFFF' : 'rgba(255,255,255,0.25)', minWidth: 100, textAlign: 'right' }}>
                  {isQueued && '—'}
                  {isRunning && <span>RUNNING <span className="running-dots" /></span>}
                  {isComplete && 'COMPLETE ✓'}
                  {status === 'failed' && <span style={{ color: '#FF3B3B' }}>FAILED</span>}
                </div>
              </div>
            )
          })}
        </div>

        {/* Right: Progress display */}
        <div style={{ flex: 1, paddingTop: 64, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'flex-start', paddingLeft: 80 }}>
          {jobStatus === 'running' && (
            <>
              <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 120, fontWeight: 400, color: '#FFFFFF', letterSpacing: '-0.02em', lineHeight: 1.0, transition: 'all 0.5s' }}>
                {progress}%
              </div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, letterSpacing: '0.16em', color: 'rgba(255,255,255,0.65)', marginTop: 16 }}>
                {currentName}
              </div>
              <div style={{ marginTop: 24, width: 300, height: 1, background: 'rgba(255,255,255,0.20)', position: 'relative' }}>
                <div style={{ position: 'absolute', top: 0, left: 0, height: 1, background: '#FFFFFF', width: `${progress}%`, transition: 'width 0.5s' }} />
              </div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, letterSpacing: '0.14em', color: 'rgba(255,255,255,0.40)', marginTop: 12 }}>
                {completeCount} OF 7 AGENTS COMPLETE
              </div>
            </>
          )}
          {jobStatus === 'complete' && (
            <>
              <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 80, fontWeight: 400, color: '#FFFFFF', textTransform: 'uppercase', lineHeight: 1.0 }}>
                COMPLETE
              </div>
              <button
                onMouseEnter={() => setHoverBtn(true)}
                onMouseLeave={() => setHoverBtn(false)}
                onClick={onComplete}
                style={{ marginTop: 32, width: 280, height: 56, background: hoverBtn ? 'transparent' : '#FFFFFF', border: hoverBtn ? '1px solid #FFFFFF' : 'none', color: hoverBtn ? '#FFFFFF' : '#1400FF', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, letterSpacing: '0.14em', cursor: 'pointer', transition: 'all 0.15s' }}
              >
                ANALYSIS COMPLETE — VIEW RESULTS
              </button>
            </>
          )}
          {jobStatus === 'failed' && (
            <>
              <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 80, fontWeight: 400, color: '#FF3B3B', textTransform: 'uppercase', lineHeight: 1.0 }}>
                FAILED
              </div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: 'rgba(255,255,255,0.65)', marginTop: 16, maxWidth: 320 }}>{errorMsg}</div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Screen 3: Results ────────────────────────────────────────────────────────
function HoverRow({ children, height = 48 }: { children: React.ReactNode; height?: number }) {
  const [hovered, setHovered] = useState(false)
  return (
    <tr onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} style={{ height, borderBottom: '1px solid rgba(20,0,255,0.08)', background: hovered ? 'rgba(20,0,255,0.04)' : 'transparent', transition: 'background 0.1s' }}>
      {children}
    </tr>
  )
}

function DownloadBtn({ label, onLight = false, onClick }: { label: string; onLight?: boolean; onClick?: () => void }) {
  const [hovered, setHovered] = useState(false)
  const base: React.CSSProperties = {
    height: onLight ? 32 : 36,
    padding: '0 16px',
    cursor: 'pointer',
    fontFamily: "'IBM Plex Mono', monospace",
    fontSize: 10,
    fontWeight: 500,
    letterSpacing: '0.12em',
    transition: 'all 0.12s',
  }
  if (onLight) {
    return <button onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} onClick={onClick} style={{ ...base, border: '1px solid #1400FF', background: hovered ? '#1400FF' : 'transparent', color: hovered ? '#FFFFFF' : '#1400FF' }}>{label}</button>
  }
  return <button onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} onClick={onClick} style={{ ...base, border: '1px solid rgba(255,255,255,0.45)', background: hovered ? '#FFFFFF' : 'transparent', color: hovered ? '#1400FF' : '#FFFFFF' }}>{label}</button>
}

function CollapsibleSection({ title, count, content, defaultOpen = false }: { title: string; count: string; content: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [copied, setCopied] = useState(false)
  const [hoverCopy, setHoverCopy] = useState(false)
  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(content).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div style={{ marginBottom: 12 }}>
      <div onClick={() => setOpen(!open)} style={{ height: 52, display: 'flex', alignItems: 'center', padding: '0 20px', border: '1px solid rgba(20,0,255,0.15)', borderBottom: open ? 'none' : '1px solid rgba(20,0,255,0.15)', cursor: 'pointer', background: 'transparent', userSelect: 'none' }}>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, letterSpacing: '0.10em', color: '#0A0A1A', textTransform: 'uppercase' }}>{title}</span>
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, color: 'rgba(10,10,26,0.40)' }}>{count}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={handleCopy} onMouseEnter={() => setHoverCopy(true)} onMouseLeave={() => setHoverCopy(false)} style={{ height: 28, padding: '0 10px', border: '1px solid rgba(20,0,255,0.30)', background: hoverCopy ? '#1400FF' : 'transparent', color: hoverCopy ? '#FFFFFF' : '#1400FF', fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fontWeight: 500, letterSpacing: '0.12em', cursor: 'pointer', transition: 'all 0.12s' }}>
            {copied ? 'COPIED ✓' : 'COPY'}
          </button>
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: 'rgba(10,10,26,0.40)' }}>{open ? '▴' : '▾'}</span>
        </div>
      </div>
      {open && (
        <div className="auto-scroll" style={{ border: '1px solid rgba(20,0,255,0.15)', borderTop: 'none', padding: 20, maxHeight: 320, overflowY: 'auto', background: 'rgba(20,0,255,0.03)' }}>
          <pre style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: '#0A0A1A', whiteSpace: 'pre-wrap', lineHeight: 1.6, margin: 0 }}>{content}</pre>
        </div>
      )}
    </div>
  )
}

function ResultsPage({ repoUrl, jobId }: { repoUrl: string; jobId: string }) {
  const [activeTab, setActiveTab] = useState<ResultsTab>('onboarding')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [fileFilter, setFileFilter] = useState('')

  useEffect(() => {
    if (!jobId) { setLoading(false); return }
    fetch(`/api/jobs/${jobId}/result`)
      .then(r => r.json())
      .then(data => { setResult(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [jobId])

  const TABS: { id: ResultsTab; label: string }[] = [
    { id: 'onboarding', label: 'ONBOARDING DOC' },
    { id: 'dependency', label: 'DEPENDENCY GRAPH' },
    { id: 'complexity', label: 'COMPLEXITY REPORT' },
    { id: 'raw', label: 'RAW OUTPUT' },
  ]

  const displayRepo = (repoUrl.replace(/^https?:\/\/github\.com\//, '') || 'owner/repo').toUpperCase()
  const s = result?.summary
  const riskDist = s?.risk_distribution || {}
  const depRows = result?.dependency_rows || []
  const readingOrder = result?.reading_order || []
  const complexityRows = (result?.complexity_rows || []).filter(r => !fileFilter || r.file.toLowerCase().includes(fileFilter.toLowerCase()))

  const handleDownload = (content: string, filename: string, mime = 'text/plain') => {
    const blob = new Blob([content], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', background: '#1400FF', paddingBottom: 64 }}>
      <NavBar onLogoClick={() => {}} />

      {/* Results header */}
      <div style={{ padding: '28px 96px 24px', borderBottom: '1px solid rgba(255,255,255,0.15)', flexShrink: 0, boxSizing: 'border-box' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 12 }}>
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 500, letterSpacing: '0.10em', color: '#FFFFFF' }}>{displayRepo}</span>
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.50)' }}>ON MAIN</span>
        </div>
        <div style={{ display: 'flex', gap: 32, alignItems: 'center', flexWrap: 'wrap' }}>
          {[
            { n: s?.total_files ?? '—', l: 'FILES' },
            { n: s?.total_functions ?? '—', l: 'FUNCTIONS' },
            { n: s?.total_classes ?? '—', l: 'CLASSES' },
            { n: s?.import_edges ?? '—', l: 'IMPORT EDGES' },
            { n: s?.explained ?? '—', l: 'EXPLAINED' },
          ].map(stat => (
            <div key={stat.l}>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, fontWeight: 500, color: '#FFFFFF' }}>{String(stat.n)}</div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.50)' }}>{stat.l}</div>
            </div>
          ))}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginLeft: 8 }}>
            {(['CRITICAL','HIGH','MEDIUM','LOW'] as RiskLevel[]).map(level => {
              const count = riskDist[level] ?? 0
              const styleMap: Record<RiskLevel, React.CSSProperties> = {
                CRITICAL: { background: '#FFFFFF', color: '#1400FF', border: 'none' },
                HIGH: { background: 'transparent', color: '#FFFFFF', border: '1px solid #FFFFFF' },
                MEDIUM: { background: 'transparent', color: 'rgba(255,255,255,0.65)', border: '1px solid rgba(255,255,255,0.40)' },
                LOW: { background: 'transparent', color: 'rgba(255,255,255,0.40)', border: 'none' },
              }
              return <span key={level} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', padding: '3px 10px', ...styleMap[level] }}>{level}: {count}</span>
            })}
          </div>
          {(s?.circular_cycles ?? 0) > 0 && (
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', color: '#FFFFFF', background: 'rgba(255,255,255,0.10)', border: '1px solid rgba(255,255,255,0.30)', padding: '6px 12px', marginLeft: 'auto' }}>
              ⚠ {s!.circular_cycles} CIRCULAR DEPENDENCY {s!.circular_cycles === 1 ? 'CYCLE' : 'CYCLES'} DETECTED
            </span>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ height: 52, background: '#0F00CC', borderBottom: '1px solid rgba(255,255,255,0.15)', padding: '0 96px', display: 'flex', alignItems: 'stretch', flexShrink: 0 }}>
        {TABS.map((tab, idx) => {
          const isActive = tab.id === activeTab
          const nextActive = idx < TABS.length - 1 && TABS[idx + 1].id === activeTab
          const showSep = idx < TABS.length - 1 && !isActive && !nextActive
          return (
            <div key={tab.id} style={{ display: 'flex', alignItems: 'stretch' }}>
              <button
                onClick={() => setActiveTab(tab.id)}
                style={{ padding: '0 32px', height: '100%', background: 'transparent', border: 'none', borderBottom: isActive ? '2px solid #FFFFFF' : '2px solid transparent', color: isActive ? '#FFFFFF' : 'rgba(255,255,255,0.45)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 500, letterSpacing: '0.14em', cursor: 'pointer', textTransform: 'uppercase', transition: 'color 0.12s' }}
                onMouseEnter={e => { if (!isActive) (e.target as HTMLElement).style.color = '#FFFFFF' }}
                onMouseLeave={e => { if (!isActive) (e.target as HTMLElement).style.color = 'rgba(255,255,255,0.45)' }}
              >
                {tab.label}
              </button>
              {showSep && <div style={{ width: 1, background: 'rgba(255,255,255,0.15)', alignSelf: 'stretch', margin: '12px 0' }} />}
            </div>
          )
        })}
      </div>

      {/* Tab content */}
      <div className="auto-scroll" style={{ background: '#F0F0FF', padding: '48px 96px', flex: 1, overflowY: 'auto' }}>

        {/* Loading state */}
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 300 }}>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, letterSpacing: '0.12em', color: 'rgba(10,10,26,0.40)' }}>LOADING RESULTS ···</span>
          </div>
        )}

        {/* ── Tab 1: Onboarding Doc ── */}
        {!loading && activeTab === 'onboarding' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(10,10,26,0.50)' }}>ONBOARDING DOCUMENT</span>
              <DownloadBtn label="↓ DOWNLOAD .MD" onLight onClick={() => handleDownload(result?.onboarding_doc || '', 'onboarding.md')} />
            </div>
            <div className="gnosis-markdown" style={{ maxWidth: 760, margin: '0 auto' }}>
              {result?.onboarding_doc
                ? <ReactMarkdown>{result.onboarding_doc}</ReactMarkdown>
                : <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'rgba(10,10,26,0.40)', letterSpacing: '0.10em' }}>NO DOCUMENT GENERATED YET</p>
              }
            </div>
          </div>
        )}

        {/* ── Tab 2: Dependency Graph ── */}
        {!loading && activeTab === 'dependency' && (
          <div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.16em', color: 'rgba(10,10,26,0.45)', marginBottom: 16 }}>MOST IMPORTED FILES</div>
            {depRows.length === 0
              ? <EmptyState label="NO DEPENDENCY DATA AVAILABLE" />
              : (
                <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid rgba(20,0,255,0.15)', marginBottom: 48 }}>
                  <thead>
                    <tr style={{ background: 'rgba(20,0,255,0.06)', height: 40 }}>
                      {['FILE','IMPORTED BY','IMPORTS','RISK'].map(h => (
                        <th key={h} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(10,10,26,0.50)', padding: '0 20px', textAlign: h === 'FILE' ? 'left' : 'center', border: '1px solid rgba(20,0,255,0.12)' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {depRows.map(row => (
                      <HoverRow key={row.path}>
                        <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: '#1400FF', padding: '0 20px', height: 48 }}>{row.file}</td>
                        <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 500, color: '#1400FF', textAlign: 'center', padding: '0 20px' }}>{row.imported_by}</td>
                        <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 400, color: 'rgba(10,10,26,0.65)', textAlign: 'center', padding: '0 20px' }}>{row.imports}</td>
                        <td style={{ textAlign: 'center', padding: '0 20px' }}><RiskBadge level={row.risk} onLight /></td>
                      </HoverRow>
                    ))}
                  </tbody>
                </table>
              )
            }

            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.16em', color: 'rgba(10,10,26,0.45)', marginBottom: 8 }}>SUGGESTED READING ORDER</div>
            <div style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: 13, color: 'rgba(10,10,26,0.50)', marginBottom: 16 }}>Files ordered so each appears after everything it depends on.</div>
            {readingOrder.length === 0
              ? <EmptyState label="NO GRAPH DATA AVAILABLE" />
              : readingOrder.map((path, idx) => (
                <div key={path} style={{ display: 'flex', alignItems: 'center', height: 40, borderBottom: '1px solid rgba(20,0,255,0.08)', gap: 16 }}>
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'rgba(10,10,26,0.35)', fontWeight: 400, width: 28 }}>{String(idx + 1).padStart(2, '0')}</span>
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: '#1400FF' }}>{path}</span>
                </div>
              ))
            }
          </div>
        )}

        {/* ── Tab 3: Complexity Report ── */}
        {!loading && activeTab === 'complexity' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
              <select style={{ height: 40, border: '1px solid rgba(20,0,255,0.20)', background: '#FFFFFF', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 500, letterSpacing: '0.10em', color: '#1400FF', textTransform: 'uppercase', padding: '0 12px', outline: 'none', cursor: 'pointer' }}>
                <option>SORT BY RISK ▾</option>
                <option>SORT BY AVG CC ▾</option>
                <option>SORT BY MAX CC ▾</option>
              </select>
              <input type="text" value={fileFilter} onChange={e => setFileFilter(e.target.value)} placeholder="FILTER BY FILENAME..." style={{ height: 40, width: 240, border: '1px solid rgba(20,0,255,0.20)', background: '#FFFFFF', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: '#1400FF', padding: '0 12px', outline: 'none' }} />
              <span style={{ marginLeft: 'auto', fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, letterSpacing: '0.10em', color: 'rgba(10,10,26,0.40)' }}>
                SHOWING {complexityRows.length} OF {result?.complexity_rows?.length ?? 0} FILES
              </span>
            </div>
            {complexityRows.length === 0
              ? <EmptyState label="NO COMPLEXITY DATA AVAILABLE" />
              : (
                <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid rgba(20,0,255,0.15)' }}>
                  <thead>
                    <tr style={{ background: 'rgba(20,0,255,0.06)', height: 44 }}>
                      {['FILE','RISK','AVG CC','MAX CC','WORST FUNCTION','COUPLING','FLAGS'].map(h => (
                        <th key={h} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(10,10,26,0.45)', padding: '0 16px', textAlign: (h === 'FILE' || h === 'WORST FUNCTION' || h === 'FLAGS') ? 'left' : 'center', borderBottom: '1px solid rgba(20,0,255,0.12)' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {complexityRows.map(row => (
                      <HoverRow key={row.path} height={52}>
                        <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: '#1400FF', padding: '0 16px' }}>{row.file}</td>
                        <td style={{ padding: '0 16px', textAlign: 'center' }}><RiskBadge level={row.risk} onLight /></td>
                        <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 500, color: '#0A0A1A', textAlign: 'center', padding: '0 16px' }}>{typeof row.avg_cc === 'number' ? row.avg_cc.toFixed(1) : row.avg_cc}</td>
                        <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 500, color: row.max_cc >= 21 ? '#1400FF' : '#0A0A1A', textAlign: 'center', padding: '0 16px' }}>{row.max_cc}</td>
                        <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 400, color: '#1400FF', padding: '0 16px', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.worst_fn}</td>
                        <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: 'rgba(10,10,26,0.65)', textAlign: 'center', padding: '0 16px' }}>{row.coupling}</td>
                        <td style={{ padding: '0 16px' }}>
                          {(row.flags || []).map(f => (
                            <span key={f} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: f.includes('PARSE') ? '#FF3B3B' : 'rgba(20,0,255,0.70)', marginRight: 6 }}>{f}</span>
                          ))}
                        </td>
                      </HoverRow>
                    ))}
                  </tbody>
                </table>
              )
            }
          </div>
        )}

        {/* ── Tab 4: Raw Output ── */}
        {!loading && activeTab === 'raw' && (
          <div>
            <CollapsibleSection
              title="SUMMARY"
              count={`${Object.keys(s || {}).length} FIELDS`}
              content={JSON.stringify(s || {}, null, 2)}
              defaultOpen
            />
            <CollapsibleSection
              title="EXPLANATIONS"
              count={`${Object.keys(result?.explanations || {}).length} FILES EXPLAINED`}
              content={JSON.stringify(result?.explanations || {}, null, 2)}
            />
            <CollapsibleSection
              title="COMPLEXITY REPORT"
              count={`${result?.complexity_rows?.length ?? 0} FILES`}
              content={result?.complexity_report_json || '{}'}
            />
            <CollapsibleSection
              title="GRAPH SUMMARY"
              count={`${depRows.length} FILES TRACKED`}
              content={JSON.stringify({ nodes: s?.total_files, edges: s?.import_edges, circular_cycles: s?.circular_cycles, reading_order: readingOrder }, null, 2)}
            />
          </div>
        )}
      </div>

      {/* Sticky download bar */}
      <div style={{ position: 'fixed', bottom: 0, left: 0, right: 0, height: 64, background: '#1400FF', borderTop: '1px solid rgba(255,255,255,0.20)', display: 'flex', alignItems: 'center', padding: '0 96px', gap: 16, zIndex: 100 }}>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.16em', color: 'rgba(255,255,255,0.45)' }}>DOWNLOAD OUTPUTS</span>
        <div style={{ display: 'flex', gap: 12, marginLeft: 24 }}>
          <DownloadBtn label="↓ ONBOARDING.MD" onClick={() => handleDownload(result?.onboarding_doc || '', 'onboarding.md')} />
          <DownloadBtn label="↓ COMPLEXITY_REPORT.JSON" onClick={() => handleDownload(result?.complexity_report_json || '{}', 'complexity_report.json', 'application/json')} />
          <DownloadBtn label="↓ DEPENDENCY_GRAPH.JSON" onClick={() => handleDownload(JSON.stringify(result?.dependency_rows || [], null, 2), 'dependency_graph.json', 'application/json')} />
        </div>
      </div>
    </div>
  )
}

// ─── Empty State ──────────────────────────────────────────────────────────────
function EmptyState({ label }: { label: string }) {
  return (
    <div style={{ textAlign: 'center', padding: '80px 0' }}>
      <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 48, color: 'rgba(20,0,255,0.20)' }}>—</div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'rgba(10,10,26,0.40)', letterSpacing: '0.12em', marginTop: 16 }}>{label}</div>
    </div>
  )
}

// ─── Root App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [screen, setScreen] = useState<Screen>('landing')
  const [repoUrl, setRepoUrl] = useState('')
  const [jobId, setJobId] = useState('')

  const handleSubmit = (url: string, id: string) => {
    setRepoUrl(url)
    setJobId(id)
    setScreen('progress')
  }

  return (
    <>
      {screen === 'landing' && <LandingPage onSubmit={handleSubmit} />}
      {screen === 'progress' && <ProgressPage repoUrl={repoUrl} jobId={jobId} onComplete={() => setScreen('results')} />}
      {screen === 'results' && <ResultsPage repoUrl={repoUrl} jobId={jobId} />}
    </>
  )
}
