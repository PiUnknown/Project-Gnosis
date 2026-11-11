export type RiskLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
export type ResultsTab = 'onboarding' | 'agent_context' | 'explanations' | 'dependency' | 'complexity' | 'raw'

export interface ResultSummary {
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

export interface DepRow {
  file: string
  path: string
  imported_by: number
  imports: number
  risk: RiskLevel
}

export interface ComplexityRow {
  file: string
  path: string
  risk: RiskLevel
  avg_cc: number
  max_cc: number
  worst_fn: string | null
  coupling: number
  flags: string[]
}

export interface GraphNodeData {
  id: string
  path: string
  file: string
  risk: RiskLevel
  imported_by: number
  imports: number
}

export interface GraphLinkData {
  source: string
  target: string
}

export interface AnalysisResult {
  summary: ResultSummary
  branch?: string
  error?: string
  onboarding_doc?: string
  agent_context?: string
  file_explanations_md?: string
  dependency_rows?: DepRow[]
  graph_data?: {
    nodes: GraphNodeData[]
    links: GraphLinkData[]
    circular_deps: string[][]
    circular_deps_truncated?: boolean
  }
  reading_order?: string[]
  complexity_rows?: ComplexityRow[]
  explanations?: Record<string, string>
  explanation_status?: string
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
  analyzed_files?: Array<{
    path: string
    name?: string
    language?: string
    risk?: string
    avg_cc?: number
    max_cc?: number
    function_count?: number
  }>
}

export type ResultField = keyof AnalysisResult
