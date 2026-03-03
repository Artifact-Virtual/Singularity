#!/bin/bash
# Mid-week Health Check - Execute Wednesdays 14:00 UTC

LOG_FILE="/var/log/system-maintenance.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "=== MID-WEEK HEALTH CHECK $TIMESTAMP ===" | tee -a "$LOG_FILE"

# System metrics
SWAP_PCT=$(cat /proc/swaps | tail -1 | awk '{printf "%.0f", $3/$2*100}')
ROOT_PCT=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
HOME_PCT=$(df /home | tail -1 | awk '{print $5}' | tr -d '%')
MEM_PCT=$(free | grep Mem | awk '{printf "%.0f", $3/$2*100}')

echo "System Status: Swap:${SWAP_PCT}% | Root:${ROOT_PCT}% | Home:${HOME_PCT}% | Mem:${MEM_PCT}%" | tee -a "$LOG_FILE"

# Alert on critical conditions
if [ "$SWAP_PCT" -gt 90 ]; then
    echo "🚨 CRITICAL: Swap >90% - Emergency intervention needed" | tee -a "$LOG_FILE"
    
    # Emergency cache flush
    sync
    echo 1 > /proc/sys/vm/drop_caches 2>/dev/null || echo "Cache drop failed"
    
    # Show memory hogs
    echo "Top memory consumers:" | tee -a "$LOG_FILE"
    ps aux --sort=-%mem | head -5 | tee -a "$LOG_FILE"
fi

if [ "$ROOT_PCT" -gt 85 ]; then
    echo "⚠️ WARNING: Root disk >85%" | tee -a "$LOG_FILE"
    echo "Space usage breakdown:" | tee -a "$LOG_FILE"
    du -sh /var/log /tmp ~/.cache 2>/dev/null | sort -hr | tee -a "$LOG_FILE"
fi

if [ "$HOME_PCT" -gt 80 ]; then
    echo "⚠️ WARNING: Home disk >80%" | tee -a "$LOG_FILE"
    echo "Largest home directories:" | tee -a "$LOG_FILE"
    du -sh /home/adam/* 2>/dev/null | sort -hr | head -5 | tee -a "$LOG_FILE"
fi

# Cache size monitoring
CACHE_SIZE=$(du -sh ~/.cache 2>/dev/null | cut -f1)
echo "Current cache size: $CACHE_SIZE" | tee -a "$LOG_FILE"

if [ "$(du -sb ~/.cache 2>/dev/null | cut -f1)" -gt 2147483648 ]; then # >2GB
    echo "⚠️ Cache size >2GB - Consider cleanup" | tee -a "$LOG_FILE"
fi

echo "=== CHECK COMPLETE $TIMESTAMP ===" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"