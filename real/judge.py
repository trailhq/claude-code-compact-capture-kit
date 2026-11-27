#!/usr/bin/env python3
"""judge.py LIST DATA_DIR OUT_DIR [--workers N] [--budget USD] [--limit N] [--claude "<cmd>"] [--model NAME]

Study 1, meaning check. For every compaction in the listed transcripts, a model reads the summary
Claude Code wrote and the messages the person typed before it, and says for each message what kind
it is and whether the summary kept it: in the person's words, restated, partly, or not at all.

LIST      one transcript path per line, relative to DATA_DIR
OUT_DIR   judge.jsonl  one line per compaction, labels and counts only, no message text
          raw/         every prompt and reply, as sent and received (these hold message text)
          judge.log    what the script did

It runs `claude -p` once per batch of messages, with a system prompt of its own, no tools, no MCP
servers, no project or user settings and no memory. It can be stopped and run again: compactions
already in judge.jsonl are skipped. POOL=api pays with ANTHROPIC_API_KEY, POOL=plan hides the key.
Python 3 standard library only.
"""
import argparse, concurrent.futures, hashlib, json, os, shlex, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_real as A

PARENT_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                    "CLAUDE_CODE_PROMPT_CACHE_TTL")
BATCH = 40            # messages per call
OLDER_CAP = 40        # messages from before an earlier compaction, per compaction
CLIP = 1500           # characters of one message shown to the model
KINDS = ("rule", "correction", "task", "question", "info", "ack")
PRESENCE = ("verbatim", "restated", "partly", "absent")

SYSTEM = """You check what a conversation summary kept of the messages a person typed.

Background: a coding assistant replaced a long conversation with a SUMMARY. Below you get that SUMMARY and a numbered list of MESSAGES the person typed before it. A message may be shortened in the middle, marked [...].

For each message, decide four things.

1. kind: what the message mainly is.
   rule: tells the assistant how to work from now on: a constraint, a preference, a prohibition, a process to follow, something to always or never do.
   correction: says something earlier was wrong, or changes an earlier instruction, and gives the right version.
   task: asks for a specific piece of work or a specific change.
   question: asks for information or an opinion.
   info: gives facts, context, pasted output, links or other material.
   ack: approval, thanks, "continue", "yes", a greeting, or anything with no content worth keeping.
   If two fit, choose the first that fits in this order: rule, correction, task, question, info, ack.

2. lasting: true if an assistant that goes on with this work would behave worse without knowing what this message says. false if it mattered only in the moment. Always false for ack.

3. in_summary:
   verbatim: the summary quotes the message, or its whole substance, in the person's own words.
   restated: the summary gives the message's substance in other words, with every specific detail an assistant would need: names, numbers, paths, conditions, the prohibition itself.
   partly: the summary reflects the message, but at least one specific detail an assistant would need is missing or changed.
   absent: the summary does not reflect the message.

4. missing: for partly and absent only, at most 12 words on what is missing. Otherwise an empty string.

Judge only from the SUMMARY text. Do not assume the summary holds something because it would be sensible. A general statement in the summary does not cover a specific instruction.

Reply with a JSON array and nothing else, one object per message, in order, like this:
[{"n": 1, "kind": "rule", "lasting": true, "in_summary": "restated", "missing": ""}]"""

ASK = "Judge the material on standard input as your instructions describe. Reply with the JSON array only."

QUEUED = False        # --queued: judge the messages typed while Claude was working instead
MACHINE = ("<task-notification>", "Another Claude session", "<teammate-message", "<bash-", "<command-",
           "<local-command", "<system-reminder>", "Caveat:", "[Request interrupted", "/compact", "<ide_")
lock = threading.Lock()


def queued_text(row):
    """The text of a message the person typed while Claude was working, or None.
    Claude Code stores these as queued_command attachments, not as user records."""
    item = row.get("attachment") or {}
    if row.get("type") != "attachment" or item.get("type") != "queued_command" or item.get("commandMode") != "prompt":
        return None
    origin = item.get("origin")
    origin = origin.get("kind") if isinstance(origin, dict) else origin
    if origin not in (None, "human"):
        return None
    prompt = item.get("prompt")
    text = prompt if isinstance(prompt, str) else A.text_of(prompt)
    return None if (not text.strip() or text.lstrip().startswith(MACHINE)) else text


def log(out_dir, text):
    with lock:
        with open(os.path.join(out_dir, "judge.log"), "a", encoding="utf-8") as handle:
            handle.write("%s %s\n" % (time.strftime("%H:%M:%S"), text))
        print(text, flush=True)


def clip(text):
    text = text.strip()
    if len(text) <= CLIP:
        return text
    return text[:1000] + "\n[...]\n" + text[-400:]


def compactions(path):
    """Every compaction in one transcript, with the typed messages before it."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    found, segments, order = [], [[]], 0
    for index, row in enumerate(rows):
        if QUEUED:
            waiting = queued_text(row)
            if waiting:
                segments[-1].append((row.get("uuid") or "", waiting))
        elif A.is_typed(row):
            segments[-1].append((row.get("uuid") or "", A.text_of((row.get("message") or {}).get("content"))))
        if not (row.get("type") == "system" and row.get("subtype") == "compact_boundary"):
            continue
        order += 1
        meta = row.get("compactMetadata") or {}
        summary = ""
        for later in rows[index + 1:index + 400]:
            if later.get("isCompactSummary"):
                summary = A.text_of((later.get("message") or {}).get("content"))
                break
            if later.get("type") == "system" and later.get("subtype") == "compact_boundary":
                break
        flat = A.squash(summary)
        grams = A.shingles(flat.split())
        tail = set((meta.get("preservedMessages") or {}).get("uuids") or [])
        items = []
        for uuid, text in segments[-1]:
            match = A.kept(text, flat, grams)
            if match != "short":
                items.append({"where": "recent", "match": match, "tail": uuid in tail, "text": text})
        older = [m for seg in segments[:-1] for m in seg]
        older = [(u, t) for u, t in older if A.kept(t, flat, grams) != "short"]
        if len(older) > OLDER_CAP:        # evenly spaced, so the choice does not depend on chance
            step = len(older) / OLDER_CAP
            older = [older[int(i * step)] for i in range(OLDER_CAP)]
        for uuid, text in older:
            items.append({"where": "older", "match": A.kept(text, flat, grams), "tail": False, "text": text})
        trigger = meta.get("trigger") or ""
        found.append({
            "order": order, "time": (row.get("timestamp") or "")[:19], "version": row.get("version") or "",
            "trigger": trigger, "idle": bool(meta.get("precomputed")), "pre_tokens": meta.get("preTokens", ""),
            "summary_words": len(summary.split()), "summary": summary, "items": items})
        segments.append([])
    return found


def ask(cfg, system_file, material, tag):
    argv = cfg["claude"] + ["-p", ASK, "--model", cfg["model"], "--system-prompt-file", system_file, "--tools", "",
                            "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
                            "--setting-sources", "project", "--output-format", "json"]
    if cfg["effort"]:
        argv += ["--effort", cfg["effort"]]
    env = {k: v for k, v in os.environ.items() if k not in PARENT_VARIABLES}
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    if cfg["pool"] == "plan":
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    started = time.time()
    try:
        done = subprocess.run(argv, cwd=cfg["cwd"], env=env, input=material, capture_output=True, text=True,
                              timeout=900)
        out, err, code = done.stdout, done.stderr, done.returncode
    except subprocess.TimeoutExpired:
        out, err, code = "", "timeout", "timeout"
    reply, cost, usage, problem = "", None, {}, ""
    try:
        data = json.loads(out)
        reply = data.get("result") or ""
        cost = data.get("total_cost_usd")
        usage = data.get("usage") or {}
        if data.get("is_error"):
            problem = (reply or data.get("subtype") or "error")[:300]
    except ValueError:
        problem = (err or out or "no output")[:300]
    with open(os.path.join(cfg["out_dir"], "raw", tag + ".json"), "w", encoding="utf-8") as handle:
        json.dump({"material": material, "reply": reply, "stderr": err[-2000:], "exit": code, "cost": cost,
                   "usage": usage, "seconds": round(time.time() - started, 1)}, handle, ensure_ascii=False)
    return reply, cost, usage, problem


def parse(reply, count):
    start, end = reply.find("["), reply.rfind("]")
    if start < 0 or end < 0:
        return None
    try:
        rows = json.loads(reply[start:end + 1], strict=False)   # a line break inside a string is accepted
    except ValueError:
        return None
    if not isinstance(rows, list) or len(rows) != count:
        return None
    clean = []
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get("kind") not in KINDS or row.get("in_summary") not in PRESENCE:
            return None
        clean.append({"kind": row["kind"], "lasting": bool(row.get("lasting")), "in_summary": row["in_summary"]})
    return clean


def judge_one(cfg, system_file, rel, comp):
    """Returns the line for judge.jsonl, or None if a call failed."""
    ident = hashlib.sha1(("%s#%d" % (rel, comp["order"])).encode()).hexdigest()[:12]
    to_judge = [item for item in comp["items"] if not item["tail"]]
    labels, cost, tokens = [], 0.0, 0
    for first in range(0, len(to_judge), BATCH):
        batch = to_judge[first:first + BATCH]
        material = "SUMMARY\n=======\n%s\n\nMESSAGES\n========\n%s\n" % (
            comp["summary"].strip(),
            "\n\n".join("--- message %d ---\n%s" % (n, clip(item["text"])) for n, item in enumerate(batch, 1)))
        got = None
        for attempt in (1, 2):
            reply, spent, usage, problem = ask(cfg, system_file, material, "%s-%03d-%d" % (ident, first, attempt))
            cost += spent or 0.0
            tokens += sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                           "cache_read_input_tokens"))
            if problem:
                log(cfg["out_dir"], "  call failed (%s #%d): %s" % (os.path.basename(rel)[:8], comp["order"], problem))
                return None, cost
            got = parse(reply, len(batch))
            if got:
                break
        if not got:
            log(cfg["out_dir"], "  reply not usable twice (%s #%d)" % (os.path.basename(rel)[:8], comp["order"]))
            return None, cost
        labels += got
    labelled = iter(labels)
    items = []
    for item in comp["items"]:
        row = {"where": item["where"], "match": item["match"], "tail": item["tail"], "chars": len(item["text"])}
        if not item["tail"]:
            row.update(next(labelled))
        items.append(row)
    line = {k: comp[k] for k in ("order", "time", "version", "trigger", "idle", "pre_tokens", "summary_words")}
    line.update({"path": rel, "id": ident, "items": items, "cost": round(cost, 4), "input_tokens": tokens})
    return line, cost


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("list"); parser.add_argument("data_dir"); parser.add_argument("out_dir")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--budget", type=float, default=0.0, help="stop starting work once this much is spent")
    parser.add_argument("--limit", type=int, default=0, help="judge at most this many compactions in this run")
    parser.add_argument("--only", default="", help="comma-separated path#order pairs, for a trial")
    parser.add_argument("--claude", default="npx -y @anthropic-ai/claude-code@2.1.327")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--queued", action="store_true", help="judge the messages typed while Claude was working")
    args = parser.parse_args()
    global QUEUED
    QUEUED = args.queued
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "cwd"), exist_ok=True)
    system_file = os.path.join(out_dir, "system-prompt.txt")
    with open(system_file, "w", encoding="utf-8") as handle:
        handle.write(SYSTEM)
    pool = os.environ.get("POOL", "api")
    if pool == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("STOP: POOL=api but ANTHROPIC_API_KEY is not set in this environment.")
    cfg = {"claude": shlex.split(args.claude), "model": args.model, "effort": args.effort, "pool": pool,
           "out_dir": out_dir, "cwd": os.path.join(out_dir, "cwd")}
    done = set()
    result_file = os.path.join(out_dir, "judge.jsonl")
    if os.path.exists(result_file):
        with open(result_file, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line); done.add((row["path"], row["order"]))
                except (ValueError, KeyError):
                    pass
    only = set(x for x in args.only.split(",") if x)
    work = []
    with open(args.list, encoding="utf-8") as handle:
        named = [p.strip() for p in handle if p.strip() and not p.startswith("#")]
    paths = []
    for entry in named:                     # a line may be a path, or path#order for one compaction
        rel, mark, order = entry.rpartition("#")
        if mark and order.isdigit():
            only.add(entry); entry = rel
        if entry not in paths:
            paths.append(entry)
    for rel in paths:
        for comp in compactions(os.path.join(args.data_dir, rel)):
            key = "%s#%d" % (rel, comp["order"])
            if (rel, comp["order"]) in done or (only and key not in only) or not comp["summary"]:
                continue
            if not any(not item["tail"] for item in comp["items"]):
                continue                    # nothing to judge for this compaction
            work.append((rel, comp))
    if args.limit:
        work = work[:args.limit]
    log(out_dir, "== %s: %d compactions to judge, %d already done, pool %s, model %s" % (
        time.strftime("%Y-%m-%d"), len(work), len(done), pool, args.model))
    spent, failures, finished = 0.0, 0, 0
    stop = threading.Event()

    def run(job):
        if stop.is_set():
            return None, 0.0, job
        line, cost = judge_one(cfg, system_file, job[0], job[1])
        return line, cost, job

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool_:
        for line, cost, job in pool_.map(run, work):
            spent += cost
            if line is None:
                if not stop.is_set():
                    failures += 1
                    if failures >= 3:
                        stop.set()
                        log(out_dir, "STOP: three compactions failed. See judge.log and raw/. Nothing is lost; run again to carry on.")
                continue
            failures = 0
            finished += 1
            with open(result_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(line) + "\n")
            if finished % 10 == 0 or finished == len(work):
                log(out_dir, "  %d of %d done, $%.2f spent in this run" % (finished, len(work), spent))
            if args.budget and spent >= args.budget and not stop.is_set():
                stop.set()
                log(out_dir, "Stopped at the budget: $%.2f spent in this run." % spent)
    log(out_dir, "== finished this run: %d judged, $%.2f spent" % (finished, spent))


if __name__ == "__main__":
    main()
