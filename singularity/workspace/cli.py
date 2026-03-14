"""
Workspace CLI — setup, status, and quick actions.

Commands:
    singularity workspace setup    — Interactive OAuth setup wizard
    singularity workspace status   — Check connection status for all services
    singularity workspace test     — Quick connectivity test
    singularity workspace revoke   — Revoke credentials
    singularity workspace podcast  — Generate podcast from research papers
"""
from __future__ import annotations

import json
import sys
import os
import webbrowser
from pathlib import Path
from typing import Optional


def workspace_command(args: list[str]) -> None:
    """Route workspace subcommands."""
    if not args:
        print_usage()
        return

    cmd = args[0]
    handlers = {
        "setup": cmd_setup,
        "status": cmd_status,
        "test": cmd_test,
        "revoke": cmd_revoke,
        "podcast": cmd_podcast,
        "gmail": cmd_gmail,
        "drive": cmd_drive,
    }

    handler = handlers.get(cmd)
    if handler:
        handler(args[1:])
    else:
        print(f"Unknown workspace command: {cmd}")
        print_usage()


def print_usage():
    print("""
⚡ Singularity Workspace — Google Workspace Integration

Commands:
  setup              Interactive OAuth setup wizard
  status             Check connection status for all services
  test               Quick connectivity test
  revoke             Revoke stored credentials
  podcast [files..]  Generate podcast from source files
  gmail              Gmail quick actions
  drive              Drive quick actions

Setup:
  1. Go to Google Cloud Console → APIs & Services → Credentials
  2. Create OAuth 2.0 Client ID (Desktop Application)
  3. Download the JSON and save to: ~/.singularity/workspace_client_secret.json
  4. Run: singularity workspace setup
""")


def cmd_setup(args: list[str]):
    """Interactive workspace setup wizard."""
    from singularity.workspace.auth import WorkspaceAuth, DEFAULT_CLIENT_SECRET_PATH

    print("\n⚡ Singularity Workspace Setup")
    print("=" * 50)

    auth = WorkspaceAuth()

    # Check if already authenticated
    if auth.is_authenticated:
        email = auth.email
        print(f"\n✅ Already authenticated as: {email}")
        resp = input("Re-authenticate? (y/N): ").strip().lower()
        if resp != "y":
            print("Setup complete. Run 'singularity workspace status' to verify.")
            return

    # Step 1: Check for client secret
    print(f"\nStep 1: OAuth Client Secret")
    if DEFAULT_CLIENT_SECRET_PATH.exists():
        print(f"  ✅ Found: {DEFAULT_CLIENT_SECRET_PATH}")
    else:
        print(f"  ❌ Not found: {DEFAULT_CLIENT_SECRET_PATH}")
        print()
        print("  To create OAuth credentials:")
        print("  1. Go to: https://console.cloud.google.com/apis/credentials")
        print(f"     Project: artifact-virtual")
        print("  2. Click '+ CREATE CREDENTIALS' → 'OAuth client ID'")
        print("  3. Application type: 'Desktop app'")
        print("  4. Name: 'Singularity Workspace'")
        print("  5. Download the JSON")
        print(f"  6. Save to: {DEFAULT_CLIENT_SECRET_PATH}")
        print()

        # Offer to open browser
        resp = input("Open Google Cloud Console in browser? (y/N): ").strip().lower()
        if resp == "y":
            webbrowser.open("https://console.cloud.google.com/apis/credentials?project=artifact-virtual")

        print()
        input("Press Enter once the client_secret.json is saved...")

        if not DEFAULT_CLIENT_SECRET_PATH.exists():
            print(f"\n❌ Still not found: {DEFAULT_CLIENT_SECRET_PATH}")
            print("Please save the downloaded JSON and try again.")
            return

    # Step 2: OAuth consent flow
    print(f"\nStep 2: OAuth Authentication")
    print("  A browser window will open for Google sign-in.")
    print("  Grant access to all requested services.")
    print()
    input("Press Enter to start authentication...")

    try:
        creds = auth.authenticate_interactive(port=8091)
        print(f"\n✅ Authentication successful!")

        # Verify email
        email = auth.email
        if email:
            print(f"  Authenticated as: {email}")

    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        return
    except Exception as e:
        print(f"\n❌ Authentication failed: {e}")
        return

    # Step 3: Verify services
    print(f"\nStep 3: Verifying service access...")
    _print_status(auth)

    # Step 4: Gemini API key (for NotebookLM features)
    print(f"\nStep 4: Gemini API Key (for podcast generation)")
    gemini_key_path = Path.home() / ".singularity" / "gemini_api_key"
    if gemini_key_path.exists() or os.environ.get("GEMINI_API_KEY"):
        print("  ✅ Gemini API key configured")
    else:
        print("  ⚠️  No Gemini API key found")
        print("  Get one from: https://aistudio.google.com/apikey")
        key = input("  Paste API key (or Enter to skip): ").strip()
        if key:
            gemini_key_path.parent.mkdir(parents=True, exist_ok=True)
            gemini_key_path.write_text(key)
            gemini_key_path.chmod(0o600)
            print("  ✅ Gemini API key saved")
        else:
            print("  Skipped. Podcast generation will use OAuth-based Gemini access.")

    print(f"\n{'=' * 50}")
    print("⚡ Workspace setup complete!")
    print()
    print("Quick start:")
    print("  singularity workspace status    — check all services")
    print("  singularity workspace gmail     — check Gmail")
    print("  singularity workspace podcast paper1.md paper2.md")


def cmd_status(args: list[str]):
    """Show workspace connection status."""
    from singularity.workspace.auth import WorkspaceAuth
    auth = WorkspaceAuth()

    if not auth.is_authenticated:
        print("❌ Not authenticated. Run: singularity workspace setup")
        return

    _print_status(auth)


def _print_status(auth):
    """Print service status."""
    from singularity.workspace.client import WorkspaceClient
    client = WorkspaceClient(auth)
    status = client.status()

    print(f"\n  Account: {status.get('email', 'unknown')}")
    print(f"  Authenticated: {'✅' if status['authenticated'] else '❌'}")
    print()
    for service, state in status.get("services", {}).items():
        print(f"  {service:12s} {state}")


def cmd_test(args: list[str]):
    """Quick connectivity test."""
    from singularity.workspace.auth import WorkspaceAuth
    from singularity.workspace.client import WorkspaceClient

    auth = WorkspaceAuth()
    if not auth.is_authenticated:
        print("❌ Not authenticated.")
        return

    client = WorkspaceClient(auth)
    print("Testing Gmail...")
    try:
        profile = client.gmail.profile()
        print(f"  ✅ Gmail: {profile['emailAddress']} ({profile['messagesTotal']} messages)")
    except Exception as e:
        print(f"  ❌ Gmail: {e}")

    print("Testing Drive...")
    try:
        about = client.drive.about()
        print(f"  ✅ Drive: {about['user']['emailAddress']}")
    except Exception as e:
        print(f"  ❌ Drive: {e}")

    print("Testing Calendar...")
    try:
        events = client.calendar.today()
        print(f"  ✅ Calendar: {len(events)} events today")
    except Exception as e:
        print(f"  ❌ Calendar: {e}")


def cmd_revoke(args: list[str]):
    """Revoke stored credentials."""
    from singularity.workspace.auth import WorkspaceAuth
    auth = WorkspaceAuth()

    resp = input("Revoke Workspace credentials? This will require re-authentication. (y/N): ").strip().lower()
    if resp == "y":
        auth.revoke()
        print("✅ Credentials revoked.")
    else:
        print("Cancelled.")


def cmd_podcast(args: list[str]):
    """Generate podcast from source files."""
    if not args:
        print("Usage: singularity workspace podcast <file1> [file2] [--duration 10] [--output podcast.wav]")
        print()
        print("Options:")
        print("  --duration N     Target duration in minutes (default: 10)")
        print("  --output PATH    Output file path (default: podcast.wav)")
        print("  --style STYLE    Script style: conversational, interview, debate (default: conversational)")
        print("  --script-only    Generate script only, no audio")
        return

    # Parse args
    sources = []
    duration = 10
    output = "podcast.wav"
    style = "conversational"
    script_only = False
    i = 0
    while i < len(args):
        if args[i] == "--duration" and i + 1 < len(args):
            duration = int(args[i + 1])
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output = args[i + 1]
            i += 2
        elif args[i] == "--style" and i + 1 < len(args):
            style = args[i + 1]
            i += 2
        elif args[i] == "--script-only":
            script_only = True
            i += 1
        else:
            sources.append(args[i])
            i += 1

    if not sources:
        print("❌ No source files provided")
        return

    from singularity.workspace.services.notebook import NotebookService
    notebook = NotebookService()

    print(f"⚡ Generating {duration}-minute {style} podcast from {len(sources)} sources...")
    print()

    # Generate script
    result = notebook.generate_podcast_script(
        sources=sources,
        style=style,
        duration_minutes=duration,
    )

    print(f"Title: {result['title']}")
    print(f"Description: {result['description']}")
    print(f"Sources: {', '.join(result['sources'])}")
    print()

    # Save script
    script_path = Path(output).with_suffix(".md")
    script_path.write_text(result["script"])
    print(f"📝 Script saved: {script_path}")

    if not script_only:
        print(f"\n🎙️ Generating audio...")
        audio_path = notebook.generate_multi_speaker_audio(
            result["script"],
            output_path=output,
        )
        if audio_path:
            print(f"🔊 Audio saved: {audio_path} ({audio_path.stat().st_size} bytes)")
        else:
            print("⚠️  Audio generation unavailable. Script saved as text.")


def cmd_gmail(args: list[str]):
    """Quick Gmail actions."""
    from singularity.workspace.auth import WorkspaceAuth
    from singularity.workspace.client import WorkspaceClient

    auth = WorkspaceAuth()
    if not auth.is_authenticated:
        print("❌ Not authenticated. Run: singularity workspace setup")
        return

    client = WorkspaceClient(auth)

    if not args or args[0] == "inbox":
        # Show inbox
        print("📬 Recent inbox messages:")
        messages = client.gmail.search("is:inbox", max_results=10)
        for msg in messages:
            unread = "●" if "UNREAD" in msg.get("labels", []) else " "
            print(f"  {unread} {msg['date'][:16]}  {msg['from'][:30]:30s}  {msg['subject'][:50]}")

    elif args[0] == "unread":
        count = client.gmail.unread_count()
        print(f"📬 Unread messages: {count}")

    elif args[0] == "search" and len(args) > 1:
        query = " ".join(args[1:])
        messages = client.gmail.search(query, max_results=10)
        print(f"📬 Search results for '{query}':")
        for msg in messages:
            print(f"  {msg['date'][:16]}  {msg['from'][:30]:30s}  {msg['subject'][:50]}")

    else:
        print("Gmail commands: inbox, unread, search <query>")


def cmd_drive(args: list[str]):
    """Quick Drive actions."""
    from singularity.workspace.auth import WorkspaceAuth
    from singularity.workspace.client import WorkspaceClient

    auth = WorkspaceAuth()
    if not auth.is_authenticated:
        print("❌ Not authenticated. Run: singularity workspace setup")
        return

    client = WorkspaceClient(auth)

    if not args or args[0] == "list":
        files = client.drive.list(max_results=15)
        print("📁 Recent files:")
        for f in files:
            size = f.get("size", "—")
            if size != "—":
                size = f"{int(size) / 1024:.0f}K"
            print(f"  {f['name'][:40]:40s}  {size:>8s}  {f.get('modifiedTime', '')[:10]}")

    elif args[0] == "search" and len(args) > 1:
        query = " ".join(args[1:])
        files = client.drive.search(f"name contains '{query}'")
        print(f"📁 Search results for '{query}':")
        for f in files:
            print(f"  {f['name'][:50]:50s}  {f.get('modifiedTime', '')[:10]}")

    elif args[0] == "usage":
        usage = client.drive.storage_usage()
        used_gb = usage["used"] / (1024**3)
        limit_gb = usage["limit"] / (1024**3) if usage["limit"] else 0
        print(f"📁 Drive storage: {used_gb:.2f} GB / {limit_gb:.1f} GB")

    else:
        print("Drive commands: list, search <query>, usage")
