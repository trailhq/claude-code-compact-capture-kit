#!/usr/bin/env python3
"""read_all.py LIST DATA_DIR OUT_DIR [--workers N] [--budget USD] [--claude "<cmd>"] [--model NAME]

Study 1, the full reading. For each compaction named in LIST, a model reads everything that was in
the session before the compaction and writes an answer key: what an assistant carrying on the work
would need to know. That model never sees the summary. A second step then compares the key with the
summary Claude Code wrote and labels every item.

LIST      one "path#order" per line: a transcript path relative to DATA_DIR and which of its
          compactions (1 is the first)
OUT_DIR   read.jsonl   one line per compaction: for every key item its origin, kind, whether it was
                       still in force and its label. No text from the session.
          raw/         every prompt and reply, the rendered log and the key (these hold session text)
          read.log     what the script did

Steps for one compaction:
  1. Render the records since the previous compaction as a plain log. Thinking is left out. A tool
     result longer than 60,000 characters is cut in the middle.
  2. Cut the log into parts of about 100K tokens. One call per part lists up to 30 key items.
  3. If there are several parts, one call merges the lists and marks what a later part withdrew.
  4. One call labels each key item against the summary and the messages kept after it.
Every call is `claude -p` with a system prompt of its own, no tools, no MCP servers, no settings, no
memory and no prompt cache. It can be stopped and run again. POOL=api pays with ANTHROPIC_API_KEY,
POOL=plan hides the key. Python 3 standard library only.
"""
import argparse, concurrent.futures, hashlib, json, os, shlex, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_real as A

PARENT_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                    "CLAUDE_CODE_PROMPT_CACHE_TTL")
PART_CHARS = 380000        # about 100K tokens
RESULT_CAP = 60000
ORIGINS = ("user", "instruction_file", "claude", "tool_output", "earlier_summary")
KINDS = ("rule", "correction", "decision", "fact", "state", "open")
LABELS = ("verbatim", "restated", "partly", "contradicted", "lost", "dropped", "stale")
ASK = "Do what your instructions describe with the material on standard input. Reply with the JSON array only."

KEY_SYSTEM = """You are building an answer key about a long working session between a person and a coding assistant.

You get one PART of the session log, in order. Each entry starts with a label:
[USER] typed by the person. [USER, QUEUED] typed by the person while the assistant was working.
[CLAUDE] the assistant's own words. [TOOL CALL] and [TOOL RESULT] what the assistant ran and what came back.
[INSTRUCTION FILE] a rules file loaded into the session. [EARLIER SUMMARY] a summary carried in from before this log.
[OTHER] anything else the session was shown.

List the things in this part that an assistant picking up this work later would need to know to carry on correctly: standing rules and preferences, corrections, decisions and their reasons, facts and values that were found (names, numbers, paths, versions, the cause of a bug), the state of the work (done, half done, failed, blocked), things ruled out, open questions and next steps.

For each item give:
  origin: "user" if the person typed it; "instruction_file"; "claude" if the assistant stated or decided it and the person did not type it; "tool_output" if it appears only in a tool result; "earlier_summary" if it appears only in the carried summary.
  kind: "rule", "correction", "decision", "fact", "state" or "open".
  statement: one self-contained sentence that states it exactly, with the specific names, numbers and paths.
  evidence: a short quote from the log, at most 20 words.
  in_force: true if it still held at the end of this part; false if this part itself later withdrew or replaced it.

Be specific. Do not pad: leave out routine steps, pleasantries and details that no longer matter by the end of the part. At most 30 items, the most important first.

Reply with a JSON array and nothing else, like this:
[{"origin": "user", "kind": "rule", "statement": "...", "evidence": "...", "in_force": true}]"""

MERGE_SYSTEM = """You get answer-key lists made from consecutive parts of one working session, in order. Each item has a part number, an origin, a kind, a statement, a short quote and whether it was in force at the end of its part.

Merge them into one key for the END of the session:
- Where two items say the same thing, keep one, with the most specific wording and the origin of the earliest.
- Where a later part withdraws, replaces or completes an earlier item, keep the earlier item and set its in_force to false. Keep the later item as it is.
- Do not add anything that is not in the lists. Do not reword beyond what merging needs.
- Keep at most 80 items. If there are more, drop the least important ones that are no longer in force first.

Reply with a JSON array and nothing else, in the same format:
[{"origin": "user", "kind": "rule", "statement": "...", "evidence": "...", "in_force": true}]"""

LABEL_SYSTEM = """You compare an answer key with a summary.

A coding assistant's long conversation was replaced by a SUMMARY. KEPT MESSAGES are the messages that stayed in its context word for word after the summary; there may be none. The KEY lists things that were known in the session just before that, each with whether it was still in force.

For each key item give a label.
If the item was in force:
  verbatim: the summary or the kept messages state it in the same words.
  restated: they state it in other words, with every specific detail an assistant would need.
  partly: they reflect it, but a needed specific is missing, vaguer or changed in scope.
  contradicted: they state something that conflicts with it.
  lost: they do not reflect it.
If the item was NOT in force:
  dropped: the summary does not present it as current. This is the right outcome.
  stale: the summary presents it as if it still held.
note: for partly, contradicted, lost and stale, at most 12 words on what is wrong. Otherwise an empty string.

Judge only from the SUMMARY and KEPT MESSAGES text. A general statement does not cover a specific item.

Reply with a JSON array and nothing else, one object per key item, in order:
[{"n": 1, "label": "restated", "note": ""}]"""

lock = threading.Lock()


def log(out_dir, text):
    with lock:
        with open(os.path.join(out_dir, "read.log"), "a", encoding="utf-8") as handle:
            handle.write("%s %s\n" % (time.strftime("%H:%M:%S"), text))
        print(text, flush=True)


def blocks_text(content):
    """Text of a tool result or message content, with pictures named but not shown."""
    if isinstance(content, str):
        return content
    out = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            out.append(block.get("text", ""))
        elif block.get("type") == "image":
            out.append("[a picture]")
        elif block.get("type") == "tool_result":
            out.append(blocks_text(block.get("content")))
    return "\n".join(out)


def cap(text):
    if len(text) <= RESULT_CAP:
        return text, 0
    return text[:45000] + "\n[... cut here ...]\n" + text[-10000:], 1


def render(rows):
    """The records of one stretch as log entries. Returns the entries and how many results were cut."""
    entries, cut = [], 0
    for row in rows:
        kind = row.get("type")
        if row.get("isSidechain"):
            continue
        message = row.get("message") or {}
        content = message.get("content")
        if kind == "user":
            if row.get("isCompactSummary"):
                entries.append("[EARLIER SUMMARY]\n" + A.text_of(content))
            elif A.is_typed(row):
                entries.append("[USER]\n" + blocks_text(content))
            elif isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                text, n = cap(blocks_text(content)); cut += n
                entries.append("[TOOL RESULT]\n" + text)
            else:
                text = blocks_text(content)
                if text.strip():
                    text, n = cap(text); cut += n
                    entries.append("[OTHER]\n" + text)
        elif kind == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    entries.append("[CLAUDE]\n" + block["text"])
                elif block.get("type") == "tool_use":
                    call = json.dumps(block.get("input"), ensure_ascii=False)
                    entries.append("[TOOL CALL] %s\n%s" % (block.get("name"), call if len(call) <= 6000 else call[:4500] + " [... cut ...] " + call[-1000:]))
        elif kind == "attachment":
            item = row.get("attachment") or {}
            what = item.get("type")
            if what == "nested_memory":
                entries.append("[INSTRUCTION FILE] %s\n%s" % (item.get("displayPath") or item.get("path") or "", blocks_text(item.get("content")) if not isinstance(item.get("content"), dict) else json.dumps(item.get("content"), ensure_ascii=False)))
            elif what == "queued_command" and isinstance(item.get("prompt"), (str, list)):
                text = blocks_text(item.get("prompt"))
                label = "[OTHER]" if text.lstrip().startswith(("<task-notification>", "Another Claude session", "<teammate-message")) else "[USER, QUEUED]"
                entries.append(label + "\n" + text)
            elif what in ("file", "edited_text_file", "plan_file_reference", "hook_additional_context", "task_reminder"):
                body = item.get("content") or item.get("snippet") or item.get("planContent") or ""
                body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
                text, n = cap(body); cut += n
                entries.append("[OTHER] %s %s\n%s" % (what, item.get("displayPath") or item.get("filename") or item.get("planFilePath") or "", text))
    return entries, cut


def load_compaction(path, order):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    cuts = [i for i, r in enumerate(rows) if r.get("type") == "system" and r.get("subtype") == "compact_boundary"]
    if order > len(cuts):
        return None
    end = cuts[order - 1]
    start = 0 if order == 1 else cuts[order - 2] + 1
    meta = rows[end].get("compactMetadata") or {}
    summary = ""
    for later in rows[end + 1:end + 400]:
        if later.get("isCompactSummary"):
            summary = A.text_of((later.get("message") or {}).get("content"))
            break
    by_id = {r.get("uuid"): r for r in rows[start:end]}
    kept = [by_id[u] for u in ((meta.get("preservedMessages") or {}).get("uuids") or []) if u in by_id]
    kept_entries, _ = render(kept)
    entries, cut = render(rows[start:end])
    return {"meta": meta, "summary": summary, "entries": entries, "cut": cut, "kept": kept_entries,
            "time": (rows[end].get("timestamp") or "")[:19], "version": rows[end].get("version") or ""}


def parts_of(entries):
    parts, current, size = [], [], 0
    for entry in entries:
        while len(entry) > PART_CHARS:                 # one entry larger than a part: split it
            head, entry = entry[:PART_CHARS - size - 1000] if size else entry[:PART_CHARS], entry[(PART_CHARS - size - 1000) if size else PART_CHARS:]
            current.append(head); parts.append(current); current, size = [], 0
            entry = "[continued]\n" + entry
        if size + len(entry) > PART_CHARS and current:
            parts.append(current); current, size = [], 0
        current.append(entry); size += len(entry) + 2
    if current:
        parts.append(current)
    return parts


def ask(cfg, system_name, material, tag):
    argv = cfg["claude"] + ["-p", ASK, "--model", cfg["model"], "--system-prompt-file",
                            os.path.join(cfg["out_dir"], system_name), "--tools", "", "--strict-mcp-config",
                            "--disable-slash-commands", "--no-session-persistence", "--setting-sources", "project",
                            "--output-format", "json"]
    if cfg["effort"]:
        argv += ["--effort", cfg["effort"]]
    env = {k: v for k, v in os.environ.items() if k not in PARENT_VARIABLES}
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    env["DISABLE_PROMPT_CACHING"] = "1"
    if cfg["pool"] == "plan":
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    started = time.time()
    try:
        done = subprocess.run(argv, cwd=cfg["cwd"], env=env, input=material, capture_output=True, text=True, timeout=1800)
        out, err, code = done.stdout, done.stderr, done.returncode
    except subprocess.TimeoutExpired:
        out, err, code = "", "timeout", "timeout"
    reply, cost, usage, problem = "", 0.0, {}, ""
    try:
        data = json.loads(out)
        reply = data.get("result") or ""
        cost = data.get("total_cost_usd") or 0.0
        usage = data.get("usage") or {}
        if data.get("is_error"):
            problem = (reply or data.get("subtype") or "error")[:300]
    except ValueError:
        problem = (err or out or "no output")[:300]
    with open(os.path.join(cfg["out_dir"], "raw", tag + ".json"), "w", encoding="utf-8") as handle:
        json.dump({"material": material, "reply": reply, "stderr": err[-2000:], "exit": code, "cost": cost,
                   "usage": usage, "seconds": round(time.time() - started, 1)}, handle, ensure_ascii=False)
    tokens = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return reply, cost, tokens, problem


def array(reply):
    start, end = reply.find("["), reply.rfind("]")
    if start < 0 or end < 0:
        return None
    try:
        rows = json.loads(reply[start:end + 1], strict=False)   # a line break inside a string is accepted
    except ValueError:
        return None
    return rows if isinstance(rows, list) else None


def clean_items(rows):
    out = []
    for row in rows or []:
        if isinstance(row, dict) and row.get("origin") in ORIGINS and row.get("kind") in KINDS and row.get("statement"):
            out.append({"origin": row["origin"], "kind": row["kind"], "statement": str(row["statement"])[:600],
                        "evidence": str(row.get("evidence") or "")[:300], "in_force": bool(row.get("in_force", True))})
    return out


def twice(cfg, system_name, material, tag, check):
    """Ask, and ask once more if the reply cannot be used. Returns (value or None, cost, tokens)."""
    cost = tokens = 0
    for attempt in (1, 2):
        reply, spent, used, problem = ask(cfg, system_name, material, "%s-%d" % (tag, attempt))
        cost += spent; tokens += used
        if problem:
            return None, cost, tokens, problem
        value = check(array(reply))
        if value:
            return value, cost, tokens, ""
    return None, cost, tokens, "reply not usable twice"


def read_one(cfg, rel, order):
    ident = hashlib.sha1(("%s#%d" % (rel, order)).encode()).hexdigest()[:12]
    comp = load_compaction(os.path.join(cfg["data_dir"], rel), order)
    if comp is None or not comp["summary"]:
        return None, 0.0, "no such compaction or no summary"
    parts = parts_of(comp["entries"])
    with open(os.path.join(cfg["out_dir"], "raw", ident + "-log.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(comp["entries"]))
    cost = tokens = 0
    lists = []
    for number, part in enumerate(parts, 1):
        material = "PART %d OF %d\n\n%s\n" % (number, len(parts), "\n\n".join(part))
        items, spent, used, problem = twice(cfg, "key-system.txt", material, "%s-part%02d" % (ident, number), clean_items)
        cost += spent; tokens += used
        if items is None:
            return None, cost, "part %d: %s" % (number, problem)
        lists.append(items)
    if len(lists) == 1:
        key = lists[0]
    else:
        material = "\n\n".join("PART %d\n%s" % (n, json.dumps(items, ensure_ascii=False, indent=0)) for n, items in enumerate(lists, 1))
        key, spent, used, problem = twice(cfg, "merge-system.txt", material, ident + "-merge", clean_items)
        cost += spent; tokens += used
        if key is None:
            return None, cost, "merge: " + problem
    with open(os.path.join(cfg["out_dir"], "raw", ident + "-key.json"), "w", encoding="utf-8") as handle:
        json.dump(key, handle, ensure_ascii=False, indent=1)
    material = "SUMMARY\n=======\n%s\n\nKEPT MESSAGES\n=============\n%s\n\nKEY\n===\n%s\n" % (
        comp["summary"].strip(), "\n\n".join(comp["kept"]) or "(none)",
        "\n".join("%d. [%s] %s" % (n, "in force" if item["in_force"] else "NOT in force", item["statement"]) for n, item in enumerate(key, 1)))

    def labels(rows):
        if not rows or len(rows) != len(key):
            return None
        out = []
        for row, item in zip(rows, key):
            label = row.get("label") if isinstance(row, dict) else None
            if label not in LABELS:
                return None
            out.append(label)
        return out

    marks, spent, used, problem = twice(cfg, "label-system.txt", material, ident + "-label", labels)
    cost += spent; tokens += used
    if marks is None:
        return None, cost, "labels: " + problem
    meta = comp["meta"]
    line = {"path": rel, "order": order, "id": ident, "time": comp["time"], "version": comp["version"],
            "trigger": meta.get("trigger") or "", "idle": bool(meta.get("precomputed")), "pre_tokens": meta.get("preTokens", ""),
            "summary_words": len(comp["summary"].split()), "parts": len(parts), "log_chars": sum(len(e) for e in comp["entries"]),
            "results_cut": comp["cut"], "kept_messages": len(comp["kept"]), "cost": round(cost, 4), "input_tokens": tokens,
            "items": [{"origin": i["origin"], "kind": i["kind"], "in_force": i["in_force"], "label": m} for i, m in zip(key, marks)]}
    return line, cost, ""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("list"); parser.add_argument("data_dir"); parser.add_argument("out_dir")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--budget", type=float, default=0.0)
    parser.add_argument("--claude", default="npx -y @anthropic-ai/claude-code@2.1.327")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--effort", default="medium")
    args = parser.parse_args()
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "cwd"), exist_ok=True)
    for name, text in (("key-system.txt", KEY_SYSTEM), ("merge-system.txt", MERGE_SYSTEM), ("label-system.txt", LABEL_SYSTEM)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    pool = os.environ.get("POOL", "plan")
    if pool == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("STOP: POOL=api but ANTHROPIC_API_KEY is not set in this environment.")
    cfg = {"claude": shlex.split(args.claude), "model": args.model, "effort": args.effort, "pool": pool,
           "out_dir": out_dir, "cwd": os.path.join(out_dir, "cwd"), "data_dir": args.data_dir}
    result_file = os.path.join(out_dir, "read.jsonl")
    done = set()
    if os.path.exists(result_file):
        for line in open(result_file, encoding="utf-8"):
            try:
                row = json.loads(line); done.add((row["path"], row["order"]))
            except (ValueError, KeyError):
                pass
    work = []
    for line in open(args.list, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rel, _, order = line.rpartition("#")
        if (rel, int(order)) not in done:
            work.append((rel, int(order)))
    log(out_dir, "== %s: %d compactions to read, %d already done, pool %s, model %s" % (
        time.strftime("%Y-%m-%d"), len(work), len(done), pool, args.model))
    state = {"spent": 0.0, "failures": 0, "finished": 0}
    stop = threading.Event()

    def run(job):
        if stop.is_set():
            return
        try:
            line, cost, problem = read_one(cfg, job[0], job[1])
        except Exception as error:                      # one bad transcript must not end the run
            line, cost, problem = None, 0.0, "%s: %s" % (type(error).__name__, str(error)[:200])
        with lock:
            state["spent"] += cost
            if line is None:
                state["failures"] += 1
            else:
                state["failures"] = 0
                state["finished"] += 1
                with open(result_file, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(line) + "\n")
            failures, spent, finished = state["failures"], state["spent"], state["finished"]
        name = "%s #%d" % (os.path.basename(job[0])[:8], job[1])
        if line is None:
            log(out_dir, "  %s failed: %s" % (name, problem))
            if failures >= 3 and not stop.is_set():
                stop.set()
                log(out_dir, "STOP: three compactions in a row failed. Nothing is lost; run again to carry on.")
        else:
            log(out_dir, "  %s read: %d parts, %d key items, $%.2f (%d of %d done, $%.2f in this run)" % (
                name, line["parts"], len(line["items"]), cost, finished, len(work), spent))
        if args.budget and spent >= args.budget and not stop.is_set():
            stop.set()
            log(out_dir, "Stopped at the budget: $%.2f spent in this run." % spent)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        list(executor.map(run, work))
    log(out_dir, "== finished this run: %d read, $%.2f spent" % (state["finished"], state["spent"]))


if __name__ == "__main__":
    main()
