#!/bin/bash
# The meaning check on the replayed summaries, in the background, paid by the subscription.
set -u
R="$HOME/compact-capture-kit/replay"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
export POOL=plan
nohup python3 "$R/replay_judge.py" "$R/six-list-final.txt" "$HOME/compact-capture-kit/data/SWE-chat" "$R/out-proto" >> "$R/out-proto/judge-run.log" 2>&1 < /dev/null &
echo "replay judge started in the background, pid $!. Progress: $R/out-proto/judge-run.log"
