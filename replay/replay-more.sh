#!/bin/bash
# Two follow-ups to the questions, one after the other, in the background, paid by the subscription:
# one more try, with a cap on the length of a reply, for the two copies that never answered; then the
# before-compaction check for the three sessions recorded near 1M tokens.
set -u
R="$HOME/compact-capture-kit/replay"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
if [ "${1:-}" != "--run" ]; then
  nohup bash "$0" --run >> "$R/out-proto/more-run.log" 2>&1 < /dev/null &
  echo "follow-ups started in the background, pid $!. Progress: $R/out-proto/more-run.log"
  exit 0
fi
export ASK_SKIP=none
echo "== $(date -u +%H:%MZ) capped retry"
python3 "$R/replay_ask.py" "$R/six-list-final.txt" "$HOME/compact-capture-kit/data/SWE-chat" "$R/out-proto" "$HOME/compact-capture-kit/real/judge-swechat/judge.jsonl"
echo "== $(date -u +%H:%MZ) before-compaction check"
python3 "$R/replay_control.py" "$R/six-list-final.txt" "$HOME/compact-capture-kit/data/SWE-chat" "$R/out-proto" "$HOME/compact-capture-kit/real/judge-swechat/judge.jsonl"
echo "== $(date -u +%H:%MZ) all done"
