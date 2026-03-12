#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Singularity [AE] — One-Command Install
#  Usage:  curl -fsSL https://raw.githubusercontent.com/Artifact-Virtual/singularity/main/install.sh | bash
#  Or:     ./install.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

R='\033[0m'; B='\033[1m'; CY='\033[36m'; GR='\033[32m'; RD='\033[31m'; DIM='\033[2m'
ok()  { echo -e "  ${GR}✓${R} $1"; }
err() { echo -e "  ${RD}✗${R} $1"; exit 1; }
hdr() { echo -e "\n${CY}${B}$1${R}"; }

echo -e "\n${CY}${B}SINGULARITY [AE]${R}  Autonomous Enterprise Runtime\n"

# ── 1. Python 3.11+ ──────────────────────────────────────────
hdr "[ 1/5 ] Runtime"
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3 || true)
[ -z "$PY" ] && err "Python 3.11+ required"
VER=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
[[ "${VER}" < "3.11" ]] && err "Python $VER found — 3.11+ required"
ok "Python $VER → $PY"

# ── 2. System dependencies ───────────────────────────────────
hdr "[ 2/5 ] Dependencies"
MISSING=()
for cmd in git curl node npm; do
  command -v $cmd &>/dev/null && ok "$cmd" || MISSING+=("$cmd")
done
[ ${#MISSING[@]} -gt 0 ] && err "Missing: ${MISSING[*]}"

# pip install
$PY -m pip install --quiet --upgrade pip
$PY -m pip install --quiet -e "$(dirname "$0")"
ok "singularity package installed"

# ── 3. COMB — memory store ───────────────────────────────────
hdr "[ 3/5 ] COMB"
COMB_DIR="${HOME}/.ava-memory"
mkdir -p "$COMB_DIR"
touch "$COMB_DIR/comb-pending.jsonl"
ok "COMB store → $COMB_DIR"

# ── 4. Sentinel — security layer ─────────────────────────────
hdr "[ 4/5 ] Sentinel"
SENTINEL_DIR="$(dirname "$0")/poa/sentinel"
if [ -f "$SENTINEL_DIR/sentinel.py" ]; then
  # Check if systemd available
  if command -v systemctl &>/dev/null; then
    UNIT="${HOME}/.config/systemd/user/sentinel.service"
    mkdir -p "$(dirname "$UNIT")"
    cat > "$UNIT" <<EOF
[Unit]
Description=Singularity Sentinel — ExfilGuard + OpenAnt
After=network.target

[Service]
Type=simple
WorkingDirectory=$SENTINEL_DIR
ExecStart=$PY $SENTINEL_DIR/sentinel.py daemon
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now sentinel 2>/dev/null || true
    ok "sentinel.service enabled"
  else
    ok "Sentinel present (no systemd — start manually: python3 poa/sentinel/sentinel.py daemon)"
  fi
else
  echo -e "  ${DIM}Sentinel not found — skipping${R}"
fi

# ── 5. Wizard ────────────────────────────────────────────────
hdr "[ 5/5 ] Setup"
echo -e "  ${DIM}Launching configuration wizard...${R}\n"
$PY -m singularity init
