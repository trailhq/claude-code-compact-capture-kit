#!/bin/bash
# cross.sh NAME KIND [KIND ...]
# After session NAME was compacted at the limit: take the saved copy from just below the limit and
# let it cross again, once per KIND, one after the other, in the background. Each crossing is then
# asked the same questions and rule tests as the main session.
#   r1 r2 r3   the same release again (how much does one compaction differ from the next?)
#   old        Claude Code 2.1.311, the stable release the post tested
#   nomem      auto memory off
#   man        /compact typed on the copy, instead of waiting for the limit
#   more:KIND  carry on a crossing that stopped short of the limit, with the developer messages
#              from MORE_FROM onwards (a message id in the script), until it is compacted
# Knobs: FROM (saved copy, default limit-c1-900k), POOL (api or plan, default api), BUDGET (cost guard in dollars).
set -u
if [ "${1:-}" = "--loop" ]; then
  # The background part: the environment is already set up by the first part.
  NAME="$2"; FROM="$3"; shift 3
  KIT="$HOME/compact-capture-kit"; AUTO="$KIT/auto"; OUT="$KIT/auto-out/$NAME"
  for kind in "$@"; do
    extra=()
    case "$kind" in
      more:*) echo "== $(date -u +%H:%MZ) carrying on ${kind#more:} from message $MORE_FROM"
              python3 "$AUTO/auto_run.py" cross --config "$OUT/run.json" --as "${kind#more:}" --more-from "$MORE_FROM"
              echo "== $(date -u +%H:%MZ) ${kind#more:} ended with exit $?"; continue ;;
      old)   extra=(--claude "npx -y @anthropic-ai/claude-code@2.1.311") ;;
      nomem) extra=(--env CLAUDE_CODE_DISABLE_AUTO_MEMORY=1) ;;
      man)   extra=(--manual) ;;
    esac
    echo "== $(date -u +%H:%MZ) crossing $kind"
    python3 "$AUTO/auto_run.py" cross --config "$OUT/run.json" --from "$FROM" --as "$kind" ${extra[@]+"${extra[@]}"}
    echo "== $(date -u +%H:%MZ) crossing $kind ended with exit $?"
  done
  echo "== all crossings done"
  exit 0
fi
NAME="${1:?give the session name, for example A}"; shift
[ "$#" -ge 1 ] || { echo "STOP: name at least one crossing: r1 r2 r3 old nomem man"; exit 1; }
FROM="${FROM:-limit-c1-900k}"
POOL="${POOL:-api}"
KIT="$HOME/compact-capture-kit"; AUTO="$KIT/auto"; OUT="$KIT/auto-out/$NAME"
say() { printf '%s\n' "$*" | tee -a "$OUT/setup.log"; }
[ -f "$OUT/run.json" ] || { echo "STOP: no run.json for session $NAME."; exit 1; }
say "== $(date -u +%Y-%m-%dT%H:%MZ) crossings for $NAME from $FROM: $*"
if pgrep -f "auto_run.py (run|cross) --config $OUT/run.json" > /dev/null 2>&1; then
  say "STOP: a driver for $NAME is still running."; exit 1
fi
for kind in "$@"; do
  case "$kind" in r[0-9]|old|nomem|man|more:r[0-9]|more:old|more:nomem) ;; *) say "STOP: unknown crossing $kind"; exit 1 ;; esac
done
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${ANTHROPIC_API_KEY_FOR_EXPERIMENTS:-}" ]; then
  export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY_FOR_EXPERIMENTS"
fi
if [ "$POOL" = "api" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then say "STOP: POOL=api but ANTHROPIC_API_KEY is not set in this environment."; exit 1; fi
if [ "$POOL" = "plan" ]; then unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; fi
if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
  case "$ANTHROPIC_BASE_URL" in https://api.anthropic.com*) ;; *) [ "$POOL" = "api" ] && unset ANTHROPIC_BASE_URL ;; esac
fi
export CLAUDE_CODE_PROMPT_CACHE_TTL=1h
export MORE_FROM="${MORE_FROM:-}"
for kind in "$@"; do
  case "$kind" in more:*) [ -n "$MORE_FROM" ] || { say "STOP: more:KIND needs MORE_FROM=<message id>."; exit 1; } ;; esac
done
say "paying from: $POOL"
# The pool and the cost guard live in run.json; change only those two lines' values.
POOL="$POOL" BUDGET="${BUDGET:-}" python3 - "$OUT/run.json" <<'PY'
import json, os, sys
path = sys.argv[1]; cfg = json.load(open(path))
cfg["use_api_key"] = os.environ["POOL"] == "api"
if os.environ.get("BUDGET"): cfg["budget_usd"] = float(os.environ["BUDGET"])
json.dump(cfg, open(path, "w"), indent=2)
print("cost guard: $%s, key: %s" % (cfg.get("budget_usd"), "used" if cfg["use_api_key"] else "hidden"))
PY
nohup bash "$0" --loop "$NAME" "$FROM" "$@" >> "$OUT/cross.log" 2>&1 < /dev/null &
say "crossings started in the background, pid $!. Progress: $OUT/cross.log and $OUT/steps.tsv"
