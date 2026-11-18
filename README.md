# compact-capture-kit

Scripts that measure what Claude Code's `/compact` keeps and what it drops.

They ran every test in the Trail post "Claude Code /compact: what it keeps and what it drops, measured up to 804K tokens", on the [Trail blog](https://trailhq.com/blog). The numbers behind that post's two charts are in `data/`.

## What is here

| File | What it does |
| --- | --- |
| `compact-capture.sh` | Builds a scratch repo, plants facts in one Claude Code session, runs `/compact`, and asks what Claude still knows. Its `ladder` command grows the same session task by task and compacts it at several sizes. |
| `compact-rounds.sh` | Types six ground rules once into a session on pytest 8.3.3. It then compacts three times, with work in between, and probes whether the rules still hold. |
| `compact-stress.sh` | Types 36 notes that hold 26 threads into a session on pytest 8.3.3. Ten threads change later. It compacts three times and asks for the current state of each thread. |
| `compact-shots.sh`, `tui-capture.py` | Record an interactive session in a pseudo-terminal, with nobody typing. |
| `render_cast.py` | Turns such a recording into pictures. |
| `analyze_capture.py`, `analyze_ladder.py`, `analyze_rounds.py`, `analyze_stress.py` | Each prints a plain-text report for one run. |
| `tools/ladder_kinds.py` | Counts the ladder's right answers by where each fact came from. |
| `tools/request_sizes.py` | Reads request sizes around a compaction from session transcripts. |
| `tools/make_charts.py` | Draws the post's charts from the two files in `data/`. |
| `data/ladder_kinds.csv`, `data/request_sizes.csv` | Our results, from the runs of 17 Nov 2026. |

## What you need

- macOS or Linux, with bash, git and Python 3.
- Claude Code, signed in, as the `claude` command. We used version 2.1.311.
- matplotlib, for `tools/make_charts.py` only.
- `render_cast.py` needs more. Its first lines list what.

Every script asks its questions of copies of the session, made with `--fork-session`. The questions never enter the session that gets compacted.

## What a run costs

These are real Claude Code sessions. They use your plan or your credit.

By Claude Code's own count, our runs on claude-opus-5-5 at medium effort cost:

| Run | Cost in USD |
| --- | --- |
| `compact-capture.sh run` | 1.37 for the session, plus four quiz copies |
| `compact-capture.sh ladder`, to 804K tokens | 13.06 |
| `compact-rounds.sh` | 4.47 |
| `compact-stress.sh` | 4.93 |
| `compact-stress.sh` with auto memory off | 3.52 |

Each script caps what one step may spend with `MAX_BUDGET_PER_STEP_USD`. The ladder also stops once the run has cost more than `MAX_TOTAL_USD`, which is 20 unless you set it.

## Run a test

Give each run a directory that does not exist yet. A script stops if the directory is already there.

```bash
# Optional. Leave these unset to use your own defaults.
export CAPTURE_MODEL=claude-opus-5-5 CAPTURE_EFFORT=medium

bash compact-capture.sh run ~/compact-capture       # one session, one compaction
bash compact-capture.sh ladder ~/compact-ladder     # the same session at several sizes
bash compact-rounds.sh ~/compact-rounds             # six rules, three compactions
bash compact-stress.sh ~/compact-stress             # 36 notes, three compactions
```

To run the stress test with Claude Code's auto memory off:

```bash
CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 bash compact-stress.sh ~/compact-stress-nomem
```

To record an interactive session, with and without your MCP servers, and to measure what one `/context` call adds:

```bash
bash compact-shots.sh run ~/compact-shots
SHOTS_FLAGS="--strict-mcp-config" bash compact-shots.sh run ~/compact-shots-b
bash compact-shots.sh context-cost ~/compact-context-cost
```

The ladder has four settings:

| Variable | Default | What it sets |
| --- | --- | --- |
| `MAX_UNITS` | 10 | How many tasks the session can grow by. Each task adds about 68K tokens. |
| `LADDER_SIZES` | `240000 500000` | The sizes at which a copy of the session is compacted. |
| `STOP_AT_TOKENS` | 780000 | The size past which the session itself is compacted. |
| `MAX_TOTAL_USD` | 20 | The cost at which the run stops growing. |

A script writes in the directory you name, in a sibling `<directory>-out` folder and in `<directory>-out.tgz`. It deletes nothing. Claude Code keeps its own records of each session under `~/.claude/projects/`, as it does for any session.

## Read a run

```bash
python3 -I analyze_capture.py ~/compact-capture-out
python3 -I analyze_ladder.py ~/compact-ladder-out
python3 -I analyze_rounds.py ~/compact-rounds-out
python3 -I analyze_stress.py ~/compact-stress-out
```

To count the ladder's answers by where each fact came from, and to draw the charts:

```bash
python3 tools/ladder_kinds.py ~/compact-ladder-out data/ladder_kinds.csv
python3 tools/make_charts.py data img
```

`ladder_kinds.py` looks every planted value up in the transcript before it counts. It stops if a value turns up somewhere its kind says it should not.

## Before you share a run

An `-out` folder holds a copy of the session's transcript. A transcript carries your account's email address and organisation ID. A recording made with MCP servers loaded lists every tool they offer. Read both before you publish them.

## The data

`data/ladder_kinds.csv` has one row for each compaction, kind of fact and counting rule.

- `pre_tokens` is Claude Code's own count before the compaction. `request_before` is the size of the first quiz request sent to a copy just before, so it includes the quiz prompt.
- `kind` is where the fact came from. `typed`: the user typed it. `file`: it sits in an instruction file. `claude`: Claude stated it in a reply. `read`: it was only in the output of a Read call. `script`: it was only in the output of a Bash call.
- `rule` says which answer counts when a reply gives two. The post uses "later answer counts".

`data/request_sizes.csv` has one row for each recorded session: its first request, the last request before `/compact`, the first one after, and Claude Code's own `preTokens` and `postTokens`.

## Limits

- One run of each setup, on one Mac, one account and one model.
- Claude Code 2.1.311. Later versions may differ.
- A manual `/compact` with no instructions. No automatic or idle compaction was run.
- A script scores each answer against a pattern. Read the answers it flags.

## An experiment to try

The stress test's 36 notes fit in one summary. Add notes to `compact-stress.sh` until an answer comes back wrong.
