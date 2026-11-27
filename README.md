# compact-capture-kit

Scripts and data that measure what Claude Code's `/compact` keeps and what it drops.

They are behind the Trail post "Claude Code /compact: what it keeps and what it drops", on the [Trail blog](https://trailhq.com/blog). Every count in that post is in a results file here, and each results file names the script that wrote it.

The repository holds labels, counts and scripts. It holds no session transcripts.

## Where each number in the post comes from

| In the post | Results file | Written by | Reads |
| --- | --- | --- | --- |
| 383 compactions, 147 sessions, 187 manual and 196 automatic; the text-match check (3,408 of 3,430); the second judge | `analysis/results-real.json` | `analysis/freeze1.py` | `real/judge-swechat/`, `real/judge-queued/`, `real/judge-second/`, `real/read-swechat/` |
| 32 users; rules kept at the first, second and third compaction (the three-row chart); the one-user check; text search | `analysis/results-clusters.json` | `analysis/freeze4.py` | `real/judge-swechat/` and SWE-chat's `sessions.parquet` |
| The replay: answers before and after one, two and three compactions (the first chart); the two releases compared | `analysis/results-replay.json` | `analysis/freeze2.py` | `replay/out-proto/` |
| The 1M-token scripted session: 26 questions, seven summaries, auto memory on and off | `analysis/results-session-a.json` | `analysis/freeze3.py` | the raw run, which is not published |
| The examples quoted in the post | `analysis/results-examples.json` | `analysis/freeze5.py` | the raw runs, which are not published |

The two charts are `analysis/figure-01-rules-after-compactions.png` and `analysis/figure-03-kept-by-compaction.png`. `analysis/make_chart_v5.py` draws them from the results files. The post's second picture is a screenshot of `/context`, so there is no script for it.

## What you can rerun from this repository

These need Python 3 only, and they reproduce the published results files byte for byte:

```bash
git clone https://github.com/trailhq/claude-code-compact-capture-kit.git ~/compact-capture-kit
cd ~/compact-capture-kit
KIT=$PWD python3 analysis/freeze1.py     # writes analysis/results-real.json
KIT=$PWD python3 analysis/freeze2.py     # writes analysis/results-replay.json
python3 analysis/make_chart_v5.py        # redraws the two charts; needs matplotlib
```

A chart you redraw can differ from ours by a pixel, because fonts and matplotlib versions differ.

`freeze4.py` also reproduces its file, once you have SWE-chat's index. It needs pyarrow and `data/SWE-chat/sessions.parquet`, which you download yourself (see "The dataset").

`freeze3.py` and `freeze5.py` read the raw output of our own runs. They are here to show how the numbers were counted. To run them, make your own run with `auto/` first.

The shell wrappers (`*.sh` under `real/`, `replay/` and `auto/`) expect the repository at `~/compact-capture-kit`.

## What is here

| Folder | What it holds |
| --- | --- |
| `real/` | The study of real compactions. `scan_swechat.py` finds compactions in transcripts. `judge.py` has a model compare each summary with the messages the user typed before it. `read_all.py` is the full reading of 24 compactions. The `judge-*/` and `read-swechat/` folders hold our labels and the prompts the judges were given. |
| `replay/` | The replay of seven real sessions on Claude Code 2.1.327. `slice.py` cuts a transcript at each original compaction. `replay.py` lets the automatic compaction run. `replay_ask.py` writes questions from the rules a user typed and asks them of copies. `out-proto/` holds the sizes, the grades and the labels. |
| `auto/` | The scripted session that ran to the 1M-token limit. `build_script.py` writes the developer's messages, the 36 side notes and the 26 questions. `auto_run.py` types them into one session, and `cross.sh` takes saved copies over the limit. See `auto/README.md`. |
| `analysis/` | The freeze scripts, the results files, the chart script and the charts. Also the seven summaries of the scripted session (`summary-*.txt`), its memory index, and the answers to the 26 questions after each compaction (`session-a/`). |
| Top level, `tools/`, `data/` | The first scripted tests, on Claude Code 2.1.311. The post quotes one answer pair from the ladder at 804K tokens. See "The first scripted tests". |

### The label files

`judge.jsonl` has one line per compaction. `path` is the SWE-chat transcript, and `order` is which compaction of the session it is. `trigger`, `pre_tokens`, `summary_words`, `time` and `version` come from the transcript. `cost` and `input_tokens` are what the judge's call used.

`items` has one entry per message the user typed:

- `where`: `recent` if the message was typed since the previous compaction, `older` if before it.
- `chars`: the length of the message. The text itself is not stored.
- `match`: what a plain text search of the summary found: `word for word`, `mostly` or `absent`.
- `tail`: true if Claude Code kept the message itself after the compaction. The judge skipped those.
- `kind`: `rule`, `correction`, `task`, `question`, `info` or `ack`.
- `lasting`: true if an assistant going on with the work would behave worse without knowing the message.
- `in_summary`: the judge's label, `verbatim`, `restated`, `partly` or `absent`.

`read-swechat/read.jsonl` has one line per compaction of the full reading. Each item has an `origin` (`user`, `claude`, `tool_output` or `earlier_summary`), a `kind`, `in_force` and a `label`.

`replay/out-proto/ask/ask.jsonl` has one line per session and round. Each item is one question, with the round its rule was typed in and a grade: `right`, `partly`, `wrong` or `unknown`.

## The dataset

The real sessions come from [SWE-chat](https://huggingface.co/datasets/SALT-NLP/SWE-chat), a dataset of real coding-agent sessions by [Baumann et al.](https://arxiv.org/abs/2604.20779). When we read its dataset card in November 2026, the licence was ODC-By and access needed a request on Hugging Face.

This repository holds what we derived from it: labels, counts and session ids. To get the transcripts, request access there, then run `real/fetch_swechat.sh` with one of the list files in `real/`.

## What is not here, and why

- **SWE-chat transcripts and their index.** They are the dataset's to give out.
- **The replay's questions, answer keys and answers.** They restate what SWE-chat users typed. `analysis/results-examples.json` keeps one traced example and leaves the text of the other three wrong answers out.
- **Prompts and replies of the judges (`raw/`).** They hold message text.
- **The raw output of our own runs.** A transcript carries the account's email address and organisation ID.
- **The author's own Claude Code sessions.** They were judged the same way, and only their counts are in `results-real.json`, under `own_meaning` and `own_reading`. `freeze1.py` keeps those counts as they are when the label files are absent.
- **`auto/ripgrep/tickets/`.** These are task files from the SWE-Milestone benchmark. `build_script.py` copies them from the benchmark's data, which you download yourself.

## What the runs cost

By the API's own count, on `claude-opus-5-5` unless noted:

| Run | Cost in USD |
| --- | --- |
| Judging 425 compaction records of SWE-chat (`real/judge-swechat/`) | 48.83 |
| Judging 290 records for messages typed while Claude was working (`real/judge-queued/`) | 25.67 |
| Second judge, `claude-sonnet-5-5`, 50 compactions | 3.62 |
| Full reading of 24 compactions | 40.88 |
| Replay, the 7 of 23 rows that report a cost. The other 16 rounds were ended once the summary was on disk, and Claude Code reports no cost for those. | 14.12 |
| Judging the replay's 21 summaries | 3.34 |
| The scripted session, as its driver summed the cost Claude Code reported | 198.73 |

Of the 425 judged records, 383 are counted. Eight are duplicates, and 34 come from sessions that did not run on a Claude model (`real/swe-chat-not-claude.json`).

## Limits

- A model judged every summary and graded every answer. No person graded.
- One user typed 166 of the 383 compactions and four of the seven replayed sessions.
- We could not see the `CLAUDE.md` files or the disks of the real sessions. A rule missing from a summary may still have been on disk.
- The replay and the scripted session ran on Claude Code 2.1.327, on one Mac. One copy of the scripted session crossed the limit on 2.1.311. The real sessions ran on releases 2.1.76 to 2.1.259.
- We tested what Claude could recall, not how it then behaved.

## The first scripted tests

These are the scripts at the top level. They ran on Claude Code 2.1.311 on 17 Nov 2026, with a manual `/compact` and sessions up to 804K tokens.

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
| `tools/make_charts.py` | Draws two charts of an earlier draft from the files in `data/`. |
| `data/ladder_kinds.csv`, `data/request_sizes.csv` | Our results from those runs. |

### What you need

- macOS or Linux, with bash, git and Python 3.
- Claude Code, signed in, as the `claude` command. We used version 2.1.311.
- matplotlib, for `tools/make_charts.py` only.
- `render_cast.py` needs more. Its first lines list what.

Every script asks its questions of copies of the session, made with `--fork-session`. The questions never enter the session that gets compacted.

### What a run costs

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

### Run a test

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

### Read a run

```bash
python3 -I analyze_capture.py ~/compact-capture-out
python3 -I analyze_ladder.py ~/compact-ladder-out
python3 -I analyze_rounds.py ~/compact-rounds-out
python3 -I analyze_stress.py ~/compact-stress-out
```

To count the ladder's answers by where each fact came from, and to draw the charts of an earlier draft:

```bash
python3 tools/ladder_kinds.py ~/compact-ladder-out data/ladder_kinds.csv
python3 tools/make_charts.py data img
```

`ladder_kinds.py` looks every planted value up in the transcript before it counts. It stops if a value turns up somewhere its kind says it should not.

### Before you share a run

An `-out` folder holds a copy of the session's transcript. A transcript carries your account's email address and organisation ID. A recording made with MCP servers loaded lists every tool they offer. Read both before you publish them.

### The data

`data/ladder_kinds.csv` has one row for each compaction, kind of fact and counting rule.

- `pre_tokens` is Claude Code's own count before the compaction. `request_before` is the size of the first quiz request sent to a copy just before, so it includes the quiz prompt.
- `kind` is where the fact came from. `typed`: the user typed it. `file`: it sits in an instruction file. `claude`: Claude stated it in a reply. `read`: it was only in the output of a Read call. `script`: it was only in the output of a Bash call.
- `rule` says which answer counts when a reply gives two. The post uses "later answer counts".

`data/request_sizes.csv` has one row for each recorded session: its first request, the last request before `/compact`, the first one after, and Claude Code's own `preTokens` and `postTokens`.

### Limits of these tests

- One run of each setup, on one Mac, one account and one model.
- A manual `/compact` with no instructions.
- A script scores each answer against a pattern. Read the answers it flags.
