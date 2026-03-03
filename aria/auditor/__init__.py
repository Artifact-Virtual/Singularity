"""
AUDITOR — Workspace Scanner & Analyzer
==========================================

First-boot capability: scan workspace, assess maturity,
recommend executives and POAs.

Usage:
    from aria.auditor import WorkspaceScanner, scan_workspace

    scanner = WorkspaceScanner("/path/to/workspace")
    result = scanner.scan()  # Returns ScanResult

    from aria.auditor import WorkspaceAnalyzer
    analysis = WorkspaceAnalyzer().analyze(result)
"""

from .scanner import (
    WorkspaceScanner, 
    ScanResult, 
    ProjectInfo, 
    InfraInfo,
    GitInfo,
    CICDInfo,
    ProjectFiles,
    scan_workspace,
)
from .analyzer import (
    WorkspaceAnalyzer,
    WorkspaceAnalysis,
    ProjectAnalysis,
    MaturityScore,
    Gap,
    Risk,
    ExecRecommendation,
    POARecommendation,
)
from .report import AuditReport, ReportGenerator

class _AnalyzerWrapper:
    """Wrapper to provide Analyzer()/analyze(scan) interface."""
    def analyze(self, scan: ScanResult) -> WorkspaceAnalysis:
        analyzer = WorkspaceAnalyzer(scan.projects, scan.workspace)
        return analyzer.analyze()

# Aliases for compatibility
Analyzer = _AnalyzerWrapper
AnalysisResult = WorkspaceAnalysis
ProjectAssessment = ProjectAnalysis


def generate_report(scan: ScanResult, analysis: WorkspaceAnalysis) -> dict:
    """Generate a complete audit report dict."""
    gen = ReportGenerator(analysis)
    report = gen.generate()
    d = report.json_data
    # Add compatibility keys
    if "summary" not in d:
        d["summary"] = {
            "overall_health": analysis.health_score,
            "total_projects": analysis.total_projects,
            "total_loc": analysis.total_lines,
            "total_files": analysis.total_files,
            "env_files": len(scan.env_files),
        }
    if "meta" not in d:
        d["meta"] = {
            "workspace": scan.workspace,
            "timestamp": report.generated_at,
            "scan_duration_ms": scan.scan_duration_ms,
        }
    return d


def report_to_markdown(report_dict: dict) -> str:
    """Convert report dict to markdown. Best-effort reconstruction."""
    lines = []
    lines.append("# Workspace Audit Report\n")
    
    meta = report_dict.get("meta", {})
    summary = report_dict.get("summary", {})
    
    if meta:
        lines.append(f"**Workspace:** {meta.get('workspace', 'unknown')}")
        lines.append(f"**Time:** {meta.get('timestamp', '')}")
    
    health = summary.get("overall_health", report_dict.get("health_score", 0))
    icon = "🟢" if health >= 70 else "🟡" if health >= 40 else "🔴"
    lines.append(f"\n## Summary")
    lines.append(f"- Health: {icon} **{health}/100**")
    lines.append(f"- Projects: **{summary.get('total_projects', report_dict.get('total_projects', '?'))}**")
    lines.append(f"- LOC: **{summary.get('total_loc', report_dict.get('total_lines', '?')):,}**")
    
    return "\n".join(lines)


def save_report(report_dict: dict, output_dir) -> tuple:
    """Save report as JSON + Markdown."""
    from pathlib import Path
    import json
    from datetime import datetime, timezone

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")

    json_path = output_dir / f"{ts}.json"
    md_path = output_dir / f"{ts}.md"

    json_path.write_text(json.dumps(report_dict, indent=2))
    md_path.write_text(report_to_markdown(report_dict))

    (output_dir / "latest.json").write_text(json.dumps(report_dict, indent=2))
    (output_dir / "latest.md").write_text(report_to_markdown(report_dict))

    return json_path, md_path


__all__ = [
    "WorkspaceScanner", "ScanResult", "ProjectInfo", "InfraInfo",
    "GitInfo", "CICDInfo", "ProjectFiles", "scan_workspace",
    "WorkspaceAnalyzer", "WorkspaceAnalysis", "ProjectAnalysis",
    "Analyzer", "AnalysisResult", "ProjectAssessment",
    "MaturityScore", "Gap", "Risk",
    "ExecRecommendation", "POARecommendation",
    "AuditReport", "ReportGenerator",
    "generate_report", "report_to_markdown", "save_report",
]
