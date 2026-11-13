import { useCallback, useEffect, useRef, useState, lazy, Suspense, type FormEvent } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { LandingNav, NavBar } from './components/AppChrome'
import { AthenaCanvas } from './components/AthenaCanvas'
import { track } from './lib/analytics'
import { createElapsedClock, formatDuration } from './lib/elapsed'

const API_BASE = import.meta.env.VITE_API_URL || ''
const AnalysisResultsPage = lazy(() => import('./pages/AnalysisResultsPage'))

type Screen = 'landing' | 'progress' | 'results' | 'error'
type JobStatus = 'queued' | 'running' | 'complete' | 'failed'
type AgentStatus = 'queued' | 'running' | 'complete' | 'failed'

interface AgentState {
  id: string
  name: string
  status: AgentStatus
}

interface JobState {
  status: JobStatus
  agents: AgentState[]
  error: string | null
  progress_pct?: number
  current_phase?: string | null
  phases_completed?: string[]
  explanations_completed?: number
  explanations_total?: number
  created_at?: string
  completed_at?: string | null
}

interface LogLine {
  id: number
  text: string
  ok?: boolean
}

const GITHUB_RE = /^https?:\/\/github\.com\/[^/]+\/[^/]+/

function displayRepo(repoUrl: string) {
  return repoUrl.replace(/^https?:\/\/(www\.)?github\.com\//, '').replace(/\.git$/, '').replace(/\/$/, '') || 'owner/repo'
}

// ─── Landing ─────────────────────────────────────────────────────────────────
function LandingPage({ onSubmit }: { onSubmit: (url: string, jobId: string) => void }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (event?: FormEvent) => {
    event?.preventDefault()
    if (submitting) return

    const value = url.trim()
    if (!GITHUB_RE.test(value)) {
      setError('INVALID GITHUB URL — MUST MATCH github.com/owner/repo')
      track('repo_analysis_validation_failed', { input_url: value })
      return
    }

    setError('')
    setSubmitting(true)
    track('repo_analysis_submitted', { repo_url: value, file_explanations: 'on-demand' })

    try {
      const response = await fetch(`${API_BASE}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_url: value,
          options: { defer_code_index: true },
        }),
      })

      if (!response.ok) {
        let data: any = null
        try {
          data = await response.json()
        } catch {
          // A non-JSON error page is handled below.
        }

        if (response.status === 409 && data && data.job_id) {
          track('repo_analysis_attached_existing_job', { repo_url: value, job_id: data.job_id })
          onSubmit(value, data.job_id)
          return
        }

        let message = `Server error: ${response.status}`
        if (data && data.detail) message = data.detail
        else if (data && data.message) message = data.message
        throw new Error(message)
      }

      const { job_id } = await response.json()
      onSubmit(value, job_id)
    } catch (err) {
      const rawMessage = err instanceof Error ? err.message : 'unknown error'
      track('repo_analysis_submission_error', { repo_url: value, error: rawMessage })
      if (
        rawMessage.includes('Failed to fetch') ||
        rawMessage.includes('NetworkError') ||
        rawMessage.includes('Network request failed')
      ) {
        setError(`CONNECTION FAILED — IS THE SERVER RUNNING? (${rawMessage})`)
      } else {
        setError(rawMessage.toUpperCase())
      }
      setSubmitting(false)
    }
  }

  return (
    <section className="screen landing" aria-labelledby="landing-title">
      <AthenaCanvas className="athena" alpha={1} />
      <div className="athena-fade" aria-hidden="true" />

      <LandingNav />

      <div className="hero">
        <div className="hcopy">
          <div className="eyebrow reveal" style={{ ['--d' as string]: '0.05s' }}>
            Code archaeology agent
          </div>
          <h1 id="landing-title" className="reveal" style={{ ['--d' as string]: '0.15s' }}>
            Understand
            <br />
            any codebase.
          </h1>
          <p className="sub reveal" style={{ ['--d' as string]: '0.3s' }}>
            Enter a public GitHub URL. Gnosis maps every import, scores every function, and writes the
            onboarding document your team never did.
          </p>

          <form
            className="repo-form reveal"
            style={{ ['--d' as string]: '0.45s' }}
            onSubmit={handleSubmit}
            noValidate
          >
            <label htmlFor="repo-url">REPOSITORY URL</label>
            <div className="formrow">
              <input
                id="repo-url"
                name="repo-url"
                type="url"
                inputMode="url"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                value={url}
                disabled={submitting}
                placeholder="https://github.com/owner/repo"
                aria-invalid={Boolean(error)}
                aria-describedby={error ? 'repo-url-error' : undefined}
                onChange={(event) => {
                  setUrl(event.target.value)
                  if (error) setError('')
                }}
              />
              <button type="submit" className="analyze-btn" disabled={submitting}>
                {submitting ? (
                  'SUBMITTING ···'
                ) : (
                  <>
                    ANALYZE REPOSITORY <span className="ar" aria-hidden="true">→</span>
                  </>
                )}
              </button>
            </div>
            {error ? (
              <p className="form-error" id="repo-url-error" role="alert">
                {error}
              </p>
            ) : null}
            <p className="form-note">FILE EXPLANATIONS ARE AVAILABLE ON DEMAND AFTER ANALYSIS.</p>
          </form>
        </div>
      </div>

      <footer className="landing-foot">
        <span>FREE &nbsp;·&nbsp; NO SIGNUP &nbsp;·&nbsp; PUBLIC REPOS ONLY</span>
        <span className="r">GNOSIS · PIUNKNOWN · v1.2.0</span>
      </footer>
    </section>
  )
}

// ─── Progress ────────────────────────────────────────────────────────────────
interface ProgressPageProps {
  repoUrl: string
  jobId: string
  onComplete: () => void
  onHome: () => void
}

function ProgressPage({ repoUrl, jobId, onComplete, onHome }: ProgressPageProps) {
  const [agents, setAgents] = useState<AgentState[]>([])
  const [status, setStatus] = useState<JobStatus>('queued')
  const [progressPct, setProgressPct] = useState<number | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [explanationProgress, setExplanationProgress] = useState({ completed: 0, total: 0 })
  const [log, setLog] = useState<LogLine[]>([])
  const [elapsedMs, setElapsedMs] = useState(0)

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const previousAgentsRef = useRef(new Map<string, AgentStatus>())
  const previousExplanationRef = useRef({ completed: 0, total: 0 })
  const logIdRef = useRef(0)

  const pushLog = useCallback((text: string, ok = false) => {
    logIdRef.current += 1
    const line = { id: logIdRef.current, text, ok }
    setLog((current) => [...current, line].slice(-5))
  }, [])

  useEffect(() => {
    setLog([])
    setAgents([])
    setProgressPct(null)
    setStatus('queued')
    setErrorMessage('')
    setElapsedMs(0)
    previousAgentsRef.current = new Map()
    previousExplanationRef.current = { completed: 0, total: 0 }
    if (jobId) pushLog(`job ${jobId.slice(0, 8)} — attached`)
  }, [jobId, pushLog])

  useEffect(() => {
    if (!jobId) {
      setStatus('queued')
      return
    }

    // Owned by this effect: a late response from a previous job can never
    // touch the timer of the job currently on screen.
    const clock = createElapsedClock(setElapsedMs)
    clock.reset(Date.now())

    let cancelled = false
    let finished = false
    let delayMs = 5000
    const clearPoll = () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
    const schedulePoll = () => {
      if (cancelled || finished) return
      clearPoll()
      pollTimerRef.current = setTimeout(() => {
        pollTimerRef.current = null
        if (document.visibilityState === 'hidden') {
          schedulePoll()
          return
        }
        void poll()
      }, delayMs)
    }

    const applyAgents = (next: AgentState[]) => {
      const previous = previousAgentsRef.current
      for (const agent of next) {
        const before = previous.get(agent.id)
        if (before === agent.status) continue
        if (agent.status === 'running') pushLog(`agent ${agent.id} ${agent.name} — running`)
        else if (agent.status === 'complete') pushLog(`agent ${agent.id} ${agent.name} — complete`, true)
        else if (agent.status === 'failed') pushLog(`agent ${agent.id} ${agent.name} — failed`)
        previous.set(agent.id, agent.status)
      }
      setAgents(next)
    }

    const applyExplanations = (completed: number, total: number) => {
      setExplanationProgress({ completed, total })
      const before = previousExplanationRef.current
      if (total > 0 && (before.completed !== completed || before.total !== total)) {
        pushLog(`explanations ${completed}/${total} files`, completed === total)
      }
      previousExplanationRef.current = { completed, total }
    }

    const poll = async () => {
      if (cancelled) return
      try {
        const response = await fetch(`${API_BASE}/api/jobs/${jobId}`)
        if (cancelled) return
        if (response.status === 404 || response.status === 410) {
          finished = true
          setStatus('failed')
          setErrorMessage('This analysis job is no longer available. Return home and submit it again.')
          clock.freeze('failed')
          clearPoll()
          return
        }
        if (!response.ok) {
          delayMs = Math.min(10000, delayMs * 2)
          schedulePoll()
          return
        }

        const data: JobState = await response.json()
        if (cancelled) return
        if (!Array.isArray(data.agents)) {
          finished = true
          setStatus('failed')
          setErrorMessage(data.error || 'The server returned an invalid job status.')
          clock.freeze('failed')
          clearPoll()
          return
        }

        applyAgents(data.agents)
        applyExplanations(data.explanations_completed || 0, data.explanations_total || 0)

        clock.applyServerTimestamps(data.created_at, data.completed_at)
        setProgressPct(typeof data.progress_pct === 'number' ? Math.max(0, Math.min(100, data.progress_pct)) : null)

        if (data.status === 'complete') {
          finished = true
          setStatus('complete')
          setProgressPct(100)
          clock.freeze('complete')
          pushLog('analysis complete — rendering results', true)
          clearPoll()
          return
        }
        if (data.status === 'failed') {
          finished = true
          setStatus('failed')
          setErrorMessage(data.error || 'Unknown error')
          clock.freeze('failed')
          pushLog('analysis failed')
          track('repo_analysis_failed', {
            repo_url: repoUrl,
            job_id: jobId,
            error: data.error || 'Unknown error',
          })
          clearPoll()
          return
        }

        setStatus(data.status === 'queued' ? 'queued' : 'running')
        delayMs = Math.min(10000, Math.round(delayMs * 1.5))
        schedulePoll()
      } catch {
        if (cancelled) return
        delayMs = Math.min(10000, delayMs * 2)
        schedulePoll()
      }
    }

    const handleVisibility = () => {
      if (!cancelled && document.visibilityState === 'visible' && !finished) {
        delayMs = 5000
        clearPoll()
        void poll()
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)

    void poll()
    return () => {
      cancelled = true
      clearPoll()
      clock.dispose()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [jobId, pushLog, repoUrl])

  const elapsedLabel = formatDuration(elapsedMs)
  const repoLabel = displayRepo(repoUrl).toUpperCase()
  const isIndeterminate = progressPct === null && status !== 'complete'
  const pctLabel = progressPct === null ? '--' : String(Math.round(progressPct))
  const runningIndex = agents.findIndex((agent) => agent.status === 'running')
  const completeCount = agents.filter((agent) => agent.status === 'complete').length
  const currentName = runningIndex >= 0 ? agents[runningIndex].name : null

  const statusWord =
    status === 'failed'
      ? 'FAILED'
      : status === 'complete'
        ? 'COMPLETE'
        : status === 'queued'
          ? 'QUEUED'
          : 'RUNNING'

  return (
    <section className="screen screen--fixed loading-screen" aria-labelledby="loading-title">
      <AthenaCanvas className="loading-athena" alpha={1} />
      <div className="loading-scrim" aria-hidden="true" />

      <NavBar>
        <span className="nav-run">ANALYSIS RUN — {repoLabel}</span>
      </NavBar>

      <div className="load">
        <div className="loadbox">
          <div className="loadtop">
            <span>AGENTS {agents.length > 0 ? `01–${String(agents.length).padStart(2, '0')}` : '01–07'}</span>
            <span className="right" aria-live="polite">
              {statusWord} · {elapsedLabel}
              {status === 'running' && currentName ? ` · ${currentName}` : ''}
            </span>
          </div>

          <h1 id="loading-title" className="pct">
            {pctLabel}
            <small>%</small>
          </h1>

          <div className={`bar${isIndeterminate ? ' indeterminate' : ''}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPct ?? undefined} aria-valuetext={progressPct === null ? 'Progress is not reported yet' : `${Math.round(progressPct)} percent`}>
            <i style={isIndeterminate ? undefined : { width: `${progressPct ?? 0}%` }} />
          </div>

          {agents.length > 0 ? (
            <div className="stages">
              {agents.map((agent, index) => {
                const stateClass =
                  agent.status === 'complete'
                    ? 'done'
                    : agent.status === 'running'
                      ? 'run'
                      : agent.status === 'failed'
                        ? 'failed'
                        : ''
                const mark = agent.status === 'complete' ? '✓' : agent.status === 'running' ? '▸' : agent.status === 'failed' ? '!' : '·'
                return (
                  <div className={`stage ${stateClass}`} key={agent.id}>
                    <b aria-hidden="true">{mark}</b>
                    <span>
                      {String(index + 1).padStart(2, '0')} {agent.name}
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="stages">
              <div className="stage">
                <b aria-hidden="true">·</b>
                <span>{jobId ? 'AWAITING PIPELINE STATE' : 'WAITING FOR JOB ID'}</span>
              </div>
            </div>
          )}

          <div className="log" aria-live="polite">
            {log.map((line) => (
              <div key={line.id} className={line.ok ? 'ok' : undefined}>
                {line.text}
              </div>
            ))}
          </div>

          {status === 'complete' ? (
            <div className="complete-actions">
              <button type="button" className="btn-primary" onClick={onComplete}>
                VIEW RESULTS <span aria-hidden="true">→</span>
              </button>
              <span className="status-note">
                {completeCount} OF {agents.length || 7} AGENTS COMPLETE · {explanationProgress.total > 0 ? `${explanationProgress.completed}/${explanationProgress.total} EXPLANATIONS` : 'EXPLANATIONS ON DEMAND'}
              </span>
            </div>
          ) : null}

          {status === 'failed' ? (
            <div>
              <p className="status-note error" role="alert">
                {errorMessage || 'THE ANALYSIS COULD NOT BE COMPLETED.'}
              </p>
              <div className="complete-actions">
                <button type="button" className="btn-ghost" onClick={onHome}>
                  ← NEW ANALYSIS
                </button>
              </div>
            </div>
          ) : null}

          {!jobId && status !== 'complete' && status !== 'failed' ? (
            <p className="status-note">NO JOB ID WAS RETURNED. RETURN HOME AND SUBMIT THE REPOSITORY AGAIN.</p>
          ) : null}
        </div>
      </div>
    </section>
  )
}

// ─── Error ───────────────────────────────────────────────────────────────────
function ErrorPage({ onHome }: { onHome: () => void }) {
  return (
    <section className="screen landing" aria-labelledby="error-title">
      <AthenaCanvas className="athena" alpha={0.7} />
      <div className="athena-fade" aria-hidden="true" />
      <NavBar onLogoClick={onHome} />

      <div className="hero">
        <div className="hcopy">
          <div className="eyebrow">Unexpected state</div>
          <h1 id="error-title" style={{ marginTop: 24 }}>
            Something
            <br />
            went wrong.
          </h1>
          <p className="sub">
            This screen is not part of the analysis flow. Return home and submit a public GitHub
            repository to start again.
          </p>
          <div style={{ marginTop: 32 }}>
            <button type="button" className="btn-primary" onClick={onHome}>
              RETURN HOME <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>
      </div>

      <footer className="landing-foot">
        <span>GNOSIS</span>
        <span className="r">CODE ARCHAEOLOGY AGENT</span>
      </footer>
    </section>
  )
}

// ─── Root ────────────────────────────────────────────────────────────────────
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

  const goHome = useCallback(() => {
    setScreen('landing')
    setJobId('')
    setRepoUrl('')
  }, [])

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={screen}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: reducedMotion ? 0 : 0.18 }}
        style={{ minHeight: '100dvh' }}
      >
        {screen === 'landing' ? <LandingPage onSubmit={handleSubmit} /> : null}
        {screen === 'progress' ? (
          <ProgressPage
            repoUrl={repoUrl}
            jobId={jobId}
            onComplete={() => setScreen('results')}
            onHome={goHome}
          />
        ) : null}
        {screen === 'results' ? (
          <Suspense fallback={<div style={{ minHeight: '100dvh', background: 'var(--bg)' }} />}>
            <AnalysisResultsPage repoUrl={repoUrl} jobId={jobId} onHome={goHome} />
          </Suspense>
        ) : null}
        {screen === 'error' ? <ErrorPage onHome={goHome} /> : null}
      </motion.div>
    </AnimatePresence>
  )
}
