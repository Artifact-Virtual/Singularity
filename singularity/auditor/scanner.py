"""
SCANNER — Workspace Filesystem Intelligence
=============================================

Walks a workspace directory tree, detects projects, infrastructure,
CI/CD, git repos, live services, and counts lines of code.

Industry-agnostic. Works on any workspace structure.

No external dependencies — pure stdlib.
"""

from __future__ import annotations

import os
import re
import json
import subprocess
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone


# Directories always skipped during scanning
DEFAULT_SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    ".env", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", "target", ".next", ".nuxt", ".output",
    "vendor", "bower_components", ".gradle", ".idea", ".vscode",
    ".terraform", ".pulumi", "coverage", "htmlcov", ".eggs",
    "*.egg-info", ".cache", ".parcel-cache",
}

# File extensions to count as code
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".lua", ".r", ".jl", ".zig", ".nim",
    ".html", ".css", ".scss", ".less", ".vue", ".svelte",
    ".sql", ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".proto",
    ".tf", ".hcl", ".nix", ".dockerfile",
    ".gd", ".gdscript",  # Godot
}


import logging
logger = logging.getLogger("singularity.auditor.scanner")

@dataclass
class GitInfo:
    """Git repository status."""
    is_repo: bool = False
    branch: str = ""
    remotes: dict[str, str] = field(default_factory=dict)
    uncommitted_files: int = 0
    untracked_files: int = 0
    last_commit_date: str = ""
    last_commit_msg: str = ""
    total_commits: int = 0
    has_unpushed: bool = False
    stale_days: int = 0  # days since last commit


@dataclass
class CICDInfo:
    """CI/CD configuration detected."""
    github_actions: bool = False
    gitlab_ci: bool = False
    jenkins: bool = False
    docker: bool = False
    docker_compose: bool = False
    makefile: bool = False
    taskfile: bool = False
    workflows: list[str] = field(default_factory=list)


@dataclass
class ProjectFiles:
    """Common project files detected."""
    has_readme: bool = False
    has_license: bool = False
    has_tests: bool = False
    has_docs: bool = False
    has_env: bool = False
    has_env_example: bool = False
    has_changelog: bool = False
    has_contributing: bool = False
    has_security: bool = False
    test_dirs: list[str] = field(default_factory=list)
    doc_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)


@dataclass
class ProjectInfo:
    """Complete information about a detected project."""
    name: str
    path: str
    relative_path: str
    project_type: str  # python, node, rust, go, docker, generic
    language: str      # primary language
    
    # Code metrics
    total_lines: int = 0
    file_count: int = 0
    language_breakdown: dict[str, int] = field(default_factory=dict)
    
    # Structure
    files: ProjectFiles = field(default_factory=ProjectFiles)
    git: GitInfo = field(default_factory=GitInfo)
    cicd: CICDInfo = field(default_factory=CICDInfo)
    
    # Dependencies
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    
    # Metadata
    version: str = ""
    description: str = ""
    entry_points: list[str] = field(default_factory=list)
    
    # Live status
    is_live: bool = False
    live_ports: list[int] = field(default_factory=list)
    live_processes: list[str] = field(default_factory=list)
    
    # Timestamps
    scan_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "path": self.path,
            "relative_path": self.relative_path,
            "project_type": self.project_type,
            "language": self.language,
            "total_lines": self.total_lines,
            "file_count": self.file_count,
            "language_breakdown": self.language_breakdown,
            "files": {
                "has_readme": self.files.has_readme,
                "has_license": self.files.has_license,
                "has_tests": self.files.has_tests,
                "has_docs": self.files.has_docs,
                "has_env": self.files.has_env,
                "has_env_example": self.files.has_env_example,
                "has_changelog": self.files.has_changelog,
                "has_contributing": self.files.has_contributing,
                "has_security": self.files.has_security,
                "test_dirs": self.files.test_dirs,
                "doc_files": self.files.doc_files,
                "config_files": self.files.config_files,
            },
            "git": {
                "is_repo": self.git.is_repo,
                "branch": self.git.branch,
                "remotes": self.git.remotes,
                "uncommitted_files": self.git.uncommitted_files,
                "untracked_files": self.git.untracked_files,
                "last_commit_date": self.git.last_commit_date,
                "last_commit_msg": self.git.last_commit_msg,
                "total_commits": self.git.total_commits,
                "has_unpushed": self.git.has_unpushed,
                "stale_days": self.git.stale_days,
            },
            "cicd": {
                "github_actions": self.cicd.github_actions,
                "gitlab_ci": self.cicd.gitlab_ci,
                "jenkins": self.cicd.jenkins,
                "docker": self.cicd.docker,
                "docker_compose": self.cicd.docker_compose,
                "makefile": self.cicd.makefile,
                "workflows": self.cicd.workflows,
            },
            "dependencies": self.dependencies[:50],  # Cap for report size
            "dev_dependencies": self.dev_dependencies[:50],
            "version": self.version,
            "description": self.description,
            "entry_points": self.entry_points,
            "is_live": self.is_live,
            "live_ports": self.live_ports,
            "live_processes": self.live_processes,
            "scan_time": self.scan_time,
        }


class WorkspaceScanner:
    """
    Scans a workspace directory to discover and catalog all projects.
    
    Usage:
        scanner = WorkspaceScanner("/path/to/workspace")
        projects = scanner.scan()
    """
    
    # Project marker files → type mapping
    PROJECT_MARKERS = {
        "pyproject.toml": "python",
        "setup.py": "python",
        "setup.cfg": "python",
        "requirements.txt": "python",
        "Pipfile": "python",
        "package.json": "node",
        "Cargo.toml": "rust",
        "go.mod": "go",
        "Gemfile": "ruby",
        "pom.xml": "java",
        "build.gradle": "java",
        "build.gradle.kts": "kotlin",
        "mix.exs": "elixir",
        "pubspec.yaml": "dart",
        "CMakeLists.txt": "cpp",
        "Makefile": "generic",
        "project.godot": "godot",
    }
    
    # Priority order for type detection (first match wins)
    TYPE_PRIORITY = [
        "pyproject.toml", "Cargo.toml", "go.mod", "package.json",
        "setup.py", "pom.xml", "build.gradle", "mix.exs",
        "Gemfile", "pubspec.yaml", "CMakeLists.txt",
        "setup.cfg", "requirements.txt", "Pipfile",
        "project.godot", "Makefile",
    ]

    LANGUAGE_MAP = {
        "python": "Python", "node": "JavaScript/TypeScript",
        "rust": "Rust", "go": "Go", "ruby": "Ruby",
        "java": "Java", "kotlin": "Kotlin", "elixir": "Elixir",
        "dart": "Dart", "cpp": "C/C++", "godot": "GDScript",
        "generic": "Mixed", "docker": "Docker",
    }
    
    def __init__(self, root: str, skip_dirs: list[str] | None = None, max_depth: int = 6):
        self.root = os.path.abspath(root)
        self.skip_dirs = DEFAULT_SKIP_DIRS | set(skip_dirs or [])
        self.max_depth = max_depth
        self._projects: list[ProjectInfo] = []
        self._gitignore_patterns: list[str] = []
        self._listening_ports: set[int] = set()
        self._running_procs: dict[str, list[str]] = {}
    
    def scan(self) -> list[ProjectInfo]:
        """
        Execute full workspace scan.
        
        Returns list of ProjectInfo for every detected project.
        """
        # Pre-scan: gather system state
        self._scan_listening_ports()
        self._scan_running_processes()
        
        # Load root .gitignore
        gi = os.path.join(self.root, ".gitignore")
        if os.path.isfile(gi):
            self._gitignore_patterns = self._parse_gitignore(gi)
        
        # Walk and detect projects
        self._walk(self.root, depth=0)
        
        return self._projects
    
    def _should_skip(self, dirname: str, full_path: str) -> bool:
        """Check if a directory should be skipped."""
        if dirname in self.skip_dirs:
            return True
        if dirname.startswith(".") and dirname not in (".github", ".gitlab", ".circleci"):
            return True
        if dirname.endswith(".egg-info"):
            return True
        # Check gitignore patterns (simple matching)
        rel = os.path.relpath(full_path, self.root)
        for pat in self._gitignore_patterns:
            if pat.endswith("/") and rel.startswith(pat.rstrip("/")):
                return True
            if rel == pat or dirname == pat.rstrip("/"):
                return True
        return False
    
    def _walk(self, directory: str, depth: int) -> None:
        """Recursively walk directory tree looking for project roots."""
        if depth > self.max_depth:
            return
        
        try:
            entries = os.listdir(directory)
        except PermissionError:
            return
        
        # Check if this directory is a project root
        detected_type = self._detect_project_type(directory, entries)
        if detected_type:
            project = self._build_project_info(directory, detected_type, entries)
            self._projects.append(project)
            # Don't recurse into sub-projects deeper than 1 level
            # (monorepo support: still scan subdirs for nested projects)
        
        # Recurse into subdirectories
        for entry in sorted(entries):
            full = os.path.join(directory, entry)
            if os.path.isdir(full) and not os.path.islink(full):
                if not self._should_skip(entry, full):
                    self._walk(full, depth + 1)
    
    def _detect_project_type(self, directory: str, entries: list[str]) -> Optional[str]:
        """Detect project type from marker files. Returns type or None."""
        entry_set = set(entries)
        
        for marker in self.TYPE_PRIORITY:
            if marker in entry_set:
                return self.PROJECT_MARKERS[marker]
        
        # Check for Dockerfile separately (project AND infrastructure)
        if "Dockerfile" in entry_set or "dockerfile" in entry_set:
            return "docker"
        
        return None
    
    def _build_project_info(self, directory: str, ptype: str, entries: list[str]) -> ProjectInfo:
        """Build complete ProjectInfo for a detected project."""
        name = os.path.basename(directory)
        rel_path = os.path.relpath(directory, self.root)
        
        project = ProjectInfo(
            name=name,
            path=directory,
            relative_path=rel_path if rel_path != "." else "",
            project_type=ptype,
            language=self.LANGUAGE_MAP.get(ptype, "Unknown"),
        )
        
        entry_set = set(entries)
        
        # Detect common files
        project.files = self._detect_common_files(directory, entry_set)
        
        # Parse project metadata
        self._parse_metadata(project, directory, entry_set)
        
        # Git info
        project.git = self._detect_git(directory)
        
        # CI/CD
        project.cicd = self._detect_cicd(directory, entry_set)
        
        # Count lines of code
        loc, file_count, breakdown = self._count_loc(directory)
        project.total_lines = loc
        project.file_count = file_count
        project.language_breakdown = breakdown
        
        # Check live status
        self._check_live_status(project)
        
        return project
    
    def _detect_common_files(self, directory: str, entries: set[str]) -> ProjectFiles:
        """Check for common project files."""
        pf = ProjectFiles()
        
        # README variants
        pf.has_readme = any(
            e.lower().startswith("readme") for e in entries
        )
        
        # LICENSE variants
        pf.has_license = any(
            e.lower().startswith("license") or e.lower().startswith("licence")
            for e in entries
        )
        
        # Tests
        test_indicators = {"tests", "test", "spec", "specs", "__tests__"}
        found_tests = test_indicators & {e.lower() for e in entries}
        pf.has_tests = bool(found_tests) or any(
            e.startswith("test_") or e.endswith("_test.py") for e in entries
        )
        pf.test_dirs = list(found_tests)
        
        # Docs
        doc_indicators = {"docs", "doc", "documentation", "wiki"}
        found_docs = doc_indicators & {e.lower() for e in entries}
        pf.has_docs = bool(found_docs) or any(
            e.lower() in ("api.md", "architecture.md", "design.md") for e in entries
        )
        pf.doc_files = [e for e in entries if e.lower().endswith((".md", ".rst", ".txt")) and e.lower() not in ("readme.md", "license.md")]
        
        # Env
        pf.has_env = ".env" in entries
        pf.has_env_example = ".env.example" in entries or ".env.sample" in entries
        
        # Other
        pf.has_changelog = any(e.lower().startswith("changelog") or e.lower().startswith("changes") for e in entries)
        pf.has_contributing = any(e.lower().startswith("contributing") for e in entries)
        pf.has_security = any(e.lower().startswith("security") for e in entries)
        
        # Config files
        config_patterns = {
            ".eslintrc", ".prettierrc", "tsconfig.json", "jest.config",
            "webpack.config", "vite.config", "rollup.config",
            "pyproject.toml", "setup.cfg", "tox.ini", ".flake8",
            "rustfmt.toml", ".clippy.toml", ".editorconfig",
            "nginx.conf", "supervisord.conf",
        }
        pf.config_files = [e for e in entries if any(e.startswith(p) or e == p for p in config_patterns)]
        
        return pf
    
    def _parse_metadata(self, project: ProjectInfo, directory: str, entries: set[str]) -> None:
        """Parse project metadata from config files."""
        try:
            if "pyproject.toml" in entries:
                self._parse_pyproject(project, os.path.join(directory, "pyproject.toml"))
            elif "package.json" in entries:
                self._parse_package_json(project, os.path.join(directory, "package.json"))
            elif "Cargo.toml" in entries:
                self._parse_cargo(project, os.path.join(directory, "Cargo.toml"))
            elif "go.mod" in entries:
                self._parse_gomod(project, os.path.join(directory, "go.mod"))
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
    
    def _parse_pyproject(self, project: ProjectInfo, path: str) -> None:
        """Parse pyproject.toml for metadata."""
        try:
            content = Path(path).read_text(errors="replace")
        except Exception:
            return
        
        # Simple TOML parsing without external deps
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("name") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    project.name = val
            elif line.startswith("version") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and not project.version:
                    project.version = val
            elif line.startswith("description") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    project.description = val
        
        # Dependencies (simple extraction)
        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "[project.dependencies]" or stripped == "[tool.poetry.dependencies]":
                in_deps = True
                continue
            elif stripped.startswith("["):
                in_deps = False
                continue
            if in_deps and stripped and not stripped.startswith("#"):
                dep = stripped.strip('"').strip("'").strip(",").split(">=")[0].split("==")[0].split("<")[0].strip()
                if dep and dep != "python":
                    project.dependencies.append(dep)
    
    def _parse_package_json(self, project: ProjectInfo, path: str) -> None:
        """Parse package.json for metadata."""
        try:
            data = json.loads(Path(path).read_text(errors="replace"))
        except Exception:
            return
        
        project.name = data.get("name", project.name)
        project.version = data.get("version", "")
        project.description = data.get("description", "")
        
        if "dependencies" in data:
            project.dependencies = list(data["dependencies"].keys())[:50]
        if "devDependencies" in data:
            project.dev_dependencies = list(data["devDependencies"].keys())[:50]
        
        # Entry points
        if "main" in data:
            project.entry_points.append(data["main"])
        if "scripts" in data and "start" in data["scripts"]:
            project.entry_points.append(f"npm start: {data['scripts']['start']}")
    
    def _parse_cargo(self, project: ProjectInfo, path: str) -> None:
        """Parse Cargo.toml for metadata."""
        try:
            content = Path(path).read_text(errors="replace")
        except Exception:
            return
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("name") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"')
                if val:
                    project.name = val
            elif line.startswith("version") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"')
                if val and not project.version:
                    project.version = val

    def _parse_gomod(self, project: ProjectInfo, path: str) -> None:
        """Parse go.mod for metadata."""
        try:
            content = Path(path).read_text(errors="replace")
        except Exception:
            return
        for line in content.splitlines():
            if line.startswith("module "):
                project.name = line.split()[-1]
            elif line.startswith("go "):
                project.version = line.split()[-1]
    
    def _detect_git(self, directory: str) -> GitInfo:
        """Detect git repository status."""
        git_dir = os.path.join(directory, ".git")
        if not os.path.exists(git_dir):
            return GitInfo(is_repo=False)
        
        info = GitInfo(is_repo=True)
        
        def _git(cmd: str) -> str:
            try:
                r = subprocess.run(
                    f"git {cmd}", shell=True, cwd=directory,
                    capture_output=True, text=True, timeout=10
                )
                return r.stdout.strip()
            except Exception:
                return ""
        
        info.branch = _git("rev-parse --abbrev-ref HEAD")
        
        # Remotes
        remotes_raw = _git("remote -v")
        for line in remotes_raw.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "(fetch)" in line:
                info.remotes[parts[0]] = parts[1]
        
        # Status
        status = _git("status --porcelain")
        if status:
            lines = status.splitlines()
            info.uncommitted_files = sum(1 for l in lines if not l.startswith("??"))
            info.untracked_files = sum(1 for l in lines if l.startswith("??"))
        
        # Last commit
        info.last_commit_date = _git("log -1 --format=%aI")
        info.last_commit_msg = _git("log -1 --format=%s")[:200]
        
        # Total commits
        count = _git("rev-list --count HEAD")
        info.total_commits = int(count) if count.isdigit() else 0
        
        # Unpushed
        unpushed = _git("log @{u}..HEAD --oneline 2>/dev/null")
        info.has_unpushed = bool(unpushed)
        
        # Staleness
        if info.last_commit_date:
            try:
                from datetime import datetime, timezone
                commit_dt = datetime.fromisoformat(info.last_commit_date.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - commit_dt
                info.stale_days = delta.days
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
        
        return info
    
    def _detect_cicd(self, directory: str, entries: set[str]) -> CICDInfo:
        """Detect CI/CD configuration."""
        ci = CICDInfo()
        
        # GitHub Actions
        gh_dir = os.path.join(directory, ".github", "workflows")
        if os.path.isdir(gh_dir):
            ci.github_actions = True
            try:
                ci.workflows = [f for f in os.listdir(gh_dir) if f.endswith((".yml", ".yaml"))]
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
        
        # GitLab CI
        ci.gitlab_ci = ".gitlab-ci.yml" in entries
        
        # Jenkins
        ci.jenkins = "Jenkinsfile" in entries
        
        # Docker
        ci.docker = "Dockerfile" in entries or "dockerfile" in entries
        ci.docker_compose = "docker-compose.yml" in entries or "docker-compose.yaml" in entries or "compose.yml" in entries
        
        # Build tools
        ci.makefile = "Makefile" in entries or "makefile" in entries
        ci.taskfile = "Taskfile.yml" in entries
        
        return ci
    
    def _count_loc(self, directory: str, max_files: int = 5000) -> tuple[int, int, dict[str, int]]:
        """Count lines of code. Returns (total_lines, file_count, breakdown_by_ext)."""
        total = 0
        count = 0
        breakdown: dict[str, int] = {}
        
        for root, dirs, files in os.walk(directory):
            # Skip excluded dirs
            dirs[:] = [d for d in dirs if d not in DEFAULT_SKIP_DIRS and not d.startswith(".")]
            
            for f in files:
                if count >= max_files:
                    return total, count, breakdown
                
                ext = os.path.splitext(f)[1].lower()
                if ext not in CODE_EXTENSIONS:
                    continue
                
                fp = os.path.join(root, f)
                try:
                    with open(fp, "r", errors="replace") as fh:
                        lines = sum(1 for _ in fh)
                    total += lines
                    count += 1
                    breakdown[ext] = breakdown.get(ext, 0) + lines
                except (PermissionError, OSError) as e:
                    logger.debug(f"Suppressed (PermissionError, OSError): {e}")
        
        return total, count, breakdown
    
    def _scan_listening_ports(self) -> None:
        """Detect currently listening TCP ports."""
        try:
            r = subprocess.run(
                "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.splitlines():
                match = re.search(r":(\d+)\s", line)
                if match:
                    port = int(match.group(1))
                    if port < 65536:
                        self._listening_ports.add(port)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
    
    def _scan_running_processes(self) -> None:
        """Scan running processes for known service patterns."""
        try:
            r = subprocess.run(
                "ps aux", shell=True, capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.splitlines()[1:]:  # skip header
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    cmd = parts[10]
                    # Index by recognizable keywords
                    for keyword in ("node", "python", "java", "go", "ruby", "nginx", "redis", "postgres", "mongo", "uvicorn", "gunicorn", "flask", "django", "fastapi"):
                        if keyword in cmd.lower():
                            self._running_procs.setdefault(keyword, []).append(cmd[:200])
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
    
    def _check_live_status(self, project: ProjectInfo) -> None:
        """Check if a project has live running processes or listening ports."""
        name_lower = project.name.lower()
        
        # Check if any running process references this project
        for keyword, cmds in self._running_procs.items():
            for cmd in cmds:
                if name_lower in cmd.lower() or project.path in cmd:
                    project.is_live = True
                    project.live_processes.append(cmd[:150])
        
        # Check for common port patterns in package.json scripts or config
        # This is heuristic — check if known ports are listening
        common_ports = {3000, 5000, 8000, 8080, 8888, 4000, 9000}
        for port in common_ports & self._listening_ports:
            # We can't definitively tie a port to a project without deeper analysis
            # but we record it as potentially live
            pass
    
    def _parse_gitignore(self, path: str) -> list[str]:
        """Parse .gitignore into patterns."""
        patterns = []
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        return patterns


# ══════════════════════════════════════════════════════════════
# WRAPPER TYPES — compatibility with analyzer/report/cli
# ══════════════════════════════════════════════════════════════

@dataclass
class InfraInfo:
    """System-level infrastructure information."""
    listening_ports: list[dict] = field(default_factory=list)
    active_services: list[str] = field(default_factory=list)
    cron_jobs: list[str] = field(default_factory=list)
    disk_used_pct: float = 0.0
    disk_free_gb: float = 0.0
    memory_used_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "listening_ports": self.listening_ports,
            "active_services": self.active_services,
            "cron_jobs_count": len(self.cron_jobs),
            "disk_used_pct": round(self.disk_used_pct, 1),
            "disk_free_gb": round(self.disk_free_gb, 1),
            "memory_used_pct": round(self.memory_used_pct, 1),
        }

    @staticmethod
    def collect() -> "InfraInfo":
        """Collect current system infrastructure info."""
        infra = InfraInfo()
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            infra.disk_used_pct = (1 - free / total) * 100
            infra.disk_free_gb = free / (1024**3)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        try:
            with open("/proc/meminfo") as f:
                info = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        info[parts[0].strip()] = int(parts[1].strip().split()[0])
                total = info.get("MemTotal", 1)
                avail = info.get("MemAvailable", 0)
                infra.memory_used_pct = (1 - avail / total) * 100
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        try:
            r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    infra.listening_ports.append({"address": parts[3]})
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        try:
            r = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--state=active", "--no-legend", "--no-pager"],
                capture_output=True, text=True, timeout=5,
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip():
                    infra.active_services.append(line.split()[0])
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        try:
            r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
            infra.cron_jobs = [l for l in r.stdout.strip().split("\n") if l.strip() and not l.startswith("#")]
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        return infra


import time as _time

@dataclass
class ScanResult:
    """Complete workspace scan result — wraps project list + infra."""
    workspace: str
    timestamp: float = field(default_factory=_time.time)
    scan_duration_ms: float = 0.0
    projects: list[ProjectInfo] = field(default_factory=list)
    infra: InfraInfo = field(default_factory=InfraInfo)
    total_loc: int = 0
    total_files: int = 0
    env_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "workspace": self.workspace,
            "timestamp": self.timestamp,
            "scan_duration_ms": round(self.scan_duration_ms, 1),
            "projects": [p.to_dict() for p in self.projects],
            "infrastructure": self.infra.to_dict(),
            "total_loc": self.total_loc,
            "total_files": self.total_files,
            "total_projects": len(self.projects),
            "env_files": self.env_files,
        }

    def to_audit_data(self) -> dict:
        """Convert to the format expected by RoleRegistry.propose_roles()."""
        has_finance = any(
            any(kw in p.name.lower() for kw in ["finance", "billing", "payment", "pricing"])
            for p in self.projects
        )
        has_data = any(
            any(kw in p.name.lower() for kw in ["data", "pipeline", "etl", "ml", "analytics"])
            for p in self.projects
        )
        live_count = sum(1 for p in self.projects if p.is_live)
        return {
            "has_code": any(p.project_type != "generic" for p in self.projects),
            "has_infrastructure": bool(self.infra.active_services),
            "has_finance": has_finance,
            "has_security_concerns": bool(self.env_files),
            "has_data_pipeline": has_data,
            "has_marketing": False,
            "has_compliance_needs": False,
            "has_customers": live_count > 0,
            "live_products": live_count,
            "project_count": len(self.projects),
            "code_projects": sum(1 for p in self.projects if p.project_type != "generic"),
        }


# Patch WorkspaceScanner to return ScanResult
_original_scan = WorkspaceScanner.scan

def _wrapped_scan(self) -> ScanResult:
    """Enhanced scan that returns ScanResult with infrastructure info."""
    start = _time.monotonic()
    projects = _original_scan(self)
    duration = (_time.monotonic() - start) * 1000
    
    # Collect infrastructure
    infra = InfraInfo.collect()
    
    # Find .env files
    env_files = []
    root = Path(self.root)
    skip = set(self.skip_dirs) if self.skip_dirs else DEFAULT_SKIP_DIRS
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f == ".env" or f.endswith(".env"):
                env_files.append(os.path.relpath(os.path.join(dirpath, f), root))
    
    return ScanResult(
        workspace=str(root),
        scan_duration_ms=duration,
        projects=projects,
        infra=infra,
        total_loc=sum(p.total_lines for p in projects),
        total_files=sum(p.file_count for p in projects),
        env_files=env_files,
    )

WorkspaceScanner.scan = _wrapped_scan


def scan_workspace(root: str, skip_dirs: list[str] | None = None) -> ScanResult:
    """Convenience function — scan a workspace and return ScanResult."""
    scanner = WorkspaceScanner(root, skip_dirs=skip_dirs)
    return scanner.scan()
