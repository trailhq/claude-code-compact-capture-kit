#!/bin/bash
# read.sh NAME LIST DATA_DIR [read_all.py options]
# Start the full reading (read_all.py) in the background. Results: ~/compact-capture-kit/real/read-NAME/.
# POOL=plan (default) hides the key so the subscription pays; POOL=api uses the experiments key.
# Safe to run again: it carries on from where it stopped.
set -u
NAME="${1:?give the run a name}"; LIST="${2:?give the list file}"; DATA="${3:?give the data directory}"; shift 3
POOL="${POOL:-plan}"
REAL="$HOME/compact-capture-kit/real"; OUT="$REAL/read-$NAME"
mkdir -p "$OUT"
say() { printf '%s\n' "$*" | tee -a "$OUT/setup.log"; }
say "== $(date -u +%Y-%m-%dT%H:%MZ) read $NAME, pool $POOL, options: $*"
if pgrep -f "read_all.py .* $OUT( |$)" > /dev/null 2>&1; then say "STOP: the reading $NAME is already running."; exit 1; fi
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${ANTHROPIC_API_KEY_FOR_EXPERIMENTS:-}" ]; then
  export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY_FOR_EXPERIMENTS"
fi
if [ "$POOL" = "api" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then say "STOP: POOL=api but ANTHROPIC_API_KEY is not set in this environment."; exit 1; fi
if [ "$POOL" = "plan" ]; then unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; fi
export POOL
nohup python3 "$REAL/read_all.py" "$LIST" "$DATA" "$OUT" "$@" >> "$OUT/run.log" 2>&1 < /dev/null &
say "reading started in the background, pid $!. Progress: $OUT/read.log"
