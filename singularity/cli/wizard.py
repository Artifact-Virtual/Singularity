"""
CLI — Init Wizard
===================

Interactive setup wizard for bootstrapping a Singularity workspace.

Asks for:
    - Workspace path
    - Enterprise name and industry
    - Channels (Discord, WhatsApp — optional)
    - LLM provider config
    - Generates singularity.yaml
    - Creates .singularity/ directory
    - Runs first audit

Completable in under 60 seconds. Sensible defaults for everything.
"""

from __future__ import annotations

import os
import json
import hashlib
import time
from pathlib import Path
from typing import Any, Optional

from .formatters import (
    fmt, BOX, banner, section, kv, success, error, warn, info, dim,
    ProgressBar, bold, human_bytes,
)


# ── Default Industry Presets ──────────────────────────────────────

INDUSTRY_PRESETS: dict[str, dict[str, Any]] = {
    "tech": {
        "label": "Technology / Software",
        "execs": ["cto", "coo", "cfo", "ciso"],
        "poa_templates": ["saas-product"],
    },
    "finance": {
        "label": "Finance / Fintech",
        "execs": ["cto", "coo", "cfo", "ciso"],
        "poa_templates": ["trading-system", "compliance-product"],
    },
    "health": {
        "label": "Healthcare / Biotech",
        "execs": ["cto", "coo", "cfo", "ciso"],
        "poa_templates": ["patient-platform"],
    },
    "creative": {
        "label": "Creative / Media",
        "execs": ["cto", "coo", "cfo"],
        "poa_templates": ["content-platform"],
    },
    "other": {
        "label": "Other",
        "execs": ["cto", "coo", "cfo", "ciso"],
        "poa_templates": [],
    },
}


# ── Helpers ───────────────────────────────────────────────────────

def _prompt(
    label: str,
    default: str = "",
    required: bool = False,
    secret: bool = False,
    validator: Optional[callable] = None,
) -> str:
    """Prompt the user for input with optional default, validation, and masking."""
    while True:
        if default:
            prompt_str = f"  {fmt.CYAN}›{fmt.RESET} {label} [{dim(default)}]: "
        else:
            prompt_str = f"  {fmt.CYAN}›{fmt.RESET} {label}: "

        try:
            if secret:
                import getpass
                value = getpass.getpass(prompt_str)
            else:
                value = input(prompt_str)
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit(1)

        value = value.strip()
        if not value and default:
            value = default
        if not value and required:
            print(f"    {error('This field is required.')}")
            continue
        if validator and value:
            err = validator(value)
            if err:
                print(f"    {error(err)}")
                continue
        return value


def _confirm(label: str, default: bool = True) -> bool:
    """Yes/No confirmation prompt."""
    hint = "Y/n" if default else "y/N"
    prompt_str = f"  {fmt.CYAN}›{fmt.RESET} {label} [{dim(hint)}]: "
    try:
        value = input(prompt_str).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(1)
    if not value:
        return default
    return value in ("y", "yes", "1", "true")


def _choose(label: str, options: list[tuple[str, str]], default: str = "") -> str:
    """
    Multiple-choice prompt.
    options: list of (key, display_label)
    Returns: selected key
    """
    print(f"  {fmt.CYAN}›{fmt.RESET} {label}")
    for i, (key, display) in enumerate(options, 1):
        marker = f"{fmt.BR_GREEN}*{fmt.RESET} " if key == default else "  "
        print(f"    {marker}{fmt.BOLD}{i}{fmt.RESET}. {display}")
    while True:
        choice = _prompt("Choice", default=str(
            next((i for i, (k, _) in enumerate(options, 1) if k == default), 1)
        ))
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except ValueError:
            # Try matching by key
            for key, _ in options:
                if key.lower() == choice.lower():
                    return key
        print(f"    {error('Invalid choice. Enter a number or key.')}")


def _detect_workspace(path: str) -> dict[str, Any]:
    """Detect existing workspace structure and return pre-fill data."""
    ws = Path(path)
    detected: dict[str, Any] = {"exists": ws.exists()}

    if not ws.exists():
        return detected

    # Look for existing config
    for cfg_name in ("singularity.yaml", "singularity.json", "config/singularity.yaml"):
        cfg = ws / cfg_name
        if cfg.exists():
            detected["config_file"] = str(cfg)

    # Look for .env
    env_file = ws / ".env"
    if env_file.exists():
        detected["env_file"] = str(env_file)
        env_vars = _parse_env_file(env_file)
        if "DISCORD_BOT_TOKEN" in env_vars:
            detected["discord_token"] = env_vars["DISCORD_BOT_TOKEN"]
        if "DISCORD_CHANNEL_ID" in env_vars:
            detected["discord_channel"] = env_vars["DISCORD_CHANNEL_ID"]

    # Look for existing directories
    detected["has_poa"] = (ws / "poa").is_dir()
    detected["has_executives"] = (ws / "executives").is_dir()
    detected["has_singularity_dir"] = (ws / ".singularity").is_dir()

    # Count files for scale analysis
    try:
        file_count = sum(1 for _ in ws.rglob("*") if _.is_file())
        detected["file_count"] = file_count
    except Exception:
        detected["file_count"] = 0

    return detected


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into key-value pairs."""
    result = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                result[key] = value
    except Exception:
        pass
    return result


def _generate_yaml(config: dict[str, Any]) -> str:
    """
    Generate singularity.yaml from a config dict.
    Hand-rolled YAML emission — no PyYAML dependency required.
    """
    lines = [
        "# Singularity [AE] Configuration",
        f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"# Enterprise: {config.get('enterprise_name', 'Unnamed')}",
        "",
    ]

    def _emit(data: Any, indent: int = 0) -> list[str]:
        prefix = "  " * indent
        result = []
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    result.append(f"{prefix}{k}:")
                    result.extend(_emit(v, indent + 1))
                elif isinstance(v, list):
                    result.append(f"{prefix}{k}:")
                    for item in v:
                        if isinstance(item, dict):
                            result.append(f"{prefix}  -")
                            for ik, iv in item.items():
                                result.append(f"{prefix}    {ik}: {_val(iv)}")
                        else:
                            result.append(f"{prefix}  - {_val(item)}")
                else:
                    result.append(f"{prefix}{k}: {_val(v)}")
        return result

    def _val(v: Any) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        s = str(v)
        # Quote strings with special YAML characters
        if any(c in s for c in (":", "#", "[", "]", "{", "}", ",", "&", "*", "!", "|", ">", "'", '"', "%", "@", "`")):
            return f'"{s}"'
        if not s or s.lower() in ("true", "false", "null", "yes", "no", "on", "off"):
            return f'"{s}"'
        return s

    lines.extend(_emit(config.get("yaml_data", config)))
    lines.append("")
    return "\n".join(lines)


# ── The Wizard ────────────────────────────────────────────────────

class InitWizard:
    """
    Interactive setup wizard for Singularity.

    Collects configuration through guided prompts,
    generates config files, and bootstraps the workspace.
    """

    def __init__(self):
        self.config: dict[str, Any] = {}
        self.workspace: Path = Path.cwd()
        self.enterprise_name: str = ""
        self.industry: str = ""

    def run(self) -> bool:
        """Run the full wizard. Returns True on success."""
        try:
            self._print_header()
            self._step_workspace()
            self._step_enterprise()
            self._step_channels()
            self._step_llm()
            self._step_review()
            self._step_write()
            self._step_audit()
            self._print_footer()
            return True
        except KeyboardInterrupt:
            print(f"\n\n{warn('Setup cancelled.')}")
            return False
        except SystemExit:
            return False

    # ── Steps ─────────────────────────────────────────────────

    def _print_header(self) -> None:
        print()
        print(banner([
            "SINGULARITY [AE]",
            "Autonomous Enterprise Setup",
            "",
            "This wizard will configure your workspace.",
            "Press Enter to accept defaults. Ctrl+C to cancel.",
        ]))
        print()

    def _step_workspace(self) -> None:
        print(section("1/5  Workspace"))
        print()

        default_ws = str(Path.cwd())
        ws_path = _prompt("Workspace path", default=default_ws)
        self.workspace = Path(ws_path).resolve()

        # Detect existing structure
        detected = _detect_workspace(str(self.workspace))

        if detected.get("config_file"):
            print(f"    {info('Existing config found:')} {dim(detected['config_file'])}")
            if not _confirm("Overwrite existing configuration?", default=False):
                print(f"    {error('Aborting — existing config preserved.')}")
                raise SystemExit(0)

        if detected.get("env_file"):
            print(f"    {info('.env file detected — will auto-import credentials')}")

        if detected.get("file_count", 0) > 0:
            print(f"    {info(f'{detected["file_count"]:,} files in workspace')}")

        self.config["workspace"] = str(self.workspace)
        self.config["_detected"] = detected
        print()

    def _step_enterprise(self) -> None:
        print(section("2/5  Enterprise Identity"))
        print()

        self.enterprise_name = _prompt(
            "Enterprise name",
            default=self.workspace.name.replace("-", " ").replace("_", " ").title(),
            required=True,
        )

        self.industry = _choose(
            "Industry",
            [(k, v["label"]) for k, v in INDUSTRY_PRESETS.items()],
            default="tech",
        )

        preset = INDUSTRY_PRESETS[self.industry]
        label = preset["label"]
        exec_list = ", ".join(e.upper() for e in preset["execs"])
        print(f"    {success('Industry: ' + label)}")
        print(f"    {info('Default executives: ' + exec_list)}")

        self.config["enterprise_name"] = self.enterprise_name
        self.config["industry"] = self.industry
        self.config["executives"] = preset["execs"]
        print()

    def _step_channels(self) -> None:
        print(section("3/5  Communication Channels"))
        print()

        detected = self.config.get("_detected", {})

        # Discord
        setup_discord = _confirm("Configure Discord?", default=True)
        discord_config: dict[str, Any] = {"token": "", "guild_ids": [], "authorized_users": []}

        if setup_discord:
            default_token = detected.get("discord_token", "")
            hint = " (auto-detected from .env)" if default_token else ""
            token_display = f"{default_token[:8]}...{default_token[-4:]}" if len(default_token) > 12 else default_token

            if default_token:
                print(f"    {info(f'Token detected{hint}: {dim(token_display)}')}")
                use_detected = _confirm("Use detected token?", default=True)
                if use_detected:
                    discord_config["token"] = default_token
                else:
                    discord_config["token"] = _prompt("Discord bot token", secret=True, required=True)
            else:
                discord_config["token"] = _prompt("Discord bot token", secret=True)

            if discord_config["token"]:
                guild_id = _prompt("Primary guild (server) ID", default=detected.get("discord_channel", ""))
                if guild_id:
                    discord_config["guild_ids"] = [guild_id]

                owner_id = _prompt("Your Discord user ID (for owner privileges)")
                if owner_id:
                    discord_config["authorized_users"] = [owner_id]

                discord_config["require_mention"] = _confirm("Require @mention in channels?", default=True)
                discord_config["dm_policy"] = "allowlist" if _confirm("Restrict DMs to allowlist?", default=True) else "open"

                if discord_config["dm_policy"] == "allowlist" and owner_id:
                    discord_config["dm_allowlist"] = [owner_id]

        self.config["discord"] = discord_config

        # WhatsApp
        print()
        setup_wa = _confirm("Configure WhatsApp?", default=False)
        if setup_wa:
            print(f"    {info('WhatsApp requires a separate adapter (Baileys/WA Web).')}")
            print(f"    {info('The adapter will be configured in singularity.yaml.')}")
            wa_number = _prompt("Bot phone number (with country code)", default="")
            self.config["whatsapp"] = {"number": wa_number, "enabled": bool(wa_number)}
        else:
            self.config["whatsapp"] = {"enabled": False}

        print()

    def _step_llm(self) -> None:
        print(section("4/5  LLM Provider"))
        print()

        provider_type = _choose(
            "Primary LLM provider",
            [
                ("proxy", "Copilot Proxy (GitHub Copilot → any model)"),
                ("ollama", "Ollama (local, sovereign)"),
                ("openai", "OpenAI API (direct)"),
                ("anthropic", "Anthropic API (direct)"),
            ],
            default="proxy",
        )

        voice_config: dict[str, Any] = {
            "primary_model": "claude-sonnet-4",
            "temperature": 0.5,
            "max_tokens": 4096,
        }

        if provider_type == "proxy":
            voice_config["proxy"] = {
                "base_url": _prompt("Proxy URL", default="http://localhost:3000/v1"),
                "api_key": _prompt("API key", default="n/a"),
                "timeout": 120.0,
            }
            voice_config["primary_model"] = _prompt("Model", default="claude-sonnet-4")

        elif provider_type == "ollama":
            voice_config["ollama"] = {
                "enabled": True,
                "base_url": _prompt("Ollama URL", default="http://localhost:11434"),
                "models": [_prompt("Model", default="qwen2.5-coder:7b")],
                "timeout": 120.0,
            }
            voice_config["primary_model"] = voice_config["ollama"]["models"][0]

        elif provider_type in ("openai", "anthropic"):
            voice_config["proxy"] = {
                "base_url": _prompt(
                    "API base URL",
                    default="https://api.openai.com/v1" if provider_type == "openai" else "https://api.anthropic.com/v1",
                ),
                "api_key": _prompt("API key", secret=True, required=True),
                "timeout": 120.0,
            }
            if provider_type == "openai":
                voice_config["primary_model"] = _prompt("Model", default="gpt-4.1-mini")
            else:
                voice_config["primary_model"] = _prompt("Model", default="claude-sonnet-4")

        # Ollama fallback (if primary isn't already Ollama)
        if provider_type != "ollama":
            if _confirm("Enable Ollama as fallback?", default=False):
                voice_config["ollama"] = {
                    "enabled": True,
                    "base_url": _prompt("Ollama URL", default="http://localhost:11434"),
                    "models": [_prompt("Fallback model", default="qwen2.5-coder:7b")],
                    "timeout": 120.0,
                }

        self.config["voice"] = voice_config
        print()

    def _step_review(self) -> None:
        print(section("5/5  Review"))
        print()

        print(kv("Workspace", str(self.workspace)))
        print(kv("Enterprise", self.enterprise_name))
        print(kv("Industry", INDUSTRY_PRESETS[self.industry]["label"]))
        print(kv("Executives", ", ".join(e.upper() for e in self.config.get("executives", []))))

        discord = self.config.get("discord", {})
        if discord.get("token"):
            token = discord["token"]
            masked = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"
            print(kv("Discord", f"Enabled (token: {masked})"))
        else:
            print(kv("Discord", dim("Not configured")))

        wa = self.config.get("whatsapp", {})
        if wa.get("enabled"):
            print(kv("WhatsApp", f"Enabled ({wa.get('number', '?')})"))
        else:
            print(kv("WhatsApp", dim("Not configured")))

        voice = self.config.get("voice", {})
        print(kv("LLM Model", voice.get("primary_model", "?")))

        proxy = voice.get("proxy", {})
        ollama = voice.get("ollama", {})
        if proxy:
            print(kv("LLM Provider", f"Proxy → {proxy.get('base_url', '?')}"))
        if ollama and ollama.get("enabled"):
            print(kv("LLM Fallback", f"Ollama → {ollama.get('base_url', '?')}"))

        print()
        if not _confirm("Proceed with setup?", default=True):
            raise SystemExit(0)
        print()

    def _step_write(self) -> None:
        print(f"  {info('Writing configuration...')}")

        # Build YAML data structure
        yaml_data = self._build_config_dict()

        # Create directories
        config_dir = self.workspace / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        singularity_dir = self.workspace / ".singularity"
        singularity_dir.mkdir(parents=True, exist_ok=True)
        (singularity_dir / "sessions.db").touch()
        (singularity_dir / "comb").mkdir(exist_ok=True)

        # Write config file
        config_file = config_dir / "singularity.yaml"
        self.config["yaml_data"] = yaml_data
        yaml_content = _generate_yaml(self.config)
        config_file.write_text(yaml_content, encoding="utf-8")
        print(f"    {success(f'Config written: {config_file}')}")

        # Write workspace marker
        marker = singularity_dir / "workspace.json"
        marker.write_text(json.dumps({
            "enterprise": self.enterprise_name,
            "industry": self.industry,
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "workspace": str(self.workspace),
            "config_file": str(config_file),
            "version": "0.1.0",
        }, indent=2), encoding="utf-8")
        print(f"    {success(f'Workspace marker: {marker}')}")

        # Create executive directories
        execs = self.config.get("executives", [])
        if execs:
            exec_dir = self.workspace / "executives"
            exec_dir.mkdir(exist_ok=True)
            for role in execs:
                role_dir = exec_dir / role
                role_dir.mkdir(exist_ok=True)
            print(f"    {success('Executive dirs: ' + ', '.join(e.upper() for e in execs))}")

        print()

    def _step_audit(self) -> None:
        print(f"  {info('Running first audit...')}")
        print()

        ws = self.workspace
        checks = []

        # Config exists
        cfg = ws / "config" / "singularity.yaml"
        checks.append(("Config file", cfg.exists()))

        # Workspace dir
        sd = ws / ".singularity"
        checks.append(("Workspace directory", sd.is_dir()))

        # Sessions DB
        sdb = sd / "sessions.db"
        checks.append(("Sessions database", sdb.exists()))

        # COMB directory
        comb = sd / "comb"
        checks.append(("COMB store", comb.is_dir()))

        # Executive directories
        execs = self.config.get("executives", [])
        if execs:
            all_exist = all((ws / "executives" / e).is_dir() for e in execs)
            checks.append(("Executive directories", all_exist))

        # Config parseable
        try:
            content = cfg.read_text()
            # Simple validation — check it's not empty and has key markers
            valid = len(content) > 50 and "voice:" in content
            checks.append(("Config parseable", valid))
        except Exception:
            checks.append(("Config parseable", False))

        # Workspace marker
        marker = sd / "workspace.json"
        try:
            data = json.loads(marker.read_text())
            checks.append(("Workspace marker", bool(data.get("enterprise"))))
        except Exception:
            checks.append(("Workspace marker", False))

        # Print results
        all_pass = True
        for name, passed in checks:
            icon = success(name) if passed else error(name)
            print(f"    {icon}")
            if not passed:
                all_pass = False

        print()
        if all_pass:
            print(f"  {success(f'Audit: {len(checks)}/{len(checks)} checks passed')}")
        else:
            failed = sum(1 for _, p in checks if not p)
            print(f"  {warn(f'Audit: {len(checks) - failed}/{len(checks)} passed, {failed} failed')}")

    def _print_footer(self) -> None:
        print()
        print(banner([
            "Setup Complete ⚡",
            "",
            f"  Workspace:  {self.workspace}",
            f"  Config:     config/singularity.yaml",
            "",
            "  Next steps:",
            "    singularity status       — Check runtime",
            "    singularity poa create X  — Add a product",
            "    python3 -m singularity     — Start Singularity",
        ], color=fmt.BR_GREEN))
        print()

    # ── Config Builder ────────────────────────────────────────

    def _build_config_dict(self) -> dict[str, Any]:
        """Build the config dictionary for YAML emission."""
        voice = self.config.get("voice", {})
        discord = self.config.get("discord", {})

        cfg: dict[str, Any] = {
            "# Enterprise": None,
            "log_level": "INFO",
        }

        # Voice
        voice_dict: dict[str, Any] = {
            "primary_model": voice.get("primary_model", "claude-sonnet-4"),
            "temperature": voice.get("temperature", 0.5),
            "max_tokens": voice.get("max_tokens", 4096),
        }
        if voice.get("proxy"):
            voice_dict["proxy"] = voice["proxy"]
        if voice.get("ollama") and voice["ollama"].get("enabled"):
            voice_dict["ollama"] = voice["ollama"]
        else:
            voice_dict["ollama"] = {"enabled": False}

        cfg["voice"] = voice_dict

        # Discord
        if discord.get("token"):
            cfg["discord"] = {
                "token": discord["token"],
                "guild_ids": discord.get("guild_ids", []),
                "authorized_users": discord.get("authorized_users", []),
                "require_mention": discord.get("require_mention", True),
                "dm_policy": discord.get("dm_policy", "allowlist"),
                "dm_allowlist": discord.get("dm_allowlist", []),
                "status_message": "⚡ Singularity Online",
            }
        else:
            cfg["discord"] = {"token": ""}

        # Memory
        cfg["memory"] = {
            "comb_store_path": str(self.workspace / ".singularity" / "comb"),
            "session_db": str(self.workspace / ".singularity" / "sessions.db"),
            "max_context_tokens": 100000,
            "recall_on_boot": True,
        }

        # Tools
        cfg["tools"] = {
            "workspace": str(self.workspace),
            "exec_timeout": 30,
        }

        # Pulse
        cfg["pulse"] = {
            "default_cap": 20,
            "expanded_cap": 40,
        }

        # Immune
        cfg["immune"] = {
            "check_interval": 30.0,
            "max_restart_attempts": 5,
        }

        # C-Suite
        cfg["csuite"] = {
            "enabled": True,
            "report_dir": str(self.workspace / "executives"),
        }

        # Identity
        cfg["identity_files"] = ["SOUL.md", "AGENTS.md", "USER.md"]

        return cfg
