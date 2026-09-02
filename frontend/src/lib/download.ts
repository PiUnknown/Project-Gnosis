import posthog from "posthog-js";

function triggerDownload(content: string, filename: string, mimeType: string): void {
    posthog.capture('report_downloaded', {
        filename,
        file_type: filename.endsWith('.md') ? 'markdown' : (filename.endsWith('.json') ? 'json' : 'other'),
    });
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

export function downloadOnboarding(content: string, repoName?: string): void {
    const filename = repoName ? `${repoName}-onboarding.md` : "onboarding.md";
    triggerDownload(content, filename, "text/markdown;charset=utf-8");
}

export function downloadAgentContext(content: string, repoName?: string): void {
    const filename = repoName ? `${repoName}-agent_context.md` : "agent_context.md";
    triggerDownload(content, filename, "text/markdown;charset=utf-8");
}

export function downloadComplexityReport(content: string, repoName?: string): void {
    const filename = repoName ? `${repoName}-complexity_report.json` : "complexity_report.json";
    triggerDownload(content, filename, "application/json;charset=utf-8");
}

export function downloadDependencyGraph(graphData: object, repoName?: string): void {
    const filename = repoName ? `${repoName}-dependency_graph.json` : "dependency_graph.json";
    const content = JSON.stringify(graphData, null, 2);
    triggerDownload(content, filename, "application/json;charset=utf-8");
}

export function downloadFileExplanations(content: string, repoName?: string): void {
    const filename = repoName ? `${repoName}-file_explanations.md` : "file_explanations.md";
    triggerDownload(content, filename, "text/markdown;charset=utf-8");
}