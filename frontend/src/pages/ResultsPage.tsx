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
    downloadFileExplanations,
} from "../lib/download";

type Tab =
    | "ONBOARDING DOC"
    | "FILE EXPLANATIONS"
    | "AGENT CONTEXT"
    | "DEPENDENCY GRAPH"
    | "COMPLEXITY REPORT"
    | "RAW OUTPUT";

const TABS: Tab[] = [
    "ONBOARDING DOC",
    "FILE EXPLANATIONS",
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
        UNKNOWN: onLight
            ? { background: 'transparent', color: 'rgba(10,10,26,0.35)', border: 'none' }
            : { background: 'transparent', color: 'rgba(255,255,255,0.40)', border: 'none' },
    };
    return (
        <span style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: "9px",
            fontWeight: 500,
            color: styles[level]?.color || styles.LOW.color,
            background: styles[level]?.background || styles.LOW.background,
            border: styles[level]?.border || styles.LOW.border,
            padding: "3px 8px",
            borderRadius: "0px",
            letterSpacing: "0.12em",
            display: "inline-block",
        }}>
            {level}{count !== undefined ? `: ${count}` : ''}
        </span>
    );
}

function RiskDistributionBar({ riskDist }: { riskDist: Record<string, number> }) {
    const critical = riskDist.CRITICAL || 0;
    const high = riskDist.HIGH || 0;
    const medium = riskDist.MEDIUM || 0;
    const low = riskDist.LOW || 0;
    const total = critical + high + medium + low;
    if (total === 0) return null;

    const pct = (val: number) => (val / total) * 100;

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
    );
}

function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <button
            onClick={(e) => {
                e.stopPropagation();
                navigator.clipboard.writeText(text).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                }).catch(() => {});
            }}
            style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: "9px",
                fontWeight: 500,
                color: "#1400FF",
                background: "transparent",
                border: "1px solid rgba(20,0,255,0.30)",
                padding: "3px 10px",
                borderRadius: "0px",
                cursor: "pointer",
                letterSpacing: "0.12em",
                height: 28,
            }}
        >
            {copied ? "COPIED ✓" : "COPY"}
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
                    h3: ({ children }) => {
                        // Extract text content recursively to build the id matching doc_generator.py format
                        const extractText = (node: any): string => {
                            if (!node) return "";
                            if (typeof node === "string") return node;
                            if (Array.isArray(node)) return node.map(extractText).join("");
                            if (node.props && node.props.children) return extractText(node.props.children);
                            return "";
                        };
                        const text = extractText(children);
                        const cleanText = text.toLowerCase()
                            .replace(/[^a-z0-9]+/g, "-")
                            .replace(/(^-|-$)/g, "");
                        const id = cleanText ? `exp-${cleanText}` : undefined;
                        return (
                            <h3 id={id} style={{
                                fontFamily: "'IBM Plex Mono', monospace",
                                fontSize: "12px",
                                fontWeight: 600,
                                color: "#0F00CC",
                                marginTop: "24px",
                                marginBottom: "8px",
                            }}>{children}</h3>
                        );
                    },
                    a: ({ href, children }) => (
                        <a 
                            href={href} 
                            style={{ 
                                color: "#1400FF", 
                                textDecoration: "underline", 
                                fontWeight: 500 
                            }}
                        >
                            {children}
                        </a>
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

function DependencyGraphPane({ result, riskDist }: { result: JobResult; riskDist: Record<string, number> }) {
    const { graph_data } = result;
    if (!graph_data) {
        return <div style={{ padding: "40px", fontFamily: "'IBM Plex Mono', monospace", color: "rgba(10,10,26,0.40)", fontSize: "13px" }}>Dependency graph data not available.</div>;
    }

    const in_deg = graph_data.in_degree || {};
    const topFiles = Object.entries(in_deg).sort(([, a], [, b]) => (b as number) - (a as number)).slice(0, 20);
    const shortPath = (p: string) => p.replace(/\\/g, "/").split("/").slice(-3).join("/");
    const complexityData: Record<string, any> = result.complexity_report_json ? JSON.parse(result.complexity_report_json) : {};

    const maxImportedBy = Math.max(...topFiles.map(([, deg]) => deg as number), 1);
    const maxImports = Math.max(...topFiles.map(([fp]) => graph_data.out_degree?.[fp] || 1), 1);

    return (
        <div style={{ padding: "32px 40px", background: "#F0F0FF", color: "#0A0A1A" }}>
            <RiskDistributionBar riskDist={riskDist} />

            <h2 style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.16em", color: "rgba(10,10,26,0.45)", marginBottom: "16px" }}>
                MOST IMPORTED FILES
            </h2>
            <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", border: "1px solid rgba(20,0,255,0.15)", marginBottom: "48px" }}>
                    <thead>
                        <tr style={{ background: "rgba(20,0,255,0.06)", height: "40px" }}>
                            {["File", "Imported By", "Imports", "Risk"].map(h => (
                                <th key={h} style={{ textAlign: h === "File" ? "left" : "center", padding: "8px 14px", border: "1px solid rgba(20,0,255,0.12)", color: "rgba(10,10,26,0.40)", fontWeight: 500, letterSpacing: "0.12em", fontSize: "10px", textTransform: "uppercase", fontFamily: "'IBM Plex Mono', monospace" }}>{h}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {topFiles.map(([fp, deg]) => {
                            const cs = complexityData[fp];
                            const risk: RiskLevel = cs?.risk_level || "UNKNOWN";
                            const fileImports = graph_data.out_degree?.[fp] || 0;
                            return (
                                <tr key={fp} style={{ borderBottom: "1px solid rgba(20,0,255,0.08)" }}>
                                    <td style={{ padding: "9px 14px", color: "#1400FF", fontFamily: "'IBM Plex Mono', monospace", fontSize: "13px" }} title={fp}>{shortPath(fp)}</td>
                                    <td style={{ padding: "9px 14px" }}>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 500, color: '#1400FF' }}>{deg as number}</span>
                                            <div style={{ width: 60, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                                <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${((deg as number) / maxImportedBy) * 100}%`, background: '#1400FF' }} />
                                            </div>
                                        </div>
                                    </td>
                                    <td style={{ padding: "9px 14px" }}>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 400, color: 'rgba(10,10,26,0.65)' }}>{fileImports}</span>
                                            <div style={{ width: 60, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                                <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${(fileImports / maxImports) * 100}%`, background: 'rgba(20,0,255,0.40)' }} />
                                            </div>
                                        </div>
                                    </td>
                                    <td style={{ padding: "9px 14px", textAlign: "center" }}><RiskBadge level={risk} onLight /></td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {graph_data.circular_deps?.length > 0 && (
                <div style={{ marginTop: "36px", marginBottom: "36px" }}>
                    <h2 style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.16em", color: "#FF3B3B", marginBottom: "14px" }}>
                        CIRCULAR DEPENDENCIES ({graph_data.circular_deps.length})
                    </h2>
                    {graph_data.circular_deps.slice(0, 10).map((cycle: string[], i: number) => (
                        <div key={i} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: "#FF3B3B", background: "rgba(255,59,59,0.06)", border: "1px solid rgba(255,59,59,0.15)", padding: "7px 12px", marginBottom: "4px" }}>
                            {cycle.map(shortPath).join(" → ")} → {shortPath(cycle[0])}
                        </div>
                    ))}
                </div>
            )}

            {graph_data.topological_order?.length > 0 && (
                <div style={{ marginTop: "36px" }}>
                    <h2 style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.16em", color: "rgba(10,10,26,0.45)", marginBottom: "8px" }}>
                        SUGGESTED READING ORDER
                    </h2>
                    <div style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: 13, color: 'rgba(10,10,26,0.50)', marginBottom: 16 }}>Files ordered so each appears after everything it depends on.</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, borderLeft: '1px solid rgba(20,0,255,0.15)', marginLeft: 10, paddingLeft: 24, marginBottom: 24 }}>
                        {graph_data.topological_order.slice(0, 20).map((fp: string, idx: number) => (
                            <div key={fp} style={{ display: 'flex', alignItems: 'center', height: 44, position: 'relative', borderBottom: idx === Math.min(graph_data.topological_order.length, 20) - 1 ? 'none' : '1px solid rgba(20,0,255,0.08)' }}>
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
                                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 400, color: '#1400FF' }}>{fp}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

// ── COMPLEXITY REPORT tab ─────────────────────────────────────────────────

function ComplexityReportPane({ result, riskDist }: { result: JobResult; riskDist: Record<string, number> }) {
    const [sortKey, setSortKey] = useState("max_complexity");
    const [filterRisk, setFilterRisk] = useState("ALL");
    const [search, setSearch] = useState("");

    const raw: Record<string, any> = result.complexity_report_json ? JSON.parse(result.complexity_report_json) : {};
    const shortPath = (p: string) => p.replace(/\\/g, "/").split("/").slice(-3).join("/");
    const risks: RiskLevel[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

    let rows = Object.entries(raw).map(([fp, cs]: [string, any]) => ({ fp, short: shortPath(fp), ...cs }));
    if (filterRisk !== "ALL") rows = rows.filter(r => r.risk_level === filterRisk);
    if (search.trim()) rows = rows.filter(r => r.short.toLowerCase().includes(search.toLowerCase()));

    const RISK_WEIGHTS: Record<RiskLevel, number> = {
        CRITICAL: 4,
        HIGH: 3,
        MEDIUM: 2,
        LOW: 1,
        UNKNOWN: 0,
    };

    rows.sort((a, b) => {
        if (sortKey === "risk_level") {
            return (RISK_WEIGHTS[b.risk_level as RiskLevel] || 0) - (RISK_WEIGHTS[a.risk_level as RiskLevel] || 0);
        } else if (sortKey === "max_complexity") {
            return b.max_complexity - a.max_complexity;
        } else if (sortKey === "avg_complexity") {
            return b.avg_complexity - a.avg_complexity;
        } else if (sortKey === "num_functions") {
            return b.num_functions - a.num_functions;
        } else if (sortKey === "coupling_score") {
            return b.coupling_score - a.coupling_score;
        } else {
            return a.short.localeCompare(b.short);
        }
    });

    const colStyle = (key: string) => ({
        textAlign: (key === "short" || key === "worst_fn" || key === "flags") ? "left" as const : "center" as const,
        padding: "8px 14px",
        background: sortKey === key ? "rgba(20,0,255,0.08)" : "rgba(20,0,255,0.04)",
        color: "rgba(10,10,26,0.50)",
        fontWeight: 500,
        letterSpacing: "0.08em",
        fontSize: "10px",
        textTransform: "uppercase" as const,
        cursor: "pointer",
        userSelect: "none" as const,
        fontFamily: "'IBM Plex Mono', monospace",
        border: "1px solid rgba(20,0,255,0.12)",
    });

    const maxAvgCC = Math.max(...rows.map(r => r.avg_complexity || 1), 1);
    const maxMaxCC = Math.max(...rows.map(r => r.max_complexity || 1), 1);
    const maxCoupling = Math.max(...rows.map(r => r.coupling_score || 1), 1);

    return (
        <div style={{ padding: "28px 40px", background: "#F0F0FF", color: "#0A0A1A" }}>
            <RiskDistributionBar riskDist={riskDist} />

            <div style={{ display: "flex", gap: "12px", marginBottom: "20px", alignItems: "center" }}>
                <input
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="FILTER BY FILENAME..."
                    style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", background: "#FFFFFF", border: "1px solid rgba(20,0,255,0.20)", borderRadius: "0px", color: "#1400FF", padding: "7px 12px", outline: "none", width: "240px" }}
                />
                <div style={{ display: "flex", gap: "4px" }}>
                    {["ALL", ...risks].map(r => (
                        <button key={r} onClick={() => setFilterRisk(r)} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", fontWeight: 600, padding: "5px 10px", borderRadius: "0px", border: "1px solid", cursor: "pointer", background: filterRisk === r ? "rgba(20,0,255,0.08)" : "transparent", borderColor: filterRisk === r ? "rgba(20,0,255,0.4)" : "rgba(20,0,255,0.15)", color: filterRisk === r ? "#1400FF" : "rgba(10,10,26,0.50)", letterSpacing: "0.05em" }}>
                            {r}
                        </button>
                    ))}
                </div>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: "rgba(10,10,26,0.40)", marginLeft: "auto" }}>
                    SHOWING {rows.length} OF {Object.keys(raw).length} FILES
                </span>
            </div>
            <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", border: "1px solid rgba(20,0,255,0.15)" }}>
                    <thead>
                        <tr>
                            <th onClick={() => setSortKey("short")} style={colStyle("short")}>File</th>
                            <th onClick={() => setSortKey("risk_level")} style={colStyle("risk_level")}>Risk</th>
                            <th onClick={() => setSortKey("avg_complexity")} style={colStyle("avg_complexity")}>Avg CC</th>
                            <th onClick={() => setSortKey("max_complexity")} style={colStyle("max_complexity")}>Max CC</th>
                            <th style={colStyle("worst_fn")}>Worst Function</th>
                            <th onClick={() => setSortKey("coupling_score")} style={colStyle("coupling_score")}>Coupling</th>
                            <th style={colStyle("flags")}>Flags</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map(row => (
                            <tr key={row.fp} style={{ borderBottom: "1px solid rgba(20,0,255,0.08)", height: "52px" }}>
                                <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "13px", color: "#1400FF", padding: "8px 14px" }} title={row.fp}>
                                    {row.short}
                                </td>
                                <td style={{ padding: "8px 14px", textAlign: "center" }}><RiskBadge level={row.risk_level as RiskLevel} onLight /></td>
                                <td style={{ padding: "8px 14px" }}>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "14px", fontWeight: 500, color: "#0A0A1A" }}>{(row.avg_complexity ?? 0).toFixed(1)}</span>
                                        <div style={{ width: 50, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                            <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${((row.avg_complexity ?? 0) / maxAvgCC) * 100}%`, background: '#1400FF' }} />
                                        </div>
                                    </div>
                                </td>
                                <td style={{ padding: "8px 14px" }}>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "14px", fontWeight: 500, color: row.max_complexity >= 21 ? '#1400FF' : '#0A0A1A' }}>{(row.max_complexity ?? 0).toFixed(0)}</span>
                                        <div style={{ width: 50, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                            <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${((row.max_complexity ?? 0) / maxMaxCC) * 100}%`, background: row.max_complexity >= 21 ? '#1400FF' : 'rgba(20,0,255,0.50)' }} />
                                        </div>
                                    </div>
                                </td>
                                <td style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "#1400FF", padding: "8px 14px", maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={row.worst_fn || ""}>
                                    {row.worst_fn || "—"}
                                </td>
                                <td style={{ padding: "8px 14px" }}>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                                        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "13px", color: "rgba(10,10,26,0.65)" }}>{row.coupling_score ?? 0}</span>
                                        <div style={{ width: 50, height: 3, background: 'rgba(20,0,255,0.06)', border: '1px solid rgba(20,0,255,0.08)', position: 'relative' }}>
                                            <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${((row.coupling_score ?? 0) / maxCoupling) * 100}%`, background: 'rgba(20,0,255,0.40)' }} />
                                        </div>
                                    </div>
                                </td>
                                <td style={{ padding: "8px 14px" }}>
                                    {row.parse_failed && <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9px", fontWeight: 500, color: "#FF3B3B", marginRight: 8 }}>⚠ PARSE ERROR</span>}
                                    {row.in_circular_dependency && <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9px", fontWeight: 500, color: "rgba(20,0,255,0.70)", marginRight: 8 }}>↻ CYCLE</span>}
                                </td>
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

    const complexityData = result.complexity_report_json ? JSON.parse(result.complexity_report_json) : {};
    const graphInDegree = result.graph_data?.in_degree || {};

    const panels = [
        { key: "complexity", label: "complexity_report.json", count: `${Object.keys(complexityData).length} FILES`, content: result.complexity_report_json || "{}" },
        { key: "graph", label: "dependency_graph.json", count: `${Object.keys(graphInDegree).length} FILES TRACKED`, content: JSON.stringify(result.graph_data || {}, null, 2) },
        { key: "explanations", label: "explanations.json", count: `${Object.keys(result.explanations || {}).length} FILES EXPLAINED`, content: JSON.stringify(result.explanations || {}, null, 2) },
        { key: "symbol_tables", label: "symbol_tables.json", count: `${Object.keys(result.symbol_tables || {}).length} FILES`, content: JSON.stringify(result.symbol_tables || {}, null, 2) },
    ];

    return (
        <div style={{ padding: "28px 40px", display: "flex", flexDirection: "column", gap: "12px", background: "#F0F0FF" }}>
            {panels.map(p => (
                <div key={p.key} style={{ border: "1px solid rgba(20,0,255,0.15)", background: "#FFFFFF", marginBottom: "12px" }}>
                    <div onClick={() => toggle(p.key)} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 20px", cursor: "pointer", background: open[p.key] ? "rgba(20,0,255,0.04)" : "transparent" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", fontWeight: 500, color: "#0A0A1A", textTransform: "uppercase", letterSpacing: "0.10em" }}>{p.label}</span>
                            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", fontWeight: 400, color: "rgba(10,10,26,0.40)" }}>{p.count}</span>
                        </div>
                        <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                            <CopyButton text={p.content} />
                            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "rgba(10,10,26,0.40)", transform: open[p.key] ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 200ms ease" }}>▾</span>
                        </div>
                    </div>
                    {open[p.key] && (
                        <div style={{ borderTop: "1px solid rgba(20,0,255,0.15)", padding: "20px", maxHeight: "320px", overflowY: "auto", background: "rgba(20,0,255,0.03)" }}>
                            <pre style={{ margin: 0, fontFamily: "'IBM Plex Mono', monospace", fontSize: "12px", color: "#0A0A1A", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                                {p.content}
                            </pre>
                        </div>
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
            .then(data => {
                const res = data.result || data;
                if (res.onboarding_doc && !res.final_doc) {
                    res.final_doc = res.onboarding_doc;
                }
                setResult(res);
                setLoading(false);
            })
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
    const riskCounts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, UNKNOWN: 0 };
    Object.values(complexityData).forEach((cs: any) => {
        const r = cs.risk_level as keyof typeof riskCounts;
        if (r in riskCounts) riskCounts[r]++;
    });

    const totalFiles = result.files_analyzed || 0;
    const totalFunctions = Object.values(complexityData).reduce((acc, cs: any) => acc + (cs.num_functions || 0), 0);
    const totalClasses = result.symbol_tables ? Object.values(result.symbol_tables).reduce((acc, st: any) => acc + (st.classes?.length || 0), 0) : 0;
    const importEdges = result.graph_data?.edges?.length || 0;
    const explainedCount = result.explanations ? Object.keys(result.explanations).length : 0;
    const circularCycles = result.graph_data?.circular_deps?.length || 0;

    return (
        <div style={{ minHeight: "100vh", background: "#1400FF", display: "flex", flexDirection: "column" }}>

            {/* Results header */}
            <div style={{ padding: '32px 96px', borderBottom: '1px solid rgba(255,255,255,0.15)', flexShrink: 0, boxSizing: 'border-box', minHeight: 120, background: '#1400FF', display: 'flex', flexDirection: 'column', gap: 12 }}>
                {/* Row 1: Repo + Branch */}
                <div style={{ display: 'flex', alignItems: 'baseline' }}>
                    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 500, letterSpacing: '0.10em', color: '#FFFFFF' }}>{repoName.toUpperCase()}</span>
                    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 400, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.50)', marginLeft: 16 }}>ON MAIN</span>
                </div>
                {/* Row 2: Stats */}
                <div style={{ display: 'flex', gap: 32, alignItems: 'center' }}>
                    {[
                        { n: totalFiles, l: 'FILES' },
                        { n: totalFunctions, l: 'FUNCTIONS' },
                        { n: totalClasses, l: 'CLASSES' },
                        { n: importEdges, l: 'IMPORT EDGES' },
                        { n: explainedCount, l: 'EXPLAINED' },
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
                        const count = riskCounts[level] ?? 0;
                        return <RiskBadge key={level} level={level} count={count} />;
                    })}
                </div>
                {/* Row 4: Circular Dep Warning */}
                {circularCycles > 0 && (
                    <div>
                        <span style={{ display: 'inline-block', fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', color: '#FFFFFF', background: 'rgba(255,255,255,0.10)', border: '1px solid rgba(255,255,255,0.30)', padding: '6px 12px', marginTop: 12 }}>
                            ⚠ {circularCycles} CIRCULAR DEPENDENCY {circularCycles === 1 ? 'CYCLE' : 'CYCLES'} DETECTED
                        </span>
                    </div>
                )}
            </div>

            {/* Tab bar */}
            <div style={{ height: 52, background: '#0F00CC', borderBottom: '1px solid rgba(255,255,255,0.15)', padding: '0 96px', display: 'flex', alignItems: 'stretch', flexShrink: 0, position: 'relative' }}>
                {TABS.map((tab, idx) => {
                    const isActive = tab === activeTab;
                    const nextActive = idx < TABS.length - 1 && TABS[idx + 1] === activeTab;
                    const showSep = idx < TABS.length - 1 && !isActive && !nextActive;
                    return (
                        <div key={tab} style={{ display: 'flex', alignItems: 'stretch' }}>
                            <button
                                onClick={() => setActiveTab(tab)}
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
                                    borderBottom: isActive ? "2px solid #FFFFFF" : "none",
                                }}
                            >
                                {tab}
                            </button>
                            {showSep && <div style={{ width: 1, background: 'rgba(255,255,255,0.15)', alignSelf: 'stretch', margin: '12px 0' }} />}
                        </div>
                    );
                })}
            </div>

            {/* Tab content */}
            <div className="auto-scroll" style={{ background: '#F0F0FF', padding: '48px 96px', flex: 1, overflowY: 'auto', minHeight: 'calc(100vh - 72px - 120px - 52px - 64px)', paddingBottom: '80px' }}>
                {activeTab === "ONBOARDING DOC" && (
                    result.final_doc
                        ? <MarkdownPane content={result.final_doc} />
                        : <div style={{ padding: "40px", fontFamily: "'IBM Plex Mono', monospace", color: "rgba(10,10,26,0.40)", fontSize: "13px" }}>onboarding.md not available.</div>
                )}
                {activeTab === "FILE EXPLANATIONS" && (
                    result.file_explanations_md
                        ? <MarkdownPane content={result.file_explanations_md} />
                        : <div style={{ padding: "40px", fontFamily: "'IBM Plex Mono', monospace", color: "rgba(10,10,26,0.40)", fontSize: "13px" }}>file_explanations.md not available.</div>
                )}
                {activeTab === "AGENT CONTEXT" && (
                    <AgentContextPane content={result.agent_context_md} />
                )}
                {activeTab === "DEPENDENCY GRAPH" && <DependencyGraphPane result={result} riskDist={riskCounts} />}
                {activeTab === "COMPLEXITY REPORT" && <ComplexityReportPane result={result} riskDist={riskCounts} />}
                {activeTab === "RAW OUTPUT" && <RawOutputPane result={result} />}
            </div>

            {/* Sticky download bar */}
            <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, height: 64, background: "#1400FF", borderTop: "1px solid rgba(255,255,255,0.20)", padding: "0 96px", display: "flex", gap: "16px", alignItems: "center", zIndex: 100 }}>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", color: "rgba(255,255,255,0.45)", letterSpacing: "0.16em" }}>DOWNLOAD OUTPUTS</span>
                <div style={{ display: 'flex', gap: 12, marginLeft: 24 }}>
                    {result.final_doc && (
                        <button onClick={() => downloadOnboarding(result.final_doc!, repoName)} style={downloadBtnStyle}>↓ ONBOARDING.MD</button>
                    )}
                    {result.file_explanations_md && (
                        <button onClick={() => downloadFileExplanations(result.file_explanations_md!, repoName)} style={downloadBtnStyle}>↓ FILE_EXPLANATIONS.MD</button>
                    )}
                    {result.agent_context_md && (
                        <button onClick={() => downloadAgentContext(result.agent_context_md!, repoName)} style={downloadBtnStyle}>↓ AGENT_CONTEXT.MD</button>
                    )}
                    {result.complexity_report_json && (
                        <button onClick={() => downloadComplexityReport(result.complexity_report_json!, repoName)} style={downloadBtnStyle}>↓ COMPLEXITY_REPORT.JSON</button>
                    )}
                    {result.graph_data && (
                        <button onClick={() => downloadDependencyGraph(result.graph_data!, repoName)} style={downloadBtnStyle}>↓ DEPENDENCY_GRAPH.JSON</button>
                    )}
                </div>
            </div>
        </div>
    );
}