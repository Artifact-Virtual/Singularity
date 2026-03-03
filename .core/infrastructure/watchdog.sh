#!/bin/bash
# C-Suite Watchdog — monitors copilot-proxy + plug-csuite services
# Run via cron or systemd timer

LOGFILE="/home/adam/.plug/watchdog.log"
NOW=$(date '+%Y-%m-%d %H:%M:%S')

check_service() {
    local svc=$1
    if systemctl --user is-active --quiet "$svc"; then
        return 0
    else
        echo "[$NOW] ❌ $svc is DOWN — restarting" >> "$LOGFILE"
        systemctl --user restart "$svc"
        sleep 3
        if systemctl --user is-active --quiet "$svc"; then
            echo "[$NOW] ✅ $svc recovered" >> "$LOGFILE"
        else
            echo "[$NOW] 🔴 $svc FAILED to restart" >> "$LOGFILE"
            return 1
        fi
    fi
}

# Check proxy first (plug depends on it)
check_service "copilot-proxy"
PROXY_OK=$?

# Check plug
check_service "plug-csuite"
PLUG_OK=$?

# Verify proxy is actually serving (not just running)
if [ $PROXY_OK -eq 0 ]; then
    MODELS=$(curl -s --max-time 5 http://localhost:3000/v1/models 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null)
    if [ -z "$MODELS" ] || [ "$MODELS" = "0" ]; then
        echo "[$NOW] ⚠️ copilot-proxy running but not serving — restarting" >> "$LOGFILE"
        systemctl --user restart copilot-proxy
        sleep 5
        systemctl --user restart plug-csuite
    fi
fi

# Trim log to last 500 lines
if [ -f "$LOGFILE" ]; then
    tail -500 "$LOGFILE" > "$LOGFILE.tmp" && mv "$LOGFILE.tmp" "$LOGFILE"
fi
