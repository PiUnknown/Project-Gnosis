/**
 * ResultsPage — displays analysis output across five tabs.
 *
 * Tabs: ONBOARDING DOC · AGENT CONTEXT · DEPENDENCY GRAPH · COMPLEXITY REPORT · RAW OUTPUT
 * Download bar: onboarding.md · agent_context.md · complexity_report.json · dependency_graph.json
 */

import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { JobResult, RiskLevel } from "../types/api";
import {
    downloadOnboarding,
    downloadAgentContext,
    downloadComplexityReport,
    downloadDependencyGraph,
} from "../lib/download";

type Tab =
    | "ONBOARDING DOC"
    | "AGENT CONTEXT"
    | "DEPENDENCY GRAPH"
    | "COMPLEXITY REPORT"
    | "RAW OUTPUT";

const TABS: Tab[] = [
    "ONBOARDING DOC",
    "AGENT CONTEXT",
    "DEPENDENCY GRAPH",
    "COMPLEXITY REPORT",
    "RAW OUTPUT",
];

function repoNameFromUrl(url?: string): string {
    if (!url) return "repo";
    const parts = url.replace(/\/$/, "").split("/");
    return parts[parts.length - 1] || "repo";
}

function riskColor(level: RiskLevel): string {
    switch (level) {
        case "CRITICAL": return "#FF2D2D";
        case "HIGH": return "#FF8C00";
        case "MEDIUM": return "#FFD700";
        case "LOW": return "#4ADE80";
        default: return "rgba(255,255,255,0.4)";
    }
}

function riskBg(level: RiskLevel): string {
    switch (level) {
        case "CRITICAL": return "rgba(255,45,45,0.15)";
        case "HIGH": return "rgba(255,140,0,0.15)";
        case "MEDIUM": return "rgba(255,215,0,0.12)";
        case "LOW": return "rgba(74,222,128,0.12)";
        default: return "rgba(255,255,255,0.05)";
    }
}

function RiskBadge({ level }: { level: RiskLevel }) {
    return (
        <span style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: "11px",
            fontWeight: 600,
            color: riskColor(level),
            background: riskBg(level),
            border: `1px solid ${riskColor(level)}`,
            padding: "2px 6px",
            borderRadius: "0px",
            letterSpacing: "0.05em",
        }}>
            {level}
        </span>
    );
}

function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <button
            onClick={() => {
                navigator.clipboard.writeText(text).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                });
            }}
            style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: "11px",
                color: copied ? "#4ADE80" : "rgba(255,255,255,0.6)",
                background: "transparent",
                border: "1px solid rgba(255,255,255,0.2)",
                padding: "3px 10px",
                borderRadius: "0px",
                cursor: "pointer",
            }}
        >
            {copied ? "COPIED" : "COPY"}
        </button>
    );
}

// ── Shared markdown renderer ───────────────────────────────────────────────

function MarkdownPane({ content }: { content: string }) {
    return (
        <div style={{
            background: "#F0F0FF",
            padding: "32px 40px",
            color: "#0A0030",
            fontFamily: "'Inter', sans-serif",
            lineHeight: 1.7,
            minHeight: "60vh",
        }}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                    h1: ({ children }) => (
                        <h1 style={{
                            fontFamily: "'Playfair Display', serif",
                            fontWeight: 400,
                            textTransform: "uppercase",
                            fontSize: "28px",
                            letterSpacing: "0.04em",
                            color: "#1400FF",
                            marginBottom: "8px",
                        }}>{children}</h1>
                    ),
                    h2: ({ children }) => (
                        <h2 style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: "13px",
                            fontWeight: 600,
                            textTransform: "uppercase",
                            letterSpacing: "0.1em",
                            color: "#1400FF",
                            borderBottom: "1px solid rgba(20,0,255,0.15)",
                            paddingBottom: "6px",
                            marginTop: "36px",
                            marginBottom: "14px",
                        }}>{children}</h2>
                    ),
                    h3: ({ children }) => (
                        <h3 style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: "12px",
                            fontWeight: 600,
                            color: "#0F00CC",
                            marginTop: "24px",
                            marginBottom: "8px",
                        }}>{children}</h3>
                    ),
                    code: ({ inline, children, ...props }: any) =>
                        inline ? (
                            <code style={{
                                fontFamily: "'IBM Plex Mono', monospace",
                                fontSize: "12px",
                                background: "rgba(20,0,255,0.08)",
                                padding: "1px 5px",
                                color: "#0F00CC",
                            }} {...props}>{children}</code>
                        ) : (
                            <pre style={{
                                background: "#0A0030",
                                color: "#C8C8FF",
                                fontFamily: "'IBM Plex Mono', monospace",
                                fontSize: "12px",
                                padding: "16px 20px",
                                overflowX: "auto",
                                margin: "16px 0",
                                border: "1px solid rgba(20,0,255,0.2)",
                            }}><code {...props}>{children}</code></pre>
                        ),
                    table: ({ children }) => (
                        <div style={{ overflowX: "auto", margin: "16px 0" }}>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px" }}>
                                {children}
                            </table>
                        </div>
                    ),
                    th: ({ children }) => (
                        <th style={{ textAlign: "left", padding: "8px 12px", background: "#1400FF", color: "#fff", fontWeight: 600, letterSpacing: "0.05em", fontSize: "11px", textTransform: "uppercase" }}>
                            {children}
                        </th>
                    ),
                    td: ({ children }) => (
                        <td style={{ padding: "7px 12px", borderBottom: "1px solid rgba(20,0,255,0.1)", color: "#0A0030" }}>
                            {children}
                        </td>
                    ),
                    blockquote: ({ children }) => (
                        <blockquote style={{ borderLeft: "3px solid #1400FF", margin: "16px 0", paddingLeft: "16px", color: "#3D28FF", fontStyle: "italic" }}>
                            {children}
                        </blockquote>
                    ),
                }}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
}

// ── AGENT CONTEXT tab ─────────────────────────────────────────────────────

function AgentContextPane({ content }: { content?: string }) {
    if (!content) {
        return (
            <div style={{ padding: "48px 40px", fontFamily: "'IBM Plex Mono', monospace", color: "rgba(255,255,255,0.4)", fontSize: "13px" }}>
                agent_context.md was not generated for this job.
            </div>
        );
    }
    return (
        <div>
            <div style={{
                background: "rgba(255,255,255,0.06)",
                borderLeft: "3px solid rgba(255,255,255,0.5)",
                padding: "12px 20px",
                display: "flex",
                alignItems: "center",
                gap: "12px",
            }}>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", fontWeight: 600, color: "rgba(255,255,255,0.5)", textTransform: "uppercase", letterSpacing: "0.1em", whiteSpace: "nowrap" }}>
                    AI AGENT DOC
                </span>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "rgba(255,255,255,0.55)" }}>
                    Paste this document at the start of your AI assistant's context window to provide immediate architectural understanding.
                </span>
            </div>
            <MarkdownPane content={content} />
        </div>
    );
}

// ── DEPENDENCY GRAPH tab ──────────────────────────────────────────────────

function DependencyGraphPane({ result }: { result: JobResult }) {
    const { graph_data } = result;
    if (!graph_data) {
        return <div style={{ padding: "40px", fontFamily: "'IBM Plex Mono', monospace", color: "rgba(255,255,255,0.4)", fontSize: "13px" }}>Dependency graph data not available.</div>;
    }

    const in_deg = graph_data.in_degree || {};
    const topFiles = Object.entries(in_deg).sort(([, a], [, b]) => (b as number) - (a as number)).slice(0, 20);
    const shortPath = (p: string) => p.replace(/\\/g, "/").split("/").slice(-3).join("/");
    const complexityData: Record<string, any> = result.complexity_report_json ? JSON.parse(result.complexity_report_json) : {};

    return (
        <div style={{ padding: "32px 40px" }}>
            <h2 style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", color: "#fff", marginBottom: "20px" }}>
                Top Files by In-degree
            </h2>
            <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px" }}>
                    <thead>
                        <tr>
                            {["File", "In-degree", "Out-degree", "Risk"].map(h => (
                                <th key={h} style={{ textAlign: "left", padding: "8px 14px", background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.6)", fontWeight: 600, letterSpacing: "0.08em", fontSize: "10px", textTransform: "uppercase" }}>{h}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {topFiles.map(([fp, deg]) => {
                            const cs = complexityData[fp];
                            const risk: RiskLevel = cs?.risk_level || "UNKNOWN";
                            return (
                                <tr key={fp} style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                                    <td style={{ padding: "9px 14px", color: "#C8C8FF" }}>{shortPath(fp)}</td>
                                    <td style={{ padding: "9px 14px", color: "#fff" }}>{deg as number}</td>
                                    <td style={{ padding: "9px 14px", color: "rgba(255,255,255,0.5)" }}>{graph_data.out_degree?.[fp] ?? "—"}</td>
                                    <td style={{ padding: "9px 14px" }}><RiskBadge level={risk} /></td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {graph_data.circular_deps?.length > 0 && (
                <div style={{ marginTop: "36px" }}>
                    <h2 style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", color: "#FF2D2D", marginBottom: "14px" }}>
                        Circular Dependencies ({graph_data.circular_deps.length})
                    </h2>
                    {graph_data.circular_deps.slice(0, 10).map((cycle: string[], i: number) => (
                        <div key={i} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: "rgba(255,45,45,0.8)", background: "rgba(255,45,45,0.06)", border: "1px solid rgba(255,45,45,0.15)", padding: "7px 12px", marginBottom: "4px" }}>
                            {cycle.map(shortPath).join(" → ")} → {shortPath(cycle[0])}
                        </div>
                    ))}
                </div>
            )}

            {graph_data.topological_order?.length > 0 && (
                <div style={{ marginTop: "36px" }}>
                    <h2 style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", color: "#fff", marginBottom: "14px" }}>
                        Suggested Reading Order
                    </h2>
                    <ol style={{ listStyle: "decimal inside", padding: 0, display: "flex", flexDirection: "column", gap: "5px" }}>
                        {graph_data.topological_order.slice(0, 20).map((fp: string) => (
                            <li key={fp} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "rgba(255,255,255,0.7)", padding: "4px 0" }}>
                                {shortPath(fp)}
                            </li>
                        ))}
                    </ol>
                </div>
            )}
        </div>
    );
}

// ── COMPLEXITY REPORT tab ─────────────────────────────────────────────────

function ComplexityReportPane({ result }: { result: JobResult }) {
    const [sortKey, setSortKey] = useState("max_complexity");
    const [filterRisk, setFilterRisk] = useState("ALL");
    const [search, setSearch] = useState("");

    const raw: Record<string, any> = result.complexity_report_json ? JSON.parse(result.complexity_report_json) : {};
    const shortPath = (p: string) => p.replace(/\\/g, "/").split("/").slice(-3).join("/");
    const risks: RiskLevel[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

    let rows = Object.entries(raw).map(([fp, cs]: [string, any]) => ({ fp, short: shortPath(fp), ...cs }));
    if (filterRisk !== "ALL") rows = rows.filter(r => r.risk_level === filterRisk);
    if (search.trim()) rows = rows.filter(r => r.short.toLowerCase().includes(search.toLowerCase()));
    rows.sort((a, b) => (b[sortKey] ?? 0) - (a[sortKey] ?? 0));

    const colStyle = (key: string) => ({
        textAlign: "left" as const,
        padding: "8px 14px",
        background: sortKey === key ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.07)",
        color: sortKey === key ? "#fff" : "rgba(255,255,255,0.5)",
        fontWeight: 600,
        letterSpacing: "0.08em",
        fontSize: "10px",
        textTransform: "uppercase" as const,
        cursor: "pointer",
        userSelect: "none" as const,
        fontFamily: "'IBM Plex Mono', monospace",
    });

    return (
        <div style={{ padding: "28px 40px" }}>
            <div style={{ display: "flex", gap: "12px", marginBottom: "20px", alignItems: "center" }}>
                <input
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="Filter by file path..."
                    style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "0px", color: "#fff", padding: "7px 12px", outline: "none", width: "260px" }}
                />
                <div style={{ display: "flex", gap: "4px" }}>
                    {["ALL", ...risks].map(r => (
                        <button key={r} onClick={() => setFilterRisk(r)} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", fontWeight: 600, padding: "5px 10px", borderRadius: "0px", border: "1px solid", cursor: "pointer", background: filterRisk === r ? "rgba(255,255,255,0.12)" : "transparent", borderColor: filterRisk === r ? "rgba(255,255,255,0.4)" : "rgba(255,255,255,0.15)", color: filterRisk === r ? "#fff" : "rgba(255,255,255,0.5)", letterSpacing: "0.05em" }}>
                            {r}
                        </button>
                    ))}
                </div>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: "rgba(255,255,255,0.35)", marginLeft: "auto" }}>
                    {rows.length} file(s)
                </span>
            </div>
            <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                        <tr>
                            <th onClick={() => setSortKey("short")} style={colStyle("short")}>File</th>
                            <th onClick={() => setSortKey("risk_level")} style={colStyle("risk_level")}>Risk</th>
                            <th onClick={() => setSortKey("max_complexity")} style={colStyle("max_complexity")}>Max CC {sortKey === "max_complexity" ? "↓" : ""}</th>
                            <th onClick={() => setSortKey("avg_complexity")} style={colStyle("avg_complexity")}>Avg CC</th>
                            <th onClick={() => setSortKey("num_functions")} style={colStyle("num_functions")}>Functions</th>
                            <th onClick={() => setSortKey("coupling_score")} style={colStyle("coupling_score")}>Coupling</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map(row => (
                            <tr key={row.fp} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                                <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: "#C8C8FF", padding: "8px 14px" }}>
                                    {row.short}
                                    {row.parse_failed && <span style={{ marginLeft: "8px", color: "#FF2D2D", fontSize: "10px" }}>PARSE ERR</span>}
                                    {row.in_circular_dependency && <span style={{ marginLeft: "8px", color: "#FF8C00", fontSize: "10px" }}>CYCLE</span>}
                                </td>
                                <td style={{ padding: "8px 14px" }}><RiskBadge level={row.risk_level as RiskLevel} /></td>
                                <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "#fff", padding: "8px 14px" }}>{(row.max_complexity ?? 0).toFixed(0)}</td>
                                <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "rgba(255,255,255,0.7)", padding: "8px 14px" }}>{(row.avg_complexity ?? 0).toFixed(1)}</td>
                                <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "rgba(255,255,255,0.6)", padding: "8px 14px" }}>{row.num_functions ?? 0}</td>
                                <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "rgba(255,255,255,0.6)", padding: "8px 14px" }}>{row.coupling_score ?? 0}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// ── RAW OUTPUT tab ────────────────────────────────────────────────────────

function RawOutputPane({ result }: { result: JobResult }) {
    const [open, setOpen] = useState<Record<string, boolean>>({});
    const toggle = (k: string) => setOpen(p => ({ ...p, [k]: !p[k] }));

    const panels = [
        { key: "complexity", label: "complexity_report.json", content: result.complexity_report_json || "{}" },
        { key: "graph", label: "dependency_graph.json", content: JSON.stringify(result.graph_data || {}, null, 2) },
        { key: "explanations", label: "explanations.json", content: JSON.stringify(result.explanations || {}, null, 2) },
        { key: "symbol_tables", label: "symbol_tables.json", content: JSON.stringify(result.symbol_tables || {}, null, 2) },
    ];

    return (
        <div style={{ padding: "28px 40px", display: "flex", flexDirection: "column", gap: "8px" }}>
            {panels.map(p => (
                <div key={p.key} style={{ border: "1px solid rgba(255,255,255,0.1)" }}>
                    <div onClick={() => toggle(p.key)} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", cursor: "pointer", background: open[p.key] ? "rgba(255,255,255,0.06)" : "transparent" }}>
                        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "rgba(255,255,255,0.8)" }}>{p.label}</span>
                        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                            <CopyButton text={p.content} />
                            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "rgba(255,255,255,0.3)" }}>{open[p.key] ? "▲" : "▼"}</span>
                        </div>
                    </div>
                    {open[p.key] && (
                        <pre style={{ margin: 0, padding: "16px 20px", background: "#050020", color: "#C8C8FF", fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", overflowX: "auto", maxHeight: "400px", overflowY: "auto", borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                            {p.content}
                        </pre>
                    )}
                </div>
            ))}
        </div>
    );
}

// ── Main page ─────────────────────────────────────────────────────────────

const downloadBtnStyle: React.CSSProperties = {
    fontFamily: "'IBM Plex Mono', monospace",
    fontSize: "11px",
    fontWeight: 600,
    letterSpacing: "0.05em",
    color: "#fff",
    background: "transparent",
    border: "1px solid rgba(255,255,255,0.35)",
    padding: "7px 14px",
    borderRadius: "0px",
    cursor: "pointer",
};

export default function ResultsPage() {
    const { jobId } = useParams<{ jobId: string }>();
    const navigate = useNavigate();
    const [result, setResult] = useState<JobResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [activeTab, setActiveTab] = useState<Tab>("ONBOARDING DOC");

    const apiBase = import.meta.env.VITE_API_URL || "";

    useEffect(() => {
        if (!jobId) return;
        fetch(`${apiBase}/jobs/${jobId}/result`)
            .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
            .then(data => { setResult(data.result || data); setLoading(false); })
            .catch(err => { setError(err.message); setLoading(false); });
    }, [jobId]);

    if (loading) {
        return (
            <div style={{ minHeight: "100vh", background: "#1400FF", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", color: "rgba(255,255,255,0.6)", fontSize: "13px", letterSpacing: "0.1em" }}>LOADING RESULTS…</span>
            </div>
        );
    }

    if (error || !result) {
        return (
            <div style={{ minHeight: "100vh", background: "#1400FF", display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: "16px" }}>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", color: "#FF2D2D", fontSize: "13px" }}>{error || "Result not found."}</span>
                <button onClick={() => navigate("/")} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "#fff", background: "transparent", border: "1px solid rgba(255,255,255,0.3)", padding: "8px 20px", cursor: "pointer", borderRadius: "0px" }}>← BACK</button>
            </div>
        );
    }

    const repoName = repoNameFromUrl(result.repo_url);
    const complexityData: Record<string, any> = result.complexity_report_json ? JSON.parse(result.complexity_report_json) : {};
    const riskCounts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    Object.values(complexityData).forEach((cs: any) => {
        const r = cs.risk_level as keyof typeof riskCounts;
        if (r in riskCounts) riskCounts[r]++;
    });

    return (
        <div style={{ minHeight: "100vh", background: "#1400FF", display: "flex", flexDirection: "column" }}>

            {/* Top bar */}
            <div style={{ padding: "20px 40px", borderBottom: "1px solid rgba(255,255,255,0.12)", display: "flex", alignItems: "center", gap: "24px" }}>
                <button onClick={() => navigate("/")} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: "rgba(255,255,255,0.5)", background: "transparent", border: "none", cursor: "pointer", padding: 0, letterSpacing: "0.05em" }}>← GNOSIS</button>
                <span style={{ fontFamily: "'Playfair Display', serif", fontSize: "22px", fontWeight: 400, color: "#fff", textTransform: "uppercase", letterSpacing: "0.04em" }}>{repoName}</span>
                {result.analysis_mode && (
                    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", color: "rgba(255,255,255,0.4)", letterSpacing: "0.1em" }}>{result.analysis_mode.toUpperCase()} MODE</span>
                )}
                <div style={{ marginLeft: "auto", display: "flex", gap: "12px", alignItems: "center" }}>
                    {result.files_analyzed && (
                        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: "rgba(255,255,255,0.5)" }}>{result.files_analyzed} files</span>
                    )}
                </div>
            </div>

            {/* Risk pills */}
            <div style={{ padding: "10px 40px", borderBottom: "1px solid rgba(255,255,255,0.08)", display: "flex", gap: "8px" }}>
                {(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const).map(r =>
                    riskCounts[r] > 0 ? (
                        <span key={r} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", fontWeight: 600, color: riskColor(r), background: riskBg(r), border: `1px solid ${riskColor(r)}`, padding: "3px 8px", letterSpacing: "0.06em" }}>
                            {riskCounts[r]} {r}
                        </span>
                    ) : null
                )}
            </div>

            {/* Tab bar */}
            <div style={{ display: "flex", borderBottom: "1px solid rgba(255,255,255,0.12)", padding: "0 40px" }}>
                {TABS.map(tab => (
                    <button key={tab} onClick={() => setActiveTab(tab)} style={{
                        fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: "11px",
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        color: activeTab === tab ? "#fff" : "rgba(255,255,255,0.4)",
                        background: "transparent",
                        border: "none",
                        borderBottom: activeTab === tab ? "2px solid #fff" : "2px solid transparent",
                        padding: "14px 18px 12px",
                        cursor: "pointer",
                    }}>
                        {tab}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            <div style={{ flex: 1, overflowY: "auto", paddingBottom: "80px" }}>
                {activeTab === "ONBOARDING DOC" && (
                    result.final_doc
                        ? <MarkdownPane content={result.final_doc} />
                        : <div style={{ padding: "40px", fontFamily: "'IBM Plex Mono', monospace", color: "rgba(255,255,255,0.4)", fontSize: "13px" }}>onboarding.md not available.</div>
                )}
                {activeTab === "AGENT CONTEXT" && (
                    <AgentContextPane content={result.agent_context_md} />
                )}
                {activeTab === "DEPENDENCY GRAPH" && <DependencyGraphPane result={result} />}
                {activeTab === "COMPLEXITY REPORT" && <ComplexityReportPane result={result} />}
                {activeTab === "RAW OUTPUT" && <RawOutputPane result={result} />}
            </div>

            {/* Sticky download bar */}
            <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, background: "#0F00CC", borderTop: "1px solid rgba(255,255,255,0.15)", padding: "12px 40px", display: "flex", gap: "10px", alignItems: "center", zIndex: 100 }}>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", color: "rgba(255,255,255,0.35)", letterSpacing: "0.1em", marginRight: "4px" }}>DOWNLOAD</span>
                {result.final_doc && (
                    <button onClick={() => downloadOnboarding(result.final_doc!, repoName)} style={downloadBtnStyle}>onboarding.md</button>
                )}
                {result.agent_context_md && (
                    <button onClick={() => downloadAgentContext(result.agent_context_md!, repoName)} style={downloadBtnStyle}>agent_context.md</button>
                )}
                {result.complexity_report_json && (
                    <button onClick={() => downloadComplexityReport(result.complexity_report_json!, repoName)} style={downloadBtnStyle}>complexity_report.json</button>
                )}
                {result.graph_data && (
                    <button onClick={() => downloadDependencyGraph(result.graph_data!, repoName)} style={downloadBtnStyle}>dependency_graph.json</button>
                )}
            </div>
        </div>
    );
}