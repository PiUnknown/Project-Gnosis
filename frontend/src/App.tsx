import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { motion, AnimatePresence, useMotionValue, useSpring, useTransform, useReducedMotion } from 'motion/react'
const API_BASE = import.meta.env.VITE_API_URL || "";
const APP_VERSION = "1.0.3";

function useWindowWidth() {
  const [width, setWidth] = useState(
    typeof window !== 'undefined' ? window.innerWidth : 1440
  )
  useEffect(() => {
    const fn = () => setWidth(window.innerWidth)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return width
}

type Screen = 'landing' | 'progress' | 'results' | 'error'
type AgentStatus = 'queued' | 'running' | 'complete' | 'failed'
type ResultsTab = 'onboarding' | 'agent_context' | 'explanations' | 'dependency' | 'complexity' | 'raw'

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
  agent_context?: string
  file_explanations_md?: string
  dependency_rows: DepRow[]
  reading_order: string[]
  complexity_rows: ComplexityRow[]
  explanations: Record<string, string>
  complexity_report_json: string
  circular_deps: string[][]
  skip_llm?: boolean
}

type RiskLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

const AGENT_DESCS = [
  'Fetching repository file tree from GitHub API',
  'Parsing syntax trees with tree-sitter',
  'Building directed import graph with NetworkX',
  'Scoring cyclomatic complexity and tech debt',
  'Embedding code chunks into ChromaDB',
  'Generating explanations via LLM',
  'Synthesizing all outputs into onboarding.md',
]

// ─── GnosisLogo ───────────────────────────────────────────────────────────────
// Gnosis (Greek: γνῶσις) means knowledge through direct seeing.
// The eye: a diamond outline + diamond pupil — knowledge that perceives.
// All straight lines, no curves, consistent with 0px radius system.
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
      <path d="M1,9 L9,2 L17,9 L9,16 Z" stroke="white" strokeWidth="1.2" />
      <rect x="7.5" y="7.5" width="3" height="3" transform="rotate(45 9 9)" fill="white" />
    </svg>
  )
}

// ─── NavBar ───────────────────────────────────────────────────────────────────
function NavBar({ onLogoClick }: { onLogoClick: () => void }) {
  const isMobile = useWindowWidth() < 768
  return (
    <nav
      style={{
        height: isMobile ? 56 : 72,
        background: '#1400FF',
        borderBottom: '1px solid rgba(255,255,255,0.15)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: isMobile ? '0 20px' : '0 96px',
        flexShrink: 0,
      }}
    >
      <motion.button
        onClick={onLogoClick}
        whileTap={{ scale: 0.97 }}
        transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
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
      </motion.button>
      {!isMobile && (
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
      )}
    </nav>
  )
}

// ─── Athena Figure ────────────────────────────────────────────────────────────
function AthenaFigure({ brightness = 0.88 }: { brightness?: number }) {
  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden' }}>
      <img
        src="https://images.unsplash.com/photo-1670813885725-e3c5391dcd31?w=900&h=1400&fit=crop&auto=format"
        alt="Athena — goddess of wisdom"
        style={{
          position: 'absolute',
          top: 0,
          left: '50%',
          transform: 'translateX(-40%)',
          height: '100%',
          width: 'auto',
          filter: `grayscale(1) contrast(1.55) brightness(${brightness})`,
          mixBlendMode: 'screen',
          opacity: 0.9,
          WebkitMaskImage: 'linear-gradient(to right, transparent 0%, black 18%, black 80%, transparent 100%)',
          maskImage: 'linear-gradient(to right, transparent 0%, black 18%, black 80%, transparent 100%)',
        }}
      />
    </div>
  )
}

// ─── RiskBadge ────────────────────────────────────────────────────────────────
function RiskBadge({ level, count, onLight = false }: { level: RiskLevel; count?: number; onLight?: boolean }) {
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
      {level}{count !== undefined ? `: ${count}` : ''}
    </span>
  )
}

function RiskDistributionBar({ riskDist }: { riskDist: Record<string, number> }) {
  const critical = riskDist.CRITICAL || 0
  const high = riskDist.HIGH || 0
  const medium = riskDist.MEDIUM || 0
  const low = riskDist.LOW || 0
  const total = critical + high + medium + low
  if (total === 0) return null

  const pct = (val: number) => (val / total) * 100

  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(10,10,26,0.50)' }}>CODEBASE RISK DISTRIBUTION</span>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, color: 'rgba(10,10,26,0.40)' }}>{total} FILES</span>
      </div>
      <div style={{ display: 'flex', height: 12, background: 'rgba(20,0,255,0.04)', border: '1px solid rgba(20,0,255,0.15)', overflow: 'hidden' }}>
        {critical > 0 && (
          <div style={{ width: `${pct(critical)}%`, background: '#1400FF' }} title={`CRITICAL: ${critical} files (${pct(critical).toFixed(1)}%)`} />
        )}
        {high > 0 && (
          <div style={{ width: `${pct(high)}%`, background: 'transparent', border: '1px solid #1400FF', boxSizing: 'border-box' }} title={`HIGH: ${high} files (${pct(high).toFixed(1)}%)`} />
        )}
        {medium > 0 && (
          <div style={{ width: `${pct(medium)}%`, background: 'rgba(20,0,255,0.08)', border: '1px solid rgba(20,0,255,0.20)', boxSizing: 'border-box' }} title={`MEDIUM: ${medium} files (${pct(medium).toFixed(1)}%)`} />
        )}
        {low > 0 && (
          <div style={{ width: `${pct(low)}%`, background: 'transparent' }} title={`LOW: ${low} files (${pct(low).toFixed(1)}%)`} />
        )}
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
        {[
          { label: 'CRITICAL', count: critical, background: '#1400FF', border: 'none' },
          { label: 'HIGH', count: high, background: 'transparent', border: '1px solid #1400FF' },
          { label: 'MEDIUM', count: medium, background: 'rgba(20,0,255,0.08)', border: '1px solid rgba(20,0,255,0.20)' },
          { label: 'LOW', count: low, background: 'transparent', border: '1px solid rgba(20,0,255,0.15)' },
        ].map(item => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{
              width: 8,
              height: 8,
              display: 'inline-block',
              background: item.background,
              border: item.border,
              boxSizing: 'border-box'
            }} />
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, color: 'rgba(10,10,26,0.65)' }}>{item.label}: {item.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Toggle ───────────────────────────────────────────────────────────────────
function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  const reducedMotion = useReducedMotion()
  return (
    <motion.button
      onClick={() => onChange(!on)}
      whileTap={{ scale: 0.97 }}
      transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
      style={{
        width: 44,
        height: 24,
        background: on ? '#FFFFFF' : 'transparent',
        border: on ? '1px solid #FFFFFF' : '1px solid rgba(255,255,255,0.40)',
        cursor: 'pointer',
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        flexShrink: 0,
      }}
    >
      <motion.div
        animate={{
          left: on ? 24 : 2,
          background: on ? '#1400FF' : 'rgba(255,255,255,0.60)',
        }}
        transition={
          reducedMotion
            ? { duration: 0.1 }
            : { type: 'spring', bounce: 0, duration: 0.3 }
        }
        style={{
          width: 16,
          height: 16,
          position: 'absolute',
        }}
      />
    </motion.button>
  )
}

// ─── Screen 1: Landing ────────────────────────────────────────────────────────
function LandingPage({ onSubmit }: { onSubmit: (url: string, jobId: string) => void }) {
  const [url, setUrl] = useState('')
  const [maxExplanations, setMaxExplanations] = useState(20)
  const [skipLlm, setSkipLlm] = useState(true)
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
      const res = await fetch(`${API_BASE}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_url: url,
          max_explanations: maxExplanations,
          skip_llm: skipLlm,
        }),
      })
      if (!res.ok) {
        let data: any = null
        try {
          data = await res.json()
        } catch {
          // ignore parsing error
        }

        if (res.status === 409 && data && data.job_id) {
          onSubmit(url, data.job_id)
          return
        }

        let msg = `Server error: ${res.status}`
        if (data && data.detail) {
          msg = data.detail
        } else if (data && data.message) {
          msg = data.message
        }
        throw new Error(msg)
      }
      const { job_id } = await res.json()
      onSubmit(url, job_id)
    } catch (err) {
      const rawMsg = err instanceof Error ? err.message : 'unknown error'
      if (rawMsg.includes('Failed to fetch') || rawMsg.includes('NetworkError') || rawMsg.includes('Network request failed')) {
        setError(`CONNECTION FAILED — IS THE SERVER RUNNING? (${rawMsg})`)
      } else {
        setError(rawMsg.toUpperCase())
      }
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: '#1400FF' }}>
      <NavBar onLogoClick={() => { }} />
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
                    <motion.button
                      onMouseEnter={() => setShowTooltip(true)}
                      onMouseLeave={() => setShowTooltip(false)}
                      whileTap={{ scale: 0.97 }}
                      transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
                      style={{ width: 16, height: 16, background: 'transparent', border: '1px solid rgba(255,255,255,0.40)', color: 'rgba(255,255,255,0.65)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, cursor: 'default', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0 }}
                    >
                      ?
                    </motion.button>
                    {showTooltip && (
                      <div style={{ position: 'absolute', left: 24, top: -8, width: 220, background: '#0F00CC', border: '1px solid #FFFFFF', padding: '10px 14px', fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: '#FFFFFF', lineHeight: 1.5, zIndex: 10 }}>
                        Skips LLM calls. Pipeline completes faster but without per-file explanations.
                      </div>
                    )}
                  </div>
                </div>
                <Toggle on={skipLlm} onChange={setSkipLlm} />
              </div>
            </div>

            <motion.button
              onClick={handleSubmit}
              disabled={loading}
              onMouseEnter={() => !loading && setHoverSubmit(true)}
              onMouseLeave={() => setHoverSubmit(false)}
              whileTap={{ scale: 0.97 }}
              transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
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
            </motion.button>
          </div>

          <div style={{ position: 'fixed', bottom: 32, right: 96, fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.35)' }}>
            v{APP_VERSION} · PiUnknown · Project Gnosis
          </div>
        </div>

        <div style={{ flex: 1, position: 'relative', overflow: 'hidden', minWidth: 0 }}>
          <AthenaFigure brightness={0.88} />
        </div>
      </div>
    </div>
  )
}

// ─── Screen 2: Progress ───────────────────────────────────────────────────────
function ProgressPage({ repoUrl, jobId, onComplete, onHome }: { repoUrl: string; jobId: string; onComplete: () => void; onHome: () => void }) {
  const [agentStatuses, setAgentStatuses] = useState<AgentStatus[]>(
    Array(7).fill('queued' as AgentStatus)
  )
  const [agentNames, setAgentNames] = useState<string[]>(
    ['INGESTION', 'AST PARSER', 'DEPENDENCY GRAPH', 'COMPLEXITY SCORER', 'CODE RAG', 'EXPLAINABILITY', 'DOC GENERATOR']
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
        const res = await fetch(`${API_BASE}/api/jobs/${jobId}`)
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

  const reducedMotion = useReducedMotion()
  const smoothProgress = useMotionValue(0)
  const springProgress = useSpring(smoothProgress, {
    duration: 0.6,
    bounce: 0,
  })
  const displayProgress = useTransform(springProgress, (v) => Math.round(v))

  // Keep a ref to track displayed value for the counter
  const [displayValue, setDisplayValue] = useState(0)
  useEffect(() => {
    smoothProgress.set(progress)
  }, [progress, smoothProgress])

  useEffect(() => {
    const unsubscribe = displayProgress.on('change', (v) => {
      setDisplayValue(Math.round(v))
    })
    return unsubscribe
  }, [displayProgress])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', background: '#1400FF', position: 'relative', overflow: 'hidden' }}>
      <AthenaFigure brightness={0.55} />
      <NavBar onLogoClick={onHome} />

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
          <motion.div
            initial="hidden"
            animate="show"
            variants={
              reducedMotion
                ? undefined
                : { show: { transition: { staggerChildren: 0.06 } } }
            }
          >
            {agentNames.map((name, idx) => {
              const status = agentStatuses[idx]
              const isRunning = status === 'running'
              const isComplete = status === 'complete'
              const isQueued = status === 'queued'
              return (
                <motion.div
                  key={idx}
                  variants={
                    reducedMotion
                      ? undefined
                      : {
                          hidden: { opacity: 0, x: -12 },
                          show: { opacity: 1, x: 0 },
                        }
                  }
                  transition={
                    reducedMotion
                      ? { duration: 0.1 }
                      : { type: 'spring', bounce: 0, duration: 0.3 }
                  }
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
                </motion.div>
              )
            })}
          </motion.div>
        </div>

        {/* Right: Progress display */}
        <div style={{ flex: 1, paddingTop: 64, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'flex-start', paddingLeft: 80 }}>
          {jobStatus === 'running' && (
            <>
              <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 120, fontWeight: 400, color: '#FFFFFF', letterSpacing: '-0.02em', lineHeight: 1.0 }}>
                {displayValue}%
              </div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, letterSpacing: '0.16em', color: 'rgba(255,255,255,0.65)', marginTop: 16 }}>
                {currentName}
              </div>
              <div style={{ marginTop: 24, width: 300, height: 1, background: 'rgba(255,255,255,0.20)', position: 'relative' }}>
                <motion.div
                  animate={{ width: `${progress}%` }}
                  transition={
                    reducedMotion
                      ? { duration: 0.1 }
                      : { type: 'spring', bounce: 0, duration: 0.6 }
                  }
                  style={{ position: 'absolute', top: 0, left: 0, height: 1, background: '#FFFFFF' }}
                />
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
              <motion.button
                onMouseEnter={() => setHoverBtn(true)}
                onMouseLeave={() => setHoverBtn(false)}
                onClick={onComplete}
                whileTap={{ scale: 0.97 }}
                transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
                style={{ marginTop: 32, width: 280, height: 56, background: hoverBtn ? 'transparent' : '#FFFFFF', border: hoverBtn ? '1px solid #FFFFFF' : 'none', color: hoverBtn ? '#FFFFFF' : '#1400FF', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, letterSpacing: '0.14em', cursor: 'pointer', transition: 'all 0.15s' }}
              >
                ANALYSIS COMPLETE — VIEW RESULTS
              </motion.button>
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
    return (
      <motion.button
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={onClick}
        whileTap={{ scale: 0.97 }}
        transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
        style={{ ...base, border: '1px solid #1400FF', background: hovered ? '#1400FF' : 'transparent', color: hovered ? '#FFFFFF' : '#1400FF' }}
      >
        {label}
      </motion.button>
    )
  }
  return (
    <motion.button
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
      whileTap={{ scale: 0.97 }}
      transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
      style={{ ...base, border: '1px solid rgba(255,255,255,0.45)', background: hovered ? '#FFFFFF' : 'transparent', color: hovered ? '#1400FF' : '#FFFFFF' }}
    >
      {label}
    </motion.button>
  )
}

function CollapsibleSection({ title, count, content, defaultOpen = false }: { title: string; count: string; content: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [copied, setCopied] = useState(false)
  const [hoverCopy, setHoverCopy] = useState(false)
  const reducedMotion = useReducedMotion()
  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(content).catch(() => { })
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
          <motion.button
            onClick={handleCopy}
            onMouseEnter={() => setHoverCopy(true)}
            onMouseLeave={() => setHoverCopy(false)}
            whileTap={{ scale: 0.97 }}
            transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
            style={{ height: 28, padding: '0 10px', border: '1px solid rgba(20,0,255,0.30)', background: hoverCopy ? '#1400FF' : 'transparent', color: hoverCopy ? '#FFFFFF' : '#1400FF', fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fontWeight: 500, letterSpacing: '0.12em', cursor: 'pointer', transition: 'all 0.12s' }}
          >
            {copied ? 'COPIED ✓' : 'COPY'}
          </motion.button>
          <motion.span
            animate={{ rotate: open ? 180 : 0 }}
            transition={
              reducedMotion
                ? { duration: 0.1 }
                : { type: 'spring', bounce: 0, duration: 0.3 }
            }
            style={{ display: 'inline-block', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: 'rgba(10,10,26,0.40)', transformOrigin: 'center' }}
          >
            ▾
          </motion.span>
        </div>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={reducedMotion ? { opacity: 0 } : { height: 0, opacity: 0 }}
            animate={reducedMotion ? { opacity: 1 } : { height: 'auto', opacity: 1 }}
            exit={reducedMotion ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={
              reducedMotion
                ? { duration: 0.15 }
                : { type: 'spring', bounce: 0, duration: 0.35 }
            }
            style={{ overflow: 'hidden' }}
          >
            <div className="auto-scroll" style={{ border: '1px solid rgba(20,0,255,0.15)', borderTop: 'none', padding: 20, maxHeight: 320, overflowY: 'auto', background: 'rgba(20,0,255,0.03)' }}>
              <pre style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: '#0A0A1A', whiteSpace: 'pre-wrap', lineHeight: 1.6, margin: 0 }}>{content}</pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function ResultsPage({ repoUrl, jobId, onHome }: { repoUrl: string; jobId: string; onHome: () => void }) {
  const [activeTab, setActiveTab] = useState<ResultsTab>('onboarding')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [fileFilter, setFileFilter] = useState('')
  const [sortBy, setSortBy] = useState<'risk' | 'avg_cc' | 'max_cc'>('risk')
  const reducedMotion = useReducedMotion()

  useEffect(() => {
    if (!jobId) { setLoading(false); return }
    fetch(`${API_BASE}/api/jobs/${jobId}/result`)
      .then(r => r.json())
      .then(data => { setResult(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [jobId])

  const TABS: { id: ResultsTab; label: string }[] = [
    { id: 'onboarding', label: 'ONBOARDING DOC' },
    { id: 'agent_context', label: 'AGENT CONTEXT' },
    { id: 'explanations', label: 'FILE EXPLANATIONS' },
    { id: 'dependency', label: 'DEPENDENCY GRAPH' },
    { id: 'complexity', label: 'COMPLEXITY REPORT' },
    { id: 'raw', label: 'RAW OUTPUT' },
  ]

  const displayRepo = (repoUrl.replace(/^https?:\/\/github\.com\//, '') || 'owner/repo').toUpperCase()
  const s = result?.summary
  const riskDist = s?.risk_distribution || {}
  const depRows = result?.dependency_rows || []
  const readingOrder = result?.reading_order || []

  const RISK_WEIGHTS: Record<RiskLevel, number> = {
    CRITICAL: 4,
    HIGH: 3,
    MEDIUM: 2,
    LOW: 1,
  }

  const complexityRows = [...(result?.complexity_rows || [])]
    .filter(r => !fileFilter || r.file.toLowerCase().includes(fileFilter.toLowerCase()))
    .sort((a, b) => {
      if (sortBy === 'risk') {
        return (RISK_WEIGHTS[b.risk] || 0) - (RISK_WEIGHTS[a.risk] || 0)
      } else if (sortBy === 'avg_cc') {
        return b.avg_cc - a.avg_cc
      } else if (sortBy === 'max_cc') {
        return b.max_cc - a.max_cc
      }
      return 0
    })

  const handleDownload = (content: string, filename: string, mime = 'text/plain') => {
    const blob = new Blob([content], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename; a.click()
    URL.revokeObjectURL(url)
  }

  const explainedValue = (() => {
    if (!result) return '—'
    if (result.skip_llm === true) {
      return 'Skipped'
    }
    if (result.explanations) {
      return Object.keys(result.explanations).length
    }
    if (s?.explained !== undefined && s?.explained !== null) {
      return s.explained
    }
    return 0
  })()

  const importEdgesValue = (() => {
    if (!result) return '—'
    if (s?.import_edges !== undefined && s?.import_edges !== null) {
      return s.import_edges
    }
    if (result.dependency_rows) {
      return result.dependency_rows.reduce((acc, r) => acc + (r.imports || 0), 0)
    }
    return 0
  })()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', background: '#1400FF', paddingBottom: 64 }}>
      <NavBar onLogoClick={onHome} />

      {/* Results header */}
      <div style={{ padding: '32px 96px', borderBottom: '1px solid rgba(255,255,255,0.15)', flexShrink: 0, boxSizing: 'border-box', minHeight: 120, background: '#1400FF', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* Row 1: Repo + Branch */}
        <div style={{ display: 'flex', alignItems: 'baseline' }}>
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 500, letterSpacing: '0.10em', color: '#FFFFFF' }}>{displayRepo}</span>
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.50)', marginLeft: 16 }}>ON MAIN</span>
        </div>
        {/* Row 2: Stats */}
        <div style={{ display: 'flex', gap: 32, alignItems: 'center' }}>
          {[
            { n: s?.total_files ?? '—', l: 'FILES' },
            { n: s?.total_functions ?? '—', l: 'FUNCTIONS' },
            { n: s?.total_classes ?? '—', l: 'CLASSES' },
            { n: importEdgesValue, l: 'IMPORT EDGES' },
            { n: explainedValue, l: 'EXPLAINED' },
          ].map(stat => (
            <div key={stat.l} style={{ display: 'flex', flexDirection: 'column' }}>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, fontWeight: 500, color: '#FFFFFF' }}>{String(stat.n)}</div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.50)', marginTop: 2 }}>{stat.l}</div>
            </div>
          ))}
        </div>
        {/* Row 3: Risk Pills */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as RiskLevel[]).map(level => {
            const count = riskDist[level] ?? 0
            return <RiskBadge key={level} level={level} count={count} />
          })}
        </div>
        {/* Row 4: Circular Dep Warning */}
        {(s?.circular_cycles ?? 0) > 0 && (
          <div>
            <span style={{ display: 'inline-block', fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', color: '#FFFFFF', background: 'rgba(255,255,255,0.10)', border: '1px solid rgba(255,255,255,0.30)', padding: '6px 12px', marginTop: 12 }}>
              ⚠ {s!.circular_cycles} CIRCULAR DEPENDENCY {s!.circular_cycles === 1 ? 'CYCLE' : 'CYCLES'} DETECTED
            </span>
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div style={{ height: 52, background: '#0F00CC', borderBottom: '1px solid rgba(255,255,255,0.15)', padding: '0 96px', display: 'flex', alignItems: 'stretch', flexShrink: 0, position: 'relative' }}>
        {TABS.map((tab, idx) => {
          const isActive = tab.id === activeTab
          const nextActive = idx < TABS.length - 1 && TABS[idx + 1].id === activeTab
          const showSep = idx < TABS.length - 1 && !isActive && !nextActive
          return (
            <div key={tab.id} style={{ display: 'flex', alignItems: 'stretch' }}>
              <motion.button
                onClick={() => setActiveTab(tab.id)}
                whileTap={{ scale: 0.97 }}
                transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
                style={{
                  padding: '0 32px',
                  height: '100%',
                  background: 'transparent',
                  border: 'none',
                  color: isActive ? '#FFFFFF' : 'rgba(255,255,255,0.45)',
                  fontFamily: "'IBM Plex Mono', monospace",
                  fontSize: 11,
                  fontWeight: 500,
                  letterSpacing: '0.14em',
                  cursor: 'pointer',
                  textTransform: 'uppercase',
                  position: 'relative',
                }}
                onMouseEnter={e => { if (!isActive) (e.target as HTMLElement).style.color = '#FFFFFF' }}
                onMouseLeave={e => { !isActive && ((e.target as HTMLElement).style.color = 'rgba(255,255,255,0.45)') }}
              >
                {tab.label}
                {isActive && (
                  <motion.div
                    layoutId="tab-indicator"
                    style={{
                      position: 'absolute',
                      bottom: 0,
                      left: 0,
                      right: 0,
                      height: 2,
                      background: '#FFFFFF',
                    }}
                    transition={
                      reducedMotion
                        ? { duration: 0.1 }
                        : { type: 'spring', bounce: 0, duration: 0.35 }
                    }
                  />
                )}
              </motion.button>
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
                ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.onboarding_doc}</ReactMarkdown>
                : <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'rgba(10,10,26,0.40)', letterSpacing: '0.10em' }}>NO DOCUMENT GENERATED YET</p>
              }
            </div>
          </div>
        )}

        {!loading && activeTab === 'agent_context' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(10,10,26,0.50)' }}>AGENT CONTEXT DOCUMENT</span>
              <DownloadBtn label="↓ DOWNLOAD .MD" onLight onClick={() => handleDownload(result?.agent_context || '', 'agent_context.md')} />
            </div>
            <div className="gnosis-markdown" style={{ maxWidth: 760, margin: '0 auto' }}>
              {result?.agent_context
                ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.agent_context}</ReactMarkdown>
                : <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'rgba(10,10,26,0.40)', letterSpacing: '0.10em' }}>NO AGENT CONTEXT GENERATED</p>
              }
            </div>
          </div>
        )}

        {/* ── Tab: File Explanations ── */}
        {!loading && activeTab === 'explanations' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(10,10,26,0.50)' }}>FILE EXPLANATIONS</span>
              <DownloadBtn label="↓ DOWNLOAD .MD" onLight onClick={() => handleDownload(result?.file_explanations_md || '', 'file_explanations.md')} />
            </div>
            <div className="gnosis-markdown" style={{ maxWidth: 760, margin: '0 auto' }}>
              {result?.file_explanations_md
                ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.file_explanations_md}</ReactMarkdown>
                : (
                  <div style={{ padding: '24px 0' }}>
                    <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, color: '#1400FF', letterSpacing: '0.08em', marginBottom: 6 }}>
                      SKIPPED AI EXPLANATIONS
                    </p>
                    <p style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: 13, color: 'rgba(10,10,26,0.60)' }}>
                      Want file walkthroughs? Just turn on AI explanations and run the analysis again.
                    </p>
                  </div>
                )
              }
            </div>
          </div>
        )}

        {/* ── Tab 2: Dependency Graph ── */}
        {!loading && activeTab === 'dependency' && (
          <div>
            {/* Risk Distribution Summary Bar */}
            <RiskDistributionBar riskDist={riskDist} />

            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.16em', color: 'rgba(10,10,26,0.45)', marginBottom: 16 }}>MOST IMPORTED FILES</div>
            {depRows.length === 0
              ? <EmptyState label="NO DEPENDENCY DATA AVAILABLE" />
              : (() => {
                  const maxImportedBy = Math.max(...depRows.map(r => r.imported_by || 1), 1)
                  const maxImports = Math.max(...depRows.map(r => r.imports || 1), 1)
                  return (
                    <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid rgba(20,0,255,0.15)', marginBottom: 48 }}>
                      <thead>
                        <tr style={{ background: 'rgba(20,0,255,0.06)', height: 40 }}>
                          <th style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(10,10,26,0.40)', padding: '0 20px', textAlign: 'left', border: '1px solid rgba(20,0,255,0.12)' }}>FILE</th>
                          <th style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(10,10,26,0.40)', padding: '0 20px', textAlign: 'center', border: '1px solid rgba(20,0,255,0.12)' }}>IMPORTED BY</th>
                          <th style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(10,10,26,0.40)', padding: '0 20px', textAlign: 'center', border: '1px solid rgba(20,0,255,0.12)' }}>IMPORTS</th>
                          <th style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(10,10,26,0.40)', padding: '0 20px', textAlign: 'center', border: '1px solid rgba(20,0,255,0.12)' }}>RISK</th>
                        </tr>
                      </thead>
                      <tbody>
                        {depRows.map(row => (
                          <HoverRow key={row.path}>
                            <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: '#1400FF', padding: '0 20px', height: 48 }} title={row.path}>
                              {row.file}
                            </td>
                            <td style={{ padding: '0 20px' }}>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 500, color: '#1400FF' }}>{row.imported_by}</span>
                                <div style={{ width: 60, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                  <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${(row.imported_by / maxImportedBy) * 100}%`, background: '#1400FF' }} />
                                </div>
                              </div>
                            </td>
                            <td style={{ padding: '0 20px' }}>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 400, color: 'rgba(10,10,26,0.65)' }}>{row.imports}</span>
                                <div style={{ width: 60, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                  <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${(row.imports / maxImports) * 100}%`, background: 'rgba(20,0,255,0.40)' }} />
                                </div>
                              </div>
                            </td>
                            <td style={{ textAlign: 'center', padding: '0 20px' }}><RiskBadge level={row.risk} onLight /></td>
                          </HoverRow>
                        ))}
                      </tbody>
                    </table>
                  )
                })()
            }

            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.16em', color: 'rgba(10,10,26,0.45)', marginBottom: 8 }}>SUGGESTED READING ORDER</div>
            <div style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: 13, color: 'rgba(10,10,26,0.50)', marginBottom: 16 }}>Files ordered so each appears after everything it depends on.</div>
            {readingOrder.length === 0
              ? <EmptyState label="NO GRAPH DATA AVAILABLE" />
              : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 0, borderLeft: '1px solid rgba(20,0,255,0.15)', marginLeft: 10, paddingLeft: 24, marginBottom: 24 }}>
                  {readingOrder.map((path, idx) => (
                    <div key={path} style={{ display: 'flex', alignItems: 'center', height: 44, position: 'relative', borderBottom: idx === readingOrder.length - 1 ? 'none' : '1px solid rgba(20,0,255,0.08)' }}>
                      {/* Connector Node */}
                      <div style={{
                        position: 'absolute',
                        left: -29,
                        width: 9,
                        height: 9,
                        background: '#1400FF',
                        border: '1px solid #F0F0FF',
                      }} />
                      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'rgba(10,10,26,0.40)', fontWeight: 400, width: 28, marginRight: 8 }}>{String(idx + 1).padStart(2, '0')}</span>
                      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: '#1400FF' }}>{path}</span>
                    </div>
                  ))}
                </div>
              )
            }
          </div>
        )}

        {/* ── Tab 3: Complexity Report ── */}
        {!loading && activeTab === 'complexity' && (
          <div>
            {/* Risk Distribution Summary Bar */}
            <RiskDistributionBar riskDist={riskDist} />

            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as 'risk' | 'avg_cc' | 'max_cc')}
                style={{ height: 40, border: '1px solid rgba(20,0,255,0.20)', background: '#FFFFFF', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 500, letterSpacing: '0.10em', color: '#1400FF', textTransform: 'uppercase', padding: '0 12px', outline: 'none', cursor: 'pointer' }}
              >
                <option value="risk">SORT BY RISK</option>
                <option value="avg_cc">SORT BY AVG CC</option>
                <option value="max_cc">SORT BY MAX CC</option>
              </select>
              <input type="text" value={fileFilter} onChange={e => setFileFilter(e.target.value)} placeholder="FILTER BY FILENAME..." style={{ height: 40, width: 240, border: '1px solid rgba(20,0,255,0.20)', background: '#FFFFFF', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: '#1400FF', padding: '0 12px', outline: 'none' }} />
              <span style={{ marginLeft: 'auto', fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, letterSpacing: '0.10em', color: 'rgba(10,10,26,0.40)' }}>
                SHOWING {complexityRows.length} OF {result?.complexity_rows?.length ?? 0} FILES
              </span>
            </div>
            {complexityRows.length === 0
              ? <EmptyState label="NO COMPLEXITY DATA AVAILABLE" />
              : (() => {
                  const maxAvgCC = Math.max(...complexityRows.map(r => r.avg_cc || 1), 1)
                  const maxMaxCC = Math.max(...complexityRows.map(r => r.max_cc || 1), 1)
                  const maxCoupling = Math.max(...complexityRows.map(r => r.coupling || 1), 1)
                  return (
                    <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid rgba(20,0,255,0.15)', marginBottom: 24 }}>
                      <thead>
                        <tr style={{ background: 'rgba(20,0,255,0.06)', height: 44 }}>
                          {['FILE', 'RISK', 'AVG CC', 'MAX CC', 'WORST FUNCTION', 'COUPLING', 'FLAGS'].map(h => (
                            <th key={h} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(10,10,26,0.45)', padding: '0 16px', textAlign: (h === 'FILE' || h === 'WORST FUNCTION' || h === 'FLAGS') ? 'left' : 'center', borderBottom: '1px solid rgba(20,0,255,0.12)' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {complexityRows.map(row => (
                          <HoverRow key={row.path} height={52}>
                            <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: '#1400FF', padding: '0 16px' }} title={row.path}>{row.file}</td>
                            <td style={{ padding: '0 16px', textAlign: 'center' }}><RiskBadge level={row.risk} onLight /></td>
                            <td style={{ padding: '0 16px' }}>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 500, color: '#0A0A1A' }}>
                                  {typeof row.avg_cc === 'number' ? row.avg_cc.toFixed(1) : row.avg_cc}
                                </span>
                                <div style={{ width: 50, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                  <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${(row.avg_cc / maxAvgCC) * 100}%`, background: '#1400FF' }} />
                                </div>
                              </div>
                            </td>
                            <td style={{ padding: '0 16px' }}>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 500, color: row.max_cc >= 21 ? '#1400FF' : '#0A0A1A' }}>
                                  {row.max_cc}
                                </span>
                                <div style={{ width: 50, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                  <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${(row.max_cc / maxMaxCC) * 100}%`, background: row.max_cc >= 21 ? '#1400FF' : 'rgba(20,0,255,0.50)' }} />
                                </div>
                              </div>
                            </td>
                            <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 400, color: '#1400FF', padding: '0 16px', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={row.worst_fn}>{row.worst_fn}</td>
                            <td style={{ padding: '0 16px' }}>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: 'rgba(10,10,26,0.65)' }}>{row.coupling}</span>
                                <div style={{ width: 50, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                  <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${(row.coupling / maxCoupling) * 100}%`, background: 'rgba(20,0,255,0.40)' }} />
                                </div>
                              </div>
                            </td>
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
                })()
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
          {result?.agent_context && (
            <DownloadBtn label="↓ AGENT_CONTEXT.MD" onClick={() => handleDownload(result.agent_context || '', 'agent_context.md')} />
          )}
          {result?.file_explanations_md && (
            <DownloadBtn label="↓ FILE_EXPLANATIONS.MD" onClick={() => handleDownload(result?.file_explanations_md || '', 'file_explanations.md')} />
          )}
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

// ─── Screen 4: Error ──────────────────────────────────────────────────────────
function ErrorPage({ onHome }: { onHome: () => void }) {
  const [hoverBtn, setHoverBtn] = useState(false)
  const reducedMotion = useReducedMotion()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: '#1400FF' }}>
      <NavBar onLogoClick={onHome} />
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
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 58, fontWeight: 400, color: '#FFFFFF', lineHeight: 0.95, letterSpacing: '-0.01em', textTransform: 'uppercase' }}>
              SOMETHING
            </div>
            <div style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 58, fontWeight: 400, color: '#FFFFFF', lineHeight: 0.95, letterSpacing: '-0.01em', textTransform: 'uppercase' }}>
              WENT WRONG
            </div>
          </div>

          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 120, fontWeight: 400, color: 'rgba(255,255,255,0.15)', lineHeight: 1.0, letterSpacing: '-0.02em', marginBottom: 16 }}>
            404
          </div>

          <p style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: 16, fontWeight: 400, color: 'rgba(255,255,255,0.65)', maxWidth: 420, lineHeight: 1.6, margin: '0 0 40px 0' }}>
            The page you're looking for doesn't exist or the server encountered an unexpected error. Please try again later.
          </p>

          <motion.button
            onClick={onHome}
            onMouseEnter={() => setHoverBtn(true)}
            onMouseLeave={() => setHoverBtn(false)}
            whileTap={{ scale: 0.97 }}
            transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
            style={{
              width: 280,
              height: 56,
              background: hoverBtn ? 'transparent' : '#FFFFFF',
              border: hoverBtn ? '1px solid #FFFFFF' : 'none',
              color: hoverBtn ? '#FFFFFF' : '#1400FF',
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 13,
              fontWeight: 500,
              letterSpacing: '0.14em',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            RETURN HOME →
          </motion.button>
        </div>

        <div style={{ flex: 1, position: 'relative', overflow: 'hidden', minWidth: 0 }}>
          <AthenaFigure brightness={0.55} />
        </div>
      </div>

      <div style={{ position: 'fixed', bottom: 32, right: 96, fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.35)' }}>
        v{APP_VERSION} · PiUnknown · Project Gnosis
      </div>
    </div>
  )
}

// ─── Root App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [screen, setScreen] = useState<Screen>('landing')
  const [repoUrl, setRepoUrl] = useState('')
  const [jobId, setJobId] = useState('')
  const reducedMotion = useReducedMotion()

  const handleSubmit = (url: string, id: string) => {
    setRepoUrl(url)
    setJobId(id)
    setScreen('progress')
  }

  const goHome = useCallback(() => setScreen('landing'), [])

  // Determine enter direction: landing = from left, others = from right
  const isLanding = screen === 'landing'
  const xInitial = reducedMotion ? 0 : (isLanding ? -40 : 40)
  const xAnimate = 0
  const xExit = reducedMotion ? 0 : (isLanding ? 40 : -40)

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={screen}
        initial={{ opacity: 0, x: xInitial }}
        animate={{ opacity: 1, x: xAnimate }}
        exit={{ opacity: 0, x: xExit }}
        transition={
          reducedMotion
            ? { duration: 0.15 }
            : { type: 'spring', bounce: 0, duration: 0.4 }
        }
        style={{ height: '100vh' }}
      >
        {screen === 'landing' && <LandingPage onSubmit={handleSubmit} />}
        {screen === 'progress' && (
          <ProgressPage
            repoUrl={repoUrl}
            jobId={jobId}
            onComplete={() => setScreen('results')}
            onHome={goHome}
          />
        )}
        {screen === 'results' && (
          <ResultsPage repoUrl={repoUrl} jobId={jobId} onHome={goHome} />
        )}
        {screen === 'error' && <ErrorPage onHome={goHome} />}
      </motion.div>
    </AnimatePresence>
  )
}
