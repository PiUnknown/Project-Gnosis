/**
 * TypeScript interfaces for the Project Gnosis API.
 * Mirrors src/api/models.py — keep in sync when adding fields.
 */

export interface AnalyzeRequest {
    repo_url: string;
    github_token?: string;
    max_explanations?: number;
    skip_llm?: boolean;
}

export interface AnalyzeResponse {
    job_id: string;
    status: string;
    message?: string;
}

export type JobStatus = "queued" | "running" | "complete" | "failed";

export interface JobPollResponse {
    job_id: string;
    status: JobStatus;
    phase?: string;
    progress?: number;
    error?: string;
    repo_url?: string;
    analysis_mode?: string;
    files_discovered?: number;
    files_analyzed?: number;
}

export interface JobSummary {
    job_id: string;
    status: JobStatus;
    repo_url?: string;
    analysis_mode?: string;
    created_at?: string;
}

export interface GraphData {
    nodes: string[];
    edges: [string, string][];
    in_degree: Record<string, number>;
    out_degree: Record<string, number>;
    circular_deps: string[][];
    topological_order: string[];
    stats: {
        num_nodes: number;
        num_edges: number;
        num_cycles: number;
    };
}

export interface ComplexityEntry {
    risk_level: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";
    avg_complexity: number;
    max_complexity: number;
    num_functions: number;
    avg_function_length: number;
    coupling_score: number;
    parse_failed: boolean;
    in_circular_dependency: boolean;
}

export interface JobResult {
    job_id: string;
    status: JobStatus;
    repo_url: string;

    /** onboarding.md — human-readable architectural documentation */
    final_doc?: string;
    /** agent_context.md — concise context optimised for AI coding agents */
    agent_context_md?: string;
    /** Raw JSON string for complexity_report.json */
    complexity_report_json?: string;

    explanations?: Record<string, string>;
    graph_data?: GraphData;
    symbol_tables?: Record<string, {
        functions: string[];
        classes: string[];
        imports: string[];
    }>;

    analysis_mode?: string;
    files_discovered?: number;
    files_analyzed?: number;
    error?: string;
}

export type RiskLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";