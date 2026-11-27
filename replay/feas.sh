#!/bin/bash
# feas.sh : two small checks before the replay study is built. Pays from the plan (the key is hidden).
#  a) does --autocompact make a resumed copy of our own test session compact on its next turn?
#  b) can today's Claude Code resume a cut SWE-chat transcript from a file and compact it?
set -u
KIT="$HOME/compact-capture-kit"; F="$KIT/replay/feas"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
CLEAN=(env -u CLAUDECODE -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT
       -u CLAUDE_CODE_EXECPATH -u CLAUDE_CODE_MESSAGING_SOCKET -u CLAUDE_CODE_MESSAGING_TOKEN -u CLAUDE_CODE_PROMPT_CACHE_TTL)
CC=(npx -y @anthropic-ai/claude-code@2.1.327)
COMMON=(--model claude-opus-5-5 --effort medium --permission-mode plan --output-format stream-json --verbose --max-budget-usd 6)
if [ "${1:-}" != "--run" ]; then
  nohup bash "$0" --run >> "$F/feas.log" 2>&1 < /dev/null &
  echo "feasibility checks started in the background, pid $!. Progress: $F/feas.log"
  exit 0
fi
  echo "== $(date -u +%H:%MZ) a: own session, copy from 250K, --autocompact 200k"
  cd "$KIT/work/ripgrep-A" && "${CLEAN[@]}" "${CC[@]}" -p "Say OK and nothing else." --resume 591d2019-efc1-4589-b174-8d701de70692 --fork-session \
      --autocompact 200k --setting-sources project,local "${COMMON[@]}" > "$F/a.jsonl" 2> "$F/a.err" < /dev/null
  echo "== $(date -u +%H:%MZ) a ended with exit $?"
  echo "== $(date -u +%H:%MZ) b: SWE-chat transcript cut before its first compaction, from a file, --autocompact 190k"
  cd "$F/cwd-b" && "${CLEAN[@]}" "${CC[@]}" -p "Continue." --resume "$F/F1.jsonl" --fork-session \
      --autocompact 190k --tools "" --strict-mcp-config --setting-sources project "${COMMON[@]}" > "$F/b.jsonl" 2> "$F/b.err" < /dev/null
  echo "== $(date -u +%H:%MZ) b ended with exit $?"
  echo "== done"
