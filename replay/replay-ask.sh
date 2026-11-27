#!/bin/bash
# The questions to the replayed sessions, in the background, paid by the subscription.
set -u
R="$HOME/compact-capture-kit/replay"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
# One copy is refused by the safeguards of the model and is not asked again.
export ASK_SKIP="${ASK_SKIP:-27642e0f:3}"
nohup python3 "$R/replay_ask.py" "$R/six-list-final.txt" "$HOME/compact-capture-kit/data/SWE-chat" "$R/out-proto" "$HOME/compact-capture-kit/real/judge-swechat/judge.jsonl" --control >> "$R/out-proto/ask-run.log" 2>&1 < /dev/null &
echo "replay questions started in the background, pid $!. Progress: $R/out-proto/ask-run.log"
