/**
 * Download utility functions for Project Gnosis artefacts.
 * All functions trigger a browser file download using a temporary <a> element.
 */

function triggerDownload(content: string, filename: string, mimeType: string): void {
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