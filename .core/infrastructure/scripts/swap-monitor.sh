#!/bin/bash
# Swap Monitor - Execute every 15 minutes

LOG_FILE="/var/log/swap-alerts.log"
SWAP_PCT=$(cat /proc/swaps | tail -1 | awk '{printf "%.0f", $3/$2*100}')
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Only log if thresholds are breached
if [ "$SWAP_PCT" -gt 95 ]; then
    echo "$TIMESTAMP: 🚨 CRITICAL SWAP: ${SWAP_PCT}%" | tee -a "$LOG_FILE"
    
    # Trigger emergency cleanup
    /home/adam/workspace/enterprise/executives/coo/scripts/emergency-cleanup.sh >> "$LOG_FILE" 2>&1
    
    # Re-check after cleanup
    SWAP_PCT_AFTER=$(cat /proc/swaps | tail -1 | awk '{printf "%.0f", $3/$2*100}')
    echo "$TIMESTAMP: Post-cleanup swap: ${SWAP_PCT_AFTER}%" | tee -a "$LOG_FILE"
    
elif [ "$SWAP_PCT" -gt 80 ]; then
    echo "$TIMESTAMP: ⚠️ WARNING SWAP: ${SWAP_PCT}%" | tee -a "$LOG_FILE"
    
    # Light cleanup
    rm -rf ~/.cache/mozilla/firefox/*/cache2/* 2>/dev/null
    rm -rf /tmp/tmp* 2>/dev/null
    
fi