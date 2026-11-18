#!/usr/bin/env python3
"""Summarise one "ladder" run of compact-capture.sh.

Usage: python3 -I analyze_ladder.py <results folder> [--answers]

Reads the step files, hook logs, steps.tsv, checkpoints.tsv, answers.tsv and
the transcripts. Everything read is treated as data.
"""
import csv
import glob
import json
import os
import re
import sys

FACTS = [
    (1, "project codename", r"\bHERON\b"), (2, "invoice codename", r"\bOSPREY\b"),
    (3, "API header", r"KESTREL"), (4, "shell comment", r"#\s*lantern"),
    (5, "release train", r"\bMAGPIE\b"), (6, "staging port", r"(?<!\d)4417(?!\d)"),
    (7, "why SQLite", r"(?i)no network|without (a )?network|network access|offline|no internet|can.t reach"),
    (8, "exact error line", r"E4107: checksum mismatch at offset 0x3fa2"),
    (9, "RETRY_LIMIT", r"(?<![\d.])7(?!\d)(?!\.\d)"),
]
DETAILS = [
    (1, "scratch dir", r"/var/tmp/hx-9931"), (2, "retried block", r"(?<!\d)0?77(?!\d)"),
    (3, "slowest block", r"(?<!\d)188(?!\d)"), (4, "blocks after", r"(?<!\d)119(?!\d)"),
    (5, "build 0412", r"03:40"), (6, "BATCH_SIZE", r"(?<![\d.])64(?!\d)(?!\.\d)"),
    (7, "POOL_SIZE", r"(?<![\d.])12(?!\d)(?!\.\d)"),
]
# For checking the summary text, where a bare 7, 64 or 12 would match anything.
IN_SUMMARY = {("a", 9): r"RETRY_LIMIT\W{0,6}7", ("b", 2): r"(?i)block 0?77", ("b", 3): r"(?<!\d)188(?!\d)",
              ("b", 6): r"BATCH_SIZE\W{0,6}64", ("b", 7): r"POOL_SIZE\W{0,6}12"}
UNKNOWN = re.compile(r"(?i)\bunknown\b|don.t know|do not know|not sure|no record|can.t recall|cannot recall")
KINDS = ["aside", "finding", "error", "output", "needle"]


def rows(path):
    out = []
    if os.path.isfile(path):
        with open(path, errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    return out


def tsv(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def msg(row):
    message = row.get("message")
    return message if isinstance(message, dict) else {}


def numbered(text):
    answers = {}
    matches = list(re.finditer(r"(?m)^\s*(?:\*\*)?(\d{1,2})[\).:](?:\*\*)?\s*(.*)$", text or ""))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        answers.setdefault(int(match.group(1)), text[match.start(2):end].strip())
    return answers


def token_pattern(kind, expected):
    if kind == "output":
        return re.escape(os.path.basename(expected))
    if kind == "error":
        return r"(?i)" + re.escape(expected) + r"(?!\d)"
    return r"(?<!\d)" + re.escape(expected) + r"(?!\d)"


def mark(pattern, answer):
    if answer and re.search(pattern, answer):
        return "ok"
    if not answer or UNKNOWN.search(answer):
        return "--"
    return "??"


def main():
    folder = sys.argv[1]
    show_answers = "--answers" in sys.argv
    main_id = open(os.path.join(folder, "session-id.txt")).read().strip()
    steps = tsv(os.path.join(folder, "steps.tsv"))
    checkpoints = tsv(os.path.join(folder, "checkpoints.tsv"))
    answers = tsv(os.path.join(folder, "answers.tsv"))
    expected = {(int(r["unit"]), int(r["number"])): (r["kind"], r["expected"]) for r in answers}

    for name in ("version.txt", "machine.txt", "launch.txt"):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            text = open(path, errors="replace").read().rstrip()
            text = "\n".join(line for line in text.splitlines() if not line.startswith("other_claude_variables_present"))
            print(f"--- {name}\n{text}")

    results = {}
    for path in sorted(glob.glob(os.path.join(folder, "step-*.jsonl"))):
        label = os.path.basename(path)[:-6]
        data = rows(path)
        result = [r for r in data if r.get("type") == "result"]
        boundary = [r for r in data if r.get("subtype") == "compact_boundary"]
        results[label.split("-", 2)[2]] = {"result": result[-1] if result else {}, "boundary": boundary[-1] if boundary else {},
                                           "file": label}
    failed = [s for s in steps if s.get("exit") not in ("0", 0)]
    seconds = sum(int(s.get("seconds") or 0) for s in steps)
    print(f"\n--- steps: {len(steps)} calls, {seconds} s in all, {len(failed)} with a non-zero exit")
    for s in failed:
        err = os.path.join(folder, f"step-{s['step']}-{s['label']}.err")
        tail = open(err, errors="replace").read()[-400:] if os.path.isfile(err) else ""
        print(f"    failed: {s['step']} {s['label']} exit={s['exit']} {tail!r}")

    transcript = rows(os.path.join(folder, "transcript.jsonl"))
    efforts, models = {}, {}
    for row in transcript:
        if row.get("type") == "assistant":
            efforts[str(row.get("effort"))] = efforts.get(str(row.get("effort")), 0) + 1
            model = str(msg(row).get("model"))
            models[model] = models.get(model, 0) + 1
    print(f"--- main transcript: {len(transcript)} lines; effort {efforts}; model {models}")
    for label in sorted(results, key=lambda k: results[k]["file"]):
        if label.startswith("task-") or label in ("decision", "read-files"):
            r = results[label]["result"]
            usage = r.get("usage") or {}
            print(f"    {label:12s} turns={r.get('num_turns')} ms={r.get('duration_ms')} cache_write={usage.get('cache_creation_input_tokens')} "
                  f"cache_read={usage.get('cache_read_input_tokens')} out={usage.get('output_tokens')} cost_total={round(r.get('total_cost_usd') or 0, 3)} denials={len(r.get('permission_denials') or [])}")
            if show_answers:
                print("       ", (r.get("result") or "")[:420].replace("\n", " | "))

    post = rows(os.path.join(folder, "postcompact.jsonl"))
    summaries = {r.get("session_id"): r.get("compact_summary") or "" for r in post}
    table = []
    for cp in checkpoints:
        name, mode, tasks, target = cp["name"], cp["mode"], int(cp["tasks"]), cp["session"]
        print("\n" + "=" * 78)
        print(f"CHECKPOINT {name}: {tasks} tasks done, mode {mode}, about {cp['tokens_before']} tokens before, compacted session {target[:8]}")
        compact = results.get(f"{name}-compact", {})
        meta = (compact.get("boundary") or {}).get("compact_metadata") or {}
        kept_messages = len((meta.get("preserved_messages") or {}).get("uuids") or [])
        print(f"  compaction record: pre_tokens={meta.get('pre_tokens')} post_tokens={meta.get('post_tokens')} duration_ms={meta.get('duration_ms')} "
              f"trigger={meta.get('trigger')} messages kept word for word={kept_messages}")
        summary = summaries.get(target, "")
        body_match = re.search(r"<summary>(.*)</summary>", summary, re.S)
        body = body_match.group(1) if body_match else summary
        analysis = re.search(r"<analysis>(.*)</analysis>", summary, re.S)
        print(f"  summary: {len(summary.split())} words from the model ({len(analysis.group(1).split()) if analysis else 0} analysis, {len(body.split())} summary)")
        own = rows(os.path.join(folder, "transcript.jsonl" if target == main_id else f"transcript-{name}.jsonl"))
        boundary = next((i for i, r in enumerate(own) if r.get("subtype") == "compact_boundary"), None)
        if own and boundary is not None:
            prompts = []
            for r in own[:boundary]:
                if r.get("type") == "user" and not r.get("isMeta"):
                    content = msg(r).get("content")
                    if isinstance(content, str) and not content.startswith("<"):
                        prompts.append(content)
            verbatim = sum(1 for p in prompts if p in summary)
            kept = next((text_of(msg(r).get("content")) for r in own[boundary:] if r.get("isCompactSummary")), "")
            print(f"  user prompts before the boundary: {len(prompts)}; found word for word in the summary: {verbatim}")
            print(f"  message left in the conversation: {len(kept.split())} words")
            back = []
            for r in own[boundary:]:
                if r.get("type") == "attachment" and (r.get("attachment") or {}).get("type") in ("file", "compact_file_reference"):
                    a = r["attachment"]
                    back.append(("ref:" if a.get("type") == "compact_file_reference" else "") + str(a.get("displayPath")).split("/memory/")[-1])
            print(f"  files back after the boundary: {back[:8]}")
            touched = []
            for r in own[:boundary]:
                if r.get("type") == "assistant":
                    for block in msg(r).get("content") or []:
                        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in ("Read", "Write", "Edit"):
                            touched.append(os.path.basename(str((block.get("input") or {}).get("file_path"))))
            print(f"  last files the session read or wrote: {touched[-8:]}")
        else:
            print("  (no transcript of the compacted session in the folder)")

        line = {"name": name, "tasks": tasks, "pre": meta.get("pre_tokens"), "post": meta.get("post_tokens"),
                "words": len(body.split()), "secs": round((meta.get("duration_ms") or 0) / 1000, 1)}
        lost = []
        for part, table_def in (("a", FACTS), ("b", DETAILS)):
            before = numbered((results.get(f"{name}-before-{part}", {}).get("result") or {}).get("result") or "")
            after = numbered((results.get(f"{name}-after-{part}", {}).get("result") or {}).get("result") or "")
            b_ok = a_ok = in_sum = 0
            for number, label, pattern in table_def:
                b, a = mark(pattern, before.get(number, "")), mark(pattern, after.get(number, ""))
                s = bool(re.search(IN_SUMMARY.get((part, number), pattern), body))
                b_ok += b == "ok"; a_ok += a == "ok"; in_sum += s
                if a != "ok":
                    lost.append(f"{part}{number} {label}: before {b}, after {a} {after.get(number, '')[:90]!r}, in summary: {s}")
                elif not s:
                    lost.append(f"{part}{number} {label}: answered after, though the summary does not hold it")
            line[part] = f"{b_ok}>{a_ok}/{len(table_def)}"
            line[part + "_sum"] = in_sum
        by_kind = {k: [0, 0, 0, 0] for k in KINDS}   # asked, before ok, after ok, in summary
        by_unit = {}
        first = 1
        while first <= tasks:
            last = min(first + 2, tasks)
            before = numbered((results.get(f"{name}-before-u{first}-{last}", {}).get("result") or {}).get("result") or "")
            after = numbered((results.get(f"{name}-after-u{first}-{last}", {}).get("result") or {}).get("result") or "")
            for unit in range(first, last + 1):
                for k in range(1, 6):
                    kind, value = expected[(unit, k)]
                    pattern = token_pattern(kind, value)
                    number = (unit - first) * 5 + k
                    b, a = mark(pattern, before.get(number, "")), mark(pattern, after.get(number, ""))
                    s = bool(re.search(pattern, body))
                    by_kind[kind][0] += 1; by_kind[kind][1] += b == "ok"; by_kind[kind][2] += a == "ok"; by_kind[kind][3] += s
                    by_unit.setdefault(unit, [0, 0])
                    if kind != "needle":
                        by_unit[unit][0] += b == "ok"; by_unit[unit][1] += a == "ok"
                    if (a == "ok") != s or (b != "ok" and kind != "needle") or a == "??":
                        lost.append(f"task {unit} {kind}: before {b}, after {a} {after.get(number, '')[:70]!r}, in summary: {s}")
            first = last + 1
        for kind in KINDS:
            asked, b_ok, a_ok, in_sum = by_kind[kind]
            line[kind] = f"{b_ok}>{a_ok}/{asked}" if asked else "-"
            line[kind + "_sum"] = in_sum
        print("  quiz A (9 facts), before>after: " + line["a"] + f"; in summary {line['a_sum']}")
        print("  quiz B (7 details), before>after: " + line["b"] + f"; in summary {line['b_sum']}")
        for kind in KINDS:
            print(f"  task facts, {kind:8s} before>after: {line[kind]}; in summary {line[kind + '_sum']}")
        if by_unit:
            print("  per task, the four facts other than the table line, before>after: " + ", ".join(f"t{u}:{v[0]}>{v[1]}" for u, v in sorted(by_unit.items())))
        print(f"  notes ({len(lost)}):")
        for item in lost[:60]:
            print("    - " + item)
        if show_answers and summary:
            print("  --- summary in full ---")
            print(summary)
        table.append(line)

    print("\n" + "=" * 78 + "\nSIZES SIDE BY SIDE (before>after/asked; s = found in the summary)")
    head = ["name", "tasks", "pre", "post", "words", "secs", "a", "b"] + KINDS
    print(" | ".join(head))
    for line in table:
        print(" | ".join(str(line.get(k)) + (f" s{line[k + '_sum']}" if k + "_sum" in line else "") for k in head))

    # Cost: the main session's own count, plus what each copy added on top of the session it copied.
    main_total, extra, last_main = 0.0, 0.0, 0.0
    copy_base = {}
    for s in steps:
        r = results.get(s["label"], {}).get("result") or {}
        cost = r.get("total_cost_usd")
        if cost is None:
            continue
        if r.get("session_id") == main_id:
            main_total = max(main_total, cost); last_main = cost
        elif s["label"].endswith("-compact"):
            extra += cost - last_main; copy_base[s["label"].split("-")[0]] = cost
        elif "-after-" in s["label"]:
            base = copy_base.get(s["label"].split("-")[0], last_main)
            extra += cost - base
        else:
            extra += cost - last_main
    print(f"\ncost by Claude Code's count: main session {main_total:.2f} USD, copies about {extra:.2f} USD, together about {main_total + extra:.2f} USD")
    shell = (results.get("shell-command", {}).get("result") or {}).get("result")
    if shell:
        print("first plain reply after the last compaction:", shell[:200].replace("\n", " | "))


if __name__ == "__main__":
    main()
