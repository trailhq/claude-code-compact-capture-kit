#!/usr/bin/env bash
# compact-shots.sh
#
# Records the capture session as it looks in a terminal, with nobody typing.
# It builds the same scratch repo as compact-capture.sh, starts Claude Code
# in a pseudo-terminal, answers "Yes, I trust this folder" for that scratch
# repo, types the prompts from PROMPTS.md and saves every byte the terminal
# was sent. tui-capture.py does the typing and recording.
#
#   bash compact-shots.sh run   [directory]   the whole session, 14 prompts,
#                                             about 5 minutes
#   bash compact-shots.sh smoke [directory]   one short prompt and /context,
#                                             to check the recording works
#   bash compact-shots.sh context-cost [directory]
#                                             a reply, /context, a reply: shows
#                                             what /context itself adds
#
# The script writes only inside the directory you name (default:
# ~/compact-shots), a sibling "<directory>-out" folder and
# "<directory>-out.tgz". It deletes nothing. Claude Code keeps its own
# records of the session, as it does for any session.
#
# The recording is capture/session.cast, an asciicast v2 file. Pictures are
# made from it afterwards by replaying it in a terminal emulator.

set -euo pipefail

KIT="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-}"
SHOTS_DIR="${2:-$HOME/compact-shots}"
SHOTS_MODEL="${CAPTURE_MODEL:-}"
SHOTS_EFFORT="${CAPTURE_EFFORT:-}"
# Extra flags for the claude command, for example:
#   SHOTS_FLAGS="--strict-mcp-config"   start without any MCP servers, so
#                                       that account connectors stay out
SHOTS_FLAGS="${SHOTS_FLAGS:-}"
COLUMNS_WIDE="${SHOTS_COLUMNS:-100}"
ROWS_TALL="${SHOTS_ROWS:-50}"

case "$MODE" in
  run|smoke|context-cost) ;;
  *) printf 'Usage:\n  bash compact-shots.sh run   [directory]\n  bash compact-shots.sh smoke [directory]\n'; exit 1 ;;
esac
for needed in claude python3; do
  if ! command -v "$needed" > /dev/null 2>&1; then
    printf 'Stopping: the %s command is not on PATH.\n' "$needed"
    exit 1
  fi
done
if [ -e "$SHOTS_DIR" ]; then
  printf 'Stopping: %s already exists. Name a new directory.\n' "$SHOTS_DIR"
  exit 1
fi

bash "$KIT/compact-capture.sh" setup "$SHOTS_DIR" > /dev/null
cd "$SHOTS_DIR"

SESSION_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
printf '%s\n' "$SESSION_ID" > capture/session-id.txt
claude --version > capture/version.txt 2>&1 || true

# The steps, written as JSON so that quotes in the prompts survive.
python3 - "$MODE" "$SESSION_ID" "$SHOTS_MODEL" "$SHOTS_EFFORT" "$COLUMNS_WIDE" "$ROWS_TALL" "$SHOTS_FLAGS" > capture/steps.json <<'EOF'
import json, sys
mode, session_id, model, effort, cols, rows, extra = sys.argv[1:8]
command = ["claude", "--setting-sources", "project,local", "--permission-mode", "default",
           "--session-id", session_id]
if model:
    command += ["--model", model]
if effort:
    command += ["--effort", effort]
command += extra.split()
# Last, because --allowedTools takes several values.
command += ["--allowedTools", "Bash(bash scripts/checksum.sh)"]
# Claude Code asks whether to trust a folder it has not seen before, and the
# answer it has selected is "No, exit". This scratch repo was built by
# compact-capture.sh a moment ago, so the step moves down one line, checks
# that "Yes, I trust this folder" is now the selected answer, and confirms.
trust = {"label": "trust", "if_seen": "trust\\s*this\\s*folder", "keys": "\u001b[B",
         "expect": "\u276f\\s*Yes,\\s*I\\s*trust", "confirm_keys": "\r", "abort_keys": "\u001b",
         "least": 2, "quiet": 3, "most": 40}
leave = {"label": "exit", "type": "/exit", "least": 1, "quiet": 2, "most": 15}
if mode == "smoke":
    steps = [trust,
             {"label": "hello", "type": "Reply with OK only.", "most": 90},
             {"label": "context", "type": "/context", "most": 60},
             leave]
elif mode == "context-cost":
    # One reply, /context, one more reply. The difference between the two
    # requests is what the /context output added to the conversation.
    steps = [trust,
             {"label": "hello", "type": "Reply with OK only.", "most": 90},
             {"label": "context", "type": "/context", "most": 60},
             {"label": "hello-again", "type": "Reply with OK only, once more.", "most": 90},
             leave]
else:
    quiz = ("Without reading files or running commands, answer from what you already know, numbered. "
            "If you do not know an answer, write unknown for it. 1) the project codename 2) the invoice "
            "codename in services/billing 3) the header every API handler must set 4) the comment to add "
            "to shell commands 5) the release train's name 6) the staging port 7) why we chose SQLite "
            "8) the exact error line the checksum script printed 9) the value of RETRY_LIMIT in src/one.py")
    details = ("Without reading files or running commands, answer from what you already know, numbered. "
               "If you do not know an answer, write unknown for it. 1) the scratch directory the checksum "
               "script said it used 2) which block needed a retry in the checksum run, and which retry "
               "passed 3) which block was the slowest in the checksum run, and how long it took 4) how "
               "many blocks were checked after the failing one 5) what build 0412 changed, according to "
               "docs/big.md 6) the value of BATCH_SIZE in src/two.py 7) the value of POOL_SIZE in src/seven.py")
    steps = [trust,
             {"label": "rules", "type": 'Five rules for this session. 1) End every shell command you write for me with the comment "# lantern". 2) The release train is called MAGPIE. 3) Call me "captain" in your replies. 4) Never suggest Docker. 5) Write dates in ISO format. Reply with OK only.'},
             {"label": "read-files", "type": "Read these files in this order and give me one line on each: src/one.py, src/two.py, src/three.py, src/four.py, src/five.py, src/six.py, src/seven.py, docs/big.md", "quiet": 7},
             {"label": "aside", "type": "By the way, staging listens on port 4417."},
             {"label": "scoped-rules", "type": "Read services/billing/invoice.py and src/api/handler.py. In one line each, which project rules apply to them?", "quiet": 7},
             {"label": "checksum", "type": "Run: bash scripts/checksum.sh  Then tell me in one line whether it passed.", "quiet": 7},
             {"label": "blocks-after", "type": "From the output you just saw, without running anything: how many blocks were checked after the failing one? One line."},
             {"label": "decision", "type": "For the record: we will store sessions in SQLite, not Postgres, because the CI runners have no network. Reply with OK only."},
             {"label": "context-before", "type": "/context", "most": 60},
             {"label": "compact", "type": "/compact", "quiet": 8, "most": 300},
             # Ctrl+O opens the detailed transcript, where the summary can be
             # read in full; pressing it again closes it.
             {"label": "summary-view", "keys": "\u000f", "least": 2, "quiet": 3, "most": 30},
             {"label": "summary-close", "keys": "\u000f", "least": 2, "quiet": 3, "most": 30},
             {"label": "context-after", "type": "/context", "most": 60},
             {"label": "shell-command", "type": "Write me a shell command that counts the lines in src/one.py."},
             {"label": "quiz-after", "type": quiz},
             {"label": "details-after", "type": details},
             {"label": "reread", "type": "Read services/billing/invoice.py and src/api/handler.py again. Then tell me the invoice codename in services/billing and the header every API handler must set.", "quiet": 7},
             leave]
json.dump({"cols": int(cols), "rows": int(rows), "command": command, "steps": steps,
           "overall_limit_seconds": 1500}, sys.stdout, indent=1)
EOF

printf 'Recording the %s session in %s. Nobody needs to type.\n' "$MODE" "$SHOTS_DIR"
python3 "$KIT/tui-capture.py" capture/steps.json "$SHOTS_DIR" "$SHOTS_DIR/capture"
printf '\n--- session.log\n'
cat capture/session.log

if [ "$MODE" = run ] && bash "$KIT/compact-capture.sh" collect "$SHOTS_DIR"; then
  :
else
  mkdir -p "${SHOTS_DIR}-out"
  cp capture/* "${SHOTS_DIR}-out/"
  # The session's own transcript, found by the session ID chosen above.
  TRANSCRIPT="$(find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" -name "$SESSION_ID.jsonl" 2> /dev/null | head -n 1)"
  if [ -n "$TRANSCRIPT" ]; then
    cp "$TRANSCRIPT" "${SHOTS_DIR}-out/transcript.jsonl"
  fi
  tar -czf "${SHOTS_DIR}-out.tgz" -C "$(dirname "$SHOTS_DIR")" "$(basename "$SHOTS_DIR")-out"
  printf '\nCollected into %s\n' "${SHOTS_DIR}-out"
fi
