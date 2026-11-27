#!/bin/bash
# replay.sh NAME LIST [replay.py options] : start the replay in the background, paid by the subscription.
set -u
NAME="${1:?give the run a name}"; LIST="${2:?give the list file}"; shift 2
R="$HOME/compact-capture-kit/replay"; OUT="$R/out-$NAME"; mkdir -p "$OUT"
if pgrep -f "replay.py .* $OUT( |$)" > /dev/null 2>&1; then echo "STOP: the replay $NAME is already running."; exit 1; fi
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
nohup python3 "$R/replay.py" "$LIST" "$HOME/compact-capture-kit/data/SWE-chat" "$OUT" "$@" >> "$OUT/run.log" 2>&1 < /dev/null &
echo "replay $NAME started in the background, pid $!. Progress: $OUT/replay.log and $OUT/rounds.tsv"
