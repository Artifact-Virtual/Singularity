#!/bin/bash
# Weekly System Maintenance - Execute Sundays 02:00 UTC

LOG_FILE="/var/log/system-maintenance.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "=== WEEKLY SYSTEM MAINTENANCE $TIMESTAMP ===" | tee -a "$LOG_FILE"

# 1. SYSTEM STATUS ASSESSMENT
echo "--- INITIAL SYSTEM STATE ---" | tee -a "$LOG_FILE"
free -h | tee -a "$LOG_FILE"
SWAP_PCT=$(cat /proc/swaps | tail -1 | awk '{printf "%.1f", $3/$2*100}')
echo "Swap Usage: ${SWAP_PCT}%" | tee -a "$LOG_FILE"
df -h | tee -a "$LOG_FILE"

# 2. CACHE CLEANUP
echo "--- CACHE CLEANUP ---" | tee -a "$LOG_FILE"
echo "Pre-cleanup cache sizes:" | tee -a "$LOG_FILE"
du -sh ~/.cache/* 2>/dev/null | sort -hr | head -5 | tee -a "$LOG_FILE"

# VSCode IntelliSense cleanup
VSCODE_CACHE_SIZE=$(du -sh ~/.cache/vscode-cpptools 2>/dev/null | cut -f1)
rm -rf ~/.cache/vscode-cpptools/ipch/* 2>/dev/null
echo "Cleared VSCode IntelliSense cache: $VSCODE_CACHE_SIZE" | tee -a "$LOG_FILE"

# Browser cache cleanup  
rm -rf ~/.cache/mozilla/firefox/*/cache2/* 2>/dev/null
echo "Cleared Firefox cache" | tee -a "$LOG_FILE"

# Python package cache
rm -rf ~/.cache/pip/wheels/* 2>/dev/null
echo "Cleared pip cache" | tee -a "$LOG_FILE"

# HuggingFace cache rotation (keep recent models)
find ~/.cache/huggingface -name "*.bin" -mtime +7 -delete 2>/dev/null
echo "Rotated HuggingFace cache (>7 days)" | tee -a "$LOG_FILE"

# 3. LOG MANAGEMENT
echo "--- LOG MANAGEMENT ---" | tee -a "$LOG_FILE"
journalctl --disk-usage | tee -a "$LOG_FILE"
journalctl --vacuum-time=7d --vacuum-size=500M | tee -a "$LOG_FILE"

# Force logrotate
sudo logrotate -f /etc/logrotate.conf 2>/dev/null || echo "Logrotate failed (no sudo)" | tee -a "$LOG_FILE"

# Clean large application logs
find /home/adam -name "*.log" -size +100M -mtime +3 -ls | tee -a "$LOG_FILE"

# 4. DOCKER MAINTENANCE
echo "--- DOCKER MAINTENANCE ---" | tee -a "$LOG_FILE"
if command -v docker &> /dev/null; then
    docker system df | tee -a "$LOG_FILE"
    docker system prune -f --volumes 2>&1 | tee -a "$LOG_FILE"
else
    echo "Docker not available" | tee -a "$LOG_FILE"
fi

# 5. TEMP FILE CLEANUP
echo "--- TEMP FILE CLEANUP ---" | tee -a "$LOG_FILE"
TEMP_SIZE_BEFORE=$(du -sh /tmp 2>/dev/null | cut -f1)
find /tmp -type f -mtime +2 -delete 2>/dev/null
find ~/.local/share/Trash/files -type f -mtime +7 -delete 2>/dev/null
TEMP_SIZE_AFTER=$(du -sh /tmp 2>/dev/null | cut -f1)
echo "Temp cleanup: $TEMP_SIZE_BEFORE -> $TEMP_SIZE_AFTER" | tee -a "$LOG_FILE"

# 6. LARGE FILE AUDIT
echo "--- LARGE FILE AUDIT ---" | tee -a "$LOG_FILE"
echo "Files >500MB:" | tee -a "$LOG_FILE"
find /home/adam -type f -size +500M -exec ls -lh {} \; 2>/dev/null | head -5 | tee -a "$LOG_FILE"

# 7. FINAL ASSESSMENT
echo "--- POST-MAINTENANCE STATE ---" | tee -a "$LOG_FILE"
free -h | tee -a "$LOG_FILE"
SWAP_PCT_AFTER=$(cat /proc/swaps | tail -1 | awk '{printf "%.1f", $3/$2*100}')
echo "Final Swap Usage: ${SWAP_PCT_AFTER}%" | tee -a "$LOG_FILE"
df -h / /home | tee -a "$LOG_FILE"

# Calculate improvement
SWAP_IMPROVEMENT=$(echo "$SWAP_PCT - $SWAP_PCT_AFTER" | bc 2>/dev/null || echo "N/A")
echo "Swap reduction: ${SWAP_IMPROVEMENT}%" | tee -a "$LOG_FILE"

echo "=== MAINTENANCE COMPLETE $TIMESTAMP ===" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"