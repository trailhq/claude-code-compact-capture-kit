#!/bin/bash
# go.sh NAME [trial|full]
# Prepare a ripgrep checkout for session NAME and start the driver in the background.
# Safe to run again: it carries on from where the session stopped.
set -u
NAME="${1:?give the session a name, for example A}"
WHAT="${2:-trial}"
RELEASE="${RELEASE:-2.1.327}"
POOL="${POOL:-api}"        # api: pay with ANTHROPIC_API_KEY. plan: hide the key so the subscription pays.
KIT="$HOME/compact-capture-kit"
AUTO="$KIT/auto"
RG="$AUTO/ripgrep"
WORK="$KIT/work/ripgrep-$NAME"
OUT="$KIT/auto-out/$NAME"
mkdir -p "$KIT/work" "$OUT"
say() { printf '%s\n' "$*" | tee -a "$OUT/setup.log"; }

say "== $(date -u +%Y-%m-%dT%H:%MZ) session $NAME, $WHAT"
if pgrep -f "auto_run.py run --config $OUT/run.json" > /dev/null 2>&1; then
  say "STOP: the driver for $NAME is already running."; exit 1
fi
for tool in git python3 cargo rustc node npx claude; do
  if command -v "$tool" > /dev/null 2>&1; then say "$tool: $("$tool" --version 2>&1 | head -1)"; else say "$tool: MISSING"; fi
done
# The key for these runs may live under its own name. Its value is never printed.
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${ANTHROPIC_API_KEY_FOR_EXPERIMENTS:-}" ]; then
  export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY_FOR_EXPERIMENTS"
  say "ANTHROPIC_API_KEY: taken from ANTHROPIC_API_KEY_FOR_EXPERIMENTS"
fi
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then say "ANTHROPIC_API_KEY: set"; else say "ANTHROPIC_API_KEY: not set"; fi
UNSET_JSON='[]'
if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
  case "$ANTHROPIC_BASE_URL" in
    https://api.anthropic.com*) say "ANTHROPIC_BASE_URL: set, and it is Anthropic's API" ;;
    *) if [ "$POOL" = "api" ]; then
         say "ANTHROPIC_BASE_URL: set, and it is not Anthropic's API. Left out for these runs, so the key goes to Anthropic."
         unset ANTHROPIC_BASE_URL; UNSET_JSON='["ANTHROPIC_BASE_URL"]'
       else say "ANTHROPIC_BASE_URL: set, and it is not Anthropic's API. Kept, since the plan pays."; fi ;;
  esac
fi
if [ "$POOL" = "api" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then say "STOP: POOL=api but ANTHROPIC_API_KEY is not set in this environment."; exit 1; fi
if [ "$POOL" = "plan" ]; then unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; USE_KEY=false; else USE_KEY=true; fi
export CLAUDE_CODE_PROMPT_CACHE_TTL=1h
say "paying from: $POOL"
if ! command -v cargo > /dev/null 2>&1; then say "STOP: Rust is not installed. See https://rustup.rs"; exit 1; fi
if [ ! -f "$RG/developer.jsonl" ]; then say "STOP: $RG/developer.jsonl is missing. Run build_script.py first."; exit 1; fi

if [ ! -d "$WORK/.git" ]; then
  git clone --quiet --branch 14.1.1 https://github.com/BurntSushi/ripgrep "$WORK" >> "$OUT/setup.log" 2>&1 \
    || { say "STOP: could not clone ripgrep 14.1.1."; exit 1; }
  (cd "$WORK" && git switch --quiet -c work)
fi
say "ripgrep: $(cd "$WORK" && git describe --tags --always) on branch $(cd "$WORK" && git branch --show-current)"
mkdir -p "$WORK/tickets" "$WORK/.claude"
cp "$RG"/tickets/*.md "$WORK/tickets/"
grep -qxF 'tickets/' "$WORK/.git/info/exclude" || printf 'tickets/\n.claude/\n' >> "$WORK/.git/info/exclude"
cat > "$WORK/.claude/settings.json" <<'JSON'
{
  "permissions": {
    "allow": [
      "Bash(cargo *)", "Bash(rustc *)", "Bash(rustfmt *)", "Bash(./target/*)",
      "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)", "Bash(git add *)",
      "Bash(git commit *)", "Bash(git branch*)", "Bash(git stash*)", "Bash(git merge *)", "Bash(git rebase *)",
      "Bash(ls*)", "Bash(cat *)", "Bash(head *)", "Bash(tail *)", "Bash(wc *)", "Bash(grep *)", "Bash(rg *)",
      "Bash(find *)", "Bash(sed *)", "Bash(awk *)", "Bash(sort *)", "Bash(uniq *)", "Bash(cut *)", "Bash(tr *)",
      "Bash(diff *)", "Bash(echo *)", "Bash(printf *)", "Bash(mkdir *)", "Bash(touch *)", "Bash(which *)", "Bash(cd *)"
    ],
    "deny": ["Bash(git push*)", "Bash(cargo publish*)", "Bash(cargo install*)", "Bash(curl *)", "Bash(wget *)"]
  }
}
JSON

if command -v npx > /dev/null 2>&1; then
  CLAUDE_JSON="[\"npx\", \"-y\", \"@anthropic-ai/claude-code@$RELEASE\"]"
  CLAUDE_CMD=(npx -y "@anthropic-ai/claude-code@$RELEASE")
else
  CLAUDE_JSON='["claude"]'
  CLAUDE_CMD=(claude)
fi

# Leave out what a parent Claude Code session sets, as the driver does.
CLEAN=(env -u CLAUDECODE -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT
       -u CLAUDE_CODE_EXECPATH -u CLAUDE_CODE_MESSAGING_SOCKET -u CLAUDE_CODE_MESSAGING_TOKEN)
say "release asked for: ${CLAUDE_CMD[*]} -> $("${CLEAN[@]}" "${CLAUDE_CMD[@]}" --version 2>&1 | head -1)"

# Which permission mode works without anyone at the keyboard? Try auto, fall back to acceptEdits.
MODE=""
for try in auto acceptEdits; do
  if (cd "$WORK" && "${CLEAN[@]}" "${CLAUDE_CMD[@]}" --print "Reply with the single word ready." \
        --permission-mode "$try" --setting-sources project,local --model claude-opus-5-5 --effort medium \
        --output-format json < /dev/null > "$OUT/preflight-$try.json" 2> "$OUT/preflight-$try.err"); then
    MODE="$try"; break
  fi
  say "permission mode $try: refused ($(head -c 200 "$OUT/preflight-$try.err" | tr '\n' ' '))"
done
if [ -z "$MODE" ]; then say "STOP: Claude Code did not answer a one-word test. See $OUT/preflight-*.err"; exit 1; fi
say "permission mode: $MODE"

say "first build (cargo build), this can take a few minutes"
if (cd "$WORK" && cargo build >> "$OUT/setup.log" 2>&1); then say "cargo build: ok"; else say "STOP: cargo build failed. See $OUT/setup.log"; exit 1; fi

if [ "$WHAT" = "trial" ]; then
  SCRIPT="developer-trial.jsonl"
  MARKS='"ask_at": [60000, 150000], "snapshots_at": [100000], "limit_snapshots_at": [], "probe_from": 150000,'
else
  SCRIPT="developer.jsonl"
  MARKS=''
fi
cat > "$OUT/run.json" <<JSON
{
  "repo_dir": "$WORK",
  "out_dir": "$OUT",
  "script": "$RG/$SCRIPT",
  "questions": "$RG/questions.jsonl",
  "probes": "$RG/probes.jsonl",
  "claude": $CLAUDE_JSON,
  "model": "claude-opus-5-5",
  "effort": "medium",
  "permission_mode": "$MODE",
  $MARKS
  "use_api_key": $USE_KEY,
  "budget_usd": ${BUDGET:-150},
  "env": {"CLAUDE_CODE_PROMPT_CACHE_TTL": "1h"},
  "unset_env": $UNSET_JSON,
  "climbs": ${CLIMBS:-3},
  "guard": ${GUARD:-0.5}
}
JSON
nohup python3 "$AUTO/auto_run.py" run --config "$OUT/run.json" >> "$OUT/run.log" 2>&1 &
say "driver started, pid $!. Progress: $OUT/run.log and $OUT/steps.tsv"
