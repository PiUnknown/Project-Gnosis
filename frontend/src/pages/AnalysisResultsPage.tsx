import { useCallback, useEffect, useMemo, useRef, useState, lazy, Suspense } from 'react'
import { track } from '../lib/analytics'
import type { AnalysisResult, ResultField } from '../types/result'

const API_BASE = import.meta.env.VITE_API_URL || ''
const DependencyGraphSVG = lazy(() => import('../components/DependencyGraphSVG'))
const ReportPanel = lazy(() => import('../components/ReportPanel'))

const INITIAL_RESULT_FIELDS: ResultField[] = [
  'summary',
  'onboarding_doc',
  'branch',
  'graph_data',
  'complexity_rows',
]

type MobileTab = 'graph' | 'readouts' | 'report'

function displayRepo(repoUrl: string, result?: AnalysisResult | null) {
  if (result?.repo) return result.repo.replace(/\.git$/, '')
  return (
    repoUrl
      .replace(/^https?:\/\/(www\.)?github\.com\//, '')
      .replace(/\.git$/, '')
      .replace(/\/$/, '') || 'owner/repo'
  )
}

function basename(path: string) {
  const slash = path.lastIndexOf('/')
  return slash < 0 ? path : path.slice(slash + 1)
}

function extractExcerpt(markdown?: string) {
  if (!markdown) return ''
  const withoutFrontmatter = markdown.replace(/^---[\s\S]*?---\s*/, '')
  const blocks = withoutFrontmatter.split(/\n\s*\n/)
  const paragraphs: string[] = []

  for (const block of blocks) {
    const line = block.trim()
    if (!line) continue
    if (line.startsWith('#')) continue
    if (line.startsWith('```') || line.startsWith('|') || line.startsWith('>')) continue
    if (/^[-*+]\s/.test(line) || /^\d+\.\s/.test(line)) continue

    const cleaned = line
      .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
      .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
      .replace(/[*_]{1,3}([^*_]+)[*_]{1,3}/g, '$1')
      .replace(/\s+/g, ' ')
      .trim()

    if (cleaned.length < 32) continue
    paragraphs.push(cleaned)
    if (paragraphs.join(' ').length > 320) break
  }

  const fallback = withoutFrontmatter
    .replace(/[#*_>`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  const text = paragraphs.join(' ') || fallback
  if (!text) return ''
  return text.length > 380 ? `${text.slice(0, 377).replace(/\s+\S*$/, '')}…` : text
}

function ExcerptText({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`)/g).map((part, index) =>
        part.startsWith('`') && part.endsWith('`') && part.length > 2 ? (
          <code key={index}>{part.slice(1, -1)}</code>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  )
}

interface ResultsPageProps {
  repoUrl: string
  jobId: string
  onHome: () => void
}

export default function AnalysisResultsPage({ repoUrl, jobId, onHome }: ResultsPageProps) {
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState('')
  const [downloading, setDownloading] = useState('')
  const [downloadError, setDownloadError] = useState('')
  const [reportOpen, setReportOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState<MobileTab>('graph')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const resultRef = useRef<AnalysisResult | null>(null)
  const loadedSectionsRef = useRef(new Set<ResultField>())
  const sectionRequestsRef = useRef(new Map<ResultField, Promise<void>>())

  const applyResult = useCallback((next: AnalysisResult) => {
    resultRef.current = next
    setResult(next)
  }, [])

  const loadSections = useCallback(
    async (requestedFields: ResultField[]) => {
      const missing = requestedFields.filter((field) => !loadedSectionsRef.current.has(field))
      const pending = new Set<Promise<void>>()

      for (const field of missing) {
        const existing = sectionRequestsRef.current.get(field)
        if (existing) pending.add(existing)
      }

      const fieldsToFetch = missing.filter((field) => !sectionRequestsRef.current.has(field))

      if (fieldsToFetch.length > 0) {
        const request = (async () => {
          const params = new URLSearchParams({ sections: fieldsToFetch.join(',') })
          const response = await fetch(`${API_BASE}/api/jobs/${jobId}/result?${params}`)
          if (!response.ok) throw new Error(`RESULT SECTION REQUEST FAILED (${response.status})`)
          const data = (await response.json()) as Partial<AnalysisResult>
          const merged = { ...(resultRef.current || {}), ...data } as AnalysisResult
          resultRef.current = merged
          setResult(merged)
          fieldsToFetch.forEach((field) => loadedSectionsRef.current.add(field))
        })()

        fieldsToFetch.forEach((field) => sectionRequestsRef.current.set(field, request))
        pending.add(request)

        try {
          await Promise.all(pending)
        } finally {
          fieldsToFetch.forEach((field) => {
            if (sectionRequestsRef.current.get(field) === request) {
              sectionRequestsRef.current.delete(field)
            }
          })
        }
      } else {
        await Promise.all(pending)
      }

      return resultRef.current
    },
    [jobId],
  )

  useEffect(() => {
    if (!jobId) {
      setLoading(false)
      setFetchError('NO JOB ID WAS RETURNED. RETURN HOME AND RUN THE ANALYSIS AGAIN.')
      return
    }

    let mounted = true
    let timer: ReturnType<typeof setTimeout> | null = null

    const fetchResult = async (attempt = 0) => {
      try {
        const params = new URLSearchParams({ sections: INITIAL_RESULT_FIELDS.join(',') })
        const response = await fetch(`${API_BASE}/api/jobs/${jobId}/result?${params}`)

        if (response.status === 202) {
          if (attempt < 8 && mounted) {
            timer = setTimeout(() => void fetchResult(attempt + 1), Math.min(6000, 750 * 2 ** attempt))
            return
          }
        }

        if (!response.ok) {
          let message = `FAILED TO LOAD RESULTS (${response.status})`
          try {
            const errorJson = await response.json()
            if (errorJson.detail) message = String(errorJson.detail).toUpperCase()
          } catch {
            // Keep the status-based message.
          }
          if (mounted) {
            setFetchError(message)
            setLoading(false)
            track('repo_results_fetch_failed', { repo_url: repoUrl, job_id: jobId, error: message })
          }
          return
        }

        const data = await response.json()
        if (data && data.error === 'not ready' && attempt < 8 && mounted) {
          timer = setTimeout(() => void fetchResult(attempt + 1), Math.min(6000, 750 * 2 ** attempt))
          return
        }

        if (data && !data.error && data.summary) {
          if (!mounted) return
          const initial = data as AnalysisResult
          resultRef.current = initial
          setResult(initial)
          INITIAL_RESULT_FIELDS.forEach((field) => loadedSectionsRef.current.add(field))
          setLoading(false)
          track('repo_analysis_completed', {
            repo_url: repoUrl,
            job_id: jobId,
            total_files: data.summary?.total_files,
            total_functions: data.summary?.total_functions,
            total_classes: data.summary?.total_classes,
            import_edges: data.summary?.import_edges,
            average_complexity: data.summary?.average_complexity,
            branch: data.branch || 'main',
          })
          return
        }

        if (mounted) {
          if (attempt < 5) {
            timer = setTimeout(() => void fetchResult(attempt + 1), 1500)
          } else {
            const message = data?.error ? String(data.error).toUpperCase() : 'INVALID OR EMPTY RESULT PAYLOAD'
            setFetchError(message)
            setLoading(false)
            track('repo_results_fetch_failed', { repo_url: repoUrl, job_id: jobId, error: message })
          }
        }
      } catch {
        if (attempt < 5 && mounted) {
          timer = setTimeout(() => void fetchResult(attempt + 1), Math.min(6000, 750 * 2 ** attempt))
        } else if (mounted) {
          const message = 'NETWORK ERROR FETCHING RESULTS'
          setFetchError(message)
          setLoading(false)
          track('repo_results_fetch_failed', { repo_url: repoUrl, job_id: jobId, error: message })
        }
      }
    }

    void fetchResult()
    return () => {
      mounted = false
      if (timer) clearTimeout(timer)
    }
  }, [jobId, repoUrl])

  const handleDownload = useCallback(
    async (
      fields: ResultField[],
      filename: string,
      getContent: (analysis: AnalysisResult) => string,
      mime = 'text/plain',
    ) => {
      setDownloading(filename)
      setDownloadError('')
      try {
        const analysis = await loadSections(fields)
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
          file_type: filename.endsWith('.md') ? 'markdown' : filename.endsWith('.json') ? 'json' : 'other',
        })
      } catch (error) {
        setDownloadError(error instanceof Error ? error.message : 'DOWNLOAD COULD NOT BE PREPARED')
      } finally {
        setDownloading('')
      }
    },
    [jobId, loadSections, repoUrl],
  )

  const summary = result?.summary
  const repo = displayRepo(repoUrl, result)
  const branch = result?.branch || 'main'
  const graphNodes = result?.graph_data?.nodes || []
  const graphLinks = result?.graph_data?.links || []
  const graphCycles = result?.graph_data?.circular_deps || result?.circular_deps || []
  const circularCount =
    summary?.circular_dep_count ?? summary?.circular_cycles ?? graphCycles.length ?? 0
  const filesAnalyzed = summary?.files_analyzed ?? summary?.total_files ?? 0
  const functions = summary?.total_functions ?? 0
  const importEdges = summary?.import_edges ?? summary?.total_import_edges ?? graphLinks.length

  const preferredNode = useMemo(() => {
    if (graphNodes.length === 0) return null
    return [...graphNodes].sort(
      (a, b) => b.imported_by - a.imported_by || a.path.localeCompare(b.path),
    )[0]
  }, [graphNodes])

  useEffect(() => {
    if (!preferredNode) return
    setSelectedId((current) => {
      if (current && graphNodes.some((node) => node.id === current)) return current
      return preferredNode.id
    })
  }, [preferredNode, graphNodes])

  const selectedNode = graphNodes.find((node) => node.id === selectedId) || preferredNode

  const topComplexity = useMemo(
    () => [...(result?.complexity_rows || [])].sort((a, b) => b.max_cc - a.max_cc).slice(0, 4),
    [result?.complexity_rows],
  )
  const maxComplexity = Math.max(...topComplexity.map((row) => row.max_cc), 1)
  const excerpt = useMemo(() => extractExcerpt(result?.onboarding_doc), [result?.onboarding_doc])

  const panelCount = 1 + (topComplexity.length > 0 ? 1 : 0) + (excerpt ? 1 : 0)
  const readoutPanelCount = 1 + (topComplexity.length > 0 ? 1 : 0)

  const stats = [
    { k: 'FILES ANALYZED', v: loading ? '—' : filesAnalyzed },
    { k: 'FUNCTIONS', v: loading ? '—' : functions },
    { k: 'IMPORT EDGES', v: loading ? '—' : importEdges },
    {
      k: 'CYCLES DETECTED',
      v: loading ? '—' : circularCount,
      small: !loading && circularCount > 0 ? 'NEEDS REVIEW' : undefined,
    },
  ]

  const openReport = () => {
    if (!result) return
    setReportOpen(true)
  }

  const excerptCard = (
    <div className="paper">
      <div className="ph">
        <span>ARCHITECTURE REPORT — EXCERPT</span>
        <span>P. 01</span>
      </div>
      {excerpt ? (
        <p>
          <ExcerptText text={excerpt} />
        </p>
      ) : (
        <p className="paper-empty">NO ONBOARDING DOCUMENT WAS GENERATED FOR THIS ANALYSIS.</p>
      )}
    </div>
  )

  return (
    <section className="screen screen--fixed results-screen" aria-labelledby="results-title">
      <div className="rtop">
        <div className="l">
          <button type="button" className="back-link" onClick={onHome}>
            ← NEW ANALYSIS
          </button>
          <span className="repo" id="results-title">
            {repo}
          </span>
          <span className="chip">
            {branch.toUpperCase()} · {loading ? '—' : `${filesAnalyzed} FILES`}
          </span>
        </div>
        <div className="r">
          {!loading && circularCount > 0 ? (
            <span className="chip">
              {circularCount} CIRCULAR {circularCount === 1 ? 'CYCLE' : 'CYCLES'}
            </span>
          ) : null}
          <button type="button" className="rlink" onClick={openReport} disabled={!result}>
            READ FULL REPORT ↗
          </button>
        </div>
      </div>

      <div className="rtabs" role="tablist" aria-label="Results sections">
        {(
          [
            { id: 'graph', label: 'GRAPH' },
            { id: 'readouts', label: 'READOUTS' },
            { id: 'report', label: 'REPORT' },
          ] as Array<{ id: MobileTab; label: string }>
        ).map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={mobileTab === tab.id}
            className="rtab"
            onClick={() => {
              setMobileTab(tab.id)
              track('results_tab_viewed', { repo_url: repoUrl, job_id: jobId, tab_name: tab.id })
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {fetchError ? (
        <div className="results-error" role="alert">
          <div>
            <p className="msg">{fetchError}</p>
            <p className="hint">
              THE ANALYSIS RESULTS COULD NOT BE RETRIEVED. RETURN HOME AND RUN THE ANALYSIS AGAIN.
            </p>
            <button type="button" className="btn-ghost" onClick={onHome}>
              ← RETURN HOME
            </button>
          </div>
        </div>
      ) : (
        <div className="rmain" data-tab={mobileTab}>
          <div className="rpane rpane--graph">
            <div className="ph">
              <span>DEPENDENCY GRAPH</span>
              <span className="right">
                {loading
                  ? 'LOADING ···'
                  : selectedNode
                    ? `SELECTED: ${basename(selectedNode.path)} · ${selectedNode.imported_by} IMPORTERS`
                    : `${graphNodes.length} NODES · ${graphLinks.length} EDGES`}
              </span>
            </div>

            {loading ? (
              <div className="pane-loading">LOADING GRAPH ···</div>
            ) : graphNodes.length === 0 ? (
              <div className="graph-empty">NO DEPENDENCY DATA AVAILABLE</div>
            ) : (
              <Suspense fallback={<div className="pane-loading">BUILDING GRAPH ···</div>}>
                <DependencyGraphSVG
                  nodes={graphNodes}
                  links={graphLinks}
                  cycles={graphCycles}
                  selectedId={selectedId}
                  onSelect={(node) => setSelectedId(node.id)}
                />
              </Suspense>
            )}
          </div>

          <div className="rpane rpane--readouts">
            <div className="ph">
              <span>READOUTS</span>
              <span>
                <span className="panels-desktop">{String(panelCount).padStart(2, '0')}/03 PANELS</span>
                <span className="panels-mobile">{String(readoutPanelCount).padStart(2, '0')}/02 PANELS</span>
              </span>
            </div>

            {loading ? (
              <div className="pane-loading">LOADING READOUTS ···</div>
            ) : (
              <>
                <div className="stats">
                  {stats.map((stat) => (
                    <div className="stat" key={stat.k}>
                      <span className="k">{stat.k}</span>
                      <span className="v">
                        {stat.v}
                        {stat.small ? <small>{stat.small}</small> : null}
                      </span>
                    </div>
                  ))}
                </div>

                {topComplexity.length > 0 ? (
                  <div className="cx">
                    <h4>HIGHEST COMPLEXITY</h4>
                    {topComplexity.map((row, index) => (
                      <div className="cxrow" key={row.path}>
                        <span className="n" title={row.path}>
                          {row.file}
                        </span>
                        <span className="track">
                          <span
                            className={`fill${index === 0 ? ' hot' : ''}`}
                            style={{ ['--w' as string]: `${Math.max(4, (row.max_cc / maxComplexity) * 100)}%` }}
                          />
                        </span>
                        <span className="val">{typeof row.max_cc === 'number' ? row.max_cc.toFixed(1) : row.max_cc}</span>
                      </div>
                    ))}
                  </div>
                ) : null}

                {excerptCard}

                <div className="rfoot">
                  ANALYSIS COMPLETE ON {branch.toUpperCase()} · GNOSIS v1.2.0
                </div>
              </>
            )}
          </div>

          <div className="rpane rpane--report">
            <div className="ph">
              <span>FULL REPORT</span>
              <span>01/01 PANEL</span>
            </div>

            {loading ? (
              <div className="pane-loading">LOADING REPORT ···</div>
            ) : (
              <>
                {excerptCard}

                <div className="report-teaser">
                  <h4>THE COMPLETE DOCUMENT</h4>
                  <p>
                    ONBOARDING DOC · AGENT CONTEXT · FILE EXPLANATIONS · DEPENDENCY · COMPLEXITY · RAW
                    OUTPUT
                  </p>
                  <button type="button" className="rlink" onClick={openReport} disabled={!result}>
                    READ FULL REPORT ↗
                  </button>
                </div>

                <div className="rfoot">
                  ANALYSIS COMPLETE ON {branch.toUpperCase()} · GNOSIS v1.2.0
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {reportOpen && result ? (
        <Suspense fallback={null}>
          <ReportPanel
            repoUrl={repoUrl}
            jobId={jobId}
            result={result}
            loading={loading}
            fetchError={fetchError}
            onResultChange={applyResult}
            loadSections={loadSections}
            downloading={downloading}
            downloadError={downloadError}
            onDownload={(fields, filename, getContent, mime) => {
              void handleDownload(fields, filename, getContent, mime)
            }}
            onClose={() => setReportOpen(false)}
          />
        </Suspense>
      ) : null}
    </section>
  )
}
