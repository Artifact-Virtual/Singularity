"""
ANALYZER — Workspace Intelligence Analysis Engine
===================================================

Takes raw ProjectInfo from the scanner and produces:
- Maturity scores (0-100) per project
- Gap detection (what's missing for production-readiness)
- Dependency mapping between projects
- Risk assessment (stale repos, exposed secrets, uncommitted work)
- Executive recommendations (which C-Suite roles are needed)
- POA recommendations (which live products need a Product Owner Agent)

Industry-agnostic. Works on any workspace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# Import from sibling
from .scanner import ProjectInfo


@dataclass
class MaturityScore:
    """Maturity assessment for a single project."""
    total: int = 0              # 0-100
    has_tests: int = 0          # 0-15
    has_docs: int = 0           # 0-10
    has_ci: int = 0             # 0-15
    has_deployment: int = 0     # 0-10
    has_license: int = 0        # 0-5
    has_readme: int = 0         # 0-5
    code_volume: int = 0        # 0-10
    git_health: int = 0         # 0-15
    is_live: int = 0            # 0-10
    security: int = 0           # 0-5
    breakdown: dict[str, int] = field(default_factory=dict)
    grade: str = "F"            # A/B/C/D/F


@dataclass
class Gap:
    """A detected gap in a project."""
    category: str       # testing, docs, ci, security, deployment, quality
    severity: str       # critical, high, medium, low
    description: str
    recommendation: str


@dataclass
class Risk:
    """A detected risk."""
    category: str       # stale, secrets, uncommitted, no-backup, no-tests
    severity: str       # critical, high, medium, low
    project: str
    description: str
    mitigation: str


@dataclass
class DependencyEdge:
    """A dependency relationship between projects."""
    source: str         # project that depends
    target: str         # project being depended on
    dep_type: str       # direct, dev, inferred


@dataclass
class ExecRecommendation:
    """Recommendation for a C-Suite executive role."""
    role: str           # CTO, COO, CFO, CISO, CMO
    domain: str         # technology, operations, finance, security, marketing
    justification: str
    priority: str       # critical, high, medium, low
    suggested_tasks: list[str] = field(default_factory=list)


@dataclass
class POARecommendation:
    """Recommendation for a Product Owner Agent."""
    product_name: str
    project_path: str
    justification: str
    priority: str
    suggested_checks: list[str] = field(default_factory=list)


@dataclass
class ProjectAnalysis:
    """Complete analysis of a single project."""
    project: ProjectInfo
    maturity: MaturityScore = field(default_factory=MaturityScore)
    gaps: list[Gap] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)


@dataclass
class WorkspaceAnalysis:
    """Complete analysis of the entire workspace."""
    workspace_root: str
    total_projects: int = 0
    total_lines: int = 0
    total_files: int = 0
    health_score: int = 0           # 0-100 average maturity
    project_analyses: list[ProjectAnalysis] = field(default_factory=list)
    dependency_map: list[DependencyEdge] = field(default_factory=list)
    global_risks: list[Risk] = field(default_factory=list)
    exec_recommendations: list[ExecRecommendation] = field(default_factory=list)
    poa_recommendations: list[POARecommendation] = field(default_factory=list)
    language_summary: dict[str, int] = field(default_factory=dict)
    type_summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "workspace_root": self.workspace_root,
            "total_projects": self.total_projects,
            "total_lines": self.total_lines,
            "total_files": self.total_files,
            "health_score": self.health_score,
            "language_summary": self.language_summary,
            "type_summary": self.type_summary,
            "projects": [
                {
                    "project": pa.project.to_dict(),
                    "maturity": {
                        "total": pa.maturity.total,
                        "grade": pa.maturity.grade,
                        "breakdown": pa.maturity.breakdown,
                    },
                    "gaps": [{"category": g.category, "severity": g.severity,
                              "description": g.description, "recommendation": g.recommendation}
                             for g in pa.gaps],
                    "risks": [{"category": r.category, "severity": r.severity,
                               "description": r.description, "mitigation": r.mitigation}
                              for r in pa.risks],
                }
                for pa in self.project_analyses
            ],
            "dependency_map": [
                {"source": d.source, "target": d.target, "type": d.dep_type}
                for d in self.dependency_map
            ],
            "global_risks": [
                {"category": r.category, "severity": r.severity, "project": r.project,
                 "description": r.description, "mitigation": r.mitigation}
                for r in self.global_risks
            ],
            "exec_recommendations": [
                {"role": e.role, "domain": e.domain, "justification": e.justification,
                 "priority": e.priority, "suggested_tasks": e.suggested_tasks}
                for e in self.exec_recommendations
            ],
            "poa_recommendations": [
                {"product_name": p.product_name, "project_path": p.project_path,
                 "justification": p.justification, "priority": p.priority,
                 "suggested_checks": p.suggested_checks}
                for p in self.poa_recommendations
            ],
        }


class WorkspaceAnalyzer:
    """
    Analyzes scanned projects to produce maturity scores, gaps,
    risks, and recommendations.
    
    Usage:
        analyzer = WorkspaceAnalyzer(projects)
        analysis = analyzer.analyze()
    """
    
    def __init__(self, projects: list[ProjectInfo], workspace_root: str = ""):
        self.projects = projects
        self.workspace_root = workspace_root
        self._project_names = {p.name.lower() for p in projects}
    
    def analyze(self) -> WorkspaceAnalysis:
        """Run full analysis pipeline."""
        analysis = WorkspaceAnalysis(workspace_root=self.workspace_root)
        analysis.total_projects = len(self.projects)
        
        # Per-project analysis
        maturity_sum = 0
        for project in self.projects:
            pa = ProjectAnalysis(project=project)
            pa.maturity = self._score_maturity(project)
            pa.gaps = self._detect_gaps(project)
            pa.risks = self._detect_risks(project)
            analysis.project_analyses.append(pa)
            
            analysis.total_lines += project.total_lines
            analysis.total_files += project.file_count
            maturity_sum += pa.maturity.total
            
            # Aggregate language stats
            for ext, lines in project.language_breakdown.items():
                analysis.language_summary[ext] = analysis.language_summary.get(ext, 0) + lines
            
            # Type summary
            analysis.type_summary[project.project_type] = analysis.type_summary.get(project.project_type, 0) + 1
        
        # Health score = average maturity
        if analysis.total_projects > 0:
            analysis.health_score = maturity_sum // analysis.total_projects
        
        # Cross-project analysis
        analysis.dependency_map = self._map_dependencies()
        analysis.global_risks = self._assess_global_risks(analysis)
        analysis.exec_recommendations = self._recommend_executives(analysis)
        analysis.poa_recommendations = self._recommend_poas(analysis)
        
        return analysis
    
    def _score_maturity(self, p: ProjectInfo) -> MaturityScore:
        """Score project maturity on a 0-100 scale."""
        m = MaturityScore()
        
        # Tests (0-15)
        if p.files.has_tests:
            m.has_tests = 15
        m.breakdown["tests"] = m.has_tests
        
        # Documentation (0-10)
        if p.files.has_readme:
            m.has_docs += 5
        if p.files.has_docs:
            m.has_docs += 5
        m.has_readme = 5 if p.files.has_readme else 0
        m.breakdown["docs"] = m.has_docs
        m.breakdown["readme"] = m.has_readme
        
        # CI/CD (0-15)
        if p.cicd.github_actions or p.cicd.gitlab_ci or p.cicd.jenkins:
            m.has_ci += 10
        if p.cicd.docker or p.cicd.docker_compose:
            m.has_ci += 5
        m.has_ci = min(m.has_ci, 15)
        m.breakdown["ci"] = m.has_ci
        
        # Deployment (0-10)
        if p.cicd.docker or p.cicd.docker_compose:
            m.has_deployment += 5
        if p.is_live:
            m.has_deployment += 5
        m.has_deployment = min(m.has_deployment, 10)
        m.breakdown["deployment"] = m.has_deployment
        
        # License (0-5)
        m.has_license = 5 if p.files.has_license else 0
        m.breakdown["license"] = m.has_license
        
        # Code volume (0-10) - reward substantial projects
        if p.total_lines > 5000:
            m.code_volume = 10
        elif p.total_lines > 1000:
            m.code_volume = 7
        elif p.total_lines > 200:
            m.code_volume = 4
        elif p.total_lines > 0:
            m.code_volume = 2
        m.breakdown["code_volume"] = m.code_volume
        
        # Git health (0-15)
        if p.git.is_repo:
            m.git_health += 5  # has git
            if p.git.remotes:
                m.git_health += 5  # has remote backup
            if p.git.uncommitted_files == 0 and p.git.untracked_files < 5:
                m.git_health += 3  # clean working tree
            if p.git.stale_days < 30:
                m.git_health += 2  # recently active
        m.git_health = min(m.git_health, 15)
        m.breakdown["git_health"] = m.git_health
        
        # Live status (0-10)
        m.is_live = 10 if p.is_live else 0
        m.breakdown["live"] = m.is_live
        
        # Security (0-5)
        if p.files.has_env_example and not p.files.has_env:
            m.security += 3  # env template without real env = good practice
        elif not p.files.has_env:
            m.security += 2  # no env at all = probably fine
        if p.files.has_security:
            m.security += 2
        m.security = min(m.security, 5)
        m.breakdown["security"] = m.security
        
        # Total
        m.total = (m.has_tests + m.has_docs + m.has_readme + m.has_ci + 
                   m.has_deployment + m.has_license + m.code_volume + 
                   m.git_health + m.is_live + m.security)
        m.total = min(m.total, 100)
        
        # Grade
        if m.total >= 85:
            m.grade = "A"
        elif m.total >= 70:
            m.grade = "B"
        elif m.total >= 55:
            m.grade = "C"
        elif m.total >= 40:
            m.grade = "D"
        else:
            m.grade = "F"
        
        return m
    
    def _detect_gaps(self, p: ProjectInfo) -> list[Gap]:
        """Detect what's missing for production-readiness."""
        gaps = []
        
        if not p.files.has_tests:
            gaps.append(Gap(
                category="testing", severity="critical",
                description=f"No test directory found in {p.name}",
                recommendation="Add a tests/ directory with unit tests. Aim for >60% coverage."
            ))
        
        if not p.files.has_readme:
            gaps.append(Gap(
                category="docs", severity="high",
                description=f"No README found in {p.name}",
                recommendation="Add README.md with project description, setup instructions, and usage examples."
            ))
        
        if not p.files.has_docs and p.total_lines > 1000:
            gaps.append(Gap(
                category="docs", severity="medium",
                description=f"No docs/ directory in {p.name} ({p.total_lines} LOC)",
                recommendation="Add docs/ with architecture overview, API reference, and contribution guidelines."
            ))
        
        if not (p.cicd.github_actions or p.cicd.gitlab_ci or p.cicd.jenkins):
            gaps.append(Gap(
                category="ci", severity="high",
                description=f"No CI/CD pipeline in {p.name}",
                recommendation="Add GitHub Actions or GitLab CI for automated testing and deployment."
            ))
        
        if not p.files.has_license and p.total_lines > 100:
            gaps.append(Gap(
                category="quality", severity="medium",
                description=f"No LICENSE file in {p.name}",
                recommendation="Add a LICENSE file (MIT, Apache-2.0, or proprietary)."
            ))
        
        if p.files.has_env and not p.files.has_env_example:
            gaps.append(Gap(
                category="security", severity="high",
                description=f".env exists without .env.example in {p.name}",
                recommendation="Add .env.example with placeholder values. Ensure .env is in .gitignore."
            ))
        
        if not p.cicd.docker and p.total_lines > 500 and p.is_live:
            gaps.append(Gap(
                category="deployment", severity="medium",
                description=f"No Dockerfile for live service {p.name}",
                recommendation="Add Dockerfile for reproducible deployments."
            ))
        
        if p.git.is_repo and not p.git.remotes:
            gaps.append(Gap(
                category="quality", severity="high",
                description=f"Git repo {p.name} has no remote — no backup",
                recommendation="Add a remote (GitHub, GitLab) for backup and collaboration."
            ))
        
        if not p.files.has_changelog and p.total_lines > 2000:
            gaps.append(Gap(
                category="docs", severity="low",
                description=f"No CHANGELOG in {p.name}",
                recommendation="Add CHANGELOG.md to track version history."
            ))
        
        return gaps
    
    def _detect_risks(self, p: ProjectInfo) -> list[Risk]:
        """Detect risks for a project."""
        risks = []
        
        # Stale repo
        if p.git.is_repo and p.git.stale_days > 90:
            risks.append(Risk(
                category="stale", severity="medium",
                project=p.name,
                description=f"Last commit {p.git.stale_days} days ago",
                mitigation="Review if project is still active. Archive or update."
            ))
        
        # Large uncommitted changes
        if p.git.uncommitted_files > 10:
            risks.append(Risk(
                category="uncommitted", severity="high",
                project=p.name,
                description=f"{p.git.uncommitted_files} uncommitted files",
                mitigation="Commit or stash changes. Large uncommitted diffs risk data loss."
            ))
        
        # Exposed .env without .gitignore protection
        if p.files.has_env:
            gitignore_path = os.path.join(p.path, ".gitignore")
            env_ignored = False
            if os.path.isfile(gitignore_path):
                try:
                    content = open(gitignore_path).read()
                    env_ignored = ".env" in content
                except Exception:
                    pass
            if not env_ignored and p.git.is_repo:
                risks.append(Risk(
                    category="secrets", severity="critical",
                    project=p.name,
                    description=".env file exists and may not be gitignored",
                    mitigation="Add .env to .gitignore immediately. Rotate any exposed credentials."
                ))
        
        # No tests on live service
        if p.is_live and not p.files.has_tests:
            risks.append(Risk(
                category="no-tests", severity="critical",
                project=p.name,
                description=f"Live service {p.name} has no tests",
                mitigation="Add tests before the next deployment. Prioritize integration tests."
            ))
        
        # Unpushed commits
        if p.git.has_unpushed:
            risks.append(Risk(
                category="uncommitted", severity="medium",
                project=p.name,
                description="Has unpushed commits — remote is behind",
                mitigation="Push to remote to ensure backup."
            ))
        
        return risks
    
    def _map_dependencies(self) -> list[DependencyEdge]:
        """Map inter-project dependencies."""
        edges = []
        name_to_project = {p.name.lower(): p for p in self.projects}
        
        for project in self.projects:
            # Check if any dependency name matches another project in the workspace
            all_deps = project.dependencies + project.dev_dependencies
            for dep in all_deps:
                dep_lower = dep.lower().replace("-", "_").replace(".", "_")
                for other_name, other_proj in name_to_project.items():
                    other_normalized = other_name.replace("-", "_").replace(".", "_")
                    if dep_lower == other_normalized and other_proj.path != project.path:
                        dep_type = "dev" if dep in project.dev_dependencies else "direct"
                        edges.append(DependencyEdge(
                            source=project.name,
                            target=other_proj.name,
                            dep_type=dep_type,
                        ))
        
        return edges
    
    def _assess_global_risks(self, analysis: WorkspaceAnalysis) -> list[Risk]:
        """Assess workspace-wide risks."""
        risks = []
        
        # Count projects without any version control
        no_git = [pa.project.name for pa in analysis.project_analyses 
                  if not pa.project.git.is_repo and pa.project.total_lines > 100]
        if no_git:
            risks.append(Risk(
                category="no-backup", severity="critical",
                project=", ".join(no_git[:5]),
                description=f"{len(no_git)} project(s) have no version control",
                mitigation="Initialize git and push to a remote for all substantive projects."
            ))
        
        # Count critical-severity gaps
        critical_count = sum(
            1 for pa in analysis.project_analyses
            for g in pa.gaps if g.severity == "critical"
        )
        if critical_count > 3:
            risks.append(Risk(
                category="quality", severity="high",
                project="workspace",
                description=f"{critical_count} critical gaps across workspace",
                mitigation="Prioritize critical gaps: tests for live services, secrets exposure."
            ))
        
        # Single point of failure: only one language
        if len(analysis.type_summary) == 1 and analysis.total_projects > 3:
            lang = list(analysis.type_summary.keys())[0]
            risks.append(Risk(
                category="concentration", severity="low",
                project="workspace",
                description=f"All {analysis.total_projects} projects use {lang} — technology concentration risk",
                mitigation="Consider if this is intentional. Diversification reduces ecosystem-level risk."
            ))
        
        return risks
    
    def _recommend_executives(self, analysis: WorkspaceAnalysis) -> list[ExecRecommendation]:
        """Recommend C-Suite executive roles based on workspace needs."""
        recs = []
        
        # CTO — always needed if there are >3 projects
        if analysis.total_projects > 3:
            recs.append(ExecRecommendation(
                role="CTO", domain="technology",
                justification=f"{analysis.total_projects} projects with {analysis.total_lines:,} total LOC need technical oversight",
                priority="critical",
                suggested_tasks=[
                    "Standardize CI/CD pipelines across all projects",
                    "Establish code review and testing standards",
                    "Create architecture decision records (ADRs)",
                    "Manage technical debt and dependency updates",
                ]
            ))
        
        # CISO — if any secrets risk or live services
        has_secrets_risk = any(
            r.category == "secrets" 
            for pa in analysis.project_analyses for r in pa.risks
        )
        has_live = any(pa.project.is_live for pa in analysis.project_analyses)
        if has_secrets_risk or has_live:
            recs.append(ExecRecommendation(
                role="CISO", domain="security",
                justification="Live services and/or exposed secrets detected — security oversight required",
                priority="critical" if has_secrets_risk else "high",
                suggested_tasks=[
                    "Audit all .env files and secrets management",
                    "Implement secrets rotation policy",
                    "Security review of all live services",
                    "Establish incident response procedure",
                ]
            ))
        
        # COO — if there are deployment gaps or operational needs
        deployment_gaps = sum(
            1 for pa in analysis.project_analyses
            for g in pa.gaps if g.category == "deployment"
        )
        if deployment_gaps > 0 or analysis.total_projects > 5:
            recs.append(ExecRecommendation(
                role="COO", domain="operations",
                justification=f"{deployment_gaps} deployment gaps and {analysis.total_projects} projects need operational coordination",
                priority="high",
                suggested_tasks=[
                    "Create deployment runbooks for each live service",
                    "Establish monitoring and alerting",
                    "Define SLAs and uptime targets",
                    "Coordinate cross-project releases",
                ]
            ))
        
        # CFO — if there are paid services or monetization potential
        has_payment = any(
            "stripe" in str(p.dependencies).lower() or 
            "paddle" in str(p.dependencies).lower() or
            "paypal" in str(p.dependencies).lower()
            for p in self.projects
        )
        if has_payment or analysis.total_projects > 5:
            recs.append(ExecRecommendation(
                role="CFO", domain="finance",
                justification="Payment integrations detected or sufficient scale for financial oversight",
                priority="high" if has_payment else "medium",
                suggested_tasks=[
                    "Track infrastructure costs across all projects",
                    "Revenue modeling for monetizable products",
                    "Budget allocation for development priorities",
                    "Financial reporting and runway tracking",
                ]
            ))
        
        # CMO — if there are public-facing products
        public_facing = sum(1 for p in self.projects if p.is_live)
        if public_facing > 0:
            recs.append(ExecRecommendation(
                role="CMO", domain="marketing",
                justification=f"{public_facing} live public-facing product(s) need marketing strategy",
                priority="medium",
                suggested_tasks=[
                    "Create landing pages for each product",
                    "Establish social media presence",
                    "Content marketing strategy (blog, docs, demos)",
                    "User acquisition and growth metrics",
                ]
            ))
        
        return recs
    
    def _recommend_poas(self, analysis: WorkspaceAnalysis) -> list[POARecommendation]:
        """Recommend Product Owner Agents for live products."""
        recs = []
        
        for pa in analysis.project_analyses:
            p = pa.project
            
            # POA needed for: live services, published packages, public APIs
            needs_poa = (
                p.is_live or 
                p.version and p.total_lines > 500 or
                any("api" in ep.lower() or "server" in ep.lower() for ep in p.entry_points)
            )
            
            if not needs_poa:
                continue
            
            checks = [
                "Health check: verify all endpoints respond",
                "SSL certificate expiry monitoring",
                "Error rate monitoring from logs",
                "Dependency update scanning",
            ]
            
            if p.files.has_env:
                checks.append("Secrets rotation reminder")
            if p.is_live:
                checks.append("Uptime monitoring (ping every 5 min)")
                checks.append("Performance regression detection")
            if p.version:
                checks.append("Version bump reminder on significant changes")
            
            recs.append(POARecommendation(
                product_name=p.name,
                project_path=p.relative_path or p.path,
                justification=f"{'Live service' if p.is_live else 'Published package'} with {p.total_lines:,} LOC needs ongoing ownership",
                priority="critical" if p.is_live else "high",
                suggested_checks=checks,
            ))
        
        return recs
