import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { track } from '../lib/analytics'
import type {
  AnalysisResult,
  ComplexityRow,
  ResultField,
  ResultsTab,
  RiskLevel,
} from '../types/result'

type DownloadHandler = (
  fields: ResultField[],
  filename: string,
  getContent: (analysis: AnalysisResult) => string,
  mime?: string,
) => void

interface ReportPanelProps {
  repoUrl: string
  jobId: string
  result: AnalysisResult | null
  loading: boolean
  fetchError: string
  onResultChange: (next: AnalysisResult) => void
  loadSections: (fields: ResultField[]) => Promise<AnalysisResult | null>
  downloading: string
  downloadError: string
  onDownload: DownloadHandler
  onClose: () => void
}

const TABS: Array<{ id: ResultsTab; label: string }> = [
  { id: 'onboarding', label: 'ONBOARDING DOC' },
  { id: 'agent_context', label: 'AGENT CONTEXT' },
  { id: 'explanations', label: 'FILE EXPLANATIONS' },
  { id: 'dependency', label: 'DEPENDENCY' },
  { id: 'complexity', label: 'COMPLEXITY' },
  { id: 'raw', label: 'RAW OUTPUT' },
]

const TAB_FIELDS: Record<ResultsTab, ResultField[]> = {
  onboarding: [],
  agent_context: ['agent_context'],
  explanations: ['file_explanations_md', 'explanations', 'analyzed_files', 'explanation_status'],
  dependency: ['dependency_rows', 'graph_data', 'circular_deps', 'reading_order'],
  complexity: ['complexity_rows', 'complexity_report_json', 'complexity_report'],
  raw: ['explanations', 'complexity_rows', 'complexity_report_json', 'dependency_rows', 'reading_order', 'circular_deps'],
}

const RISK_WEIGHTS: Record<string, number> = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 }

function riskClass(level: string) {
  return `risk-tag ${String(level).toLowerCase()}`
}

function RiskDistribution({ riskDist }: { riskDist: Record<string, number> }) {
  const order: RiskLevel[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
  const total = order.reduce((sum, level) => sum + (riskDist[level] || 0), 0)
  if (total === 0) return null

  return (
    <div className="risk-dist">
      <div className="risk-dist-head">
        <span>CODEBASE RISK DISTRIBUTION</span>
        <span>{total} FILES</span>
      </div>
      <div className="risk-dist-bar" aria-hidden="true">
        {order.map((level) =>
          riskDist[level] ? (
            <span
              key={level}
              className={`risk-seg ${level.toLowerCase()}`}
              style={{ width: `${((riskDist[level] || 0) / total) * 100}%` }}
            />
          ) : null,
        )}
      </div>
      <div className="risk-dist-legend">
        {order.map((level) => (
          <span key={level}>
            <i className={`risk-dot ${level.toLowerCase()}`} />
            {level}: {riskDist[level] || 0}
          </span>
        ))}
      </div>
    </div>
  )
}

function MiniBar({ value, max }: { value: number; max: number }) {
  const width = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <span className="mini-bar" aria-hidden="true">
      <i style={{ width: `${width}%` }} />
    </span>
  )
}

function DownloadButton({
  label,
  onClick,
  disabled,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button type="button" className="dl-btn" onClick={onClick} disabled={disabled}>
      {label}
    </button>
  )
}

export default function ReportPanel({
  repoUrl,
  jobId,
  result,
  loading,
  fetchError,
  onResultChange,
  loadSections,
  downloading,
  downloadError,
  onDownload,
  onClose,
}: ReportPanelProps) {
  const [tab, setTab] = useState<ResultsTab>('onboarding')
  const [sectionLoading, setSectionLoading] = useState(false)
  const [sectionError, setSectionError] = useState('')
  const [selectedFile, setSelectedFile] = useState('')
  const [generating, setGenerating] = useState(false)
  const [explanationError, setExplanationError] = useState('')
  const [sortBy, setSortBy] = useState<'risk' | 'avg_cc' | 'max_cc'>('risk')
  const [filter, setFilter] = useState('')
  const closeRef = useRef<HTMLButtonElement>(null)
  const loadSectionsRef = useRef(loadSections)
  loadSectionsRef.current = loadSections

  useEffect(() => {
    closeRef.current?.focus()
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  useEffect(() => {
    if (loading || !result || fetchError) return
    const fields = TAB_FIELDS[tab]
    if (fields.length === 0) {
      setSectionLoading(false)
      setSectionError('')
      return
    }

    let active = true
    setSectionLoading(true)
    setSectionError('')
    loadSectionsRef
      .current(fields)
      .catch((error: unknown) => {
        if (active) {
          setSectionError(error instanceof Error ? error.message : 'FAILED TO LOAD RESULT SECTION')
        }
      })
      .finally(() => {
        if (active) setSectionLoading(false)
      })

    return () => {
      active = false
    }
  }, [tab, loading, fetchError, jobId, result === null])

  const selectTab = (next: ResultsTab) => {
    setTab(next)
    setSectionError('')
    track('results_tab_viewed', { repo_url: repoUrl, job_id: jobId, tab_name: next })
  }

  const displayRepo = (result?.repo || repoUrl.replace(/^https?:\/\/(www\.)?github\.com\//, '') || 'owner/repo').replace(/\.git$/, '')
  const summary = result?.summary
  const riskDist = summary?.risk_distribution || {}
  const depRows = result?.dependency_rows || []
  const readingOrder = result?.reading_order || []
  const analyzedFiles = result?.analyzed_files || []
  const explanations = result?.explanations || {}
  const currentExplanation = selectedFile ? explanations[selectedFile] : ''
  const explanationReady = Boolean(selectedFile && explanations[selectedFile])

  const complexityRows = useMemo(() => {
    return [...(result?.complexity_rows || [])]
      .filter((row) => !filter || row.file.toLowerCase().includes(filter.toLowerCase()))
      .sort((a, b) => {
        if (sortBy === 'risk') return (RISK_WEIGHTS[b.risk] || 0) - (RISK_WEIGHTS[a.risk] || 0)
        if (sortBy === 'avg_cc') return b.avg_cc - a.avg_cc
        return b.max_cc - a.max_cc
      })
  }, [result?.complexity_rows, filter, sortBy])

  const generateExplanation = async () => {
    if (!selectedFile || generating || explanationReady) return
    setGenerating(true)
    setExplanationError('')
    try {
      const response = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/jobs/${jobId}/explanations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: selectedFile }),
      })
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload.detail || `EXPLANATION REQUEST FAILED (${response.status})`)
      }
      const current = result
      if (current) {
        const nextExplanations = { ...(current.explanations || {}), [payload.file_path]: payload.explanation }
        onResultChange({
          ...current,
          explanations: nextExplanations,
          summary: { ...current.summary, explained: Object.keys(nextExplanations).length },
        })
      }
      track('file_explanation_generated', {
        repo_url: repoUrl,
        job_id: jobId,
        file_path: selectedFile,
        cached: payload.cached,
      })
    } catch (error) {
      setExplanationError(error instanceof Error ? error.message : 'COULD NOT GENERATE EXPLANATION')
    } finally {
      setGenerating(false)
    }
  }

  const dl = (label: string, fields: ResultField[], filename: string, getContent: (analysis: AnalysisResult) => string, mime?: string) => (
    <DownloadButton
      label={downloading === filename ? 'PREPARING…' : label}
      disabled={!result || downloading === filename}
      onClick={() => onDownload(fields, filename, getContent, mime)}
    />
  )

  const body = (() => {
    if (fetchError) {
      return (
        <div className="pane-error">
          <p className="msg">{fetchError}</p>
        </div>
      )
    }
    if (loading || sectionLoading) {
      return <div className="pane-loading">LOADING REPORT SECTION ···</div>
    }
    if (sectionError) {
      return (
        <div className="pane-error">
          <p className="msg">{sectionError}</p>
        </div>
      )
    }

    if (tab === 'onboarding') {
      return (
        <div className="report-inner">
          <div className="report-toolbar">
            <span className="kicker">ONBOARDING DOCUMENT</span>
            {dl('↓ DOWNLOAD .MD', ['onboarding_doc'], 'onboarding.md', (analysis) => analysis.onboarding_doc || '')}
          </div>
          {result?.onboarding_doc ? (
            <div className="report-md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.onboarding_doc}</ReactMarkdown>
            </div>
          ) : (
            <div className="section-empty">NO ONBOARDING DOCUMENT WAS GENERATED</div>
          )}
        </div>
      )
    }

    if (tab === 'agent_context') {
      return (
        <div className="report-inner">
          <div className="report-toolbar">
            <span className="kicker">AGENT CONTEXT DOCUMENT</span>
            {dl('↓ DOWNLOAD .MD', ['agent_context'], 'agent_context.md', (analysis) => analysis.agent_context || '')}
          </div>
          {result?.agent_context ? (
            <div className="report-md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.agent_context}</ReactMarkdown>
            </div>
          ) : (
            <div className="section-empty">NO AGENT CONTEXT WAS GENERATED</div>
          )}
        </div>
      )
    }

    if (tab === 'explanations') {
      return (
        <div className="report-inner">
          <div className="report-toolbar">
            <span className="kicker">FILE EXPLANATIONS / ON DEMAND</span>
            {dl(
              '↓ DOWNLOAD .MD',
              ['explanations'],
              'file_explanations.md',
              (analysis) =>
                Object.entries(analysis.explanations || {})
                  .map(([path, text]) => `## ${path}\n\n${text}`)
                  .join('\n\n'),
            )}
          </div>
          <div className="report-controls">
            <label htmlFor="explanation-file">CHOOSE FILE</label>
            <select
              id="explanation-file"
              className="file-select"
              value={selectedFile}
              onChange={(event) => {
                setSelectedFile(event.target.value)
                setExplanationError('')
              }}
              disabled={analyzedFiles.length === 0}
            >
              <option value="">SELECT AN ANALYZED FILE</option>
              {analyzedFiles.map((file) => (
                <option key={file.path} value={file.path}>
                  {file.path}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-primary"
              style={{ minHeight: 38, height: 38, padding: '0 14px', fontSize: 10 }}
              onClick={() => void generateExplanation()}
              disabled={!selectedFile || generating || explanationReady}
            >
              {generating ? 'GENERATING…' : explanationReady ? 'EXPLANATION READY' : 'GENERATE EXPLANATION'}
            </button>
          </div>
          <p className="report-toolbar kicker" style={{ marginTop: -10 }}>
            {analyzedFiles.length} ANALYZED FILES AVAILABLE · ONLY THE SELECTED FILE IS SENT FOR EXPLANATION
          </p>
          {explanationError ? <p className="explanation-error">{explanationError}</p> : null}
          {currentExplanation ? (
            <div className="report-md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{currentExplanation}</ReactMarkdown>
            </div>
          ) : (
            <p className="explanation-empty">
              {analyzedFiles.length
                ? 'SELECT A FILE TO REQUEST ITS EXPLANATION.'
                : 'NO ANALYZED FILE LIST IS AVAILABLE FOR THIS RESULT.'}
            </p>
          )}
        </div>
      )
    }

    if (tab === 'dependency') {
      const maxImported = Math.max(...depRows.map((row) => row.imported_by || 1), 1)
      const maxImports = Math.max(...depRows.map((row) => row.imports || 1), 1)
      return (
        <div className="report-inner">
          <RiskDistribution riskDist={riskDist} />
          <div className="report-toolbar">
            <span className="kicker">MOST IMPORTED FILES</span>
          </div>
          {depRows.length === 0 ? (
            <div className="section-empty">NO DEPENDENCY DATA AVAILABLE</div>
          ) : (
            <table className="data-table data-table--dependency">
              <thead>
                <tr>
                  <th>FILE</th>
                  <th className="num">IMPORTED BY</th>
                  <th className="num">IMPORTS</th>
                  <th>RISK</th>
                </tr>
              </thead>
              <tbody>
                {depRows.map((row) => (
                  <tr key={row.path}>
                    <td title={row.path}>{row.file}</td>
                    <td className="num">
                      <span className="table-number">{row.imported_by}</span>
                      <MiniBar value={row.imported_by} max={maxImported} />
                    </td>
                    <td className="num">
                      <span className="table-number">{row.imports}</span>
                      <MiniBar value={row.imports} max={maxImports} />
                    </td>
                    <td>
                      <span className={riskClass(row.risk)}>{row.risk}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="report-toolbar">
            <span className="kicker">SUGGESTED READING ORDER</span>
          </div>
          <p className="explanation-empty" style={{ padding: '0 0 14px' }}>
            FILES ORDERED SO EACH APPEARS AFTER EVERYTHING IT DEPENDS ON.
          </p>
          {readingOrder.length === 0 ? (
            <div className="section-empty">NO GRAPH DATA AVAILABLE</div>
          ) : (
            <ol className="reading-order">
              {readingOrder.map((path, index) => (
                <li key={path}>
                  <span className="idx">{String(index + 1).padStart(2, '0')}</span>
                  <span>{path}</span>
                </li>
              ))}
            </ol>
          )}
          {result?.circular_deps_truncated || result?.graph_data?.circular_deps_truncated ? (
            <p className="explanation-empty" style={{ paddingTop: 0 }}>
              CYCLE PATH LIST CAPPED FOR PERFORMANCE · ALL CYCLE MEMBER FILES ARE INCLUDED
            </p>
          ) : null}
        </div>
      )
    }

    if (tab === 'complexity') {
      const maxAvg = Math.max(...complexityRows.map((row) => row.avg_cc || 1), 1)
      const maxMax = Math.max(...complexityRows.map((row) => row.max_cc || 1), 1)
      const maxCoupling = Math.max(...complexityRows.map((row) => row.coupling || 1), 1)
      return (
        <div className="report-inner">
          <RiskDistribution riskDist={riskDist} />
          <div className="report-controls">
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value as 'risk' | 'avg_cc' | 'max_cc')} aria-label="Sort complexity rows">
              <option value="risk">SORT BY RISK</option>
              <option value="avg_cc">SORT BY AVG CC</option>
              <option value="max_cc">SORT BY MAX CC</option>
            </select>
            <input
              type="search"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="FILTER BY FILENAME"
              aria-label="Filter complexity rows by filename"
            />
            <span className="count spacer">
              SHOWING {complexityRows.length} OF {result?.complexity_rows?.length ?? 0} FILES
            </span>
          </div>
          {complexityRows.length === 0 ? (
            <div className="section-empty">NO COMPLEXITY DATA AVAILABLE</div>
          ) : (
            <table className="data-table data-table--complexity">
              <thead>
                <tr>
                  <th>FILE</th>
                  <th>RISK</th>
                  <th className="num">AVG CC</th>
                  <th className="num">MAX CC</th>
                  <th>WORST FUNCTION</th>
                  <th className="num">COUPLING</th>
                  <th>FLAGS</th>
                </tr>
              </thead>
              <tbody>
                {complexityRows.map((row: ComplexityRow) => (
                  <tr key={row.path}>
                    <td title={row.path}>{row.file}</td>
                    <td>
                      <span className={riskClass(row.risk)}>{row.risk}</span>
                    </td>
                    <td className="num">
                      <span className="table-number">{typeof row.avg_cc === 'number' ? row.avg_cc.toFixed(1) : row.avg_cc}</span>
                      <MiniBar value={row.avg_cc} max={maxAvg} />
                    </td>
                    <td className="num">
                      <span className="table-number">{row.max_cc}</span>
                      <MiniBar value={row.max_cc} max={maxMax} />
                    </td>
                    <td title={row.worst_fn || undefined}>{row.worst_fn || '—'}</td>
                    <td className="num">
                      <span className="table-number">{row.coupling}</span>
                      <MiniBar value={row.coupling} max={maxCoupling} />
                    </td>
                    <td className="flags">{(row.flags || []).join(' · ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )
    }

    return (
      <div className="report-inner">
        <details className="raw-section" open>
          <summary>
            SUMMARY <span className="count">{Object.keys(summary || {}).length} FIELDS</span>
          </summary>
          <pre>{JSON.stringify(summary || {}, null, 2)}</pre>
        </details>
        <details className="raw-section">
          <summary>
            EXPLANATIONS <span className="count">{Object.keys(explanations).length} FILES EXPLAINED</span>
          </summary>
          <pre>{JSON.stringify(explanations, null, 2)}</pre>
        </details>
        <details className="raw-section">
          <summary>
            COMPLEXITY REPORT <span className="count">{result?.complexity_rows?.length ?? 0} FILES</span>
          </summary>
          <pre>{result?.complexity_report_json || '{}'}</pre>
        </details>
        <details className="raw-section">
          <summary>
            GRAPH SUMMARY <span className="count">{depRows.length} FILES TRACKED</span>
          </summary>
          <pre>
            {JSON.stringify(
              {
                nodes: summary?.total_files,
                edges: summary?.import_edges,
                circular_cycles: summary?.circular_dep_count ?? summary?.circular_cycles,
                reading_order: readingOrder,
              },
              null,
              2,
            )}
          </pre>
        </details>
      </div>
    )
  })()

  return (
    <div className="report-overlay" role="dialog" aria-modal="true" aria-labelledby="report-title">
      <div className="report-top">
        <div className="l">
          <button ref={closeRef} type="button" className="back-link" onClick={onClose}>
            ← CLOSE
          </button>
          <span className="title" id="report-title">
            FULL REPORT — {displayRepo}
          </span>
        </div>
        <span className="chip">GENERATED FROM ANALYSIS OUTPUT</span>
      </div>

      <div className="report-tabs" role="tablist" aria-label="Report sections">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className="report-tab"
            onClick={() => selectTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="report-body">{body}</div>

      <div className="report-foot">
        <span className="label">DOWNLOAD OUTPUTS</span>
        {downloadError ? <span className="err">{downloadError}</span> : null}
        {dl('↓ ONBOARDING.MD', ['onboarding_doc'], 'onboarding.md', (analysis) => analysis.onboarding_doc || '')}
        {dl('↓ AGENT_CONTEXT.MD', ['agent_context'], 'agent_context.md', (analysis) => analysis.agent_context || '')}
        {Object.keys(explanations).length > 0
          ? dl(
              '↓ FILE_EXPLANATIONS.MD',
              ['explanations'],
              'file_explanations.md',
              (analysis) =>
                Object.entries(analysis.explanations || {})
                  .map(([path, text]) => `## ${path}\n\n${text}`)
                  .join('\n\n'),
            )
          : null}
        {dl(
          '↓ COMPLEXITY_REPORT.JSON',
          ['complexity_report_json'],
          'complexity_report.json',
          (analysis) => analysis.complexity_report_json || '{}',
          'application/json',
        )}
        {dl(
          '↓ DEPENDENCY_GRAPH.JSON',
          ['dependency_rows'],
          'dependency_graph.json',
          (analysis) => JSON.stringify(analysis.dependency_rows || [], null, 2),
          'application/json',
        )}
      </div>
    </div>
  )
}
