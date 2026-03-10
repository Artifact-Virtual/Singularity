"""
POA Release Manager — Autonomous GitHub release pipeline.

Detects unreleased commits, generates changelogs, proposes semver bumps,
creates tags + GitHub releases. Ships when Singularity confirms.

Architecture:
  PULSE (every 4h) → scan repos → detect unreleased commits → propose release
  → Singularity reviews → confirms → tag + release published on GitHub
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("singularity.poa.release")

# ── Repo Registry ──────────────────────────────────────────────────────

@dataclass
class RepoConfig:
    """A tracked repository with release configuration."""
    product_id: str
    repo_path: str
    github_repo: str           # owner/repo format for gh CLI
    current_version: str       # last tagged version
    remotes: list[str] = field(default_factory=lambda: ["origin"])
    extra_remotes: list[str] = field(default_factory=list)  # gitlab, gitee
    release_branch: str = "main"

@dataclass
class ReleaseProposal:
    """A proposed release waiting for confirmation."""
    product_id: str
    repo_path: str
    github_repo: str
    current_version: str
    proposed_version: str
    bump_type: str             # major, minor, patch
    commits: list[dict]        # [{hash, subject, type}]
    changelog: str             # formatted release notes
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "pending"    # pending, confirmed, shipped, rejected
    remotes: list[str] = field(default_factory=lambda: ["origin"])

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "repo_path": self.repo_path,
            "github_repo": self.github_repo,
            "current_version": self.current_version,
            "proposed_version": self.proposed_version,
            "bump_type": self.bump_type,
            "commits": self.commits,
            "changelog": self.changelog,
            "created_at": self.created_at,
            "status": self.status,
            "remotes": self.remotes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReleaseProposal":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Version Helpers ────────────────────────────────────────────────────

def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse 'v1.2.3' or '1.2.3' → (1, 2, 3)."""
    v = version.lstrip("v")
    parts = v.split(".")
    if len(parts) != 3:
        return (0, 0, 0)
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return (0, 0, 0)

def bump_version(current: str, bump_type: str) -> str:
    """Bump version string by type."""
    major, minor, patch = parse_semver(current)
    if bump_type == "major":
        return f"v{major + 1}.0.0"
    elif bump_type == "minor":
        return f"v{major}.{minor + 1}.0"
    else:
        return f"v{major}.{minor}.{patch + 1}"


# ── Commit Analysis ───────────────────────────────────────────────────

# Conventional commit type → bump influence
COMMIT_TYPES = {
    "feat": "minor",
    "fix": "patch",
    "perf": "patch",
    "refactor": "patch",
    "docs": "patch",
    "chore": "patch",
    "style": "patch",
    "test": "patch",
    "ci": "patch",
    "build": "patch",
    "revert": "patch",
}

BREAKING_PATTERNS = [
    re.compile(r"BREAKING\s*CHANGE", re.IGNORECASE),
    re.compile(r"^[a-z]+!:", re.IGNORECASE),
]

def classify_commit(subject: str) -> tuple[str, str]:
    """Classify a commit subject → (type, bump_influence).
    
    Returns ('feat', 'minor'), ('fix', 'patch'), etc.
    Falls back to ('other', 'patch') for non-conventional commits.
    """
    # Check for breaking changes
    for pat in BREAKING_PATTERNS:
        if pat.search(subject):
            # Extract type if present
            m = re.match(r"^([a-z]+)!?:", subject, re.IGNORECASE)
            return (m.group(1).lower() if m else "breaking", "major")
    
    # Match conventional commit prefix
    m = re.match(r"^([a-z]+)(?:\(.+?\))?:\s", subject, re.IGNORECASE)
    if m:
        ctype = m.group(1).lower()
        return (ctype, COMMIT_TYPES.get(ctype, "patch"))
    
    return ("other", "patch")


# ── Release Manager ──────────────────────────────────────────────────

class ReleaseManager:
    """Scans repos for unreleased commits, generates proposals, ships releases."""

    def __init__(self, proposals_dir: Optional[str] = None):
        self.repos: list[RepoConfig] = []
        self.proposals: list[ReleaseProposal] = []
        self.proposals_dir = Path(proposals_dir or os.path.expanduser(
            "~/.singularity/poa/releases"
        ))
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self._load_proposals()

    def register_repo(self, config: RepoConfig):
        """Register a repository for release tracking."""
        self.repos.append(config)

    def _load_proposals(self):
        """Load pending proposals from disk."""
        pf = self.proposals_dir / "pending.json"
        if pf.exists():
            try:
                data = json.loads(pf.read_text())
                self.proposals = [ReleaseProposal.from_dict(p) for p in data]
            except Exception as e:
                logger.debug(f"Suppressed loading proposals: {e}")
                self.proposals = []

    def _save_proposals(self):
        """Persist proposals to disk."""
        pf = self.proposals_dir / "pending.json"
        try:
            pf.write_text(json.dumps(
                [p.to_dict() for p in self.proposals], indent=2
            ))
        except Exception as e:
            logger.debug(f"Suppressed saving proposals: {e}")

    def _run_git(self, repo_path: str, *args: str, timeout: int = 30) -> Optional[str]:
        """Run a git command in a repo directory."""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                logger.debug(f"git {' '.join(args)} failed in {repo_path}: {result.stderr.strip()}")
                return None
            return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Suppressed git command: {e}")
            return None

    def _get_latest_tag(self, repo_path: str) -> Optional[str]:
        """Get the latest semver tag in a repo."""
        output = self._run_git(repo_path, "tag", "--sort=-creatordate")
        if not output:
            return None
        for line in output.splitlines():
            line = line.strip()
            if re.match(r"^v?\d+\.\d+\.\d+$", line):
                return line
        return None

    def _get_unreleased_commits(self, repo_path: str, since_tag: Optional[str], branch: str = "main") -> list[dict]:
        """Get commits since the last tag."""
        if since_tag:
            output = self._run_git(repo_path, "log", f"{since_tag}..{branch}", "--oneline", "--no-merges")
        else:
            # No tags yet — get last 50 commits
            output = self._run_git(repo_path, "log", branch, "--oneline", "--no-merges", "-50")
        
        if not output:
            return []
        
        commits = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) < 2:
                continue
            hash_short = parts[0]
            subject = parts[1]
            ctype, influence = classify_commit(subject)
            commits.append({
                "hash": hash_short,
                "subject": subject,
                "type": ctype,
                "influence": influence,
            })
        return commits

    def _generate_changelog(self, commits: list[dict], product_id: str, proposed_version: str) -> str:
        """Generate release notes from classified commits."""
        sections = {}
        for c in commits:
            ctype = c["type"]
            label = {
                "feat": "Features",
                "fix": "Bug Fixes",
                "perf": "Performance",
                "refactor": "Refactoring",
                "docs": "Documentation",
                "chore": "Maintenance",
                "breaking": "Breaking Changes",
            }.get(ctype, "Other")
            sections.setdefault(label, []).append(c)
        
        lines = [f"## {product_id} {proposed_version}\n"]
        
        # Order: Breaking → Features → Fixes → everything else
        priority = ["Breaking Changes", "Features", "Bug Fixes", "Performance", "Refactoring", "Documentation", "Maintenance", "Other"]
        for section_name in priority:
            if section_name not in sections:
                continue
            lines.append(f"\n### {section_name}\n")
            for c in sections[section_name]:
                lines.append(f"- {c['subject']} (`{c['hash']}`)")
        
        return "\n".join(lines)

    def scan_all(self) -> list[ReleaseProposal]:
        """Scan all registered repos for unreleased work. Returns new proposals."""
        new_proposals = []
        
        for repo in self.repos:
            try:
                # Get latest tag (may differ from config version)
                latest_tag = self._get_latest_tag(repo.repo_path)
                current = latest_tag or repo.current_version
                
                # Get unreleased commits
                commits = self._get_unreleased_commits(
                    repo.repo_path, latest_tag, repo.release_branch
                )
                
                if not commits:
                    continue
                
                # Skip if we already have a pending proposal for this product
                existing = [p for p in self.proposals 
                           if p.product_id == repo.product_id and p.status == "pending"]
                if existing:
                    continue
                
                # Determine bump type from commits
                influences = [c["influence"] for c in commits]
                if "major" in influences:
                    bump_type = "major"
                elif "minor" in influences:
                    bump_type = "minor"
                else:
                    bump_type = "patch"
                
                proposed_version = bump_version(current, bump_type)
                changelog = self._generate_changelog(commits, repo.product_id, proposed_version)
                
                proposal = ReleaseProposal(
                    product_id=repo.product_id,
                    repo_path=repo.repo_path,
                    github_repo=repo.github_repo,
                    current_version=current,
                    proposed_version=proposed_version,
                    bump_type=bump_type,
                    commits=commits,
                    changelog=changelog,
                    remotes=repo.remotes + repo.extra_remotes,
                )
                new_proposals.append(proposal)
                self.proposals.append(proposal)
                
                logger.info(
                    f"Release proposal: {repo.product_id} {current} → {proposed_version} "
                    f"({len(commits)} commits, {bump_type} bump)"
                )
            except Exception as e:
                logger.debug(f"Suppressed scanning {repo.product_id}: {e}")
        
        if new_proposals:
            self._save_proposals()
        
        return new_proposals

    def confirm(self, product_id: str) -> Optional[ReleaseProposal]:
        """Mark a proposal as confirmed (ready to ship)."""
        for p in self.proposals:
            if p.product_id == product_id and p.status == "pending":
                p.status = "confirmed"
                self._save_proposals()
                return p
        return None

    def reject(self, product_id: str) -> Optional[ReleaseProposal]:
        """Reject a proposal."""
        for p in self.proposals:
            if p.product_id == product_id and p.status == "pending":
                p.status = "rejected"
                self._save_proposals()
                return p
        return None

    async def ship(self, product_id: str) -> dict:
        """Ship a confirmed release — tag, push, create GitHub release."""
        proposal = None
        for p in self.proposals:
            if p.product_id == product_id and p.status == "confirmed":
                proposal = p
                break
        
        if not proposal:
            return {"success": False, "error": f"No confirmed proposal for {product_id}"}
        
        result = {"success": False, "product_id": product_id, "version": proposal.proposed_version}
        
        try:
            # 1. Create annotated tag
            tag_output = self._run_git(
                proposal.repo_path,
                "tag", "-a", proposal.proposed_version,
                "-m", f"Release {proposal.proposed_version}\n\n{proposal.changelog}"
            )
            if tag_output is None:
                # Check if tag already exists
                existing = self._run_git(proposal.repo_path, "tag", "-l", proposal.proposed_version)
                if not existing or proposal.proposed_version not in existing:
                    result["error"] = "Failed to create tag"
                    return result
            
            result["tag_created"] = True
            logger.info(f"Created tag {proposal.proposed_version} for {product_id}")
            
            # 2. Push tag to all remotes
            push_results = {}
            for remote in proposal.remotes:
                push_out = self._run_git(
                    proposal.repo_path,
                    "push", remote, proposal.proposed_version,
                    timeout=120
                )
                push_results[remote] = push_out is not None
            
            result["pushed"] = push_results
            logger.info(f"Pushed tag to remotes: {push_results}")
            
            # 3. Create GitHub release via gh CLI
            if proposal.github_repo:
                try:
                    gh_result = subprocess.run(
                        [
                            "gh", "release", "create",
                            proposal.proposed_version,
                            "--repo", proposal.github_repo,
                            "--title", f"{product_id} {proposal.proposed_version}",
                            "--notes", proposal.changelog,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        cwd=proposal.repo_path,
                    )
                    if gh_result.returncode == 0:
                        result["github_release"] = True
                        result["release_url"] = gh_result.stdout.strip()
                        logger.info(f"GitHub release created: {gh_result.stdout.strip()}")
                    else:
                        result["github_release"] = False
                        result["gh_error"] = gh_result.stderr.strip()
                        logger.warning(f"GitHub release failed: {gh_result.stderr.strip()}")
                except Exception as e:
                    result["github_release"] = False
                    result["gh_error"] = str(e)
                    logger.debug(f"Suppressed GitHub release: {e}")
            
            # 4. Mark shipped
            proposal.status = "shipped"
            self._save_proposals()
            
            # 5. Archive to history
            self._archive_release(proposal)
            
            result["success"] = True
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Release ship failed for {product_id}: {e}")
        
        return result

    def _archive_release(self, proposal: ReleaseProposal):
        """Move shipped release to history."""
        history_dir = self.proposals_dir / "history"
        history_dir.mkdir(exist_ok=True)
        
        archive_file = history_dir / f"{proposal.product_id}_{proposal.proposed_version}.json"
        try:
            archive_file.write_text(json.dumps(proposal.to_dict(), indent=2))
        except Exception as e:
            logger.debug(f"Suppressed archiving release: {e}")
        
        # Remove from active proposals
        self.proposals = [p for p in self.proposals if not (
            p.product_id == proposal.product_id and p.status == "shipped"
        )]
        self._save_proposals()

    def get_pending(self) -> list[ReleaseProposal]:
        """Get all pending proposals."""
        return [p for p in self.proposals if p.status == "pending"]

    def get_status(self) -> dict:
        """Get release manager status."""
        return {
            "repos_tracked": len(self.repos),
            "pending_proposals": len([p for p in self.proposals if p.status == "pending"]),
            "confirmed": len([p for p in self.proposals if p.status == "confirmed"]),
            "shipped_total": len(list((self.proposals_dir / "history").glob("*.json"))) if (self.proposals_dir / "history").exists() else 0,
            "proposals": [
                {
                    "product_id": p.product_id,
                    "current": p.current_version,
                    "proposed": p.proposed_version,
                    "bump": p.bump_type,
                    "commits": len(p.commits),
                    "status": p.status,
                    "created": p.created_at,
                }
                for p in self.proposals
            ],
        }
