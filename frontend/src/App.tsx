import { useState, useEffect, useRef, useCallback, lazy, Suspense } from 'react'
import { motion, AnimatePresence, useMotionValue, useSpring, useTransform, useReducedMotion } from 'motion/react'
import { AthenaFigure, NavBar } from './components/AppChrome'
import { track } from './lib/analytics'
const API_BASE = import.meta.env.VITE_API_URL || "";
const APP_VERSION = "1.2.0";
const AnalysisResultsPage = lazy(() => import('./pages/AnalysisResultsPage'))

type Screen = 'landing' | 'progress' | 'results' | 'error'
type AgentStatus = 'queued' | 'running' | 'complete' | 'failed'
interface AgentState {
  id: string
  name: string
  status: AgentStatus
}

interface JobState {
  status: 'queued' | 'running' | 'complete' | 'failed'
  agents: AgentState[]
  error: string | null
  explanations_completed?: number
  explanations_total?: number
}

const AGENT_NAMES = [
  'Ingestion',
  'AST Parser',
  'Dependency Graph',
  'Complexity Scorer',
  'Code RAG',
  'Explainability',
  'Doc Generator',
]

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
// Official Project Gnosis Symbol: Isolated geometric 'G' + AST network + Eye of Gnosis
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
      track('repo_analysis_validation_failed', {
        input_url: url,
      })
      return
    }
    setError('')
    setLoading(true)
    track('repo_analysis_submitted', {
      repo_url: url,
      max_explanations: maxExplanations,
      skip_llm: skipLlm,
    })
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
          track('repo_analysis_attached_existing_job', {
            repo_url: url,
            job_id: data.job_id,
          })
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
      track('repo_analysis_submission_error', {
        repo_url: url,
        error: rawMsg,
      })
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
            <h1 style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: 58, fontWeight: 400, color: '#FFFFFF', lineHeight: 0.95, letterSpacing: '-0.01em', textTransform: 'uppercase', margin: 0 }}>
              UNDERSTAND<br />ANY CODEBASE
            </h1>
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
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [explanationProgress, setExplanationProgress] = useState({ completed: 0, total: 0 })

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

    // Recursive polling prevents overlapping requests and slows down while
    // long-running analysis phases are in progress. Each poll costs a Redis
    // read, so the floor is 5s and a hidden tab stops polling entirely.
    const POLL_MIN_MS = 5000
    const POLL_MAX_MS = 10000
    let cancelled = false
    let delayMs = POLL_MIN_MS
    const clearPoll = () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
    const schedulePoll = () => {
      if (cancelled) return
      clearPoll()
      pollTimerRef.current = setTimeout(() => {
        pollTimerRef.current = null
        if (document.visibilityState === 'hidden') {
          // Idle without hitting the API while the tab is in the background.
          schedulePoll()
          return
        }
        void poll()
      }, delayMs)
    }
    const poll = async () => {
      if (cancelled) return
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${jobId}`)
        if (cancelled) return
        if (res.status === 404 || res.status === 410) {
          setJobStatus('failed')
          setErrorMsg('This analysis job is no longer available. Return home and submit it again.')
          clearPoll()
          return
        }
        if (!res.ok) {
          delayMs = Math.min(10000, delayMs * 2)
          schedulePoll()
          return
        }
        const data: JobState = await res.json()
        if (cancelled) return
        if (!Array.isArray(data.agents)) {
          setJobStatus('failed')
          setErrorMsg(data.error || 'The server returned an invalid job status.')
          clearPoll()
          return
        }
        setAgentNames(data.agents.map(a => a.name))
        setAgentStatuses(data.agents.map(a => a.status))
        setExplanationProgress({
          completed: data.explanations_completed || 0,
          total: data.explanations_total || 0,
        })
        if (data.status === 'complete') {
          setJobStatus('complete')
          clearPoll()
          return
        }
        if (data.status === 'failed') {
          setJobStatus('failed')
          setErrorMsg(data.error || 'Unknown error')
          track('repo_analysis_failed', {
            repo_url: repoUrl,
            job_id: jobId,
            error: data.error || 'Unknown error',
          })
          clearPoll()
          return
        }
        delayMs = Math.min(POLL_MAX_MS, Math.round(delayMs * 1.5))
        schedulePoll()
      } catch {
        delayMs = Math.min(POLL_MAX_MS, delayMs * 2)
        schedulePoll()
      }
    }

    // Returning to the tab resumes immediately instead of waiting out the
    // remaining backoff.
    const handleVisibility = () => {
      if (!cancelled && document.visibilityState === 'visible') {
        delayMs = POLL_MIN_MS
        clearPoll()
        void poll()
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)

    void poll()
    return () => {
      cancelled = true
      clearPoll()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
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
                    <div style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: 12, color: 'rgba(255,255,255,0.45)', marginTop: 3 }}>
                      {idx === 5 && isRunning && explanationProgress.total > 0
                        ? `${explanationProgress.completed} OF ${explanationProgress.total} FILES PROCESSED`
                        : AGENT_DESCS[idx]}
                    </div>
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
          <Suspense fallback={<div style={{ minHeight: '100vh', background: '#1400FF' }} />}><AnalysisResultsPage repoUrl={repoUrl} jobId={jobId} onHome={goHome} /></Suspense>
        )}
        {screen === 'error' && <ErrorPage onHome={goHome} />}
      </motion.div>
    </AnimatePresence>
  )
}
