#!/bin/bash
# Carry Session A's auto-memory-off copy over the 1M limit, paid by the subscription.
# It waits for the replay follow-ups to finish first, so two near-1M sessions do not run at once.
# The copy keeps CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 for the climb, the compaction and the questions.
set -u
KIT="$HOME/compact-capture-kit"; OUT="$KIT/auto-out/A"
if [ "${1:-}" != "--run" ]; then
  nohup bash "$0" --run >> "$OUT/nomem-wait.log" 2>&1 < /dev/null &
  echo "queued in the background, pid $!. It starts when the replay follow-ups finish."
  echo "Progress: $OUT/nomem-wait.log, then $OUT/cross.log"
  exit 0
fi
echo "== $(date -u +%H:%MZ) waiting for the replay follow-ups"
waited=0
while ! grep -q "all done" "$KIT/replay/out-proto/more-run.log" 2>/dev/null; do
  sleep 30; waited=$((waited + 30))
  if [ "$waited" -ge 3600 ]; then echo "== waited an hour, starting anyway"; break; fi
done
echo "== $(date -u +%H:%MZ) starting the nomem crossing"
POOL=plan BUDGET=200 MORE_FROM=t25-test bash "$KIT/auto/cross.sh" A more:nomem
