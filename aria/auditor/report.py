"""
REPORT — Audit Report Generator
=================================
Generates human-readable Markdown and machine-readable JSON reports.
"""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from .analyzer import WorkspaceAnalysis

@dataclass
class AuditReport:
    analysis: WorkspaceAnalysis
    generated_at: str = ""
    markdown: str = ""
    json_data: dict = field(default_factory=dict)

class ReportGenerator:
    def __init__(self, analysis: WorkspaceAnalysis):
        self.analysis = analysis
        self._report: AuditReport | None = None

    def generate(self) -> AuditReport:
        report = AuditReport(analysis=self.analysis, generated_at=datetime.now(timezone.utc).isoformat())
        report.json_data = self.analysis.to_dict()
        report.json_data["generated_at"] = report.generated_at
        report.markdown = self._render_markdown()
        self._report = report
        return report

    def save(self, output_dir: str) -> tuple[str, str]:
        if not self._report: self.generate()
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        jp = os.path.join(output_dir, f"{ts}.json")
        mp = os.path.join(output_dir, f"{ts}.md")
        with open(jp, "w") as f: json.dump(self._report.json_data, f, indent=2, default=str)
        with open(mp, "w") as f: f.write(self._report.markdown)
        return jp, mp

    def _render_markdown(self) -> str:
        a = self.analysis; lines = []
        lines.append(f"# 🔍 Workspace Audit Report\n")
        lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"**Workspace:** `{a.workspace_root}`\n")
        lines.append(f"## Executive Summary\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Projects | {a.total_projects} |")
        lines.append(f"| Total LOC | {a.total_lines:,} |")
        lines.append(f"| Total Files | {a.total_files:,} |")
        lines.append(f"| Health Score | {a.health_score}/100 |")
        grade = "🟢" if a.health_score >= 70 else "🟡" if a.health_score >= 50 else "🔴"
        lines.append(f"| Overall Grade | {grade} |")
        if a.type_summary:
            lines.append(f"\n**Project Types:** {', '.join(f'{t} ({c})' for t,c in sorted(a.type_summary.items(), key=lambda x:-x[1]))}")
        if a.language_summary:
            top = sorted(a.language_summary.items(), key=lambda x:-x[1])[:8]
            lines.append(f"**Top Languages:** {', '.join(f'`{e}` ({l:,} lines)' for e,l in top)}\n")
        lines.append(f"## Projects\n")
        for pa in sorted(a.project_analyses, key=lambda x: -x.maturity.total):
            p = pa.project; m = pa.maturity
            icon = {"A":"🟢","B":"🔵","C":"🟡","D":"🟠","F":"🔴"}.get(m.grade,"⚪")
            lines.append(f"### {icon} {p.name} — Grade {m.grade} ({m.total}/100)")
            lines.append(f"- **Type:** {p.project_type} | **Language:** {p.language} | **LOC:** {p.total_lines:,} | **Files:** {p.file_count}")
            lines.append(f"- **Path:** `{p.relative_path or p.path}`")
            if p.version: lines.append(f"- **Version:** {p.version}")
            if p.git.is_repo: lines.append(f"- **Git:** branch `{p.git.branch}`, {p.git.total_commits} commits, {p.git.uncommitted_files} uncommitted, stale {p.git.stale_days}d")
            if p.is_live: lines.append(f"- **🟢 LIVE** — {', '.join(p.live_processes[:3])}")
            if pa.gaps:
                lines.append(f"- **Gaps:** {', '.join(f'{g.severity}: {g.description}' for g in pa.gaps[:5])}")
            if pa.risks:
                lines.append(f"- **Risks:** {', '.join(f'{r.severity}: {r.description}' for r in pa.risks[:3])}")
            lines.append("")
        if a.global_risks:
            lines.append(f"## ⚠️ Global Risks\n")
            for r in a.global_risks:
                lines.append(f"- **[{r.severity.upper()}]** {r.description} — *{r.mitigation}*")
            lines.append("")
        if a.exec_recommendations:
            lines.append(f"## 👔 Executive Recommendations\n")
            for e in a.exec_recommendations:
                lines.append(f"### {e.role} ({e.domain}) — {e.priority}")
                lines.append(f"{e.justification}\n")
                for t in e.suggested_tasks: lines.append(f"- {t}")
                lines.append("")
        if a.poa_recommendations:
            lines.append(f"## 🤖 POA Recommendations\n")
            for p in a.poa_recommendations:
                lines.append(f"- **{p.product_name}** [{p.priority}] — {p.justification}")
                for c in p.suggested_checks[:4]: lines.append(f"  - {c}")
            lines.append("")
        if a.dependency_map:
            lines.append(f"## 🔗 Dependency Map\n")
            for d in a.dependency_map: lines.append(f"- `{d.source}` → `{d.target}` ({d.dep_type})")
            lines.append("")
        lines.append("---\n*Generated by Singularity Workspace Auditor*")
        return "\n".join(lines)
