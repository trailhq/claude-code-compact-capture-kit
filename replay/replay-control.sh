#!/bin/bash
# The before-compaction check for the 1M sessions that the first run skipped, in the background, on the subscription.
set -u
R="$HOME/compact-capture-kit/replay"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
if [ "${1:-}" != "--run" ]; then
  nohup bash "$0" --run >> "$R/out-proto/more-run.log" 2>&1 < /dev/null &
  echo "check started in the background, pid $!. Progress: $R/out-proto/more-run.log"
  exit 0
fi
echo "== $(date -u +%H:%MZ) before-compaction check, second pass"
python3 "$R/replay_control.py" "$R/six-list-final.txt" "$HOME/compact-capture-kit/data/SWE-chat" "$R/out-proto" "$HOME/compact-capture-kit/real/judge-swechat/judge.jsonl"
echo "== $(date -u +%H:%MZ) second pass done"
