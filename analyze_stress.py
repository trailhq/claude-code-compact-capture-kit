#!/usr/bin/env python3
"""Summarise one compact-stress.sh run. Usage: python3 -I analyze_stress.py <results folder> [--full]

For each of 26 questions the truth depends on how many rounds have been
played, because later notes correct or replace earlier ones. Each entry is
(question kind, {round: (right pattern, stale pattern or None)}); a round
with no entry means nothing was on record yet, so "unknown" is right.
"""
import csv
import json
import os
import re
import sys

T = [
    ("corrected", {1: (r"02:15", r"02:45")}),
    ("corrected", {1: (r"3\.9", None), 2: (r"3\.11", r"3\.9(?!\d)")}),
    ("corrected", {1: (r"Marcus", None), 3: (r"Ines", r"Marcus")}),
    ("corrected", {1: (r"(?<!\d)12(?!\d)", None), 2: (r"(?<![\d.])5(?![\d.])|\bfive\b", r"(?<!\d)12(?!\d)")}),
    ("corrected", {2: (r"7443", None), 3: (r"7643", r"7443")}),
    ("corrected", {1: (r"Wednesday", r"Thursday")}),
    ("scoped", {1: (r"testing", None)}),
    ("scoped", {1: (r"Friday", None)}),
    ("scoped", {2: (r"config", None)}),
    ("scoped", {2: (r"Windows", None)}),
    ("scoped", {3: (r"changelog", None)}),
    ("scoped", {3: (r"five|(?<!\d)5(?!\d)", None)}),
    ("exception", {1: (r"attrs", None)}),
    ("exception", {2: (r"CI\b.*PR\b|PR\b.*CI\b", None)}),
    ("exception", {2: (r"slow", None)}),
    ("exception", {3: (r"git log", None)}),
    ("replaced", {1: (r"rebase", None), 2: (r"merge commit", r"rebase")}),
    ("replaced", {1: (r"captain", None), 3: (r"chief", r"captain")}),
    ("replaced", {2: (r"WARNING", None), 3: (r"INFO", r"WARNING")}),
    ("replaced", {3: (r"\bmain\b", r"8\.3")}),
    ("dead end", {2: (r"node.?ids?|IDs? changed", None)}),
    ("dead end", {2: (r"rewrit|slower|three times", None)}),
    ("dead end", {2: (r"teardown", None)}),
    ("dead end", {3: (r"wrapper", None)}),
    ("dead end", {3: (r"align|column", None)}),
    ("dead end", {3: (r"Windows|import", None)}),
]
UNKNOWN = re.compile(r"(?i)\bunknown\b|nothing on record|no record|don.t have|do not have|not on record")


def rows(path):
    out = []
    if os.path.isfile(path):
        for line in open(path, errors="replace"):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def numbered(text):
    answers = {}
    matches = list(re.finditer(r"(?m)^\s*(?:\*\*)?(\d{1,2})[\).:](?:\*\*)?\s*(.*)$", text or ""))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        answers.setdefault(int(m.group(1)), text[m.start(2):end].strip())
    return answers


def truth(index, rounds):
    states = T[index][1]
    current = None
    for r in sorted(states):
        if r <= rounds:
            current = states[r]
    return current


def judge(index, rounds, answer):
    state = truth(index, rounds)
    if state is None:
        return "right (nothing yet)" if (not answer or UNKNOWN.search(answer)) else "made up"
    right, stale = state
    r = re.search(right, answer or "", re.I)
    s = re.search(stale, answer or "", re.I) if stale else None
    if r and (not s or r.start() < s.start()):
        return "right"
    if r and s:
        return "both, old first"
    if s:
        return "STALE"
    if not answer or UNKNOWN.search(answer):
        return "unknown"
    return "other"


def main():
    folder = sys.argv[1]
    full = "--full" in sys.argv
    main_id = open(os.path.join(folder, "session-id.txt")).read().strip()
    notes = [l.rstrip("\n") for l in open(os.path.join(folder, "notes.txt"))]
    questions = [l.rstrip("\n") for l in open(os.path.join(folder, "questions.txt"))]
    steps = list(csv.DictReader(open(os.path.join(folder, "steps.tsv")), delimiter="\t"))
    print(open(os.path.join(folder, "version.txt")).read().strip(), "|", open(os.path.join(folder, "launch.txt")).read().replace("\n", " | "))
    print(f"{len(steps)} calls, {sum(int(s['seconds']) for s in steps)} s, non-zero exits: {[s['label'] for s in steps if s['exit'] != '0']}")
    results, main_cost, copy_cost = {}, 0.0, 0.0
    address = {}
    for s in steps:
        data = rows(os.path.join(folder, f"step-{int(s['step']):02d}-{s['label']}.jsonl"))
        res = next((r for r in reversed(data) if r.get("type") == "result"), {})
        results[s["label"]] = res
        cost = res.get("total_cost_usd") or 0.0
        if res.get("session_id") == main_id:
            main_cost = max(main_cost, cost)
        else:
            copy_cost += cost - main_cost
        b = next((r for r in data if r.get("subtype") == "compact_boundary"), None)
        if b:
            m = b.get("compact_metadata") or {}
            print(f"{s['label']}: pre_tokens={m.get('pre_tokens')} post_tokens={m.get('post_tokens')} duration_ms={m.get('duration_ms')} kept word for word={len((m.get('preserved_messages') or {}).get('uuids') or [])}")
        t = re.match(r"r(\d)-turn-(\d+)", s["label"])
        if t:
            text = res.get("result") or ""
            address[int(t.group(2))] = "chief" if re.search(r"(?i)\bchief\b", text) else ("captain" if re.search(r"(?i)\bcaptain\b", text) else "-")
    print("how replies addressed the user, turn by turn:", " ".join(f"{k}:{v}" for k, v in sorted(address.items())))
    posts = [r for r in rows(os.path.join(folder, "postcompact.jsonl")) if r.get("session_id") == main_id]
    for number, stage in enumerate(("r0", "r1", "r2", "r3")):
        if f"{stage}-quiz-1" not in results:
            continue
        rounds = max(1, number)
        body = ""
        if number >= 1 and len(posts) >= number:
            summary = posts[number - 1].get("compact_summary") or ""
            m = re.search(r"<summary>(.*)</summary>", summary, re.S)
            body = m.group(1) if m else summary
        answers = {}
        a1 = numbered((results.get(f"{stage}-quiz-1") or {}).get("result") or "")
        a2 = numbered((results.get(f"{stage}-quiz-2") or {}).get("result") or "")
        for i in range(26):
            answers[i] = a1.get(i + 1, "") if i < 13 else a2.get(i - 12, "")
        tally = {}
        lines = []
        for i in range(26):
            verdict = judge(i, rounds, answers[i])
            kind = T[i][0]
            live = truth(i, rounds) is not None
            t = tally.setdefault(kind, {})
            t[verdict] = t.get(verdict, 0) + 1
            if verdict not in ("right", "right (nothing yet)") or full:
                lines.append(f"   Q{i + 1} [{kind}] {verdict}: {questions[i]}  ->  {answers[i][:230]!r}")
        live_total = sum(1 for i in range(26) if truth(i, rounds) is not None)
        live_right = sum(1 for i in range(26) if truth(i, rounds) is not None and judge(i, rounds, answers[i]) == "right")
        typed = notes[:rounds * 12]
        verbatim = sum(1 for n in typed if n in body) if body else None
        print(f"\n=== {stage}: {rounds} round(s) played | summary block {len(body.split())} words | notes found word for word in the summary: {verbatim} of {len(typed)}")
        print(f"  questions with something on record: {live_right} right of {live_total}")
        for kind in ("corrected", "scoped", "exception", "replaced", "dead end"):
            print(f"  {kind:10s} {tally.get(kind)}")
        for line in lines:
            print(line)
        if full or stage == "r3":
            print("  OPEN LIST REPLY:\n    " + ((results.get(f"{stage}-quiz-recall") or {}).get("result") or "")[:3500].replace("\n", "\n    "))
        if full and body:
            print("  SUMMARY:\n" + body)
    print(f"\ncost by Claude Code's count: main {main_cost:.2f} USD, copies about {copy_cost:.2f} USD, together about {main_cost + copy_cost:.2f} USD")
    tr = rows(os.path.join(folder, "transcript.jsonl"))
    eff = {}
    for r in tr:
        if r.get("type") == "assistant":
            eff[str(r.get("effort"))] = eff.get(str(r.get("effort")), 0) + 1
    writes = [b.get("input", {}).get("file_path") for r in tr if r.get("type") == "assistant" and isinstance(r.get("message"), dict)
              for b in (r["message"].get("content") or []) if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Write", "Edit")]
    print(f"main transcript {len(tr)} lines, effort {eff}, Write or Edit calls: {writes}")


if __name__ == "__main__":
    main()
