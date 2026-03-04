#!/usr/bin/env python3
"""
Singularity C-Suite Dispatch — Native CLI

Drops dispatch requests into .singularity/csuite/inbox/ for the running
Singularity runtime to pick up and execute. Results appear in
.singularity/csuite/results/.

Usage:
    python3 dispatch.py cto "Review HEKTOR architecture"
    python3 dispatch.py ciso "Run security audit" -p high
    python3 dispatch.py all "Prepare Q1 status reports"
    python3 dispatch.py auto "We need better CI pipelines"
    python3 dispatch.py status
    python3 dispatch.py history

Targets: cto, coo, cfo, ciso, all, auto
Priority: low, normal, high, critical (default: normal)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

WORKSPACE = Path.home() / "workspace"
SG_DIR = WORKSPACE / ".singularity" / "csuite"
INBOX = SG_DIR / "inbox"
RESULTS = SG_DIR / "results"
DISPATCHES = SG_DIR / "dispatches"


def dispatch(target: str, description: str, priority: str = "normal",
             wait: bool = True, timeout: float = 120.0) -> dict:
    """Submit a dispatch request and optionally wait for the result."""
    INBOX.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    request_id = f"{int(time.time())}-{os.getpid()}"
    request = {
        "action": "dispatch",
        "target": target,
        "description": description,
        "priority": priority,
        "requester": "ava-cli",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    request_file = INBOX / f"{request_id}.json"
    request_file.write_text(json.dumps(request, indent=2))
    print(f"  📬 Request {request_id} submitted → {target.upper()}")

    if not wait:
        return {"status": "queued", "request_id": request_id}

    # Poll for result
    result_file = RESULTS / f"{request_id}.json"
    start = time.time()

    while time.time() - start < timeout:
        if result_file.exists():
            try:
                result = json.loads(result_file.read_text())
                result_file.unlink()  # Clean up
                return result
            except json.JSONDecodeError:
                time.sleep(0.5)
                continue
        time.sleep(1)

    return {"error": "Timed out waiting for result", "request_id": request_id}


def show_status():
    """Show recent dispatch results."""
    if not DISPATCHES.exists():
        print("  No dispatch history.")
        return

    files = sorted(DISPATCHES.glob("*.json"), reverse=True)
    if not files:
        print("  No dispatches recorded.")
        return

    print(f"\n  📋 C-Suite Dispatch History ({len(files)} total)\n")

    for f in files[:10]:
        try:
            data = json.loads(f.read_text())
            did = data.get("dispatch_id", f.stem[-8:])
            tasks = data.get("tasks", [])
            ok = data.get("all_succeeded", False)
            dur = data.get("duration", 0)

            icon = "✅" if ok else "❌"
            roles = ", ".join(t.get("role", "?").upper() for t in tasks)
            print(f"  {icon} {did}  [{roles}]  {dur:.1f}s")

            for t in tasks:
                s = t.get("status", "?")
                r = t.get("role", "?").upper()
                itr = t.get("iterations_used", 0)
                d = t.get("duration_seconds", 0)
                resp = (t.get("response") or "(empty)")[:120].replace("\n", " ")
                si = "✅" if s == "complete" else "❌"
                print(f"      {si} {r}: {itr} iters, {d:.1f}s — {resp}")
            print()
        except Exception as e:
            print(f"  ⚠️  {f.name}: {e}")

    if len(files) > 10:
        print(f"  ... +{len(files) - 10} older")


def main():
    parser = argparse.ArgumentParser(
        prog="dispatch",
        description="Singularity C-Suite — Native Dispatch CLI",
    )
    parser.add_argument(
        "target",
        choices=["cto", "coo", "cfo", "ciso", "all", "auto", "status", "history"],
        help="Executive target or command",
    )
    parser.add_argument("description", nargs="?", default="", help="Task description")
    parser.add_argument("-p", "--priority", choices=["low", "normal", "high", "critical"],
                        default="normal", help="Priority (default: normal)")
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for result")
    parser.add_argument("--timeout", type=float, default=120, help="Wait timeout (default: 120s)")
    parser.add_argument("--json", action="store_true", help="Raw JSON output")

    args = parser.parse_args()

    if args.target in ("status", "history"):
        show_status()
        return

    if not args.description:
        parser.error("description required for dispatch")

    print(f"\n  🚀 Dispatching to {args.target.upper()} (priority: {args.priority})")
    print(f"  📝 {args.description[:100]}\n")

    result = dispatch(args.target, args.description, args.priority,
                      wait=not args.no_wait, timeout=args.timeout)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if "error" in result:
        print(f"  ❌ {result['error']}")
        sys.exit(1)
    elif result.get("status") == "queued":
        print(f"  📬 Queued. Check results in {RESULTS}/")
    else:
        ok = result.get("all_succeeded", False)
        dur = result.get("duration", 0)
        print(f"  {'✅' if ok else '❌'} Complete in {dur:.1f}s\n")
        for t in result.get("tasks", []):
            si = "✅" if t.get("status") == "complete" else "❌"
            r = t.get("role", "?").upper()
            resp = (t.get("response") or "(empty)")[:200].replace("\n", " ")
            print(f"  {si} {r}: {resp}")
        print()


if __name__ == "__main__":
    main()
