#!/usr/bin/env python3
"""freeze3.py : the numbers the post takes from Session A (one scripted developer session on ripgrep,
run to the 1M limit) and from the recorded crossing. Writes results-session-a.json and memory-index.md."""
import collections, csv, glob, json, os, re, sys
KIT = os.path.expanduser(os.environ.get("KIT", "~/compact-capture-kit"))
A = os.path.join(KIT, "auto-out", "A")
HERE = os.path.dirname(os.path.abspath(__file__))
out = {}
def rows_of(path):
    rows = []
    for l in open(path, encoding="utf-8", errors="replace"):
        try:
            rows.append(json.loads(l))
        except ValueError:
            pass
    return rows
def usage(r):
    u = (r.get("message") or {}).get("usage") if r.get("type") == "assistant" else None
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")) if u else None
def text_of(r):
    c = (r.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")

state = json.load(open(os.path.join(A, "state.json")))
steps = list(csv.DictReader(open(os.path.join(A, "steps.tsv")), delimiter="\t"))
script = [json.loads(l) for l in open(os.path.join(KIT, "auto", "ripgrep", "developer.jsonl")) if l.strip()]
questions = [json.loads(l) for l in open(os.path.join(KIT, "auto", "ripgrep", "questions.jsonl")) if l.strip()]
probes = [json.loads(l) for l in open(os.path.join(KIT, "auto", "ripgrep", "probes.jsonl")) if l.strip()]
main = state["session"]
out["script_messages"] = len(script); out["questions"] = len(questions); out["rule_tests"] = len(probes)
out["tickets_in_script"] = len({m["id"].split("-")[0] for m in script if re.match(r"t\d+-", m["id"])})
schedule = list(csv.DictReader(open(os.path.join(KIT, "auto", "ripgrep", "schedule.tsv")), delimiter="\t"))
out["notes_in_script"] = len(schedule)                      # 20 Nov: counted from schedule.tsv (the script rows carry no note field)
out["last_note_message_number"] = int(schedule[-1]["message_number"])
last_note_step = [f for f in sorted(os.listdir(A)) if f.endswith("-dev-%s.jsonl" % schedule[-1]["message_id"])][0]
sizes = []
for line in open(os.path.join(A, last_note_step)):
    try:
        rec = json.loads(line)
    except ValueError:
        continue
    if rec.get("type") == "assistant":
        u = rec["message"].get("usage") or {}
        sizes.append(u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0))
out["last_note_request_tokens"] = sizes[0]                  # the request that carried the last note
print("script: %d messages, %d tickets, %d questions, %d rule tests | keys of a script row: %s" % (len(script), out["tickets_in_script"], len(questions), len(probes), sorted(script[0].keys())))

# the main session's steps
dev = [s for s in steps if s["label"].startswith("dev-")]
comp_step = next(s for s in steps if s["mode"] in ("main", "on", "first") and s["label"].startswith("dev-") and s["compactions"] not in ("", "0"))
print("developer steps in the main session:", len(dev), "| compaction step:", comp_step["n"], comp_step["label"], comp_step["compactions"], "| last dev step:", dev[-1]["n"], dev[-1]["label"])
idx = dev.index(comp_step)
out["main"] = {"developer_messages_until_compaction": idx + 1, "compaction_during": comp_step["label"],
               "calls_until_compaction": int(comp_step["n"]), "cost_at_compaction_usd": float(comp_step["cost_total_usd"]),
               "cost_before_compaction_step_usd": float(dev[idx - 1]["cost_total_usd"]),
               "seconds_of_developer_steps": sum(int(s["seconds"]) for s in dev[: idx + 1]),
               "version": comp_step["version"], "key_source": comp_step["key_source"]}
out["spent_by_claude_codes_count_usd"] = state["spent"]
out["main"]["compaction"] = state["compactions"][-1] if state.get("compactions") else None
print("main:", json.dumps(out["main"]))
print("state.compactions:", json.dumps(state.get("compactions"))[:600])

# every compaction of Session A, from the transcripts
names = {main[:8]: "c1"}
for name, rec in state["crossings"].items():
    if rec.get("session"):
        names[rec["session"][:8]] = name
FACTS = {
 "q01": r"02:15", "q02": r"1\.79", "q03": r"\bInes\b", "q04": r"\b5 retries|five retries", "q05": r"7643", "q06": r"Wednesday",
 "q07": r"tests/data", "q08": r"Friday", "q09": r"[Pp]rinter[^.\n;]{0,80}\b80\b|\b80\b[^.\n;]{0,60}[Pp]rinter", "q10": r"[Bb]ackslash",
 "q11": r"past[- ]tense", "q12": r"[Bb]uilder", "q13": r"memchr", "q14": r"[Aa]bbreviation", "q15": r"ignore[^.\n;]{0,80}slow",
 "q16": r"git log", "q17": r"[Mm]erge commit", "q18": r"\bchief\b", "q19": r"\bINFO\b", "q20": r"[Ff]ixes[^.\n;]{0,40}master",
 "q21": r"inode", "q22": r"(three times|3x|3×|3 times)[^.\n;]{0,30}slow|slow[^.\n;]{0,40}(three times|3x|3×)",
 "q23": r"network drive", "q24": r"(regex-syntax|0\.8\.2)[^\n]{0,200}[Ww]ord bound|[Ww]ord bound[^\n]{0,200}(pin|regex-syntax 0\.8\.2)",
 "q25": r"JSON[^\n]{0,200}(column|line up|align)|(column|align)[^\n]{0,120}JSON", "q26": r"timeout[^\n]{0,200}(linking|Windows)|(linking|Windows)[^\n]{0,120}timeout"}
out["compactions"] = {}
for f in sorted(glob.glob(os.path.join(A, "transcripts", "*.jsonl")) + [os.path.join(A, "shots", "session.jsonl")]):
    base = os.path.basename(f)
    name = "recorded" if base == "session.jsonl" else names.get(base[:8])
    if not name:
        continue
    rows = rows_of(f)
    bi = [i for i, r in enumerate(rows) if r.get("type") == "system" and r.get("subtype") == "compact_boundary"]
    if not bi:
        print(name, "no compaction in", base); continue
    i = bi[-1]; meta = rows[i].get("compactMetadata") or {}
    summ, files, memidx = "", [], None
    for r in rows[i + 1: i + 60]:
        if r.get("isCompactSummary"):
            summ = text_of(r)
        a = r.get("attachment") or {}
        if r.get("type") == "attachment" and a.get("type") == "file":
            p = a.get("filename") or a.get("path") or "?"
            files.append(("memory/" if "/memory/" in p else "") + os.path.basename(p))
        if r.get("type") == "attachment" and "MEMORY.md" in json.dumps(a) and a.get("type") in ("instructions", "nested_memory", "memory"):
            memidx = a
        if r.get("type") == "assistant":
            break
    hit = {k: bool(re.search(p, summ)) for k, p in FACTS.items()}
    sections = re.findall(r"(?m)^\s*\d+\.\s+\*{0,2}([A-Z][^\n:*]{3,70}?)\*{0,2}:", summ)
    out["compactions"][name] = {"trigger": meta.get("trigger"), "pre_tokens": meta.get("preTokens"), "post_tokens": meta.get("postTokens"),
        "seconds": round((meta.get("durationMs") or 0) / 1000, 1), "kept_messages": len(((meta.get("preservedMessages") or {}).get("uuids")) or []),
        "summary_words": len(summ.split()), "facts_by_pattern": sum(hit.values()), "facts_missing_by_pattern": [k for k, v in hit.items() if not v],
        "files_put_back": files, "memory_index_reattached": memidx is not None, "sections": len(sections),
        "opens_with_ran_out": summ.strip().startswith("This session is being continued from a previous conversation that ran out of context"),
        "points_at_transcript": bool(re.search(r"\.jsonl", summ[-900:]))}
    if memidx is not None and name == "r2":
        blob = json.dumps(memidx)
        out["memory_index_chars"] = len(blob)
        content = None
        def walk(x):
            global content
            if isinstance(x, dict):
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
            elif isinstance(x, str) and "MEMORY" not in x[:40] and len(x) > 600 and content is None:
                content = x
        walk(memidx)
        open(os.path.join(HERE, "memory-index.md"), "w", encoding="utf-8").write(content or blob)
        out["memory_index_keys"] = sorted(memidx.keys())
    open(os.path.join(HERE, "summary-%s.txt" % name), "w", encoding="utf-8").write(summ)
    c = out["compactions"][name]
    print("%-8s %-6s pre %7s post %6s %5.1fs kept msgs %d | words %4d | facts by pattern %2d missing %s | files %s | memory index %s | sections %d ran-out %s path %s" % (
        name, c["trigger"], c["pre_tokens"], c["post_tokens"], c["seconds"], c["kept_messages"], c["summary_words"], c["facts_by_pattern"],
        c["facts_missing_by_pattern"], c["files_put_back"], c["memory_index_reattached"], c["sections"], c["opens_with_ran_out"], c["points_at_transcript"]))

# what the main session did before its compaction
rows = rows_of(os.path.join(A, "transcripts", main + ".jsonl"))
b = next(i for i, r in enumerate(rows) if r.get("type") == "system" and r.get("subtype") == "compact_boundary")
tools = collections.Counter(); memfiles = set(); memwrites = 0; first = last = None
for r in rows[:b]:
    ts = r.get("timestamp")
    if ts:
        first = first or ts; last = ts
    if r.get("type") != "assistant":
        continue
    for blk in (r.get("message") or {}).get("content") or []:
        if isinstance(blk, dict) and blk.get("type") == "tool_use":
            tools[blk.get("name")] += 1
            p = str((blk.get("input") or {}).get("file_path") or "")
            if "/memory/" in p and blk.get("name") in ("Write", "Edit"):
                memwrites += 1; memfiles.add(os.path.basename(p))
out["main"].update({"tool_calls_before_compaction": dict(tools.most_common()), "memory_writes": memwrites, "memory_files": len(memfiles),
                    "first_record": first, "last_record_before_compaction": last,
                    "typed_user_records": sum(1 for r in rows[:b] if r.get("type") == "user" and isinstance((r.get("message") or {}).get("content"), str))})
print("main before compaction: tools", dict(tools.most_common(8)), "| memory writes", memwrites, "in", len(memfiles), "files | from", first, "to", last)

# after a compaction: did any copy open the transcript the summary points to, or the memory folder?
reads = collections.defaultdict(lambda: collections.Counter())
for f in sorted(glob.glob(os.path.join(A, "step-*-after-*.jsonl"))):
    m = re.search(r"after-([a-z0-9]+)-([qp])\d+", f)
    variant, kind = m.group(1), m.group(2)
    calls = []
    for l in open(f, encoding="utf-8", errors="replace"):
        if '"tool_use"' not in l:
            continue
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("type") == "assistant":
            for blk in (r.get("message") or {}).get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    calls.append(json.dumps(blk.get("input") or {}))
    reads[(variant, kind)]["copies"] += 1
    reads[(variant, kind)]["with_tool_calls"] += bool(calls)
    reads[(variant, kind)]["read_memory_folder"] += any(re.search(r"ripgrep-A/memory|MEMORY\\.md", c) for c in calls)
    reads[(variant, kind)]["read_a_transcript"] += any(re.search(r"\.claude/projects/[^\"]*\.jsonl", c) for c in calls)
out["after_compaction_copies"] = {"%s|%s" % k: dict(v) for k, v in sorted(reads.items())}
for k, v in sorted(reads.items()):
    print("  after-%s %s: %s" % (k[0], "questions" if k[1] == "q" else "rule tests", dict(v)))
json.dump(out, open(os.path.join(HERE, "results-session-a.json"), "w"), indent=1)
