# auto: one long session, compacted only when Claude Code decides

This is the driver behind the post's 1M-token session. That session ran on
18 Nov 2026, on Claude Code 2.1.327 with `claude-opus-5-5`. It took 181 developer
messages and was compacted automatically at 967,211 tokens.

`ripgrep/` holds the script it typed: `developer.jsonl`, the 36 side notes in
`schedule.tsv`, the 26 questions and their key. The ticket files it points at
are not here. `build_script.py` copies them from the SWE-Milestone data.

## What the driver does

`auto_run.py` types a script of developer messages into one Claude Code
session, one message per `claude --print` call. It never sends `/compact` to
that session. The session is compacted when Claude Code decides.

- **Questions go to copies.** Every question is put to a copy made with
  `--fork-session`. The session itself never sees one.
- **As the session grows** it asks the questions at set sizes, and saves copies
  for the idle, manual and other-release arms.
- **After each compaction** it asks the questions again and copies the
  transcript into the output folder.
- **The guard.** After every call it reads the weekly-limit figure Claude Code
  reports. At the guard it stops starting steps. Run it again to carry on.
- **A broken step.** If a call fails before Claude did anything, the same
  message is sent again. If it broke off part way, the session is asked to
  carry on first.

## Commands

    python3 auto_run.py run    --config run.A.json
    python3 auto_run.py status --config run.A.json
    python3 auto_run.py cross  --config run.A.json --from limit-c1-900k --as c1-old \
        --claude "npx -y @anthropic-ai/claude-code@2.1.311"
    python3 auto_run.py cross  --config run.A.json --from limit-c1-900k --as c1-nomem \
        --env CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
    python3 auto_run.py cross  --config run.A.json --from at-450k --as manual-450k --manual

`cross` takes a saved copy over the limit on a read-only step, or compacts it
by hand with `--manual`, then asks the questions.

## What it writes, in `out_dir`

- `steps.tsv`: one row per call, with size, weekly-limit figure, cost so far,
  compactions, refused tool calls, release and which key paid.
- `step-NNNN-<label>.jsonl`: the raw output of each call.
- `answers-<tag>.jsonl`: replies to the questions, by batch.
- `state.json`: where the run stands. Deleting it starts a new session.
- `transcripts/`: the session and each crossing, copied out of `~/.claude`.

## Test without spending anything

`test/fake_claude.py` stands in for Claude Code. Point `"claude"` in a config at
`["python3", "test/fake_claude.py"]` and set `FAKE_STATE` to an empty folder.
