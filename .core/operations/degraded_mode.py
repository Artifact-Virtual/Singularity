#!/usr/bin/env python3
"""
GDI C-Suite Degraded Mode Controller

Toggle between cloud and degraded (local) model for C-Suite dispatch.

Usage:
    python3 degraded_mode.py cloud      # Switch to cloud mode (claude-sonnet-4)
    python3 degraded_mode.py degraded   # Switch to degraded mode (ollama qwen2.5-coder:7b)
    python3 degraded_mode.py auto       # Monitor Redis and auto-adjust
    python3 degraded_mode.py status     # Show current mode

Writes status to /tmp/gdi-csuite-status.json
Controls Redis key 'gdi:mode'
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STATUS_FILE = Path("/tmp/gdi-csuite-status.json")
REDIS_KEY = "gdi:mode"
AUTO_CHECK_INTERVAL = 5  # seconds

# Model configs for reference
CONFIGS = {
    "cloud": {
        "model": "claude-sonnet-4",
        "base_url": "http://localhost:3000/v1",
        "max_tokens": 4096,
        "description": "Cloud mode — Claude Sonnet via proxy",
    },
    "degraded": {
        "model": "qwen2.5-coder:7b",
        "base_url": "http://localhost:11434/v1",
        "max_tokens": 2048,
        "description": "Degraded mode — Local Ollama model",
    },
}


def get_redis():
    """Get Redis connection."""
    import redis
    return redis.Redis(host="localhost", port=6379, decode_responses=True)


def get_current_mode() -> str:
    """Read current mode from Redis."""
    try:
        r = get_redis()
        mode = r.get(REDIS_KEY) or "cloud"
        return mode if mode in ("cloud", "degraded") else "cloud"
    except Exception as e:
        print(f"  ❌ Redis error: {e}")
        return "unknown"


def set_mode(mode: str) -> bool:
    """Set mode in Redis and write status file."""
    if mode not in ("cloud", "degraded"):
        print(f"  ❌ Invalid mode: {mode}. Use 'cloud' or 'degraded'.")
        return False

    try:
        r = get_redis()
        old_mode = r.get(REDIS_KEY) or "cloud"
        r.set(REDIS_KEY, mode)
        write_status(mode, f"Manual switch from {old_mode}")
        return True
    except Exception as e:
        print(f"  ❌ Redis error: {e}")
        return False


def write_status(mode: str, reason: str = ""):
    """Write current status to /tmp/gdi-csuite-status.json."""
    config = CONFIGS.get(mode, CONFIGS["cloud"])
    status = {
        "mode": mode,
        "model": config["model"],
        "base_url": config["base_url"],
        "max_tokens": config["max_tokens"],
        "description": config["description"],
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }
    STATUS_FILE.write_text(json.dumps(status, indent=2) + "\n")


def check_ollama_available() -> bool:
    """Check if Ollama is responding."""
    import urllib.request
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        resp = urllib.request.urlopen(req, timeout=3)
        return resp.status == 200
    except Exception:
        return False


def check_proxy_available() -> bool:
    """Check if the cloud proxy is responding."""
    import urllib.request
    try:
        req = urllib.request.Request("http://localhost:3000/v1/models", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status == 200
    except Exception:
        return False


def show_status():
    """Display current mode and system status."""
    mode = get_current_mode()
    config = CONFIGS.get(mode, {})
    mode_icon = "⚠️" if mode == "degraded" else "☁️" if mode == "cloud" else "❓"

    print()
    print(f"  ┌──────────────────────────────────────────────┐")
    print(f"  │  GDI C-Suite Mode: {mode_icon} {mode.upper():<25} │")
    print(f"  ├──────────────────────────────────────────────┤")
    print(f"  │  Model:      {config.get('model', 'unknown'):<32} │")
    print(f"  │  Endpoint:   {config.get('base_url', 'unknown'):<32} │")
    print(f"  │  Max Tokens: {str(config.get('max_tokens', '?')):<32} │")
    print(f"  └──────────────────────────────────────────────┘")

    # Check service availability
    proxy_ok = check_proxy_available()
    ollama_ok = check_ollama_available()
    print()
    print(f"  Services:")
    print(f"    {'✅' if proxy_ok else '❌'} Cloud proxy (localhost:3000)")
    print(f"    {'✅' if ollama_ok else '❌'} Ollama (localhost:11434)")

    # Show status file if exists
    if STATUS_FILE.exists():
        try:
            st = json.loads(STATUS_FILE.read_text())
            print(f"\n  Last status write: {st.get('timestamp', '?')[:19]}")
            if st.get("reason"):
                print(f"  Reason: {st['reason']}")
        except Exception:
            pass

    print()


def auto_mode():
    """Monitor and auto-adjust mode based on service availability.
    
    Logic:
    - If cloud proxy is down → switch to degraded (if ollama available)
    - If cloud proxy comes back → switch to cloud
    - Writes status every check cycle
    """
    print("  🔄 Auto mode — monitoring services...")
    print(f"  Check interval: {AUTO_CHECK_INTERVAL}s")
    print("  Press Ctrl+C to stop.\n")

    def handle_signal(sig, frame):
        print("\n  ⏹️  Auto mode stopped.")
        write_status(get_current_mode(), "Auto mode stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    write_status(get_current_mode(), "Auto mode started")

    while True:
        try:
            proxy_ok = check_proxy_available()
            ollama_ok = check_ollama_available()
            current = get_current_mode()

            if proxy_ok and current == "degraded":
                # Cloud is back — switch to cloud
                set_mode("cloud")
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] ☁️  Cloud proxy recovered → switching to CLOUD")
            elif not proxy_ok and current == "cloud" and ollama_ok:
                # Cloud is down, ollama available — switch to degraded
                set_mode("degraded")
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] ⚠️  Cloud proxy DOWN, Ollama available → switching to DEGRADED")
            elif not proxy_ok and not ollama_ok:
                write_status(current, "WARNING: Both cloud and ollama unavailable")
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] 🔴 Both services DOWN — no model available")
            else:
                # Everything normal
                write_status(current, f"Auto check — stable ({current})")

            time.sleep(AUTO_CHECK_INTERVAL)
        except Exception as e:
            print(f"  ❌ Error in auto loop: {e}")
            time.sleep(AUTO_CHECK_INTERVAL)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "status":
        show_status()
    elif command == "cloud":
        if set_mode("cloud"):
            print(f"\n  ☁️  Switched to CLOUD mode (claude-sonnet-4)")
            print(f"  Max tokens: 4096")
            print(f"  Status written to {STATUS_FILE}\n")
    elif command == "degraded":
        # Check if ollama is available first
        if not check_ollama_available():
            print(f"\n  ⚠️  Warning: Ollama doesn't appear to be running at localhost:11434")
            print(f"  Switching to degraded mode anyway...\n")
        if set_mode("degraded"):
            print(f"\n  ⚠️  Switched to DEGRADED mode (qwen2.5-coder:7b)")
            print(f"  Max tokens: 2048")
            print(f"  System prefix: [DEGRADED MODE - Local model, be concise]")
            print(f"  Status written to {STATUS_FILE}\n")
    elif command == "auto":
        auto_mode()
    else:
        print(f"  ❌ Unknown command: {command}")
        print(f"  Usage: python3 degraded_mode.py [cloud|degraded|auto|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
