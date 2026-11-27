#!/usr/bin/env python3
"""replay.py LIST DATA_DIR OUT_DIR [--rounds 3] [--guard 0.6] [--budget USD] [--claude "<cmd>"] [--model NAME]

Study 3. Replays real sessions that were compacted several times, on today's Claude Code.
For each transcript in LIST (paths relative to DATA_DIR) and each round k:
  1. slice.py builds a transcript that ends where the original session's k-th compaction happened.
     From round 2 on it starts from the replayed session so far, so today's summary of the earlier
     rounds is what gets carried, not the original one.
  2. Claude Code resumes that file as a new session with the auto-compact window set just under its
     size and is sent "Continue.", so the automatic pass fires. /compact is never typed. Once the
     summary is on disk the call is ended; the model's reply to "Continue." is not used. When a call
     is ended that way Claude Code reports no cost for it, so cost_usd is empty for that round.
  3. The new session's transcript is copied to OUT_DIR/<session>/round-k.jsonl.
The model has no tools in these calls and the working directory is empty: the original repositories
are not on this machine, so nothing can be re-read from disk after a compaction.

OUT_DIR/rounds.tsv has one line per round. It can be stopped and run again. The key is hidden, so
the subscription pays; it stops when the weekly limit passes --guard. Standard library only.
"""
import argparse, glob, json, os, shlex, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                    "CLAUDE_CODE_PROMPT_CACHE_TTL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
COLUMNS = ("session", "round", "original_trigger", "original_pre_tokens", "window", "trigger", "pre_tokens",
           "post_tokens", "duration_ms", "kept_after", "cost_usd", "weekly_utilization", "new_session", "seconds",
           "exit", "version", "reply_cut")


def say(out_dir, text):
    with open(os.path.join(out_dir, "replay.log"), "a", encoding="utf-8") as handle:
        handle.write("%s %s\n" % (time.strftime("%H:%M:%S"), text))
    print(text, flush=True)


def events(path):
    seen = {"session": None, "compaction": None, "cost": None, "utilization": None, "error": "", "version": ""}
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind, sub = row.get("type"), row.get("subtype")
            if kind == "system" and sub == "init":
                seen["session"] = row.get("session_id")
                seen["version"] = row.get("claude_code_version") or row.get("version") or ""
            elif kind == "system" and sub == "compact_boundary":
                seen["compaction"] = row.get("compact_metadata") or row.get("compactMetadata") or {}
            elif kind == "rate_limit_event":
                window = ((row.get("rate_limit_info") or {}).get("unifiedWindows") or {}).get("seven_day") or {}
                if window.get("utilization") is not None:
                    seen["utilization"] = window["utilization"]
            elif kind == "result":
                seen["cost"] = row.get("total_cost_usd")
                if row.get("is_error"):
                    seen["error"] = str(row.get("result") or sub)[:300]
    return seen


def last_usage(path):
    """Tokens in the context at the last assistant reply recorded in a transcript."""
    total = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"usage"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            usage = (row.get("message") or {}).get("usage") if row.get("type") == "assistant" else None
            if usage and not row.get("isSidechain"):
                total = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                             "cache_read_input_tokens", "output_tokens"))
    return total


def summary_on_disk(root, session):
    """True once the new session's transcript holds the summary and what follows it."""
    for path in glob.glob(os.path.join(root, "*", session + ".jsonl")):
        after = None
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"isCompactSummary":true' in line.replace(" ", ""):
                    after = 0
                elif after is not None:
                    after += 1
        return after is not None and after >= 1
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("list"); parser.add_argument("data_dir"); parser.add_argument("out_dir")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--guard", type=float, default=0.6)
    parser.add_argument("--budget", type=float, default=0.0)
    parser.add_argument("--claude", default="npx -y @anthropic-ai/claude-code@2.1.327")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--transcripts", default=os.path.expanduser("~/.claude/projects"))
    parser.add_argument("--retry", action="store_true", help="try again the sessions that were stopped")
    args = parser.parse_args()
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    table = os.path.join(out_dir, "rounds.tsv")
    if not os.path.exists(table):
        with open(table, "w", encoding="utf-8") as handle:
            handle.write("\t".join(COLUMNS) + "\n")
    env = {k: v for k, v in os.environ.items() if k not in PARENT_VARIABLES}
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    spent, utilization = 0.0, None
    with open(args.list, encoding="utf-8") as handle:
        paths = [p.strip() for p in handle if p.strip() and not p.startswith("#")]
    say(out_dir, "== %s: %d sessions, %d rounds each" % (time.strftime("%Y-%m-%d"), len(paths), args.rounds))
    for rel in paths:
        name = os.path.basename(rel)[:8]
        home = os.path.join(out_dir, name)
        os.makedirs(os.path.join(home, "cwd"), exist_ok=True)
        for number in range(1, args.rounds + 1):
            done = os.path.join(home, "round-%d.jsonl" % number)
            if os.path.exists(done):
                continue
            if os.path.exists(os.path.join(home, "stopped")) and not args.retry:
                break
            if utilization is not None and utilization >= args.guard:
                say(out_dir, "Stopped: the weekly limit is at %.0f%%, guard %.0f%%." % (100 * utilization, 100 * args.guard))
                return 3
            if args.budget and spent >= args.budget:
                say(out_dir, "Stopped at the budget: $%.2f spent in this run." % spent)
                return 3
            cut = os.path.join(home, "F%d.jsonl" % number)
            command = [sys.executable, os.path.join(HERE, "slice.py"), os.path.join(args.data_dir, rel), str(number), cut]
            if number > 1:
                command += ["--carry", os.path.join(home, "round-%d.jsonl" % (number - 1))]
            sliced = subprocess.run(command, capture_output=True, text=True)
            if sliced.returncode != 0:
                say(out_dir, "  %s round %d: could not build the transcript: %s" % (name, number, (sliced.stderr or sliced.stdout).strip()[:200]))
                open(os.path.join(home, "stopped"), "w").write("slice\n")
                break
            facts = json.loads(sliced.stdout.strip().splitlines()[-1])
            size = int(facts.get("original_pre_tokens") or 0)
            # Claude Code works out the size of a resumed session from the last reply recorded in it,
            # which can be well under the size the original compaction reported. The window is set
            # from the smaller of the two, so the automatic pass fires and no full-size reply is paid for.
            recorded = last_usage(cut)
            basis = min(size, recorded) if recorded else size
            window = max(100000, min(1000000, (basis + 20000) // 1000 * 1000))
            argv = shlex.split(args.claude) + [
                "-p", "Continue.", "--resume", cut, "--fork-session", "--autocompact", str(window), "--tools", "",
                "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "project",
                "--model", args.model, "--effort", args.effort, "--output-format", "stream-json", "--verbose",
                "--max-budget-usd", "15"]
            log = os.path.join(home, "round-%d.stream.jsonl" % number)
            started = time.time()
            say(out_dir, "  %s round %d: %d records, original size %d, last recorded size %d, window %d" % (name, number, facts["records"], size, recorded, window))
            with open(log, "w", encoding="utf-8") as out, open(log[:-6] + ".err", "w", encoding="utf-8") as err:
                process = subprocess.Popen(argv, cwd=os.path.join(home, "cwd"), env=env, stdin=subprocess.DEVNULL,
                                           stdout=out, stderr=err)
                code, cut_short = None, False
                while True:
                    try:
                        code = process.wait(timeout=3)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if time.time() - started > 2400:
                        process.kill(); process.wait(); code = "timeout"
                        break
                    # The summary is all this study needs. Once it is on disk, the model's reply to
                    # "Continue." is not waited for: without tools it can run to many thousands of words.
                    now = events(log)
                    if now["compaction"] and now["session"] and summary_on_disk(args.transcripts, now["session"]):
                        time.sleep(4)
                        process.terminate()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill(); process.wait()
                        code, cut_short = 0, True
                        break
            seen = events(log)
            meta = seen["compaction"] or {}
            if seen["utilization"] is not None:
                utilization = seen["utilization"]
            spent += seen["cost"] or 0.0
            kept = len(((meta.get("preserved_messages") or meta.get("preservedMessages") or {}).get("uuids")) or [])
            with open(table, "a", encoding="utf-8") as handle:
                handle.write("\t".join(str(x) for x in (
                    name, number, facts.get("original_trigger"), size, window, meta.get("trigger", ""),
                    meta.get("pre_tokens", meta.get("preTokens", "")), meta.get("post_tokens", meta.get("postTokens", "")),
                    meta.get("duration_ms", meta.get("durationMs", "")), kept,
                    "" if seen["cost"] is None else round(seen["cost"], 4),
                    "" if utilization is None else utilization, seen["session"] or "", int(time.time() - started),
                    code, seen["version"], cut_short)) + "\n")
            if code != 0 or seen["error"] or not meta:
                why = seen["error"] or ("no compaction" if code == 0 else "exit %s" % code)
                say(out_dir, "  %s round %d: stopped this session: %s" % (name, number, why))
                open(os.path.join(home, "stopped"), "w").write(why + "\n")
                break
            found = glob.glob(os.path.join(args.transcripts, "*", seen["session"] + ".jsonl"))
            if not found:
                say(out_dir, "  %s round %d: the new session's transcript was not found" % (name, number))
                open(os.path.join(home, "stopped"), "w").write("no transcript\n")
                break
            shutil.copyfile(found[0], done)
            say(out_dir, "  %s round %d: compacted (%s) at %s tokens, $%.2f, weekly limit %s" % (
                name, number, meta.get("trigger"), meta.get("pre_tokens", meta.get("preTokens")), seen["cost"] or 0.0,
                "?" if utilization is None else "%.0f%%" % (100 * utilization)))
    say(out_dir, "== finished this run, $%.2f by Claude Code's count" % spent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
