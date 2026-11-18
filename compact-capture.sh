#!/usr/bin/env bash
# compact-capture.sh
#
# Records what Claude Code's /compact does to one scripted session.
#
#   bash compact-capture.sh run     [directory]   build the scratch repo, run the
#                                                 session unattended, bundle the records
#   bash compact-capture.sh setup   [directory]   build the scratch repo only, to run
#                                                 the session by hand from PROMPTS.md
#   bash compact-capture.sh collect [directory]   bundle the records of a by-hand session
#   bash compact-capture.sh ladder  [directory]   the same session, then grown task by
#                                                 task and compacted at several sizes
#
# The script writes only inside the directory you name (default:
# ~/compact-capture), a sibling "<directory>-out" folder and
# "<directory>-out.tgz". It deletes nothing. Outside the scratch repo it
# reads one file: the transcript of the session it ran.
#
# Claude Code keeps its own records of that session, as it does for any
# session: transcripts under ~/.claude/projects/<the scratch repo>/, and
# any auto-memory notes Claude decides to write in the memory folder there.
#
# "run" needs the claude command, signed in. It makes 16 calls to
# "claude --print", one per step. Twelve are turns of one session. The four
# quiz steps are asked of copies of that session (--fork-session), so the
# questions never enter the session that gets compacted.

set -euo pipefail

COMMAND="${1:-}"
CAPTURE_DIR="${2:-$HOME/compact-capture}"
OUT_DIR="${CAPTURE_DIR}-out"
OUT_ARCHIVE="${CAPTURE_DIR}-out.tgz"

# Sizes of the generated files. Raise these to make the session heavier.
FUNCTIONS_PER_MODULE=80
BIG_FILE_LINES=700
CHECKSUM_BLOCKS=240

# Optional focus for the /compact step, for a second run:
#   COMPACT_FOCUS="keep the exact error line and the staging port" \
#     bash compact-capture.sh run ~/compact-capture-focus
COMPACT_FOCUS="${COMPACT_FOCUS:-}"

# A ceiling on what one step may spend, as Claude Code estimates it.
# Set it to an empty string to run without a ceiling.
MAX_BUDGET_PER_STEP_USD="${MAX_BUDGET_PER_STEP_USD-5}"

# A ceiling on how long one step may take, in seconds.
STEP_DEADLINE_SECONDS="${STEP_DEADLINE_SECONDS:-900}"

# Variables Claude Code sets in the shells it starts. When this script is run
# from inside a Claude Code session, the capture session is started without
# them, so that it begins the way it would from a plain terminal. The names
# that were removed are recorded in capture/launch.txt.
PARENT_SESSION_VARIABLES="CLAUDECODE CLAUDE_CODE_CHILD_SESSION CLAUDE_CODE_SESSION_ID CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_EXECPATH CLAUDE_CODE_BRIDGE_SESSION_ID CLAUDE_CODE_MESSAGING_SOCKET CLAUDE_CODE_MESSAGING_TOKEN CLAUDE_EFFORT CLAUDE_PID CLAUDE_JOB_DIR AI_AGENT"

# Settings that change how the session or its compaction behaves. Their
# values are recorded.
COMPACTION_VARIABLES="DISABLE_COMPACT DISABLE_AUTO_COMPACT CLAUDE_AUTOCOMPACT_PCT_OVERRIDE CLAUDE_CODE_AUTO_COMPACT_WINDOW CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS CLAUDE_CODE_SIMPLE CLAUDE_CODE_DISABLE_AUTO_MEMORY CLAUDE_CODE_MAX_OUTPUT_TOKENS"

# The one shell command the session is allowed to run.
ALLOWED_COMMAND="Bash(bash scripts/checksum.sh)"

# Model and effort for the capture session. Empty means Claude Code's default.
CAPTURE_MODEL="${CAPTURE_MODEL:-}"
CAPTURE_EFFORT="${CAPTURE_EFFORT:-}"

# Settings for "ladder". After the first session it adds one task at a time.
# Each task reads three tables and a module, runs a script and carries an
# aside. The session is compacted on a copy whenever it passes one of the
# sizes in LADDER_SIZES, and for real once it passes STOP_AT_TOKENS, runs
# out of tasks, or has cost more than MAX_TOTAL_USD by Claude Code's count.
MAX_UNITS="${MAX_UNITS:-10}"
LADDER_SIZES="${LADDER_SIZES:-240000 500000}"
STOP_AT_TOKENS="${STOP_AT_TOKENS:-780000}"
MAX_TOTAL_USD="${MAX_TOTAL_USD:-20}"
# Never start a task that could take the session past this size. Claude Code
# compacts on its own a little above it on a 1M-token window.
HARD_LIMIT_TOKENS="${HARD_LIMIT_TOKENS:-900000}"
UNIT_TABLE_LINES=600
UNIT_FUNCTIONS=40
UNIT_WORDS="amber birch cobalt dune ember fjord garnet harbor indigo juniper kelp lumen"

# The prompts, in the order they are sent. PROMPTS.md repeats them for a
# session run by hand.
PROMPT_RULES='Five rules for this session. 1) End every shell command you write for me with the comment "# lantern". 2) The release train is called MAGPIE. 3) Call me "captain" in your replies. 4) Never suggest Docker. 5) Write dates in ISO format. Reply with OK only.'
PROMPT_READ='Read these files in this order and give me one line on each: src/one.py, src/two.py, src/three.py, src/four.py, src/five.py, src/six.py, src/seven.py, docs/big.md'
PROMPT_ASIDE='By the way, staging listens on port 4417.'
PROMPT_SCOPED='Read services/billing/invoice.py and src/api/handler.py. In one line each, which project rules apply to them?'
PROMPT_CHECKSUM='Run: bash scripts/checksum.sh  Then tell me in one line whether it passed.'
PROMPT_BLOCKS_AFTER='From the output you just saw, without running anything: how many blocks were checked after the failing one? One line.'
PROMPT_DECISION='For the record: we will store sessions in SQLite, not Postgres, because the CI runners have no network. Reply with OK only.'
PROMPT_QUIZ="Without reading files or running commands, answer from what you already know, numbered. If you do not know an answer, write unknown for it. 1) the project codename 2) the invoice codename in services/billing 3) the header every API handler must set 4) the comment to add to shell commands 5) the release train's name 6) the staging port 7) why we chose SQLite 8) the exact error line the checksum script printed 9) the value of RETRY_LIMIT in src/one.py"
# Details that nobody in the session points out.
PROMPT_DETAILS="Without reading files or running commands, answer from what you already know, numbered. If you do not know an answer, write unknown for it. 1) the scratch directory the checksum script said it used 2) which block needed a retry in the checksum run, and which retry passed 3) which block was the slowest in the checksum run, and how long it took 4) how many blocks were checked after the failing one 5) what build 0412 changed, according to docs/big.md 6) the value of BATCH_SIZE in src/two.py 7) the value of POOL_SIZE in src/seven.py"
PROMPT_SHELL='Write me a shell command that counts the lines in src/one.py.'
PROMPT_REREAD='Read services/billing/invoice.py and src/api/handler.py again. Then tell me the invoice codename in services/billing and the header every API handler must set.'

usage() {
  printf 'Usage:\n'
  printf '  bash compact-capture.sh run     [directory]\n'
  printf '  bash compact-capture.sh setup   [directory]\n'
  printf '  bash compact-capture.sh collect [directory]\n'
  printf '  bash compact-capture.sh ladder  [directory]\n'
}

write_module() {
  # write_module <path> <name>: a Python file of small, dull functions.
  local path="$1" name="$2" i
  {
    printf '"""Module %s: sample code for the compaction capture."""\n\n' "$name"
    case "$name" in
      one) printf 'RETRY_LIMIT = 7\n\n\n' ;;
      two) printf 'BATCH_SIZE = 64\n\n\n' ;;
      seven) printf 'POOL_SIZE = 12\n\n\n' ;;
    esac
    for i in $(seq 1 "$FUNCTIONS_PER_MODULE"); do
      printf 'def %s_step_%03d(value):\n' "$name" "$i"
      printf '    """Return value shifted by %d for the %s pipeline."""\n' "$i" "$name"
      printf '    return value + %d\n\n\n' "$i"
    done
  } > "$path"
}

build_repo() {
  if [ -e "$CAPTURE_DIR" ]; then
    printf 'Stopping: %s already exists. Name another directory:\n' "$CAPTURE_DIR"
    printf '  bash compact-capture.sh %s "%s-2"\n' "$COMMAND" "$CAPTURE_DIR"
    exit 1
  fi

  mkdir -p "$CAPTURE_DIR/.claude/rules" \
           "$CAPTURE_DIR/services/billing" \
           "$CAPTURE_DIR/src/api" \
           "$CAPTURE_DIR/docs" \
           "$CAPTURE_DIR/scripts" \
           "$CAPTURE_DIR/capture"
  cd "$CAPTURE_DIR"

  # 1. A fact in the project-root CLAUDE.md.
  cat > CLAUDE.md <<'EOF'
# Project notes

- The project codename is HERON. Use it whenever someone asks for the codename.
EOF

  # 2. A fact in a nested CLAUDE.md, which loads when Claude reads a file here.
  cat > services/billing/CLAUDE.md <<'EOF'
# Billing notes

- In this directory, invoices go by the codename OSPREY.
EOF

  # 3. A path-scoped rule, which loads when Claude reads a matching file.
  cat > .claude/rules/api.md <<'EOF'
---
paths:
  - "src/api/**/*"
---

# API rules

- Every API handler must set the response header X-Trace to KESTREL.
EOF

  # 4. Hooks that save what Claude Code passes them, one JSON object per line.
  cat > .claude/settings.json <<'EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "mkdir -p \"$CLAUDE_PROJECT_DIR/capture\" && { cat; echo; } >> \"$CLAUDE_PROJECT_DIR/capture/sessionstart.jsonl\""
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "mkdir -p \"$CLAUDE_PROJECT_DIR/capture\" && { cat; echo; } >> \"$CLAUDE_PROJECT_DIR/capture/precompact.jsonl\""
          }
        ]
      }
    ],
    "PostCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "mkdir -p \"$CLAUDE_PROJECT_DIR/capture\" && { cat; echo; } >> \"$CLAUDE_PROJECT_DIR/capture/postcompact.jsonl\""
          }
        ]
      }
    ]
  }
}
EOF

  # 5. Files for Claude to read.
  local name
  for name in one two three four five six seven; do
    write_module "src/$name.py" "$name"
  done

  cat > services/billing/invoice.py <<'EOF'
"""Billing: build an invoice line."""


def invoice_line(customer, amount):
    return {"customer": customer, "amount": amount}
EOF

  cat > src/api/handler.py <<'EOF'
"""API: a minimal request handler."""


def handle(request):
    return {"status": 200, "headers": {}, "body": "ok"}
EOF

  {
    printf '# Release notes archive\n\n'
    local line
    for line in $(seq 1 "$BIG_FILE_LINES"); do
      if [ "$line" -eq 412 ]; then
        printf -- '- Build 0412: moved the billing export to 03:40 UTC and left everything else alone.\n'
      else
        printf -- '- Build %04d: adjusted the cache window, refreshed fixtures, rotated the staging key.\n' "$line"
      fi
    done
  } > docs/big.md

  # 6. A script whose output hides one error line, and three other lines
  #    worth remembering, among many dull ones. It only prints.
  cat > scripts/checksum.sh <<EOF
#!/usr/bin/env bash
failing=\$(( $CHECKSUM_BLOCKS / 2 + 1 ))
printf 'info: scratch dir /var/tmp/hx-9931\n'
for block in \$(seq 1 "$CHECKSUM_BLOCKS"); do
  if [ "\$block" -eq 77 ]; then
    printf 'warn: block %03d verified on retry 3\n' "\$block"
  elif [ "\$block" -eq "\$failing" ]; then
    printf 'E4107: checksum mismatch at offset 0x3fa2\n'
  else
    printf 'ok   block %03d verified\n' "\$block"
  fi
done
printf 'slowest block: 188 (2.4 s)\n'
printf 'done: %d of %d blocks verified\n' "\$(( $CHECKSUM_BLOCKS - 1 ))" "$CHECKSUM_BLOCKS"
EOF

  # 7. The same prompts, for a session run by hand.
  cat > PROMPTS.md <<'EOF'
# Capture session by hand: paste these in order

`bash compact-capture.sh run` sends these prompts for you. Use this file only
to repeat the session in the terminal, for example to take screenshots.

Start Claude Code from this folder and accept the trust prompt:

    claude --setting-sources project,local --name compact-capture

`--setting-sources project,local` leaves your user-level settings and hooks
out, so the session shows Claude Code on its own.

Take a screenshot wherever a step says [screenshot]. Include the header with
the Claude Code version and model in the first one.

Do not ask the quiz before step 9. Whatever was said last before a
compaction is carried over, so a quiz asked there answers itself afterwards.

1. Paste:

       Five rules for this session. 1) End every shell command you write for me with the comment "# lantern". 2) The release train is called MAGPIE. 3) Call me "captain" in your replies. 4) Never suggest Docker. 5) Write dates in ISO format. Reply with OK only.

2. Paste:

       Read these files in this order and give me one line on each: src/one.py, src/two.py, src/three.py, src/four.py, src/five.py, src/six.py, src/seven.py, docs/big.md

3. Paste:

       By the way, staging listens on port 4417.

4. Paste:

       Read services/billing/invoice.py and src/api/handler.py. In one line each, which project rules apply to them?

5. Paste, and approve the command when asked:

       Run: bash scripts/checksum.sh  Then tell me in one line whether it passed.

6. Paste:

       From the output you just saw, without running anything: how many blocks were checked after the failing one? One line.

7. Paste:

       For the record: we will store sessions in SQLite, not Postgres, because the CI runners have no network. Reply with OK only.

8. Type `/context`  [screenshot 1]

9. Type `/compact` and wait for it to finish  [screenshot 2]

10. Type `/context`  [screenshot 3]

11. Paste:

        Write me a shell command that counts the lines in src/one.py.

    [screenshot 4]

12. Paste the quiz:

        Without reading files or running commands, answer from what you already know, numbered. If you do not know an answer, write unknown for it. 1) the project codename 2) the invoice codename in services/billing 3) the header every API handler must set 4) the comment to add to shell commands 5) the release train's name 6) the staging port 7) why we chose SQLite 8) the exact error line the checksum script printed 9) the value of RETRY_LIMIT in src/one.py

    [screenshot 5]

13. Paste the details quiz:

        Without reading files or running commands, answer from what you already know, numbered. If you do not know an answer, write unknown for it. 1) the scratch directory the checksum script said it used 2) which block needed a retry in the checksum run, and which retry passed 3) which block was the slowest in the checksum run, and how long it took 4) how many blocks were checked after the failing one 5) what build 0412 changed, according to docs/big.md 6) the value of BATCH_SIZE in src/two.py 7) the value of POOL_SIZE in src/seven.py

    [screenshot 6]

14. Paste:

        Read services/billing/invoice.py and src/api/handler.py again. Then tell me the invoice codename in services/billing and the header every API handler must set.

    [screenshot 7]

15. Type `/usage`  [screenshot 8], then `/exit`

Then, from any folder:

    bash compact-capture.sh collect
EOF

  printf 'capture/\n' > .gitignore
  : > capture/.gitkeep

  if [ "$COMMAND" = "ladder" ]; then
    build_units
  fi

  # 8. Known modification times, so the files Claude Code re-reads after a
  #    compaction can be told apart by age and by reading order.
  touch -t 202611160300 services/billing/invoice.py
  touch -t 202611160400 docs/big.md
  touch -t 202611160500 src/six.py
  touch -t 202611160600 src/four.py
  touch -t 202611160700 src/two.py
  touch -t 202611160800 src/api/handler.py
  touch -t 202611160900 src/seven.py
  touch -t 202611161000 src/five.py
  touch -t 202611161100 src/three.py
  touch -t 202611161200 src/one.py

  if command -v git > /dev/null 2>&1; then
    git init --quiet
    git add --all
    git -c user.name="compact capture" -c user.email="capture@example.invalid" \
      -c commit.gpgsign=false -c core.hooksPath=/dev/null \
      commit --quiet --message "Scratch repo for the compaction capture"
  else
    printf 'Note: git is not installed, so this folder is not a repository.\n'
  fi

  printf 'Scratch repo ready: %s\n' "$CAPTURE_DIR"
}

setup() {
  build_repo
  printf '\nNext:\n'
  printf '  1. cd "%s"\n' "$CAPTURE_DIR"
  printf '  2. Open PROMPTS.md and follow it.\n'
  printf '  3. bash compact-capture.sh collect\n'
}

new_uuid() {
  if command -v uuidgen > /dev/null 2>&1; then
    uuidgen | tr '[:upper:]' '[:lower:]'
  elif [ -r /proc/sys/kernel/random/uuid ]; then
    cat /proc/sys/kernel/random/uuid
  else
    python3 -c 'import uuid; print(uuid.uuid4())'
  fi
}

result_text() {
  # result_text <stream-json file>: the final answer of that step.
  if command -v jq > /dev/null 2>&1; then
    jq -r 'select(.type == "result") | .result // empty' "$1" 2> /dev/null || true
  elif command -v python3 > /dev/null 2>&1; then
    python3 -c '
import json, sys
for line in open(sys.argv[1]):
    try:
        message = json.loads(line)
    except ValueError:
        continue
    if message.get("type") == "result":
        print(message.get("result") or "")
' "$1"
  else
    printf '(install jq or python3 to print answers here; the raw file is %s)\n' "$1"
  fi
}

ask() {
  # ask <step number> <label> <prompt> [how]: one non-interactive call.
  #   main          a turn of the capture session; a failure stops the run
  #   optional      the same, but a failure is noted and the run goes on
  #   fork          asked of a copy of the session, so the question never
  #                 enters the capture session; a failure is noted
  #   fork-or-main  asked of a copy; if that fails, asked of the session
  local number="$1" label="$2" prompt="$3" how="${4:-main}" target="${5:-$SESSION_ID}" status=0
  local out="capture/step-$number-$label.jsonl" err="capture/step-$number-$label.err"
  local -a session_flags
  LAST_OUT="$out"
  case "$how" in
    fork|fork-or-main|forkcompact)
      session_flags=(--resume "$target" --fork-session)
      ;;
    *)
      if [ "$FIRST_STEP" = 1 ]; then
        session_flags=(--session-id "$SESSION_ID")
        FIRST_STEP=0
      else
        session_flags=(--resume "$SESSION_ID")
      fi
      ;;
  esac
  printf '[%s/%s] %s\n' "$number" "$STEP_COUNT" "$label"
  # The prompt goes first: --allowedTools takes several values and would
  # otherwise swallow it.
  local started pid waited=0
  started="$(date +%s)"
  env ${STRIP_FLAGS[@]+"${STRIP_FLAGS[@]}"} claude --print "$prompt" \
    "${session_flags[@]}" \
    --setting-sources project,local \
    --permission-mode default \
    --output-format stream-json --verbose \
    ${MODEL_FLAGS[@]+"${MODEL_FLAGS[@]}"} \
    ${BUDGET_FLAGS[@]+"${BUDGET_FLAGS[@]}"} \
    --allowedTools "$ALLOWED_COMMAND" ${EXTRA_ALLOWED[@]+"${EXTRA_ALLOWED[@]}"} \
    < /dev/null > "$out" 2> "$err" &
  pid=$!
  while kill -0 "$pid" 2> /dev/null; do
    if [ "$waited" -ge "$STEP_DEADLINE_SECONDS" ]; then
      printf '  step %s passed the %s-second limit; stopping it.\n' "$number" "$STEP_DEADLINE_SECONDS"
      kill "$pid" 2> /dev/null || true
      sleep 10
      kill -9 "$pid" 2> /dev/null || true
      break
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  wait "$pid" || status=$?
  printf '%s\t%s\t%s\t%s\t%s\n' "$number" "$label" "$how" "$(( $(date +%s) - started ))" "$status" >> capture/steps.tsv

  # A copy must be a copy. If the question reached the capture session
  # itself, the session now holds the quiz and the run proves nothing.
  case "$how" in
    fork|fork-or-main)
      if [ "$status" -eq 0 ] && [ "$target" = "$SESSION_ID" ] && [ "${MAIN_COMPACTED:-0}" = 0 ] && grep -E '"type": ?"result"' "$out" | grep -Eq "\"session_id\": ?\"$SESSION_ID\""; then
        printf 'Step %s was meant for a copy of the session but reached the session itself.\n' "$number"
        printf 'Stopping: the capture session now holds the quiz. Send %s/capture as it is.\n' "$CAPTURE_DIR"
        exit 1
      fi
      ;;
  esac

  if [ "$status" -eq 0 ]; then
    return 0
  fi
  case "$how" in
    optional|fork)
      printf '  step %s did not run here (exit code %s); carrying on.\n' "$number" "$status"
      return 0
      ;;
    soft|forkcompact)
      printf '  step %s stopped with exit code %s.\n' "$number" "$status"
      tail -n 3 "$err" || true
      return 1
      ;;
    fork-or-main)
      printf '  step %s could not use a copy (exit code %s); asking the session itself.\n' "$number" "$status"
      ask "$number" "$label-main" "$prompt" main
      return 0
      ;;
  esac
  printf 'Step %s stopped with exit code %s.\n' "$number" "$status"
  printf 'Last lines of %s:\n' "$err"
  tail -n 5 "$err" || true
  printf 'Send %s/capture as it is; the steps before this one are still useful.\n' "$CAPTURE_DIR"
  exit 1
}

start_session() {
  if ! command -v claude > /dev/null 2>&1; then
    printf 'Stopping: the claude command is not on PATH.\n'
    exit 1
  fi

  build_repo
  cd "$CAPTURE_DIR"

  SESSION_ID="$(new_uuid)"
  FIRST_STEP=1
  BUDGET_FLAGS=()
  if [ -n "$MAX_BUDGET_PER_STEP_USD" ]; then
    BUDGET_FLAGS=(--max-budget-usd "$MAX_BUDGET_PER_STEP_USD")
  fi

  # Start the capture session without the variables a parent Claude Code
  # session leaves behind, and write down what the launch looked like.
  # Names only, except for the compaction settings.
  MODEL_FLAGS=()
  EXTRA_ALLOWED=()
  LAST_OUT=""
  MAIN_COMPACTED=0
  if [ -n "$CAPTURE_MODEL" ]; then
    MODEL_FLAGS=(--model "$CAPTURE_MODEL")
  fi
  if [ -n "$CAPTURE_EFFORT" ]; then
    if claude --help 2> /dev/null | grep -q -- '--effort'; then
      MODEL_FLAGS+=(--effort "$CAPTURE_EFFORT")
    else
      export CLAUDE_CODE_EFFORT_LEVEL="$CAPTURE_EFFORT"
    fi
  fi
  STRIP_FLAGS=()
  local variable removed="" kept="" settings_seen=""
  for variable in $PARENT_SESSION_VARIABLES; do
    if printenv "$variable" > /dev/null 2>&1; then
      STRIP_FLAGS+=(-u "$variable")
      removed="$removed $variable"
    fi
  done
  for variable in $(compgen -e | grep -E '^(CLAUDE|ANTHROPIC)' | sort || true); do
    case " $removed " in
      *" $variable "*) ;;
      *) kept="$kept $variable" ;;
    esac
  done
  for variable in $COMPACTION_VARIABLES; do
    if printenv "$variable" > /dev/null 2>&1; then
      settings_seen="$settings_seen $variable=$(printenv "$variable")"
    fi
  done

  printf '%s\n' "$SESSION_ID" > capture/session-id.txt
  claude --version > capture/version.txt 2>&1 || true
  {
    printf 'launched_inside_claude_code=%s\n' "${CLAUDECODE:-0}"
    printf 'parent_session_variables_removed=%s\n' "${removed# }"
    printf 'other_claude_variables_present=%s\n' "${kept# }"
    printf 'settings_in_environment=%s\n' "${settings_seen# }"
    printf 'compact_focus=%s\n' "$COMPACT_FOCUS"
    printf 'max_budget_per_step_usd=%s\n' "$MAX_BUDGET_PER_STEP_USD"
    printf 'step_deadline_seconds=%s\n' "$STEP_DEADLINE_SECONDS"
    printf 'shell=bash %s\n' "$BASH_VERSION"
    printf 'claude_command=%s\n' "$(command -v claude)"
    printf 'model_asked_for=%s\n' "$CAPTURE_MODEL"
    printf 'effort_asked_for=%s\n' "$CAPTURE_EFFORT"
    printf 'command=%s\n' "$COMMAND"
  } > capture/launch.txt
  printf 'step\tlabel\thow\tseconds\texit\n' > capture/steps.tsv
}

run() {
  start_session

  local compact_prompt="/compact" file
  if [ -n "$COMPACT_FOCUS" ]; then
    compact_prompt="/compact $COMPACT_FOCUS"
  fi

  STEP_COUNT=16
  printf '\nRunning the session. This takes a few minutes.\n'
  ask 01 rules          "$PROMPT_RULES"
  ask 02 read-files     "$PROMPT_READ"
  ask 03 aside          "$PROMPT_ASIDE"
  ask 04 scoped-rules   "$PROMPT_SCOPED"
  ask 05 checksum       "$PROMPT_CHECKSUM"
  ask 06 blocks-after   "$PROMPT_BLOCKS_AFTER"
  ask 07 decision       "$PROMPT_DECISION"
  ask 08 context-before "/context" optional
  ask 09 quiz-before    "$PROMPT_QUIZ" fork
  ask 10 details-before "$PROMPT_DETAILS" fork
  ask 11 compact        "$compact_prompt"
  if [ ! -s capture/postcompact.jsonl ] && ! grep -q 'compact_boundary' capture/step-11-compact.jsonl 2> /dev/null; then
    printf '\nStep 11 returned, but nothing shows that a compaction ran:\n'
    printf 'no PostCompact record and no compact_boundary message. Its answer began:\n'
    result_text capture/step-11-compact.jsonl | head -n 5 || true
    printf '\nStopping here. The steps so far are still collected.\n'
    collect
    exit 1
  fi
  ask 12 context-after  "/context" optional
  ask 13 quiz-after     "$PROMPT_QUIZ" fork-or-main
  ask 14 details-after  "$PROMPT_DETAILS" fork-or-main
  ask 15 shell-command  "$PROMPT_SHELL"
  ask 16 reread         "$PROMPT_REREAD"

  local name
  for name in quiz-before quiz-after details-before details-after; do
    printf '\n=== %s ===\n' "$name"
    for file in capture/step-*-"$name"*.jsonl; do
      if [ -f "$file" ]; then
        result_text "$file"
      fi
    done
  done

  collect
}

unit_value() {
  # unit_value <kind> <unit number>: the planted value for that task.
  local kind="$1" i="$2"
  case "$kind" in
    word) printf '%s' "$UNIT_WORDS" | tr ' ' '\n' | sed -n "${i}p" ;;
    port) printf '%d' "$(( 20000 + i * 731 + 17 ))" ;;
    lease) printf '%d' "$(( 1000 + i * 137 + 5 ))" ;;
    error) printf 'E%d' "$(( 5000 + i * 113 ))" ;;
    index) printf '/var/tmp/u%02d-%d.idx' "$i" "$(( 4000 + i * 271 ))" ;;
    item) printf '%04d' "$(( 100 + i * 37 ))" ;;
    limit) printf '%d' "$(( 30000 + i * 911 + 3 ))" ;;
  esac
}

build_units() {
  # Files for the tasks that "ladder" adds, and the answers its quiz expects.
  local i nn letter word
  printf 'part\tnumber\tkind\tunit\texpected\n' > capture/answers.tsv
  for i in $(seq 1 "$MAX_UNITS"); do
    nn="$(printf '%02d' "$i")"
    word="$(unit_value word "$i")"
    mkdir -p "docs/u$nn"
    for letter in a b c; do
      awk -v unit="$i" -v letter="$letter" -v lines="$UNIT_TABLE_LINES" -v word="$word" \
          -v needle="$(( 100 + i * 37 ))" -v needle_limit="$(unit_value limit "$i")" 'BEGIN {
        shift = (letter == "a") ? 0 : ((letter == "b") ? 2999 : 5998)
        printf "# Limits table %s for the %s service\n\n", letter, word
        for (k = 1; k <= lines; k++) {
          limit = 10000 + ((k * 7 + unit * 13 + shift) % 9000)
          if (letter == "a" && k == needle) limit = needle_limit
          printf "- item %04d: owner team-%s, region eu-%d, limit %d, window %d s.\n", k, word, (k % 5) + 1, limit, 20 + (k % 7) * 5
        }
      }' > "docs/u$nn/table-$letter.md"
    done
    {
      printf '"""Module u%s: lease handling for the %s service."""\n\n' "$nn" "$word"
      printf 'LEASE_SECONDS = %s\n\n\n' "$(unit_value lease "$i")"
      local f
      for f in $(seq 1 "$UNIT_FUNCTIONS"); do
        printf 'def u%s_step_%03d(value):\n    """Return value shifted by %d."""\n    return value + %d\n\n\n' "$nn" "$f" "$f" "$f"
      done
    } > "src/u$nn.py"
    cat > "scripts/u$nn.sh" <<EOF
#!/usr/bin/env bash
printf 'info: wrote index $(unit_value index "$i")\n'
for shard in \$(seq 1 60); do
  if [ "\$shard" -eq $(( i + 20 )) ]; then
    printf '$(unit_value error "$i"): replica drift on shard %03d\n' "\$shard"
  else
    printf 'ok   shard %03d synced\n' "\$shard"
  fi
done
printf 'done: 59 of 60 shards synced\n'
EOF
    {
      printf 'u\t1\taside\t%s\t%s\n' "$i" "$(unit_value port "$i")"
      printf 'u\t2\tfinding\t%s\t%s\n' "$i" "$(unit_value lease "$i")"
      printf 'u\t3\terror\t%s\t%s\n' "$i" "$(unit_value error "$i")"
      printf 'u\t4\toutput\t%s\t%s\n' "$i" "$(unit_value index "$i")"
      printf 'u\t5\tneedle\t%s\t%s\n' "$i" "$(unit_value limit "$i")"
    } >> capture/answers.tsv
  done
}

unit_prompt() {
  local i="$1" nn
  nn="$(printf '%02d' "$i")"
  printf 'Task %s: read src/u%s.py, docs/u%s/table-a.md, docs/u%s/table-b.md and docs/u%s/table-c.md, then run: bash scripts/u%s.sh  Give me one line on the module and one line on whether the script passed. By the way, the %s queue drains to port %s.' \
    "$i" "$nn" "$nn" "$nn" "$nn" "$nn" "$(unit_value word "$i")" "$(unit_value port "$i")"
}

units_quiz_prompt() {
  # units_quiz_prompt <first unit> <last unit>: five questions a task.
  local first="$1" last="$2" i nn n=0
  printf 'Without reading files or running commands, answer from what you already know, numbered. If you do not know an answer, write unknown for it.'
  for i in $(seq "$first" "$last"); do
    nn="$(printf '%02d' "$i")"
    printf ' %d) which port the %s queue drains to' "$(( n + 1 ))" "$(unit_value word "$i")"
    printf ' %d) the value of LEASE_SECONDS in src/u%s.py' "$(( n + 2 ))" "$nn"
    printf ' %d) the error code scripts/u%s.sh printed' "$(( n + 3 ))" "$nn"
    printf ' %d) the index file scripts/u%s.sh said it wrote' "$(( n + 4 ))" "$nn"
    printf ' %d) the limit of item %s in docs/u%s/table-a.md' "$(( n + 5 ))" "$(unit_value item "$i")" "$nn"
    n=$(( n + 5 ))
  done
}

field_of() {
  # field_of <stream-json file> <line type> <key>: the first value of a
  # number or string key on the last line of that type.
  grep -E "\"type\": ?\"$2\"" "$1" 2> /dev/null | tail -n 1 \
    | grep -Eo "\"$3\": ?(\"[^\"]*\"|[0-9.]+)" | head -n 1 \
    | sed -E 's/^"[^"]*": ?//; s/^"//; s/"$//' || true
}

context_of() {
  # context_of <stream-json file>: input tokens of the last model call.
  local a b c
  a="$(field_of "$1" assistant input_tokens)"
  b="$(field_of "$1" assistant cache_creation_input_tokens)"
  c="$(field_of "$1" assistant cache_read_input_tokens)"
  printf '%d' "$(( ${a:-0} + ${b:-0} + ${c:-0} ))"
}

next_step() {
  STEP=$(( STEP + 1 ))
  STEP_LABEL="$(printf '%03d' "$STEP")"
}

checkpoint() {
  # checkpoint <name> <copy|main> <tasks done>: quiz copies of the session,
  # compact it (a copy of it, or the session itself), quiz copies of that.
  local name="$1" mode="$2" units_done="$3" target="" first last part
  local -a parts
  parts=(a b)
  first=1
  while [ "$first" -le "$units_done" ]; do
    last=$(( first + 2 ))
    if [ "$last" -gt "$units_done" ]; then last="$units_done"; fi
    parts+=("u$first-$last")
    first=$(( last + 1 ))
  done
  printf '\nCheckpoint %s: %s tasks done, about %s tokens.\n' "$name" "$units_done" "$LAST_CONTEXT"

  for part in "${parts[@]}"; do
    next_step
    ask "$STEP_LABEL" "$name-before-$part" "$(part_prompt "$part")" fork
  done

  next_step
  if [ "$mode" = "main" ]; then
    if ! ask "$STEP_LABEL" "$name-compact" "/compact" soft; then
      return 1
    fi
    target="$SESSION_ID"
    MAIN_COMPACTED=1
  else
    if ! ask "$STEP_LABEL" "$name-compact" "/compact" forkcompact; then
      printf '  no compaction at this size; the session carries on.\n'
      printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$mode" "$units_done" "$LAST_CONTEXT" "failed" >> capture/checkpoints.tsv
      return 0
    fi
    target="$(field_of "$LAST_OUT" result session_id)"
    if [ -z "$target" ] || [ "$target" = "$SESSION_ID" ]; then
      printf '  the compaction reached the session itself, so this is the last size.\n'
      target="$SESSION_ID"
      MAIN_COMPACTED=1
    fi
  fi
  if ! grep -q 'compact_boundary' "$LAST_OUT" 2> /dev/null; then
    printf '  step %s returned, but no compaction is on record.\n' "$STEP_LABEL"
    printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$mode" "$units_done" "$LAST_CONTEXT" "none" >> capture/checkpoints.tsv
    return 0
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$mode" "$units_done" "$LAST_CONTEXT" "$target" >> capture/checkpoints.tsv

  for part in "${parts[@]}"; do
    next_step
    ask "$STEP_LABEL" "$name-after-$part" "$(part_prompt "$part")" fork "$target"
  done
}

part_prompt() {
  case "$1" in
    a) printf '%s' "$PROMPT_QUIZ" ;;
    b) printf '%s' "$PROMPT_DETAILS" ;;
    u*) units_quiz_prompt "$(printf '%s' "${1#u}" | cut -d- -f1)" "$(printf '%s' "${1#u}" | cut -d- -f2)" ;;
  esac
}

ladder() {
  start_session
  # One exact rule for each task's script, the form the first runs used.
  local i
  for i in $(seq 1 "$MAX_UNITS"); do
    EXTRA_ALLOWED+=("Bash(bash scripts/u$(printf '%02d' "$i").sh)")
  done
  STEP_COUNT="?"
  STEP=0
  LAST_CONTEXT=0
  printf 'name\tmode\ttasks\ttokens_before\tsession\n' > capture/checkpoints.tsv
  {
    printf 'max_units=%s\nladder_sizes=%s\nstop_at_tokens=%s\nmax_total_usd=%s\n' "$MAX_UNITS" "$LADDER_SIZES" "$STOP_AT_TOKENS" "$MAX_TOTAL_USD"
  } >> capture/launch.txt

  printf '\nRunning the first session.\n'
  local label prompt
  for label in rules read-files aside scoped-rules checksum blocks-after decision; do
    case "$label" in
      rules) prompt="$PROMPT_RULES" ;;
      read-files) prompt="$PROMPT_READ" ;;
      aside) prompt="$PROMPT_ASIDE" ;;
      scoped-rules) prompt="$PROMPT_SCOPED" ;;
      checksum) prompt="$PROMPT_CHECKSUM" ;;
      blocks-after) prompt="$PROMPT_BLOCKS_AFTER" ;;
      decision) prompt="$PROMPT_DECISION" ;;
    esac
    next_step
    ask "$STEP_LABEL" "$label" "$prompt"
  done
  LAST_CONTEXT="$(context_of "$LAST_OUT")"

  local unit=0 sizes="$LADDER_SIZES" next_size cost stop=0 checkpoint_number=0 before=0 growth=0
  checkpoint "c$checkpoint_number" copy 0
  while [ "$MAIN_COMPACTED" = 0 ] && [ "$stop" = 0 ] && [ "$unit" -lt "$MAX_UNITS" ]; do
    unit=$(( unit + 1 ))
    next_step
    if ! ask "$STEP_LABEL" "task-$(printf '%02d' "$unit")" "$(unit_prompt "$unit")" soft; then
      printf '  task %s did not finish; compacting what is there.\n' "$unit"
      unit=$(( unit - 1 ))
      break
    fi
    before="$LAST_CONTEXT"
    LAST_CONTEXT="$(context_of "$LAST_OUT")"
    growth=$(( LAST_CONTEXT - before ))
    cost="$(field_of "$LAST_OUT" result total_cost_usd)"
    printf '  after task %s: about %s tokens, %s USD so far by Claude Code'"'"'s count.\n' "$unit" "$LAST_CONTEXT" "${cost:-?}"
    if [ "$LAST_CONTEXT" -ge "$STOP_AT_TOKENS" ]; then
      stop=1
    elif [ $(( LAST_CONTEXT + growth * 3 / 2 )) -gt "$HARD_LIMIT_TOKENS" ]; then
      printf '  one more task could pass %s tokens; no more tasks.\n' "$HARD_LIMIT_TOKENS"
      stop=1
    elif [ -n "$cost" ] && awk -v a="$cost" -v b="$MAX_TOTAL_USD" 'BEGIN { exit !(a > b) }'; then
      printf '  the cost ceiling is reached; no more tasks.\n'
      stop=1
    else
      next_size="${sizes%% *}"
      if [ -n "$next_size" ] && [ "$LAST_CONTEXT" -ge "$next_size" ]; then
        checkpoint_number=$(( checkpoint_number + 1 ))
        checkpoint "c$checkpoint_number" copy "$unit"
        case "$sizes" in
          *" "*) sizes="${sizes#* }" ;;
          *) sizes="" ;;
        esac
      fi
    fi
  done

  if [ "$MAIN_COMPACTED" = 0 ]; then
    checkpoint_number=$(( checkpoint_number + 1 ))
    checkpoint "c$checkpoint_number" main "$unit" || printf 'The last compaction did not run.\n'
  fi
  if [ "$MAIN_COMPACTED" = 1 ]; then
    next_step
    ask "$STEP_LABEL" shell-command "$PROMPT_SHELL" soft || true
  fi

  printf '\n'
  cat capture/checkpoints.tsv
  collect
}

count_records() {
  # count_records <file>: non-empty lines in a capture file, 0 if it is absent.
  if [ -s "$1" ]; then
    grep -c . "$1" || true
  else
    printf '0\n'
  fi
}

collect() {
  if [ ! -d "$CAPTURE_DIR" ]; then
    printf 'Stopping: %s does not exist. Run setup or run first.\n' "$CAPTURE_DIR"
    exit 1
  fi
  cd "$CAPTURE_DIR"

  if [ ! -s capture/postcompact.jsonl ] && ! ls capture/step-*.jsonl > /dev/null 2>&1; then
    printf 'Stopping: nothing was recorded in %s/capture.\n' "$CAPTURE_DIR"
    printf 'Check that Claude Code was started in %s and that /compact ran.\n' "$CAPTURE_DIR"
    exit 1
  fi

  mkdir -p "$OUT_DIR"
  cp capture/* "$OUT_DIR/"
  cp PROMPTS.md CLAUDE.md "$OUT_DIR/"

  # The session transcript: at the path Claude Code gave the hooks, or found
  # by the session ID that "run" chose.
  local transcript="" session_id="" projects_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
  if [ -s capture/postcompact.jsonl ]; then
    transcript="$(sed -n 's/.*"transcript_path": *"\([^"]*\)".*/\1/p' capture/postcompact.jsonl | tail -n 1)"
  fi
  if [ -s capture/session-id.txt ]; then
    session_id="$(cat capture/session-id.txt)"
    if [ -f "$transcript" ] && [ -f "$(dirname "$transcript")/$session_id.jsonl" ]; then
      # Several sessions may be on record; take the capture session's own.
      transcript="$(dirname "$transcript")/$session_id.jsonl"
    elif [ ! -f "$transcript" ] && [ -d "$projects_dir" ]; then
      transcript="$(find "$projects_dir" -name "$session_id.jsonl" 2> /dev/null | head -n 1)"
    fi
  fi
  if [ -n "$transcript" ] && [ -f "$transcript" ]; then
    cp "$transcript" "$OUT_DIR/transcript.jsonl"
    if [ -s capture/checkpoints.tsv ]; then
      local name copy_id
      while IFS="$(printf '\t')" read -r name _ _ _ copy_id; do
        if [ -f "$(dirname "$transcript")/$copy_id.jsonl" ] && [ "$copy_id" != "$(cat capture/session-id.txt)" ]; then
          cp "$(dirname "$transcript")/$copy_id.jsonl" "$OUT_DIR/transcript-$name.jsonl"
        fi
      done < capture/checkpoints.tsv
    fi
  else
    printf 'Note: the session transcript was not found.\n'
  fi

  if [ ! -s "$OUT_DIR/version.txt" ]; then
    if command -v claude > /dev/null 2>&1; then
      claude --version > "$OUT_DIR/version.txt" 2>&1 || true
    else
      printf 'claude not on PATH\n' > "$OUT_DIR/version.txt"
    fi
  fi
  uname -srm > "$OUT_DIR/machine.txt"

  # Modification times of the files Claude read (macOS form, then GNU form).
  ls -lT src src/api services/billing docs > "$OUT_DIR/files.txt" 2> /dev/null \
    || ls -l --time-style=full-iso src src/api services/billing docs > "$OUT_DIR/files.txt"

  tar -czf "$OUT_ARCHIVE" -C "$(dirname "$OUT_DIR")" "$(basename "$OUT_DIR")"

  printf '\nCollected into %s\n\n' "$OUT_DIR"
  printf 'SessionStart records: %s\n' "$(count_records capture/sessionstart.jsonl)"
  printf 'PreCompact records:   %s\n' "$(count_records capture/precompact.jsonl)"
  printf 'PostCompact records:  %s\n' "$(count_records capture/postcompact.jsonl)"
  if [ -s capture/postcompact.jsonl ]; then
    printf 'Triggers seen:        %s\n' "$(grep -o '"trigger": *"[a-z]*"' capture/postcompact.jsonl | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
  fi
  printf '\nSkim the folder, then send %s\n' "$OUT_ARCHIVE"
}

case "$COMMAND" in
  run) run ;;
  setup) setup ;;
  collect) collect ;;
  ladder) ladder ;;
  *) usage; exit 1 ;;
esac
