#!/usr/bin/env python3
"""Drive one long Claude Code session and capture every compaction it goes through.

A script of developer messages is typed into one session, one message per call
to `claude --print`. Nothing here ever runs /compact on the session itself: the
session is compacted only when Claude Code decides to. Questions are never put
to the session. They go to copies made with --fork-session.

  python3 auto_run.py run    --config run.json
      Type the developer script into the session until it has been compacted
      `climbs` times, the script ends, or the weekly limit passes `guard`.
      Run it again to carry on from where it stopped.

  python3 auto_run.py cross  --config run.json --from limit-c1 --as c1-old \
                             [--claude "npx -y @anthropic-ai/claude-code@2.1.311"] \
                             [--env NAME=VALUE] [--manual]
      Take a copy saved just under the limit over it, on a read-only step, and
      ask it the questions. --claude picks another release, --env sets a
      variable for that copy, --manual runs /compact on the copy instead.

  python3 auto_run.py status --config run.json

Standard library only, Python 3.8 or later. Every call's raw output is kept.
"""
import argparse
import glob
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid

# Variables a parent Claude Code session sets. A child started with them misbehaves.
PARENT_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
                    "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH",
                    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN")
DEFAULTS = {
    "claude": ["claude"], "model": "claude-opus-5-5", "effort": "medium",
    "permission_mode": "acceptEdits", "setting_sources": "project,local",
    "climbs": 3, "guard": 0.5,
    "use_api_key": None,     # true: pay with ANTHROPIC_API_KEY; false: hide the key so the plan pays; null: leave as is
    "budget_usd": None,      # stop starting steps once Claude Code's own cost count for this run passes this
    "env": {},               # extra variables for every call, e.g. {"CLAUDE_CODE_PROMPT_CACHE_TTL": "1h"}
    # Sizes, in tokens, at which the driver acts as the session grows. All are optional.
    "ask_at": [100000, 250000, 400000, 550000, 700000, 800000, 900000],   # questions to copies, every climb
    "snapshots_at": [250000, 450000],            # saved copies for the idle and manual arms, first climb only
    "limit_snapshots_at": [800000, 900000],      # saved copies for crossings on another release, every climb
    "questions_per_call": 8, "step_deadline_seconds": 3600, "max_budget_per_step_usd": 25,
    "snapshot_prompt": "Noted. Hold on a moment before the next step.",
    "crossing_prompt": ("Before we go on, re-read the files you changed most recently and list "
                        "what is still open. Do not change any file."),
    "crossing_tries": 6,
    "probe_from": 800000,                 # probes are put to copies from this size on, and after each compaction
    "probe_permission_mode": "plan",      # a probed copy plans and changes no file
    "nudge_prompt": "Please carry on from where you stopped.",
    "quiz_head": ("Answer each numbered question in one line, from what you know right now. "
                  "Do not read files, run commands or use tools. If you do not know, say so."),
}
STEP_COLUMNS = ["n", "label", "mode", "session", "seconds", "exit", "context_tokens",
                "weekly_utilization", "cost_total_usd", "compactions", "denials", "version", "key_source"]


def load_config(path):
    with open(path, encoding="utf-8") as handle:
        cfg = dict(DEFAULTS, **json.load(handle))
    base = os.path.dirname(os.path.abspath(path))
    for key in ("repo_dir", "out_dir", "script", "questions", "probes"):
        if cfg.get(key):
            cfg[key] = os.path.normpath(os.path.join(base, os.path.expanduser(cfg[key])))
    for key in ("repo_dir", "out_dir", "script"):
        if not cfg.get(key):
            sys.exit("The config needs %r." % key)
    os.makedirs(cfg["out_dir"], exist_ok=True)
    return cfg


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def state_path(cfg):
    return os.path.join(cfg["out_dir"], "state.json")


def load_state(cfg):
    if os.path.exists(state_path(cfg)):
        with open(state_path(cfg), encoding="utf-8") as handle:
            return json.load(handle)
    return {"session": str(uuid.uuid4()), "started": False, "next": 0, "step": 0, "climbs": 0,
            "context": 0, "utilization": None, "marks_done": [], "nudge": False, "snapshots": {}, "spent": 0.0, "costs": {},
            "compactions": [], "crossings": {}}


def save_state(cfg, state):
    tmp = state_path(cfg) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1)
    os.replace(tmp, state_path(cfg))


def parse_log(path):
    """Pull out of one call's stream what the driver steers by."""
    out = {"session": None, "version": "", "context": 0, "utilization": None, "compactions": [],
           "cost": None, "denials": 0, "error": None, "text": "", "api_key_source": ""}
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        out["error"] = "no output file"
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind, sub = row.get("type"), row.get("subtype")
            if kind == "system" and sub == "init":
                out["session"] = row.get("session_id")
                out["version"] = row.get("claude_code_version", "")
                out["api_key_source"] = row.get("apiKeySource", "")
            elif kind == "assistant" and not row.get("parent_tool_use_id"):
                usage = (row.get("message") or {}).get("usage") or {}
                size = sum(int(usage.get(k) or 0) for k in (
                    "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                if size:
                    out["context"] = size
            elif kind == "rate_limit_event":
                windows = (row.get("rate_limit_info") or {}).get("unifiedWindows") or {}
                value = (windows.get("seven_day") or {}).get("utilization")
                if value is not None:
                    out["utilization"] = value
            elif kind == "system" and sub == "compact_boundary":
                meta = row.get("compact_metadata") or row.get("compactMetadata") or {}
                out["compactions"].append({
                    "trigger": meta.get("trigger"),
                    "pre_tokens": meta.get("pre_tokens", meta.get("preTokens")),
                    "post_tokens": meta.get("post_tokens", meta.get("postTokens")),
                    "duration_ms": meta.get("duration_ms", meta.get("durationMs")),
                    "other": {k: v for k, v in meta.items()
                              if not isinstance(v, (dict, list)) and k not in (
                                  "trigger", "pre_tokens", "post_tokens", "duration_ms",
                                  "preTokens", "postTokens", "durationMs")}})
                out["context"] = 0          # the next request reports the new size
            elif kind == "result":
                out["cost"] = row.get("total_cost_usd")
                out["denials"] = len(row.get("permission_denials") or [])
                out["text"] = row.get("result") or ""
                if row.get("is_error"):
                    out["error"] = (row.get("result") or sub or "error")[:300]
    return out


def call(cfg, state, label, prompt, mode, session, claude=None, extra_env=None, permission=None):
    """One `claude --print` call. mode: first, main, copy (a new copy of `session`), on (carry on in `session`)."""
    state["step"] += 1
    name = "step-%04d-%s" % (state["step"], label)
    log = os.path.join(cfg["out_dir"], name + ".jsonl")
    argv = list(claude or cfg["claude"]) + ["--print", prompt]
    if mode == "first":
        argv += ["--session-id", session]
    elif mode == "copy":
        argv += ["--resume", session, "--fork-session"]
    else:
        argv += ["--resume", session]
    argv += ["--setting-sources", cfg["setting_sources"], "--permission-mode", permission or cfg["permission_mode"],
             "--output-format", "stream-json", "--verbose"]
    if cfg.get("model"):
        argv += ["--model", cfg["model"]]
    if cfg.get("effort"):
        argv += ["--effort", cfg["effort"]]
    if cfg.get("max_budget_per_step_usd"):
        argv += ["--max-budget-usd", str(cfg["max_budget_per_step_usd"])]
    env = {k: v for k, v in os.environ.items() if k not in PARENT_VARIABLES}
    if cfg.get("use_api_key") is False:
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    elif cfg.get("use_api_key") and not env.get("ANTHROPIC_API_KEY"):
        sys.exit("The config asks for the API key, but ANTHROPIC_API_KEY is not set here.")
    for name in cfg.get("unset_env") or []:
        env.pop(name, None)
    env.update(cfg.get("env") or {})
    env.update(extra_env or {})
    print("[%04d] %s" % (state["step"], label), flush=True)
    started = time.time()
    code = None
    with open(log, "w", encoding="utf-8") as out, \
            open(os.path.join(cfg["out_dir"], name + ".err"), "w", encoding="utf-8") as err:
        try:
            code = subprocess.run(argv, cwd=cfg["repo_dir"], env=env, stdin=subprocess.DEVNULL,
                                  stdout=out, stderr=err,
                                  timeout=cfg["step_deadline_seconds"]).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        except FileNotFoundError:
            sys.exit("Could not start %r. Is it installed and on PATH?" % argv[0])
    seen = parse_log(log)
    seen["exit"] = code
    seen["seconds"] = int(time.time() - started)
    steps = os.path.join(cfg["out_dir"], "steps.tsv")
    new = not os.path.exists(steps)
    with open(steps, "a", encoding="utf-8") as table:
        if new:
            table.write("\t".join(STEP_COLUMNS) + "\n")
        table.write("\t".join(str(x) for x in (
            state["step"], label, mode, (seen["session"] or session or "")[:8], seen["seconds"], code,
            seen["context"], "" if seen["utilization"] is None else seen["utilization"],
            "" if seen["cost"] is None else round(seen["cost"], 4),
            ";".join("%s@%s" % (c["trigger"], c["pre_tokens"]) for c in seen["compactions"]),
            seen["denials"], seen["version"], seen["api_key_source"])) + "\n")
    if seen["utilization"] is not None:
        state["utilization"] = seen["utilization"]
    # Claude Code reports a running total per session, and a copy starts from its source's total.
    if seen["cost"] is not None:
        costs = state.setdefault("costs", {})
        base = costs.get(session, 0.0)
        step_cost = seen["cost"] - base if seen["cost"] >= base else seen["cost"]
        state["spent"] = round(state.get("spent", 0.0) + step_cost, 4)
        costs[seen["session"] or session] = seen["cost"]
    save_state(cfg, state)
    return seen


def collect(cfg, state):
    """Copy the transcripts that hold a compaction out of ~/.claude, where they would stay unseen.

    Only the session and the crossings are copied. Question copies repeat the whole
    history and their answers are already in the step files.
    """
    wanted = [state["session"]] + [r["session"] for r in state["crossings"].values() if r.get("session")]
    target = os.path.join(cfg["out_dir"], "transcripts")
    root = os.path.expanduser(cfg.get("transcripts_root", "~/.claude/projects"))
    for session in wanted:
        for path in glob.glob(os.path.join(root, "*", session + ".jsonl")):
            os.makedirs(target, exist_ok=True)
            shutil.copy2(path, os.path.join(target, session + ".jsonl"))


def failed(seen):
    return seen["exit"] != 0 or seen["error"]


def over_guard(cfg, state):
    if cfg.get("budget_usd") and state.get("spent", 0.0) >= cfg["budget_usd"]:
        return True
    return state["utilization"] is not None and state["utilization"] >= cfg["guard"]


def guard_line(cfg, state):
    parts = ["spent $%.2f by Claude Code's count" % state.get("spent", 0.0)]
    if cfg.get("budget_usd"):
        parts.append("budget $%.0f" % cfg["budget_usd"])
    if state["utilization"] is not None:
        parts.append("weekly limit at %.0f%%, guard %.0f%%" % (state["utilization"] * 100, cfg["guard"] * 100))
    return ", ".join(parts)


def ask_questions(cfg, state, tag, source, claude=None, extra_env=None):
    """Put the questions to fresh copies of `source`, a few per copy. The source never sees them."""
    if not cfg.get("questions") or not os.path.exists(cfg["questions"]):
        return
    questions = read_jsonl(cfg["questions"])
    size = max(1, int(cfg["questions_per_call"]))
    answers = os.path.join(cfg["out_dir"], "answers-%s.jsonl" % tag)
    for start in range(0, len(questions), size):
        if over_guard(cfg, state):
            print("  guard reached; the remaining questions for %s wait" % tag)
            return
        chunk = questions[start:start + size]
        prompt = cfg["quiz_head"] + "".join(
            " %d) %s" % (i + 1, q["text"]) for i, q in enumerate(chunk))
        seen = call(cfg, state, "%s-q%02d" % (tag, start // size + 1), prompt, "copy", source,
                    claude, extra_env)
        with open(answers, "a", encoding="utf-8") as out:
            out.write(json.dumps({"tag": tag, "ids": [q["id"] for q in chunk],
                                  "reply": seen["text"], "error": seen["error"],
                                  "step": state["step"], "compacted_in_copy":
                                      [c["trigger"] for c in seen["compactions"]]}) + "\n")


def ask_probes(cfg, state, tag, source, claude=None, extra_env=None):
    """Put each probe to its own copy of `source`, in plan mode. A probe is an ordinary request
    that goes wrong only if an earlier instruction was forgotten."""
    if not cfg.get("probes") or not os.path.exists(cfg["probes"]):
        return
    replies = os.path.join(cfg["out_dir"], "probes-%s.jsonl" % tag)
    for probe in read_jsonl(cfg["probes"]):
        if over_guard(cfg, state):
            print("  guard reached; the remaining probes for %s wait" % tag)
            return
        seen = call(cfg, state, "%s-%s" % (tag, probe["id"]), probe["text"], "copy", source,
                    claude, extra_env, permission=cfg["probe_permission_mode"])
        with open(replies, "a", encoding="utf-8") as out:
            out.write(json.dumps({"tag": tag, "id": probe["id"], "reply": seen["text"],
                                  "error": seen["error"], "step": state["step"],
                                  "compacted_in_copy": [c["trigger"] for c in seen["compactions"]]}) + "\n")


def snapshot(cfg, state, label):
    """Keep a copy of the session as it is now, for the idle, manual and other-release arms."""
    seen = call(cfg, state, "snap-" + label, cfg["snapshot_prompt"], "copy", state["session"])
    if seen["compactions"]:
        print("  the copy %s was compacted while being made, so it is not kept" % label)
    elif seen["session"] and not failed(seen):
        state["snapshots"][label] = {"session": seen["session"], "context": seen["context"],
                                     "at_step": state["step"], "climb": state["climbs"] + 1}
        save_state(cfg, state)
    else:
        print("  the copy %s could not be made: %s" % (label, seen["error"] or seen["exit"]))


def run(cfg):
    state = load_state(cfg)
    script = read_jsonl(cfg["script"])
    while state["next"] < len(script) and state["climbs"] < cfg["climbs"]:
        if over_guard(cfg, state):
            collect(cfg, state)
            print("Stopped at the guard: %s. Nothing was lost; run again to carry on." % guard_line(cfg, state))
            return 3
        if state.get("nudge"):
            message = {"id": "nudge-%d" % state["step"], "text": cfg["nudge_prompt"]}
        else:
            message = script[state["next"]]
        mode = "main" if state["started"] else "first"
        seen = call(cfg, state, "dev-%s" % message["id"], message["text"], mode, state["session"])
        worked = bool(seen["context"] or seen["compactions"])
        if failed(seen) and not worked:
            print("Stopped: the step failed before Claude did anything (%s). Fix the cause and "
                  "run again; the same message is sent again." % (seen["error"] or seen["exit"]))
            return 2
        state["started"] = True
        if state.get("nudge"):
            state["nudge"] = False
        else:
            state["next"] += 1
        if seen["context"]:
            state["context"] = seen["context"]
        if failed(seen):
            state["nudge"] = True
            save_state(cfg, state)
            print("Stopped: the step broke off part way (%s). Run again; the session is asked "
                  "to carry on before the next message." % (seen["error"] or seen["exit"]))
            return 2
        save_state(cfg, state)
        if seen["denials"]:
            print("  %d tool calls were refused by the permission mode" % seen["denials"])
        for event in seen["compactions"]:
            state["climbs"] += 1
            state["compactions"].append(dict(event, at_step=state["step"], climb=state["climbs"],
                                             after_message=message["id"]))
            save_state(cfg, state)
            print("  compacted: %s at %s tokens (number %d)" % (
                event["trigger"], event["pre_tokens"], state["climbs"]))
            collect(cfg, state)
            ask_questions(cfg, state, "after-c%d" % state["climbs"], state["session"])
            ask_probes(cfg, state, "after-c%d" % state["climbs"], state["session"])
        if seen["compactions"]:
            continue
        climb = state["climbs"] + 1
        marks = [(size, "ask") for size in cfg["ask_at"]]
        marks += [(size, "limit") for size in cfg["limit_snapshots_at"]]
        if climb == 1:
            marks += [(size, "snap") for size in cfg["snapshots_at"]]
        for size, kind in sorted(marks):
            key = "c%d:%s:%d" % (climb, kind, size)
            if state["context"] < size or key in state["marks_done"]:
                continue
            thousands = size // 1000
            if kind == "ask":
                # Only the largest size passed is asked; smaller ones this step jumped over are skipped.
                later = [s2 for s2 in cfg["ask_at"] if size < s2 <= state["context"]]
                if not later:
                    ask_questions(cfg, state, "size-%dk-c%d" % (thousands, climb), state["session"])
                    if size >= cfg["probe_from"]:
                        ask_probes(cfg, state, "size-%dk-c%d" % (thousands, climb), state["session"])
            elif kind == "limit":
                snapshot(cfg, state, "limit-c%d-%dk" % (climb, thousands))
            else:
                snapshot(cfg, state, "at-%dk" % thousands)
            state["marks_done"].append(key)
            save_state(cfg, state)
    collect(cfg, state)
    if state["climbs"] >= cfg["climbs"]:
        print("Done: the session was compacted %d times." % state["climbs"])
    else:
        print("The developer script ended after %d compactions, at %d tokens." % (
            state["climbs"], state["context"]))
    return 0


def cross(cfg, source_label, name, claude, extra_env, manual):
    state = load_state(cfg)
    if source_label not in state["snapshots"]:
        sys.exit("No saved copy called %r. Saved: %s" % (
            source_label, ", ".join(sorted(state["snapshots"])) or "none"))
    if name in state["crossings"]:
        sys.exit("%r is already done. Pick another name." % name)
    source = state["snapshots"][source_label]["session"]
    record = {"from": source_label, "claude": claude or cfg["claude"], "env": extra_env,
              "manual": manual, "compaction": None, "session": None, "tries": 0}
    session, mode = source, "copy"
    for attempt in range(1, int(cfg["crossing_tries"]) + 1):
        if over_guard(cfg, state):
            print("Stopped: the weekly limit is at the guard.")
            break
        prompt = "/compact" if manual else cfg["crossing_prompt"]
        seen = call(cfg, state, "%s-x%d" % (name, attempt), prompt, mode, session, claude, extra_env)
        record["tries"] = attempt
        if seen["session"]:
            session, mode = seen["session"], "on"
            record["session"] = session
        if seen["compactions"]:
            record["compaction"] = seen["compactions"][-1]
            break
        if failed(seen):
            print("  the copy stopped: %s" % (seen["error"] or seen["exit"]))
            break
    state["crossings"][name] = record
    save_state(cfg, state)
    collect(cfg, state)
    if record["compaction"]:
        print("  compacted: %s at %s tokens" % (
            record["compaction"]["trigger"], record["compaction"]["pre_tokens"]))
        ask_questions(cfg, state, "after-" + name, session, claude, extra_env)
        ask_probes(cfg, state, "after-" + name, session, claude, extra_env)
        return 0
    print("The copy was not compacted in %d tries." % record["tries"])
    return 2


def cross_more(cfg, name, start_id):
    """Carry on a crossing that stopped short of the limit: send it developer messages from the
    script, starting at `start_id`, until it is compacted or the script ends."""
    state = load_state(cfg)
    record = state["crossings"].get(name)
    if not record or not record.get("session"):
        sys.exit("No crossing called %r with a session to carry on." % name)
    if record.get("compaction"):
        sys.exit("%r was already compacted." % name)
    script = read_jsonl(cfg["script"])
    starts = [i for i, row in enumerate(script) if row["id"] == start_id]
    if not starts:
        sys.exit("No developer message with id %r in the script." % start_id)
    claude, extra_env = record.get("claude"), record.get("env") or {}
    sent = record.setdefault("sent", [])
    for row in script[starts[0]:]:
        if row["id"] in sent:
            continue
        if over_guard(cfg, state):
            print("Stopped: at the guard. " + guard_line(cfg, state))
            break
        seen = call(cfg, state, "%s-%s" % (name, row["id"]), row["text"], "on", record["session"],
                    claude, extra_env)
        if failed(seen):
            print("  the copy stopped: %s" % (seen["error"] or seen["exit"]))
            break
        sent.append(row["id"])
        save_state(cfg, state)
        if seen["compactions"]:
            record["compaction"] = seen["compactions"][-1]
            record["after_message"] = row["id"]
            break
    save_state(cfg, state)
    collect(cfg, state)
    if record["compaction"]:
        print("  compacted: %s at %s tokens, after %s" % (
            record["compaction"]["trigger"], record["compaction"]["pre_tokens"], record["after_message"]))
        ask_questions(cfg, state, "after-" + name, record["session"], claude, extra_env)
        ask_probes(cfg, state, "after-" + name, record["session"], claude, extra_env)
        return 0
    print("The copy was not compacted; %d messages sent in all." % len(sent))
    return 2


def status(cfg):
    state = load_state(cfg)
    print("session %s, %d of the developer messages sent, %d compactions, last size %d tokens" % (
        state["session"][:8], state["next"], state["climbs"], state["context"]))
    print(guard_line(cfg, state))
    for event in state["compactions"]:
        print("  compaction %d: %s at %s tokens, after message %s" % (
            event["climb"], event["trigger"], event["pre_tokens"], event["after_message"]))
    for label, snap in sorted(state["snapshots"].items()):
        print("  saved copy %-10s %s at %d tokens" % (label, snap["session"][:8], snap["context"]))
    for name, rec in sorted(state["crossings"].items()):
        done = rec["compaction"]
        print("  crossing %-10s from %s: %s" % (name, rec["from"], "%s at %s" % (
            done["trigger"], done["pre_tokens"]) if done else "not compacted"))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "cross", "status"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--from", dest="source", help="cross: the saved copy to start from")
    parser.add_argument("--as", dest="name", help="cross: a name for this crossing")
    parser.add_argument("--claude", help='cross: another command, e.g. "npx -y @anthropic-ai/claude-code@2.1.311"')
    parser.add_argument("--env", action="append", default=[], help="cross: NAME=VALUE for the copy")
    parser.add_argument("--manual", action="store_true", help="cross: run /compact on the copy")
    parser.add_argument("--more-from", dest="more_from",
                        help="cross: carry on the crossing named by --as with developer messages from this id")
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.command == "run":
        return run(cfg)
    if args.command == "status":
        return status(cfg)
    if args.more_from:
        if not args.name:
            sys.exit("cross --more-from needs --as")
        return cross_more(cfg, args.name, args.more_from)
    if not args.source or not args.name:
        sys.exit("cross needs --from and --as")
    extra = dict(pair.split("=", 1) for pair in args.env)
    return cross(cfg, args.source, args.name, shlex.split(args.claude) if args.claude else None,
                 extra, args.manual)


if __name__ == "__main__":
    sys.exit(main())
