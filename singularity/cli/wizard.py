"""
Singularity [AE] — Setup Wizard
Surgical. No extra.
"""
from __future__ import annotations
import os, sys, subprocess, shutil, textwrap
from pathlib import Path

# ── colours ──────────────────────────────────────────────────
R   = "\033[0m"
B   = "\033[1m"
DIM = "\033[2m"
CY  = "\033[36m"
GR  = "\033[32m"
YL  = "\033[33m"
RD  = "\033[31m"
MAG = "\033[35m"

def hdr(n: int, total: int, title: str) -> None:
    print(f"\n{CY}{B}[{n}/{total}]{R} {B}{title}{R}")

def ok(msg: str)   -> None: print(f"  {GR}✓{R} {msg}")
def warn(msg: str) -> None: print(f"  {YL}⚠{R} {msg}")
def err(msg: str)  -> None: print(f"  {RD}✗{R} {msg}")
def info(msg: str) -> None: print(f"  {DIM}{msg}{R}")

def ask(label: str, hint: str = "", secret: bool = False) -> str:
    import getpass
    marker = f"  {CY}›{R} {label}"
    marker += f" {DIM}[{hint}]{R}" if hint else ""
    marker += ": "
    try:
        return (getpass.getpass(marker) if secret else input(marker)).strip()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{RD}Aborted.{R}")
        sys.exit(0)

def ask_path(label: str, hint: str = "", must_exist: bool = False) -> Path:
    while True:
        raw = ask(label, hint)
        p = Path(raw).expanduser().resolve()
        if must_exist and not p.exists():
            err(f"Path not found: {p}")
            continue
        return p

def confirm(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = ask(label, hint).lower()
    if not raw:
        return default
    return raw.startswith("y")

def run(cmd: str, silent: bool = True) -> tuple[int, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()

# ─────────────────────────────────────────────────────────────
#  BANNER
# ─────────────────────────────────────────────────────────────
BANNER = f"""
{CY}{B}╔══════════════════════════════════════════╗
║   SINGULARITY [AE]  ⚡                   ║
║   Autonomous Enterprise Runtime          ║
╚══════════════════════════════════════════╝{R}
{DIM}  Workspace discovery · C-Suite · POA monitoring · Sentinel{R}
"""

TOTAL_STEPS = 6

# ─────────────────────────────────────────────────────────────
#  STEP 1 — workspace / enterprise repo
# ─────────────────────────────────────────────────────────────
def step_workspace() -> Path:
    hdr(1, TOTAL_STEPS, "Workspace")
    info("Where is your enterprise repo? (the root Singularity will audit and manage)")
    ws = ask_path("Workspace path", "~/workspace")
    ws.mkdir(parents=True, exist_ok=True)

    # init git if not already
    if not (ws / ".git").exists():
        if confirm("  Not a git repo — initialise?", default=True):
            run(f"git -C '{ws}' init -q")
            ok("git init")

    ok(f"Workspace → {ws}")
    return ws

# ─────────────────────────────────────────────────────────────
#  STEP 2 — identity / Discord
# ─────────────────────────────────────────────────────────────
def step_identity() -> dict:
    hdr(2, TOTAL_STEPS, "Identity")
    info("Discord bot token + your user ID. Everything else is self-discovered.")

    discord_token  = ask("Discord bot token", secret=True)
    discord_user   = ask("Your Discord user ID", "18-digit number")
    guild_id       = ask("Discord server (guild) ID", "18-digit number")

    return {
        "discord_token":   discord_token,
        "discord_user_id": discord_user,
        "guild_id":        guild_id,
    }

# ─────────────────────────────────────────────────────────────
#  STEP 3 — LLM provider
# ─────────────────────────────────────────────────────────────
def step_llm() -> dict:
    hdr(3, TOTAL_STEPS, "LLM Provider")
    providers = {
        "1": ("GitHub Copilot (recommended)",  "COPILOT_TOKEN",    "copilot"),
        "2": ("OpenAI",                         "OPENAI_API_KEY",   "openai"),
        "3": ("Anthropic",                      "ANTHROPIC_API_KEY","anthropic"),
        "4": ("Ollama (local, free)",           "",                 "ollama"),
    }
    for k, (name, _, _) in providers.items():
        print(f"  {DIM}{k}.{R} {name}")

    choice = ask("Provider", "1").strip() or "1"
    _, key_name, provider = providers.get(choice, providers["1"])

    api_key = ""
    if key_name:
        api_key = ask(f"{key_name}", secret=True)

    ok(f"Provider → {provider}")
    return {"provider": provider, "api_key_name": key_name, "api_key": api_key}

# ─────────────────────────────────────────────────────────────
#  STEP 4 — COMB + memory
# ─────────────────────────────────────────────────────────────
def step_memory(ws: Path) -> None:
    hdr(4, TOTAL_STEPS, "Memory (COMB)")
    comb_dir = ws / ".ava-memory"
    comb_dir.mkdir(parents=True, exist_ok=True)
    (comb_dir / "comb-pending.jsonl").touch()
    (ws / ".singularity" / "sessions").mkdir(parents=True, exist_ok=True)
    (ws / ".singularity" / "poas").mkdir(parents=True, exist_ok=True)
    (ws / ".singularity" / "reports").mkdir(parents=True, exist_ok=True)
    (ws / ".singularity" / "atlas").mkdir(parents=True, exist_ok=True)
    (ws / ".singularity" / "events" / "exfilguard").mkdir(parents=True, exist_ok=True)
    ok(f"COMB store → {comb_dir}")
    ok("Directory structure initialised")

# ─────────────────────────────────────────────────────────────
#  STEP 5 — write config
# ─────────────────────────────────────────────────────────────
def step_config(ws: Path, identity: dict, llm: dict) -> Path:
    hdr(5, TOTAL_STEPS, "Configuration")

    # Find singularity package root
    pkg_root = Path(__file__).resolve().parents[2]
    config_dir = pkg_root / "config"
    config_dir.mkdir(exist_ok=True)
    cfg_path = config_dir / "singularity.yaml"

    # Build provider chain entry
    provider_block = ""
    if llm["provider"] == "copilot":
        provider_block = f"""
  providers:
    - name: copilot
      type: copilot
      base_url: http://localhost:3000
      model: claude-opus-4.6
      max_tokens: 16384
    - name: ollama
      type: ollama
      base_url: http://localhost:11434
      model: qwen2.5:7b
      max_tokens: 8192"""
    elif llm["provider"] == "openai":
        provider_block = f"""
  providers:
    - name: openai
      type: openai
      api_key: ${{{llm['api_key_name']}}}
      model: gpt-4o
      max_tokens: 16384
    - name: ollama
      type: ollama
      base_url: http://localhost:11434
      model: qwen2.5:7b
      max_tokens: 8192"""
    elif llm["provider"] == "anthropic":
        provider_block = f"""
  providers:
    - name: anthropic
      type: anthropic
      api_key: ${{{llm['api_key_name']}}}
      model: claude-opus-4-5
      max_tokens: 16384"""
    else:
        provider_block = f"""
  providers:
    - name: ollama
      type: ollama
      base_url: http://localhost:11434
      model: qwen2.5:7b
      max_tokens: 8192"""

    cfg_content = f"""# Singularity [AE] — Runtime Configuration
# Generated by setup wizard

workspace: {ws}

discord:
  token: {identity['discord_token']}
  guild_id: "{identity['guild_id']}"
  operator_id: "{identity['discord_user_id']}"

voice:{provider_block}

memory:
  comb_path: {ws}/.ava-memory
  session_dir: {ws}/.singularity/sessions

atlas:
  enabled: true
  cycle_interval: 300
  report_interval: 21600

immune:
  enabled: true
  alert_channels:
    - bridge

sentinel:
  enabled: true
  event_dir: {ws}/.singularity/events/exfilguard

csuite:
  enabled: true
  executives:
    - cto
    - coo
    - cfo
    - ciso

poa:
  enabled: true
  audit_interval: 14400
  poa_dir: {ws}/.singularity/poas

logging:
  level: INFO
"""
    cfg_path.write_text(cfg_content)
    ok(f"Config → {cfg_path}")

    # Write .env
    env_path = pkg_root / ".env"
    env_lines = []
    if llm["api_key"] and llm["api_key_name"]:
        env_lines.append(f'{llm["api_key_name"]}={llm["api_key"]}')
    if env_lines:
        with open(env_path, "a") as f:
            f.write("\n".join(env_lines) + "\n")
        os.chmod(env_path, 0o600)
        ok(f".env → {env_path}")

    return cfg_path

# ─────────────────────────────────────────────────────────────
#  STEP 6 — verify + launch
# ─────────────────────────────────────────────────────────────
def step_verify(ws: Path, cfg_path: Path) -> None:
    hdr(6, TOTAL_STEPS, "Verify")

    checks = [
        ("Workspace",        ws.is_dir()),
        ("COMB store",       (ws / ".ava-memory" / "comb-pending.jsonl").exists()),
        ("POA directory",    (ws / ".singularity" / "poas").is_dir()),
        ("ATLAS directory",  (ws / ".singularity" / "atlas").is_dir()),
        ("Config file",      cfg_path.exists()),
        ("Python 3.11+",     sys.version_info >= (3, 11)),
    ]

    all_ok = True
    for label, passed in checks:
        if passed:
            ok(label)
        else:
            err(label)
            all_ok = False

    # Check sentinel
    code, _ = run("systemctl --user is-active sentinel 2>/dev/null")
    if code == 0:
        ok("Sentinel — active")
    else:
        warn("Sentinel — not running (start: systemctl --user start sentinel)")

    print()
    if all_ok:
        print(f"  {GR}{B}Ready.{R}")
        print(f"\n  {DIM}Launch:{R}  {B}python3 -m singularity --run --config {cfg_path}{R}\n")
        print(f"  {DIM}Or with systemd:{R}  {B}singularity-install-service{R}\n")
    else:
        print(f"  {RD}{B}Setup incomplete — fix errors above.{R}\n")

# ─────────────────────────────────────────────────────────────
#  SYSTEMD SERVICE INSTALLER (bonus)
# ─────────────────────────────────────────────────────────────
def install_service(cfg_path: Path) -> None:
    py = sys.executable
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / "singularity.service"
    unit.write_text(textwrap.dedent(f"""\
        [Unit]
        Description=Singularity [AE] Autonomous Enterprise Runtime
        After=network.target

        [Service]
        Type=simple
        WorkingDirectory={Path(cfg_path).parent.parent}
        ExecStart={py} -m singularity --run --config {cfg_path}
        Restart=on-failure
        RestartSec=10

        [Install]
        WantedBy=default.target
    """))
    run("systemctl --user daemon-reload")
    run("systemctl --user enable singularity")
    ok(f"Service installed → {unit}")
    info("Start: systemctl --user start singularity")

# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────
def run_wizard() -> None:
    print(BANNER)

    ws       = step_workspace()
    identity = step_identity()
    llm      = step_llm()
    step_memory(ws)
    cfg_path = step_config(ws, identity, llm)
    step_verify(ws, cfg_path)

    if confirm("Install systemd service?", default=True):
        install_service(cfg_path)

    print(f"\n{CY}{B}Singularity is configured.{R}\n")


if __name__ == "__main__":
    run_wizard()
