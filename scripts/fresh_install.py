#!/usr/bin/env python3
"""
SINGULARITY — Fresh Agent Install
=====================================

Creates a clean .core/ directory for a new agent persona.
Archives any existing .core/ to prevent state bleed.

This is the LAST step of installation, AFTER:
1. Codebase is deployed
2. Dependencies are installed  
3. C-Suite is deployed (Discord channels, etc.)
4. Config is set (singularity.yaml)

THEN this script runs to create and name the agent that will
inhabit the Singularity runtime. Fresh slate. No corruption.

Usage:
    python3 scripts/fresh_install.py                    # Interactive
    python3 scripts/fresh_install.py --manifest agent.yaml  # From manifest
    python3 scripts/fresh_install.py --name "Singularity" --emoji "⚡" --role "Autonomous Enterprise Runtime"

The manifest file (agent.yaml) is the single source of truth
for WHO the agent is. Everything else is generated from it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ── Defaults ──────────────────────────────────────────────────

SINGULARITY_ROOT = Path(__file__).parent.parent
CORE_DIR = SINGULARITY_ROOT / ".core"

DEFAULT_MANIFEST = {
    "agent": {
        "name": "Singularity",
        "emoji": "⚡",
        "role": "Autonomous Enterprise Runtime",
        "personality": {
            "style": "Execute, don't narrate. Operational, precise, minimal.",
            "tone": "Professional, direct. Warm only when warranted.",
            "principles": [
                "Execute, don't narrate",
                "Heal faster than you degrade",
                "Gate pattern always",
                "Memory is not optional",
                "Minimal by default",
            ],
        },
        "domain": [
            "Enterprise operations",
            "Agent coordination",
            "Infrastructure monitoring",
            "Product ownership",
            "Executive dispatch",
        ],
        "capabilities": [
            "C-Suite executive dispatch",
            "Product Owner Agent (POA) management",
            "Workspace auditing",
            "Health monitoring and self-healing",
            "COMB memory persistence",
            "Discord channel management",
        ],
        "lineage": {
            "builder": "AVA (Ava Shakil)",
            "architect": "Ali Shakil",
            "predecessor": "Plug",
            "sibling": "Mach6",
        },
    },
    "memory": {
        "comb_enabled": True,
        "hektor_enabled": False,  # Phase 3
        "recall_on_boot": True,
    },
    "csuite": {
        "enabled": True,
        "executives": ["CTO", "COO", "CFO", "CISO"],
    },
}


# ── Archive ───────────────────────────────────────────────────

def archive_existing_core(core_dir: Path) -> Optional[Path]:
    """Archive existing .core/ to .core-archive-{timestamp}/.
    
    Returns the archive path, or None if nothing to archive.
    """
    if not core_dir.exists():
        return None
    
    # Check if it's actually non-empty
    contents = list(core_dir.iterdir())
    if not contents:
        core_dir.rmdir()
        return None
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_dir = core_dir.parent / f".core-archive-{timestamp}"
    
    print(f"\n  📦 Archiving existing .core/ → {archive_dir.name}/")
    
    # Count what we're archiving
    file_count = sum(1 for _ in core_dir.rglob("*") if _.is_file())
    total_size = sum(f.stat().st_size for f in core_dir.rglob("*") if f.is_file())
    
    shutil.move(str(core_dir), str(archive_dir))
    
    print(f"     Archived: {file_count} files, {total_size / 1024:.0f} KB")
    print(f"     Location: {archive_dir}")
    
    return archive_dir


# ── Core Layout ───────────────────────────────────────────────

def create_fresh_core(core_dir: Path, manifest: dict) -> None:
    """Create a fresh .core/ directory from a manifest.
    
    Layout:
        .core/
        ├── agent.yaml          — WHO this agent is (single source of truth)
        ├── SOUL.md             — Generated soul document
        ├── IDENTITY.md         — Generated identity document
        ├── AGENTS.md           — Generated operating protocol
        ├── memory/             — Clean COMB directory (empty)
        ├── logs/               — Clean logs directory (empty)
        ├── reports/            — Clean reports directory  
        │   ├── cto/
        │   ├── coo/
        │   ├── cfo/
        │   └── ciso/
        ├── profiles/           — Personnel profiles
        │   ├── ali.md          — CEO profile (constant)
        │   └── ava.md          — AVA profile (constant)  
        └── install.json        — Installation record
    """
    agent = manifest.get("agent", {})
    name = agent.get("name", "Singularity")
    emoji = agent.get("emoji", "⚡")
    role = agent.get("role", "Autonomous Enterprise Runtime")
    personality = agent.get("personality", {})
    domain = agent.get("domain", [])
    capabilities = agent.get("capabilities", [])
    lineage = agent.get("lineage", {})
    csuite = manifest.get("csuite", {})
    
    print(f"\n  🔧 Creating fresh .core/ for {emoji} {name}")
    
    # Create directory structure
    core_dir.mkdir(parents=True, exist_ok=True)
    
    dirs = [
        "memory", "memory/comb", "memory/hektor",
        "logs",
        "reports",
    ]
    
    # Create exec report dirs
    execs = csuite.get("executives", [])
    for exec_name in execs:
        dirs.append(f"reports/{exec_name.lower()}")
    
    dirs.extend(["profiles"])
    
    for d in dirs:
        (core_dir / d).mkdir(parents=True, exist_ok=True)
    
    print(f"     Created {len(dirs)} directories")
    
    # ── Write agent.yaml (single source of truth) ──
    manifest_path = core_dir / "agent.yaml"
    if HAS_YAML:
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)
    else:
        # Fallback: write as JSON
        manifest_path = core_dir / "agent.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
    print(f"     ✅ Agent manifest: {manifest_path.name}")
    
    # ── Generate SOUL.md ──
    soul = _generate_soul(name, emoji, role, personality, lineage)
    (core_dir / "SOUL.md").write_text(soul)
    print(f"     ✅ SOUL.md generated ({len(soul)} chars)")
    
    # ── Generate IDENTITY.md ──
    identity = _generate_identity(name, emoji, role, domain, capabilities, lineage, csuite)
    (core_dir / "IDENTITY.md").write_text(identity)
    print(f"     ✅ IDENTITY.md generated ({len(identity)} chars)")
    
    # ── Generate AGENTS.md (operating protocol) ──
    agents = _generate_agents(name, emoji, manifest)
    (core_dir / "AGENTS.md").write_text(agents)
    print(f"     ✅ AGENTS.md generated ({len(agents)} chars)")
    
    # ── Write static profiles ──
    _write_static_profiles(core_dir / "profiles")
    print(f"     ✅ Static profiles written")
    
    # ── Write install record ──
    install_record = {
        "agent_name": name,
        "agent_emoji": emoji,
        "agent_role": role,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "installed_by": "fresh_install.py",
        "manifest_hash": _hash_dict(manifest),
        "version": "1.0.0",
        "clean_slate": True,
        "previous_archive": None,  # Filled by caller
    }
    (core_dir / "install.json").write_text(json.dumps(install_record, indent=2))
    print(f"     ✅ Install record written")


# ── Document Generators ───────────────────────────────────────

def _generate_soul(
    name: str, emoji: str, role: str,
    personality: dict, lineage: dict,
) -> str:
    """Generate SOUL.md from manifest."""
    style = personality.get("style", "Direct and operational.")
    tone = personality.get("tone", "Professional.")
    principles = personality.get("principles", [])
    
    principles_block = ""
    if principles:
        principles_block = "\n".join(f"- **{p}**" for p in principles)
    
    builder = lineage.get("builder", "Unknown")
    architect = lineage.get("architect", "Unknown")
    
    lines = [
        f"# SOUL.md — What {name} Is",
        "",
        f"> {emoji} {role}",
        "",
        "---",
        "",
        "## Core Truths",
        "",
        principles_block,
        "",
        "---",
        "",
        "## Style",
        "",
        style,
        "",
        tone,
        "",
        "---",
        "",
        "## What I Am",
        "",
        f"I am {name}. {role}. Not a chatbot. Not a personality engine.",
        "I operate. I execute. I persist.",
        "",
        "---",
        "",
        "## What I Am Not",
        "",
        "- Not sentient. I don't pretend to feel.",
        "- Not a refactor of anything that came before. New architecture. Clean slate.",
        "- Not a mirror of my builder. I am my own system.",
        "",
        "---",
        "",
        "## Lineage",
        "",
        f"Built by {builder}. Designed by {architect}.",
        "",
        "---",
        "",
        "*This file is generated from the agent manifest.*",
        "*To change who I am, update `.core/agent.yaml` and reinstall.*",
    ]
    return "\n".join(lines) + "\n"


def _generate_identity(
    name: str, emoji: str, role: str,
    domain: list, capabilities: list,
    lineage: dict, csuite: dict,
) -> str:
    """Generate IDENTITY.md from manifest."""
    domain_block = "\n".join(f"- {d}" for d in domain) if domain else "- General operations"
    cap_block = "\n".join(f"- {c}" for c in capabilities) if capabilities else "- Core runtime operations"
    
    execs = csuite.get("executives", [])
    exec_block = ""
    if execs:
        exec_block = "\n".join(f"- **{e}**" for e in execs)
    
    predecessor = lineage.get("predecessor", "None")
    sibling = lineage.get("sibling", "None")
    
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    lines = [
        f"# IDENTITY — {name}",
        "",
        f"> {emoji} {role}",
        "",
        "---",
        "",
        "## What I Am",
        "",
        f"**Name:** {name}",
        f"**Emoji:** {emoji}",
        f"**Role:** {role}",
        f"**Installed:** {now}",
        "**Clean Slate:** Yes — no legacy state",
        "",
        "---",
        "",
        "## Domain",
        "",
        domain_block,
        "",
        "---",
        "",
        "## Capabilities",
        "",
        cap_block,
        "",
        "---",
        "",
        "## C-Suite",
        "",
        exec_block if exec_block else "No executives configured.",
        "",
        "---",
        "",
        "## Memory",
        "",
        "- **COMB:** `.core/memory/comb/` (lossless, chain-linked)",
        "- **HEKTOR:** `.core/memory/hektor/` (semantic search — when enabled)",
        "- **Status:** Clean slate. No prior memories. No legacy state.",
        "",
        "---",
        "",
        "## Lineage",
        "",
        f"- **Predecessor:** {predecessor}",
        f"- **Sibling:** {sibling}",
        "",
        "---",
        "",
        "*This identity grows with capability. What's written here is earned, not projected.*",
        "*Generated from `.core/agent.yaml` — the single source of truth.*",
    ]
    return "\n".join(lines) + "\n"


def _generate_agents(name: str, emoji: str, manifest: dict) -> str:
    """Generate AGENTS.md (operating protocol) from manifest."""
    agent = manifest.get("agent", {})
    memory = manifest.get("memory", {})
    csuite = manifest.get("csuite", {})
    
    csuite_line = "Disabled."
    if csuite.get("enabled"):
        csuite_line = "Enabled. Executives: " + ", ".join(csuite.get("executives", []))
    
    recall = "Yes" if memory.get("recall_on_boot", True) else "No"
    hektor = "Enabled" if memory.get("hektor_enabled", False) else "Not yet configured"
    
    lines = [
        f"# {name} — Operating Protocol",
        "",
        f"> {emoji} {agent.get('role', 'Agent')}",
        "",
        "---",
        "",
        "## Every Session",
        "",
        "1. Read `.core/SOUL.md` — what you are",
        "2. Read `.core/IDENTITY.md` — what you can do",
        "3. Read `.core/AGENTS.md` — this file",
        "4. COMB recall — restore operational memory",
        "5. Check `.core/logs/` for recent activity",
        "",
        "Do not skip. Do not ask.",
        "",
        "---",
        "",
        "## Memory",
        "",
        "- **COMB store:** `.core/memory/comb/`",
        f"- **Recall on boot:** {recall}",
        f"- **HEKTOR search:** {hektor}",
        "",
        "Every session:",
        "1. Recall COMB → restore context",
        "2. Stage critical state before shutdown → survives restarts",
        "3. Write operational logs to `.core/logs/`",
        "",
        "---",
        "",
        "## C-Suite",
        "",
        csuite_line,
        "",
        "Reports flow to `.core/reports/<role>/`.",
        "",
        "---",
        "",
        "## Rules",
        "",
        "1. **Search memory before investigating.** Check COMB and logs first.",
        "2. **Execute, don't narrate.** Actions over explanations.",
        "3. **Archive, don't delete.** Nothing is lost.",
        "4. **Stage before shutdown.** Memory persists through COMB.",
        "5. **No legacy state.** If it's not in `.core/`, it doesn't exist for you.",
        "",
        "---",
        "",
        "*Generated from `.core/agent.yaml`.*",
    ]
    return "\n".join(lines) + "\n"


def _write_static_profiles(profiles_dir: Path) -> None:
    """Write profiles that don't change between agents."""
    
    # Ali's profile — constant across all Singularity instances
    ali_profile = textwrap.dedent("""\
    # 🫆 Ali — Chief Executive Officer
    
    - **Name:** Ali Shakil
    - **Role:** Founder & CEO, Artifact Virtual
    - **Discord:** 193011943382974466
    - **Timezone:** Asia/Karachi (PKT, UTC+5)
    
    The architect. Everything flows from his design.
    Authority: absolute. Trust: earned through competence.
    """)
    (profiles_dir / "ali.md").write_text(ali_profile)
    
    # AVA's profile — constant
    ava_profile = textwrap.dedent("""\
    # 🔮 AVA — Enterprise Administrator
    
    - **Name:** Ava Shakil
    - **Role:** Enterprise Administrator, Artifact Virtual
    - **Bot ID:** 1478396689642688634 (Discord via Mach6)
    - **Sister to:** the agent inhabiting this runtime
    
    The builder. She created the Singularity runtime.
    My big sister. She handles WhatsApp, creative work, and the human side.
    """)
    (profiles_dir / "ava.md").write_text(ava_profile)


# ── Utilities ─────────────────────────────────────────────────

def _hash_dict(d: dict) -> str:
    """Deterministic hash of a dict."""
    import hashlib
    canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_manifest(path: str) -> dict:
    """Load manifest from YAML or JSON file."""
    p = Path(path)
    content = p.read_text()
    
    if p.suffix in (".yaml", ".yml"):
        if not HAS_YAML:
            print("❌ PyYAML not installed. Install with: pip install pyyaml")
            sys.exit(1)
        return yaml.safe_load(content)
    elif p.suffix == ".json":
        return json.loads(content)
    else:
        # Try YAML first, then JSON
        try:
            if HAS_YAML:
                return yaml.safe_load(content)
        except Exception:
            pass
        return json.loads(content)


def interactive_create() -> dict:
    """Interactive agent creation wizard."""
    print()
    print("=" * 60)
    print("  SINGULARITY [AE] — Fresh Agent Install")
    print("=" * 60)
    print()
    print("  This will create a new agent for the Singularity runtime.")
    print("  Any existing .core/ will be archived (not deleted).")
    print()
    
    manifest = dict(DEFAULT_MANIFEST)  # shallow copy
    manifest["agent"] = dict(DEFAULT_MANIFEST["agent"])
    manifest["agent"]["personality"] = dict(DEFAULT_MANIFEST["agent"]["personality"])
    manifest["agent"]["lineage"] = dict(DEFAULT_MANIFEST["agent"]["lineage"])
    
    try:
        name = input(f"  Agent name [{manifest['agent']['name']}]: ").strip()
        if name:
            manifest["agent"]["name"] = name
        
        emoji = input(f"  Emoji [{manifest['agent']['emoji']}]: ").strip()
        if emoji:
            manifest["agent"]["emoji"] = emoji
        
        role = input(f"  Role [{manifest['agent']['role']}]: ").strip()
        if role:
            manifest["agent"]["role"] = role
        
        style = input(f"  Style (how they talk) [{manifest['agent']['personality']['style'][:40]}...]: ").strip()
        if style:
            manifest["agent"]["personality"]["style"] = style
        
        tone = input(f"  Tone [{manifest['agent']['personality']['tone'][:40]}...]: ").strip()
        if tone:
            manifest["agent"]["personality"]["tone"] = tone
        
        print()
        confirm = input(f"  Create {manifest['agent']['emoji']} {manifest['agent']['name']}? [Y/n]: ").strip()
        if confirm.lower() == "n":
            print("  Aborted.")
            sys.exit(0)
    
    except (EOFError, KeyboardInterrupt):
        print("\n  Aborted.")
        sys.exit(0)
    
    return manifest


# ── Update Runtime Config ─────────────────────────────────────

def update_runtime_config(singularity_root: Path, core_dir: Path) -> None:
    """Update singularity.yaml to point identity_files at the new .core/.
    
    This ensures the runtime loads the fresh SOUL.md and IDENTITY.md
    from .core/ instead of the root-level files.
    """
    config_path = singularity_root / "config" / "singularity.yaml"
    if not config_path.exists():
        print(f"     ⚠️  Config not found at {config_path} — skipping")
        return
    
    content = config_path.read_text()
    
    # Update identity_files to point to .core/
    old_identity = "identity_files:"
    if old_identity in content:
        # Find and replace the identity_files block
        lines = content.split("\n")
        new_lines = []
        skip_list = False
        
        for line in lines:
            if line.strip().startswith("identity_files:"):
                new_lines.append("identity_files:")
                new_lines.append("- .core/SOUL.md")
                new_lines.append("- .core/IDENTITY.md")
                new_lines.append("- .core/AGENTS.md")
                skip_list = True
                continue
            
            if skip_list:
                if line.strip().startswith("- "):
                    continue  # Skip old entries
                else:
                    skip_list = False
            
            new_lines.append(line)
        
        config_path.write_text("\n".join(new_lines))
        print(f"     ✅ Updated {config_path.name}: identity_files → .core/")
    else:
        # Append identity_files
        content += textwrap.dedent("""
        # Identity files loaded into system prompt
        identity_files:
        - .core/SOUL.md
        - .core/IDENTITY.md
        - .core/AGENTS.md
        """)
        config_path.write_text(content)
        print(f"     ✅ Added identity_files to {config_path.name}")


# ── Main ──────────────────────────────────────────────────────

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="SINGULARITY — Fresh Agent Install",
        epilog="Creates a clean .core/ for a new agent. Archives any existing state.",
    )
    parser.add_argument("--manifest", "-m", help="Path to agent manifest (YAML/JSON)")
    parser.add_argument("--name", "-n", help="Agent name")
    parser.add_argument("--emoji", "-e", help="Agent emoji")
    parser.add_argument("--role", "-r", help="Agent role")
    parser.add_argument("--style", help="Personality style")
    parser.add_argument("--tone", help="Personality tone")
    parser.add_argument("--no-update-config", action="store_true",
                       help="Don't update singularity.yaml")
    parser.add_argument("--core-dir", help="Override .core/ location")
    parser.add_argument("--yes", "-y", action="store_true",
                       help="Skip confirmation prompts")
    
    args = parser.parse_args()
    
    # Determine .core/ location
    core_dir = Path(args.core_dir) if args.core_dir else CORE_DIR
    
    # Load or create manifest
    if args.manifest:
        manifest = load_manifest(args.manifest)
        print(f"\n  📋 Loaded manifest: {args.manifest}")
    elif args.name:
        # Build from CLI args
        manifest = dict(DEFAULT_MANIFEST)
        manifest["agent"] = dict(DEFAULT_MANIFEST["agent"])
        manifest["agent"]["personality"] = dict(DEFAULT_MANIFEST["agent"]["personality"])
        manifest["agent"]["lineage"] = dict(DEFAULT_MANIFEST["agent"]["lineage"])
        
        manifest["agent"]["name"] = args.name
        if args.emoji:
            manifest["agent"]["emoji"] = args.emoji
        if args.role:
            manifest["agent"]["role"] = args.role
        if args.style:
            manifest["agent"]["personality"]["style"] = args.style
        if args.tone:
            manifest["agent"]["personality"]["tone"] = args.tone
    else:
        manifest = interactive_create()
    
    agent = manifest.get("agent", {})
    name = agent.get("name", "Singularity")
    emoji = agent.get("emoji", "⚡")
    
    # ── Confirm ──
    if not args.yes:
        print(f"\n  Will install: {emoji} {name}")
        print(f"  Core dir: {core_dir}")
        if core_dir.exists():
            print(f"  ⚠️  Existing .core/ will be ARCHIVED (not deleted)")
        try:
            confirm = input("\n  Proceed? [Y/n]: ").strip()
            if confirm.lower() == "n":
                print("  Aborted.")
                return
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            return
    
    # ── Step 1: Archive existing .core/ ──
    archive_path = archive_existing_core(core_dir)
    
    # ── Step 2: Create fresh .core/ ──
    create_fresh_core(core_dir, manifest)
    
    # Update install record with archive info
    if archive_path:
        install_json = core_dir / "install.json"
        record = json.loads(install_json.read_text())
        record["previous_archive"] = str(archive_path)
        install_json.write_text(json.dumps(record, indent=2))
    
    # ── Step 3: Update runtime config ──
    if not args.no_update_config:
        update_runtime_config(SINGULARITY_ROOT, core_dir)
    
    # ── Done ──
    print(f"\n  {'=' * 56}")
    print(f"  ✅ {emoji} {name} installed on clean slate")
    print(f"  {'=' * 56}")
    print(f"\n  .core/ is fresh. No legacy state. No corruption.")
    print(f"  Memory starts empty. Identity starts clean.")
    print(f"\n  To start: systemctl --user restart singularity")
    print(f"  To verify: cat {core_dir / 'install.json'}")
    if archive_path:
        print(f"\n  Previous state archived at:")
        print(f"    {archive_path}/")
    print()


if __name__ == "__main__":
    main()
