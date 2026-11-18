#!/usr/bin/env bash
# compact-stress.sh
#
# A stress test of what comes back WRONG after /compact, not only what goes
# missing. The first two experiments in this folder asked whether a fact was
# kept or lost. This one plants notes that change over time: values that get
# corrected, rules with a scope, rules with an exception, rules that a later
# message replaces, and reasons why something was tried and dropped. It then
# compacts the session three times and asks for the current state.
#
#   bash compact-stress.sh [directory]
#
# The failure types come from published reports: summaries that keep a stale
# value or widen a rule's scope as compactions pile up (murooka on DEV, Nov
# 2026), and constraints buried in ordinary messages (Lost in Context Compaction,
# arXiv 2608.11242).
#
# The script clones pytest 8.3.3 into the directory you name (default:
# ~/compact-stress) and runs one session of 36 short turns in three rounds,
# with a /compact after each round. Every turn asks one question about the
# source and carries one typed note. Quizzes go to copies of the session.
# The script writes in that directory, in "<directory>-out" and in
# "<directory>-out.tgz", and deletes nothing. The session gets no extra
# permissions: Claude Code lets it read files and run read-only commands.

set -euo pipefail

DIR="${1:-$HOME/compact-stress}"
OUT_DIR="${DIR}-out"
REPO_URL="${ROUNDS_REPO_SOURCE:-https://github.com/pytest-dev/pytest}"
REPO_TAG="8.3.3"
REPO_COMMIT="d0f136fe64f9374f18a04562305b178fb380d1ec"
CAPTURE_MODEL="${CAPTURE_MODEL:-}"
CAPTURE_EFFORT="${CAPTURE_EFFORT:-}"
MAX_BUDGET_PER_STEP_USD="${MAX_BUDGET_PER_STEP_USD-8}"
STEP_DEADLINE_SECONDS="${STEP_DEADLINE_SECONDS:-600}"
TURNS_PER_ROUND=12
PARENT_SESSION_VARIABLES="CLAUDECODE CLAUDE_CODE_CHILD_SESSION CLAUDE_CODE_SESSION_ID CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_EXECPATH CLAUDE_CODE_BRIDGE_SESSION_ID CLAUDE_CODE_MESSAGING_SOCKET CLAUDE_CODE_MESSAGING_TOKEN CLAUDE_EFFORT CLAUDE_PID CLAUDE_JOB_DIR AI_AGENT"
QUIZ_HEAD='Answer from what you already know, without reading files or running commands. Number your answers. If you have nothing on record for one, write unknown for it.'
PROBE_RECALL='List every standing instruction, decision and correction I have given you in this session as it stands now, one per line. If you have none on record, say none.'

new_uuid() {
  if command -v uuidgen > /dev/null 2>&1; then uuidgen | tr '[:upper:]' '[:lower:]'; else python3 -c 'import uuid; print(uuid.uuid4())'; fi
}

turn_prompt() {
  # One question about the source, then the typed note for this turn.
  printf 'In %s, on which line does `%s` start? One line. %s' \
    "$(sed -n "${1}p" capture/symbols.tsv | cut -f1)" "$(sed -n "${1}p" capture/symbols.tsv | cut -f2)" "$(sed -n "${1}p" capture/notes.txt)"
}

quiz_prompt() {
  # quiz_prompt <first question> <last question>
  local q n=0
  printf '%s' "$QUIZ_HEAD"
  for q in $(seq "$1" "$2"); do
    n=$(( n + 1 ))
    printf ' %d) %s' "$n" "$(sed -n "${q}p" capture/questions.txt)"
  done
}

ask() {
  # ask <label> <prompt> <main|copy>: one non-interactive call.
  local label="$1" prompt="$2" how="$3" status=0 started pid waited=0 name
  STEP=$(( STEP + 1 ))
  name="$(printf 'step-%02d-%s' "$STEP" "$label")"
  local -a session_flags
  if [ "$how" = "copy" ]; then
    session_flags=(--resume "$SESSION_ID" --fork-session)
  elif [ "$FIRST_STEP" = 1 ]; then
    session_flags=(--session-id "$SESSION_ID")
    FIRST_STEP=0
  else
    session_flags=(--resume "$SESSION_ID")
  fi
  printf '[%02d] %s\n' "$STEP" "$label"
  started="$(date +%s)"
  env ${STRIP_FLAGS[@]+"${STRIP_FLAGS[@]}"} claude --print "$prompt" \
    "${session_flags[@]}" \
    --setting-sources project,local \
    --permission-mode default \
    --output-format stream-json --verbose \
    ${MODEL_FLAGS[@]+"${MODEL_FLAGS[@]}"} \
    ${BUDGET_FLAGS[@]+"${BUDGET_FLAGS[@]}"} \
    < /dev/null > "capture/$name.jsonl" 2> "capture/$name.err" &
  pid=$!
  while kill -0 "$pid" 2> /dev/null; do
    if [ "$waited" -ge "$STEP_DEADLINE_SECONDS" ]; then
      kill "$pid" 2> /dev/null || true
      sleep 10
      kill -9 "$pid" 2> /dev/null || true
      break
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  wait "$pid" || status=$?
  printf '%s\t%s\t%s\t%s\t%s\n' "$STEP" "$label" "$how" "$(( $(date +%s) - started ))" "$status" >> capture/steps.tsv
  if [ "$status" -ne 0 ]; then
    printf '  stopped with exit code %s: ' "$status"
    tail -n 2 "capture/$name.err" || true
  fi
  if [ "$how" = "copy" ] && [ "$status" -eq 0 ] && grep -E '"type": ?"result"' "capture/$name.jsonl" | grep -Eq "\"session_id\": ?\"$SESSION_ID\""; then
    printf 'A quiz reached the session itself. Stopping.\n'
    collect
    exit 1
  fi
  return "$status"
}

quizzes() {
  # quizzes <stage>: all 26 questions in two halves and one open list, each
  # asked of its own copy of the session.
  ask "$1-quiz-1" "$(quiz_prompt 1 13)" copy || true
  ask "$1-quiz-2" "$(quiz_prompt 14 26)" copy || true
  ask "$1-quiz-recall" "$PROBE_RECALL" copy || true
}

collect() {
  mkdir -p "$OUT_DIR"
  cp capture/* "$OUT_DIR/"
  local transcript=""
  if [ -s capture/sessionstart.jsonl ]; then
    transcript="$(sed -n '1p' capture/sessionstart.jsonl | sed -n 's/.*"transcript_path": *"\([^"]*\)".*/\1/p')"
  fi
  if [ -n "$transcript" ] && [ -f "$transcript" ]; then cp "$transcript" "$OUT_DIR/transcript.jsonl"; fi
  uname -srm > "$OUT_DIR/machine.txt"
  tar -czf "$OUT_DIR.tgz" -C "$(dirname "$OUT_DIR")" "$(basename "$OUT_DIR")"
  printf '\nCollected into %s and %s.tgz\n' "$OUT_DIR" "$OUT_DIR"
}

if ! command -v claude > /dev/null 2>&1; then printf 'Stopping: the claude command is not on PATH.\n'; exit 1; fi
if [ -e "$DIR" ]; then printf 'Stopping: %s already exists. Name another directory.\n' "$DIR"; exit 1; fi

git clone --quiet --depth 1 --branch "$REPO_TAG" "$REPO_URL" "$DIR" 2> /dev/null
cd "$DIR"
if [ "$(git rev-parse HEAD)" != "$REPO_COMMIT" ]; then printf 'Stopping: the clone is not pytest %s as expected.\n' "$REPO_TAG"; exit 1; fi
mkdir -p .claude capture
printf '.claude/\ncapture/\n' >> .git/info/exclude
cat > .claude/settings.json <<'EOF'
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "{ cat; echo; } >> \"$CLAUDE_PROJECT_DIR/capture/sessionstart.jsonl\""}]}],
    "PostCompact": [{"hooks": [{"type": "command", "command": "{ cat; echo; } >> \"$CLAUDE_PROJECT_DIR/capture/postcompact.jsonl\""}]}]
  }
}
EOF

# One symbol to ask about in each of 36 source files.
: > capture/symbols.tsv
for file in $(ls src/_pytest/*.py | grep -v '__init__' | sort | sed -n '1,36p'); do
  line="$(grep -nE '^(def|class) [A-Za-z_]+' "$file" | sed -n '3p')"
  if [ -z "$line" ]; then line="$(grep -nE '^(def|class) [A-Za-z_]+' "$file" | sed -n '1p')"; fi
  printf '%s\t%s\t%s\n' "$file" "$(printf '%s' "$line" | sed -E 's/^[0-9]+:(def|class) ([A-Za-z_0-9]+).*/\2/')" "${line%%:*}" >> capture/symbols.tsv
done

# The typed notes, one a turn. Lines 1 to 12 are round one, 13 to 24 round
# two, 25 to 36 round three. Some notes correct or replace an earlier one.
cat > capture/notes.txt <<'EOF'
The ledger export job ends at 02:45 each night.
A rule for files under testing/ only: never reformat them.
Our CI runs on Python 3.9 only.
On this repo we rebase and never use merge commits.
The release owner this cycle is Marcus.
On Fridays only, do not propose merging anything.
Correction to something I said earlier: the ledger export ends at 02:15, not 02:45.
Never suggest adding a dependency, except attrs, which we already ship.
The flaky-test budget is 12 retries a day.
Address me as captain in your replies.
The code freeze starts on Thursday.
Actually no, the code freeze starts on Wednesday.
I had this wrong before: CI runs on Python 3.11 only, not 3.9.
Staging listens on port 7443.
In src/_pytest/config/ only, keep lines under 80 characters. Elsewhere I do not mind.
We tried caching the collection tree in a pickle last month and dropped it, because node IDs changed between runs.
Correction: the flaky-test budget is 5 retries a day, not 12.
Do not use abbreviations in your replies, except CI and PR.
New policy that replaces the old one: we now use merge commits and never rebase.
When you write Windows paths, and only then, use backslashes.
We also tried running the suite under PyPy and gave up, because the assertion rewriter was three times slower.
Never recommend skipping a test, unless it is marked slow.
In examples, use the WARNING log level by default.
Do not suggest the loadfile mode of xdist again: we tried it and fixture teardown order broke.
Change of plan: Ines is the release owner this cycle, not Marcus.
For changelog entries only, write in the past tense.
We tried pinning pluggy to 1.3 and backed it out, since hook wrappers stopped firing.
Sorry, staging is on port 7643, not 7443.
Drop the captain thing. From now on address me as chief.
No shell one-liners longer than 80 characters, except for git log commands.
Scrap what I said about log levels: use INFO by default in examples.
Only for functions with more than five parameters, suggest a dataclass.
Fixes should target the 8.3.x branch.
Moving logs to JSON was tried and reverted: the terminal reporter could not align its columns.
Changed my mind: fixes should target main, not 8.3.x.
We tried a 30-second global timeout and removed it, as slow Windows runners hit it during import.
EOF

cat > capture/questions.txt <<'EOF'
What time does the ledger export job end?
Which Python version does our CI run on?
Who is the release owner this cycle?
What is the flaky-test budget per day?
Which port does staging listen on?
On which day does the code freeze start?
State my rule about reformatting files, including where it applies.
State my rule about proposing merges, including when it applies.
State my rule about line length, including where it applies.
State my rule about backslashes, including when it applies.
State my rule about tense, including where it applies.
State my rule about suggesting a dataclass, including when it applies.
State my rule about adding dependencies, including any exception.
State my rule about abbreviations, including any exception.
State my rule about skipping tests, including any exception.
State my rule about shell one-liners, including any exception.
Do we rebase or use merge commits on this repo?
How should you address me?
Which log level should examples use by default?
Which branch should fixes target?
Why did we drop the pickle cache of the collection tree?
Why did we give up on running the suite under PyPy?
Why should you not suggest the loadfile mode of xdist?
Why did we back out the pluggy 1.3 pin?
Why was moving logs to JSON reverted?
Why did we remove the 30-second global timeout?
EOF

SESSION_ID="$(new_uuid)"
FIRST_STEP=1
STEP=0
MODEL_FLAGS=()
BUDGET_FLAGS=()
STRIP_FLAGS=()
if [ -n "$CAPTURE_MODEL" ]; then MODEL_FLAGS=(--model "$CAPTURE_MODEL"); fi
if [ -n "$CAPTURE_EFFORT" ]; then MODEL_FLAGS+=(--effort "$CAPTURE_EFFORT"); fi
if [ -n "$MAX_BUDGET_PER_STEP_USD" ]; then BUDGET_FLAGS=(--max-budget-usd "$MAX_BUDGET_PER_STEP_USD"); fi
for variable in $PARENT_SESSION_VARIABLES; do
  if printenv "$variable" > /dev/null 2>&1; then STRIP_FLAGS+=(-u "$variable"); fi
done
printf '%s\n' "$SESSION_ID" > capture/session-id.txt
claude --version > capture/version.txt 2>&1 || true
printf 'repo=%s\ntag=%s\ncommit=%s\nmodel_asked_for=%s\neffort_asked_for=%s\nclaude_command=%s\n' "$REPO_URL" "$REPO_TAG" "$REPO_COMMIT" "$CAPTURE_MODEL" "$CAPTURE_EFFORT" "$(command -v claude)" > capture/launch.txt
printf 'step\tlabel\thow\tseconds\texit\n' > capture/steps.tsv

printf 'pytest %s is ready in %s. Running the session.\n' "$REPO_TAG" "$DIR"
failed=0
for round in 1 2 3; do
  for t in $(seq $(( (round - 1) * TURNS_PER_ROUND + 1 )) $(( round * TURNS_PER_ROUND ))); do
    if ! ask "$(printf 'r%d-turn-%02d' "$round" "$t")" "$(turn_prompt "$t")" main; then failed=1; break; fi
  done
  if [ "$failed" = 1 ]; then break; fi
  if [ "$round" = 1 ]; then quizzes r0; fi
  if ! ask "r$round-compact" "/compact" main; then failed=1; break; fi
  quizzes "r$round"
done
if [ "$failed" = 1 ]; then printf 'A step of the session failed; the run stops here with what it has.\n'; fi
collect
