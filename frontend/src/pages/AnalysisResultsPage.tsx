import React, { useEffect, useRef, useState, lazy, Suspense } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { track } from '../lib/analytics'
import { type DependencyLink, type DependencyNode } from '../components/DependencyGraph3D'
import { NavBar } from '../components/AppChrome'

const API_BASE = import.meta.env.VITE_API_URL || ''
const DependencyGraph3D = lazy(() => import('../components/DependencyGraph3D'))

type ResultsTab = 'onboarding' | 'agent_context' | 'explanations' | 'dependency' | 'complexity' | 'raw'

interface ResultSummary {
  repo_url?: string
  branch?: string
  total_files: number
  total_functions: number
  total_classes: number
  import_edges: number
  total_import_edges?: number
  files_discovered?: number
  files_analyzed?: number
  files_with_content?: number
  circular_cycles?: number
  circular_dep_count?: number
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
  branch?: string
  error?: string
  onboarding_doc?: string
  agent_context?: string
  file_explanations_md?: string
  dependency_rows?: DepRow[]
  graph_data?: {
    nodes: DependencyNode[]
    links: DependencyLink[]
    circular_deps: string[][]
    circular_deps_truncated?: boolean
  }
  reading_order?: string[]
  complexity_rows?: ComplexityRow[]
  explanations?: Record<string, string>
  /** complete | partial | failed | skipped — see the API's explanation_status */
  explanation_status?: 'complete' | 'partial' | 'failed' | 'skipped'
  explanations_requested?: number
  explanations_failed?: number
  explanation_error?: string | null
  complexity_report_json?: string
  circular_deps?: string[][]
  circular_deps_truncated?: boolean
  complexity_report?: Record<string, unknown>
  graph_summary?: Record<string, unknown>
  repo?: string
  job_id?: string
  analysis_mode?: string
  files_discovered?: number
  files_analyzed?: number
  edges?: unknown[]
  in_degree?: Record<string, number>
  out_degree?: Record<string, number>
  topological_order?: string[]
  skip_llm?: boolean
}

type RiskLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
type ResultField = keyof AnalysisResult

const INITIAL_RESULT_FIELDS: ResultField[] = ['summary', 'onboarding_doc', 'branch', 'skip_llm']
const TAB_RESULT_FIELDS: Record<ResultsTab, ResultField[]> = {
  onboarding: [],
  agent_context: ['agent_context'],
  explanations: ['file_explanations_md', 'explanations', 'explanation_status', 'explanations_failed', 'explanation_error'],
  dependency: ['dependency_rows', 'graph_data', 'circular_deps', 'reading_order'],
  complexity: ['complexity_rows', 'complexity_report_json', 'complexity_report'],
  raw: ['explanations', 'complexity_rows', 'complexity_report_json', 'dependency_rows', 'reading_order', 'circular_deps'],
}


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

function HoverRow({ children, height = 48 }: { children: React.ReactNode; height?: number }) {
  const [hovered, setHovered] = useState(false)
  return (
    <tr onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} style={{ height, borderBottom: '1px solid rgba(20,0,255,0.08)', background: hovered ? 'rgba(20,0,255,0.04)' : 'transparent', transition: 'background 0.1s' }}>
      {children}
    </tr>
  )
}

function DownloadBtn({ label, onLight = false, onClick, disabled = false }: { label: string; onLight?: boolean; onClick?: () => void; disabled?: boolean }) {
  const [hovered, setHovered] = useState(false)
  const base: React.CSSProperties = {
    height: onLight ? 32 : 36,
    padding: '0 16px',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.55 : 1,
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
        disabled={disabled}
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
      disabled={disabled}
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
  const [sectionsLoading, setSectionsLoading] = useState(false)
  const [downloading, setDownloading] = useState('')
  const [downloadError, setDownloadError] = useState('')
  const [fetchError, setFetchError] = useState('')
  const [sectionError, setSectionError] = useState('')
  const [fileFilter, setFileFilter] = useState('')
  const [sortBy, setSortBy] = useState<'risk' | 'avg_cc' | 'max_cc'>('risk')
  const reducedMotion = useReducedMotion()
  const resultRef = useRef<AnalysisResult | null>(null)
  const loadedSectionsRef = useRef(new Set<ResultField>())
  const sectionRequestsRef = useRef(new Map<ResultField, Promise<void>>())

  const fetchSections = async (requestedFields: ResultField[]) => {
    const missing = requestedFields.filter(field => !loadedSectionsRef.current.has(field))
    const pending = new Set<Promise<void>>()
    const fieldsToFetch = missing.filter(field => !sectionRequestsRef.current.has(field))

    for (const field of missing) {
      const existing = sectionRequestsRef.current.get(field)
      if (existing) pending.add(existing)
    }

    if (fieldsToFetch.length > 0) {
      const request = (async () => {
        const params = new URLSearchParams({ sections: fieldsToFetch.join(',') })
        const response = await fetch(`${API_BASE}/api/jobs/${jobId}/result?${params}`)
        if (!response.ok) throw new Error(`RESULT SECTION REQUEST FAILED (${response.status})`)
        const data = await response.json() as Partial<AnalysisResult>
        const merged = { ...(resultRef.current || {}), ...data } as AnalysisResult
        resultRef.current = merged
        setResult(merged)
        fieldsToFetch.forEach(field => loadedSectionsRef.current.add(field))
      })()
      fieldsToFetch.forEach(field => sectionRequestsRef.current.set(field, request))
      pending.add(request)
    }

    try {
      await Promise.all(pending)
    } finally {
      requestedFields.forEach(field => {
        const request = sectionRequestsRef.current.get(field)
        if (request && pending.has(request)) sectionRequestsRef.current.delete(field)
      })
    }
    return resultRef.current
  }

  useEffect(() => {
    if (!jobId) { setLoading(false); return }
    let isMounted = true
    let timer: ReturnType<typeof setTimeout> | null = null

    const fetchResult = async (attempt = 0) => {
      try {
        const params = new URLSearchParams({ sections: INITIAL_RESULT_FIELDS.join(',') })
        const res = await fetch(`${API_BASE}/api/jobs/${jobId}/result?${params}`)
        if (res.status === 202) {
          if (attempt < 8 && isMounted) {
            timer = setTimeout(() => fetchResult(attempt + 1), Math.min(6000, 750 * (2 ** attempt)))
            return
          }
        }
        if (!res.ok) {
          let errText = `FAILED TO LOAD RESULTS (${res.status})`
          try {
            const errJson = await res.json()
            if (errJson.detail) errText = String(errJson.detail).toUpperCase()
          } catch { }
          if (isMounted) {
            setFetchError(errText)
            setLoading(false)
            track('repo_results_fetch_failed', {
              repo_url: repoUrl,
              job_id: jobId,
              error: errText,
            })
          }
          return
        }
        const data = await res.json()
        if (data && data.error === 'not ready' && attempt < 8 && isMounted) {
          timer = setTimeout(() => fetchResult(attempt + 1), Math.min(6000, 750 * (2 ** attempt)))
          return
        }
        if (data && !data.error && data.summary) {
          if (isMounted) {
            const initial = data as AnalysisResult
            resultRef.current = initial
            setResult(initial)
            INITIAL_RESULT_FIELDS.forEach(field => loadedSectionsRef.current.add(field))
            setLoading(false)
            track('repo_analysis_completed', {
              repo_url: repoUrl,
              job_id: jobId,
              total_files: data.summary?.total_files,
              total_functions: data.summary?.total_functions,
              total_classes: data.summary?.total_classes,
              import_edges: data.summary?.import_edges,
              average_complexity: data.summary?.average_complexity,
              skip_llm: data.skip_llm,
              branch: data.branch || 'main',
            })
          }
        } else if (isMounted) {
          if (attempt < 5) {
            timer = setTimeout(() => fetchResult(attempt + 1), 1500)
          } else {
            const errText = data?.error ? String(data.error).toUpperCase() : 'INVALID OR EMPTY RESULT PAYLOAD'
            setFetchError(errText)
            setLoading(false)
            track('repo_results_fetch_failed', {
              repo_url: repoUrl,
              job_id: jobId,
              error: errText,
            })
          }
        }
      } catch {
        if (attempt < 5 && isMounted) {
          timer = setTimeout(() => fetchResult(attempt + 1), Math.min(6000, 750 * (2 ** attempt)))
        } else if (isMounted) {
          setFetchError('NETWORK ERROR FETCHING RESULTS')
          setLoading(false)
          track('repo_results_fetch_failed', {
            repo_url: repoUrl,
            job_id: jobId,
            error: 'NETWORK ERROR FETCHING RESULTS',
          })
        }
      }
    }

    fetchResult()
    return () => {
      isMounted = false
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  useEffect(() => {
    if (loading || !result) return
    const fields = TAB_RESULT_FIELDS[activeTab]
    if (fields.length === 0) {
      setSectionError('')
      setSectionsLoading(false)
      return
    }

    let active = true
    setSectionsLoading(true)
    setSectionError('')
    fetchSections(fields)
      .catch((error: unknown) => {
        if (active) setSectionError(error instanceof Error ? error.message : 'FAILED TO LOAD RESULT SECTION')
      })
      .finally(() => {
        if (active) setSectionsLoading(false)
      })
    return () => { active = false }
  }, [activeTab, loading, jobId])

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
  const circularCycleCount = s?.circular_cycles ?? s?.circular_dep_count ?? 0
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

  const handleDownload = async (
    fields: ResultField[],
    filename: string,
    getContent: (analysis: AnalysisResult) => string,
    mime = 'text/plain',
  ) => {
    setDownloading(filename)
    setDownloadError('')
    try {
      const analysis = await fetchSections(fields)
      if (!analysis) throw new Error('RESULT DATA IS NOT AVAILABLE')
      const blob = new Blob([getContent(analysis)], { type: mime })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      track('report_downloaded', {
        repo_url: repoUrl,
        job_id: jobId,
        filename,
        file_type: filename.endsWith('.md') ? 'markdown' : (filename.endsWith('.json') ? 'json' : 'other'),
      })
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : 'DOWNLOAD COULD NOT BE PREPARED')
    } finally {
      setDownloading('')
    }
  }

  const explainedValue = (() => {
    if (!result) return '—'
    if (result.skip_llm === true) {
      return 'SKIPPED'
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
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.50)', marginLeft: 16 }}>
            ON {result?.branch ? result.branch.toUpperCase() : 'MAIN'}
          </span>
        </div>
        {/* Row 2: Stats */}
        <div style={{ display: 'flex', gap: 32, alignItems: 'center' }}>
          {[
            { n: s?.total_files ?? '—', l: 'FILES' },
            { n: s?.total_functions ?? '—', l: 'FUNCTIONS' },
            { n: s?.total_classes ?? '—', l: 'CLASSES' },
            { n: importEdgesValue, l: 'IMPORT EDGES' },
            { n: explainedValue, l: 'EXPLAINED' },
            ...(s?.files_with_content !== undefined &&
              s.files_discovered !== undefined &&
              s.files_with_content < s.files_discovered
              ? [{ n: `${s.files_with_content}/${s.files_discovered}`, l: 'CONTENT' }]
              : []),
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
        {circularCycleCount > 0 && (
          <div>
            <span style={{ display: 'inline-block', fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', color: '#FFFFFF', background: 'rgba(255,255,255,0.10)', border: '1px solid rgba(255,255,255,0.30)', padding: '6px 12px', marginTop: 12 }}>
              ⚠ {circularCycleCount} CIRCULAR DEPENDENCY {circularCycleCount === 1 ? 'CYCLE' : 'CYCLES'} DETECTED
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
                onClick={() => {
                  setActiveTab(tab.id)
            track('results_tab_viewed', {
                    repo_url: repoUrl,
                    job_id: jobId,
                    tab_name: tab.id,
                  })
                }}
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

        {!loading && sectionsLoading && (
          <div role="status" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 220 }}>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, letterSpacing: '0.12em', color: 'rgba(10,10,26,0.45)' }}>LOADING REPORT SECTION ···</span>
          </div>
        )}

        {!loading && !sectionsLoading && sectionError && (
          <div role="alert" style={{ maxWidth: 760, margin: '40px auto', padding: 24, background: '#FFFFFF', border: '1px solid rgba(255,59,59,0.30)', color: '#FF3B3B', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.1em' }}>
            {sectionError}
          </div>
        )}

        {/* Error state */}
        {!loading && fetchError && (
          <div style={{ background: '#FFFFFF', border: '1px solid rgba(255,59,59,0.30)', padding: '32px 40px', maxWidth: 760, margin: '40px auto', textAlign: 'center' }}>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, letterSpacing: '0.14em', color: '#FF3B3B', marginBottom: 12 }}>
              ⚠ {fetchError}
            </div>
            <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'rgba(10,10,26,0.50)', letterSpacing: '0.10em', lineHeight: 1.6, textTransform: 'uppercase', marginBottom: 24 }}>
              THE ANALYSIS RESULTS COULD NOT BE RETRIEVED. PLEASE RETURN HOME AND RUN THE ANALYSIS AGAIN.
            </p>
            <motion.button
              onClick={onHome}
              whileTap={{ scale: 0.97 }}
              transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
              style={{
                height: 40,
                padding: '0 24px',
                background: '#1400FF',
                border: 'none',
                color: '#FFFFFF',
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 11,
                fontWeight: 500,
                letterSpacing: '0.14em',
                cursor: 'pointer'
              }}
            >
              ← RETURN HOME
            </motion.button>
          </div>
        )}

        {/* ── Tab 1: Onboarding Doc ── */}
        {!loading && !fetchError && activeTab === 'onboarding' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(10,10,26,0.50)' }}>ONBOARDING DOCUMENT</span>
              <DownloadBtn label={downloading === 'onboarding.md' ? 'PREPARING…' : '↓ DOWNLOAD .MD'} onLight disabled={!result || downloading === 'onboarding.md'} onClick={() => void handleDownload(['onboarding_doc'], 'onboarding.md', analysis => analysis.onboarding_doc || '')} />
            </div>
            <div className="gnosis-markdown" style={{ maxWidth: 760, margin: '0 auto' }}>
              {result?.onboarding_doc
                ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.onboarding_doc}</ReactMarkdown>
                : <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'rgba(10,10,26,0.40)', letterSpacing: '0.10em' }}>NO DOCUMENT GENERATED YET</p>
              }
            </div>
          </div>
        )}

        {!loading && !sectionsLoading && !sectionError && !fetchError && activeTab === 'agent_context' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(10,10,26,0.50)' }}>AGENT CONTEXT DOCUMENT</span>
              <DownloadBtn label={downloading === 'agent_context.md' ? 'PREPARING…' : '↓ DOWNLOAD .MD'} onLight disabled={!result || downloading === 'agent_context.md'} onClick={() => void handleDownload(['agent_context'], 'agent_context.md', analysis => analysis.agent_context || '')} />
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
        {!loading && !sectionsLoading && !sectionError && !fetchError && activeTab === 'explanations' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.14em', color: 'rgba(10,10,26,0.50)' }}>FILE EXPLANATIONS</span>
              <DownloadBtn label={downloading === 'file_explanations.md' ? 'PREPARING…' : '↓ DOWNLOAD .MD'} onLight disabled={!result || downloading === 'file_explanations.md'} onClick={() => void handleDownload(['file_explanations_md'], 'file_explanations.md', analysis => analysis.file_explanations_md || '')} />
            </div>
            <div className="gnosis-markdown" style={{ maxWidth: 760, margin: '0 auto' }}>
              {result?.file_explanations_md
                ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.file_explanations_md}</ReactMarkdown>
                : (
                  <div style={{ padding: '24px 0' }}>
                    <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, color: '#1400FF', letterSpacing: '0.12em', marginBottom: 8, textTransform: 'uppercase' }}>
                      {result?.explanation_status === 'failed' ? 'AI EXPLANATIONS FAILED' : 'AI EXPLANATIONS SKIPPED'}
                    </p>
                    <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 400, color: 'rgba(10,10,26,0.50)', letterSpacing: '0.10em', lineHeight: 1.6, textTransform: 'uppercase' }}>
                      {result?.explanation_status === 'failed'
                        ? `ALL ${result.explanations_failed ?? 0} SELECTED FILES WERE ATTEMPTED AND NONE RETURNED AN EXPLANATION.${result.explanation_error ? ` PROVIDER ERROR: ${result.explanation_error}` : ''}`
                        : 'AI EXPLANATIONS WERE NOT GENERATED FOR THIS RUN.'}
                    </p>
                  </div>
                )
              }
            </div>
          </div>
        )}

        {/* ── Tab 2: Dependency Graph ── */}
        {!loading && !sectionsLoading && !sectionError && activeTab === 'dependency' && (
          <div>
            {/* Risk Distribution Summary Bar */}
            <RiskDistributionBar riskDist={riskDist} />

            <Suspense fallback={<div className="gnosis-graph-loading">INITIALIZING WEBGL STRUCTURAL MAP ···</div>}>
              <DependencyGraph3D
                nodes={result?.graph_data?.nodes || []}
                links={result?.graph_data?.links || []}
                cycles={result?.graph_data?.circular_deps || result?.circular_deps || []}
              />
            </Suspense>
            {result?.circular_deps_truncated && (
              <div role="status" style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, margin: '-4px 0 20px', color: 'rgba(10,10,26,0.62)' }}>
                CYCLE PATH LIST CAPPED FOR PERFORMANCE · ALL CYCLE MEMBER FILES ARE INCLUDED
              </div>
            )}

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
        {!loading && !sectionsLoading && !sectionError && activeTab === 'complexity' && (
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
        {!loading && !sectionsLoading && !sectionError && activeTab === 'raw' && (
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
        {downloadError && <span role="status" style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: '#FFB4B4' }}>{downloadError}</span>}
        <div style={{ display: 'flex', gap: 12, marginLeft: 24 }}>
          <DownloadBtn label={downloading === 'onboarding.md' ? 'PREPARING…' : '↓ ONBOARDING.MD'} disabled={!result || downloading === 'onboarding.md'} onClick={() => void handleDownload(['onboarding_doc'], 'onboarding.md', analysis => analysis.onboarding_doc || '')} />
          <DownloadBtn label={downloading === 'agent_context.md' ? 'PREPARING…' : '↓ AGENT_CONTEXT.MD'} disabled={!result || downloading === 'agent_context.md'} onClick={() => void handleDownload(['agent_context'], 'agent_context.md', analysis => analysis.agent_context || '')} />
          {result?.skip_llm !== true && <DownloadBtn label={downloading === 'file_explanations.md' ? 'PREPARING…' : '↓ FILE_EXPLANATIONS.MD'} disabled={!result || downloading === 'file_explanations.md'} onClick={() => void handleDownload(['file_explanations_md'], 'file_explanations.md', analysis => analysis.file_explanations_md || '')} />}
          <DownloadBtn label={downloading === 'complexity_report.json' ? 'PREPARING…' : '↓ COMPLEXITY_REPORT.JSON'} disabled={!result || downloading === 'complexity_report.json'} onClick={() => void handleDownload(['complexity_report_json'], 'complexity_report.json', analysis => analysis.complexity_report_json || '{}', 'application/json')} />
          <DownloadBtn label={downloading === 'dependency_graph.json' ? 'PREPARING…' : '↓ DEPENDENCY_GRAPH.JSON'} disabled={!result || downloading === 'dependency_graph.json'} onClick={() => void handleDownload(['dependency_rows'], 'dependency_graph.json', analysis => JSON.stringify(analysis.dependency_rows || [], null, 2), 'application/json')} />
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


export default ResultsPage
