#!/bin/bash
# judge.sh NAME LIST DATA_DIR [judge.py options]
# Start the meaning check (judge.py) in the background. Results go to ~/compact-capture-kit/real/judge-NAME/.
# POOL=api (default) pays with the experiments key; POOL=plan hides the key so the subscription pays.
# Safe to run again: it carries on from where it stopped.
set -u
NAME="${1:?give the run a name}"; LIST="${2:?give the list file}"; DATA="${3:?give the data directory}"; shift 3
POOL="${POOL:-api}"
REAL="$HOME/compact-capture-kit/real"; OUT="$REAL/judge-$NAME"
mkdir -p "$OUT"
say() { printf '%s\n' "$*" | tee -a "$OUT/setup.log"; }
say "== $(date -u +%Y-%m-%dT%H:%MZ) judge $NAME, pool $POOL, options: $*"
if pgrep -f "judge.py .* $OUT( |$)" > /dev/null 2>&1; then say "STOP: the judge for $NAME is already running."; exit 1; fi
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${ANTHROPIC_API_KEY_FOR_EXPERIMENTS:-}" ]; then
  export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY_FOR_EXPERIMENTS"
fi
if [ "$POOL" = "api" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then say "STOP: POOL=api but ANTHROPIC_API_KEY is not set in this environment."; exit 1; fi
if [ "$POOL" = "plan" ]; then unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; fi
if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
  case "$ANTHROPIC_BASE_URL" in https://api.anthropic.com*) ;; *) [ "$POOL" = "api" ] && unset ANTHROPIC_BASE_URL ;; esac
fi
export POOL
nohup python3 "$REAL/judge.py" "$LIST" "$DATA" "$OUT" "$@" >> "$OUT/run.log" 2>&1 < /dev/null &
say "judge started in the background, pid $!. Progress: $OUT/judge.log"
