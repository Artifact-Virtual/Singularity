#!/bin/bash
# Emergency Swap Cleanup Script
# Executes when swap usage ≥95%

echo "🚨 EMERGENCY SWAP CLEANUP - $(date)"
echo "Initial swap usage: $(cat /proc/swaps | tail -1 | awk '{printf "%.1f%%", $3/$2*100}')"

# 1. Sync and drop caches (requires sudo for full effect)
sync
echo "Dropping filesystem caches..."
echo 1 > /proc/sys/vm/drop_caches 2>/dev/null || sudo bash -c 'echo 1 > /proc/sys/vm/drop_caches' || echo "Cache drop failed - no sudo"

# 2. Aggressive cache cleanup
echo "Clearing application caches..."
rm -rf ~/.cache/vscode-cpptools/ipch/* 2>/dev/null
rm -rf ~/.cache/mozilla/firefox/*/cache2/* 2>/dev/null  
rm -rf ~/.cache/huggingface/transformers/* 2>/dev/null
rm -rf ~/.cache/pip/wheels/* 2>/dev/null

# 3. Clear temporary files
echo "Clearing temporary files..."
rm -rf /tmp/* 2>/dev/null
rm -rf ~/.local/share/Trash/files/* 2>/dev/null

# 4. Docker cleanup if available
echo "Docker cleanup..."
docker system prune -f --all 2>/dev/null || echo "Docker not accessible"

# 5. Journal cleanup
echo "Journal cleanup..."
journalctl --vacuum-time=1d --vacuum-size=100M 2>/dev/null || echo "Journal cleanup failed"

# 6. Check final state
echo "Final swap usage: $(cat /proc/swaps | tail -1 | awk '{printf "%.1f%%", $3/$2*100}')"
echo "Memory state:"
free -h

echo "🚨 EMERGENCY CLEANUP COMPLETE - $(date)"