#!/bin/bash
# replay-cd.sh : the replay, the meaning check and the questions for cd25197e, the session that would
# not compact before slice.py was fixed. Runs in the foreground, one step after the other, on the subscription.
set -u
R="$HOME/compact-capture-kit/replay"; D="$HOME/compact-capture-kit/data/SWE-chat"; O="$R/out-proto"
L="$R/cd-list.txt"; J="$HOME/compact-capture-kit/real/judge-swechat/judge.jsonl"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
export POOL=plan ASK_SKIP=none
echo "== $(date -u +%H:%MZ) replay"; python3 "$R/replay.py" "$L" "$D" "$O" --retry
[ -f "$O/cd25197e/round-3.jsonl" ] || { echo "== the replay did not get through three rounds; stopping here"; exit 1; }
echo "== $(date -u +%H:%MZ) meaning check"; python3 "$R/replay_judge.py" "$L" "$D" "$O"
echo "== $(date -u +%H:%MZ) questions"; python3 "$R/replay_ask.py" "$L" "$D" "$O" "$J"
echo "== $(date -u +%H:%MZ) before-compaction check"; python3 "$R/replay_control.py" "$L" "$D" "$O" "$J"
echo "== $(date -u +%H:%MZ) cd25197e done"
