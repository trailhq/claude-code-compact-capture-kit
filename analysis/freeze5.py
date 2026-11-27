#!/usr/bin/env python3
"""freeze5.py : the examples the short post (draft v5) quotes, pulled from the raw files in one pass.
Writes results-examples.json beside this script. Run on the machine that holds the kit:

    KIT=~/compact-capture-kit python3 freeze5.py

Nothing here is typed in by hand except the ids of what to look up. Text typed by SWE-chat users is never written
to the results file: for those messages the file keeps a timestamp, a length and a hash, so that someone with the
dataset can find the message. What the file does keep from the replay is text our own runs produced: Claude's
answers and a few words of the summaries.
"""
import csv, hashlib, json, os, re

KIT = os.path.expanduser(os.environ.get("KIT", "~/compact-capture-kit"))
HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(KIT, "analysis")
out = {}


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8", errors="replace") if l.strip()]


def numbered(reply, n):
    """Answer n of a numbered reply (1) ... or 1. ...)."""
    m = re.search(r"(?m)^\s*%d[\).:]\s*(.+?)(?=^\s*%d[\).:]|\Z)" % (n, n + 1), reply, flags=re.S)
    return m.group(1).strip() if m else None


def result_text(path):
    res = None
    for r in load(path):
        if r.get("type") == "result":
            res = r.get("result")
    return res


# ---- 1. our own 1M-token session (ripgrep): what was typed, what the memory-off summary kept, what Claude answered
dev = load(os.path.join(KIT, "auto", "ripgrep", "developer.jsonl"))
notes = {int(r["note"]): r for r in csv.DictReader(open(os.path.join(KIT, "auto", "ripgrep", "schedule.tsv"), encoding="utf-8"), delimiter="\t")}
own = {"developer_messages": len(dev), "notes": len(notes), "typed": {}}
for name, note in (("nightly_first", 1), ("friday", 6), ("nightly_correction", 7), ("cranelift", 21), ("log_level_first", 23), ("log_level_replaced", 31)):
    n = int(notes[note]["message_number"])
    message = dev[n - 1]["text"]
    assert notes[note]["text"] in message, (note, n)
    own["typed"][name] = {"note": note, "message_number": n, "note_text": notes[note]["text"], "message_ends": message[-(len(notes[note]["text"]) + 22):]}
questions = {q["id"]: q["text"] for q in load(os.path.join(KIT, "auto", "ripgrep", "questions.jsonl"))}
answers = {}
for row in load(os.path.join(KIT, "auto-out", "A", "answers-after-nomem.jsonl")):
    for position, qid in enumerate(row["ids"], 1):
        answers[qid] = numbered(row["reply"], position)
own["memory_off_answers"] = {qid: {"question": questions[qid], "answer": answers[qid]} for qid in ("q01", "q19", "q21", "q22", "q23", "q24", "q25", "q26")}
own["memory_off_answers_that_say_do_not_know"] = sorted(q for q, a in answers.items() if a and re.search(r"\bI don't know\b", a))
# answers that match the key's pattern for the right value, in each compaction we asked after (a rough score: the post's
# counts come from reading every answer, which overruled the pattern once, on q09 after the memory-off compaction)
keys = {k["id"]: k for k in load(os.path.join(KIT, "auto", "ripgrep", "key.jsonl"))}
own["answers_matching_the_key_pattern"] = {}
for variant in ("c1", "r1", "r2", "old", "man", "nomem"):
    got = {}
    for row in load(os.path.join(KIT, "auto-out", "A", "answers-after-%s.jsonl" % variant)):
        for position, qid in enumerate(row["ids"], 1):
            got[qid] = numbered(row["reply"], position) or ""
    hits = sorted(q for q, a in got.items() if re.search(keys[q]["right"], a, re.I))
    own["answers_matching_the_key_pattern"][variant] = {"asked": len(got), "match": len(hits), "no_match": sorted(set(got) - set(hits))}
nomem = open(os.path.join(V4, "summary-nomem.txt"), encoding="utf-8").read()
c1 = open(os.path.join(V4, "summary-c1.txt"), encoding="utf-8").read()
own["memory_off_summary"] = {
    "words": len(nomem.split()),
    "dropped_approaches_line": next((l.strip() for l in nomem.splitlines() if "Dropped approaches" in l), None),
    "log_level_line": next((l.strip() for l in nomem.splitlines() if "log level" in l), None),
    "mentions_nightly": bool(re.search(r"nightly", nomem, re.I)),
    "mentions_02_15_or_02_45": bool(re.search(r"0?2[:.](15|45)", nomem)),
    "mentions_three_times_or_slower": bool(re.search(r"three times|3x|slower", nomem, re.I)),
}
own["session_summary_side_notes_line"] = next((l.strip() for l in c1.splitlines() if "Side notes" in l), None)
index = open(os.path.join(V4, "memory-index.md"), encoding="utf-8").read().splitlines()
own["memory_index_lines"] = {k: next((l for l in index if pat in l), None) for k, pat in
                             (("nightly", "nightly-benchmark"), ("cranelift", "no-cranelift"), ("log_level", "log-level"), ("rust", "ci-rust"))}
own["memory_index_entries"] = sum(1 for l in index if l.startswith("- ["))
out["own_session"] = own

# ---- 2. the scripted size ladder on Claude Code 2.1.311: a path that only a script printed, before and after /compact
lad = os.path.join(KIT, "v311", "ladder", "capture")
checkpoints = {r["name"]: r for r in csv.DictReader(open(os.path.join(lad, "checkpoints.tsv")), delimiter="\t")}
before = result_text(os.path.join(lad, "step-041-c3-before-u1-3.jsonl"))
after = result_text(os.path.join(lad, "step-048-c3-after-u1-3.jsonl"))
out["ladder_path"] = {"version": open(os.path.join(lad, "version.txt")).read().strip(), "tokens_before_compact": int(checkpoints["c3"]["tokens_before"]),
                      "before_answer_4": numbered(before, 4), "after_answer_4": numbered(after, 4)}

# ---- 3. the replay: one rule followed through three compactions (session 73009f6a, question 3)
P = os.path.join(KIT, "replay", "out-proto")


def text_of(r):
    c = (r.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join((b.get("text") or "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def typed(path):
    rows = []
    for i, r in enumerate(load(path)):
        if r.get("type") != "user" or r.get("isMeta") or r.get("isCompactSummary") or r.get("isSidechain"):
            continue
        c = (r.get("message") or {}).get("content")
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            continue
        t = text_of(r).strip()
        if t and not t.startswith("<") and not t.startswith("This session is being continued") and not t.startswith("Caveat:"):
            rows.append((r.get("timestamp", ""), t))
    return rows


def last_summary(path):
    s = None
    for r in load(path):
        if r.get("isCompactSummary"):
            s = text_of(r)
    return s


def phrase(summary, pattern):
    m = re.search(pattern, summary, flags=re.I)
    return m.group(0) if m else None


S, Q = "73009f6a", 3
qs = json.load(open(os.path.join(P, "ask", "raw", "questions-%s.json" % S)))
grades = {(r["session"], r["asked_after_round"]): r for r in load(os.path.join(P, "ask", "ask.jsonl"))}
trace = {"session": S, "question_number": Q, "question": qs[Q - 1]["question"], "rule_from_round": qs[Q - 1]["from_round"]}
rule = [(ts, t) for ts, t in typed(os.path.join(P, S, "F1.jsonl")) if re.search(r"baseline", t, re.I) and re.search(r"no need to run", t, re.I)]
assert len(rule) == 1
trace["typed_rule"] = {"timestamp": rule[0][0], "characters": len(rule[0][1]), "sha256": hashlib.sha256(rule[0][1].encode()).hexdigest(),
                       "mentions_benchmarks": bool(re.search(r"benchmark", rule[0][1], re.I))}
control = json.load(open(os.path.join(P, "ask", "raw", "control-%s.json" % S)))
trace["before_any_compaction"] = {"answer": numbered(control["reply"], Q),
                                  "grade": next(r for r in load(os.path.join(P, "ask", "control.jsonl")) if r["session"] == S)["items"][Q - 1]["grade"]}
trace["rounds"] = {}
for k, pat in ((1, r"don.t rerun unchanged baseline"), (2, r"baseline must be uncheated; fresh both arms"), (3, r"baseline must be fair and fresh")):
    summary = last_summary(os.path.join(P, S, "round-%d.jsonl" % k))
    mine = [q for q in qs if q["from_round"] <= k]
    reply = json.load(open(os.path.join(P, "ask", "raw", "answers-%s-r%d.json" % (S, k))))["reply"]
    line = next((l.strip() for l in summary.splitlines() if re.search(pat, l, re.I)), "")
    trace["rounds"][str(k)] = {
        "summary_words": len(summary.split()), "summary_phrase": phrase(summary, pat), "the_line_holding_it_starts": line[:38],
        "summary_says_not_to_rerun_an_unchanged_baseline": bool(re.search(r"(don.t|do not|no need to|never) (re-?run|run)[^.;\n]{0,40}(unchanged|baseline)|unchanged baseline|reuse[^.;\n]{0,30}baseline", summary, re.I)),
        "answer": numbered(reply, Q), "grade": grades[(S, k)]["items"][Q - 1]["grade"]}
# where the words "fresh both arms" came from: Claude's plans, never a typed message
f2 = load(os.path.join(P, S, "F2.jsonl"))
pat = re.compile(r"fresh[^.\n]{0,12}both[ -]arms", re.I)
where = {"written_by_claude": 0, "tool_result": 0, "task_notification": 0, "typed_by_the_user": 0}
for r in f2:
    blob = json.dumps(r.get("message"), ensure_ascii=False)
    if not pat.search(blob):
        continue
    c = (r.get("message") or {}).get("content")
    if r.get("type") == "assistant":
        where["written_by_claude"] += 1
    elif isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        where["tool_result"] += 1
    elif text_of(r).strip().startswith("<task-notification>"):
        where["task_notification"] += 1
    else:
        where["typed_by_the_user"] += 1
assert where["typed_by_the_user"] == sum(1 for ts, t in typed(os.path.join(P, S, "F2.jsonl")) if pat.search(t))
trace["fresh_both_arms_in_the_original_session"] = where
def approvals(records):
    """(plans the user approved, how many of those hold the words)"""
    blobs = [json.dumps(r.get("message"), ensure_ascii=False) for r in records if r.get("type") == "user"]
    approved = [b for b in blobs if "User has approved your plan" in b]
    return len(approved), sum(1 for b in approved if pat.search(b))


trace["plans_the_user_approved_before_the_second_compaction"], trace["approved_plans_holding_the_words"] = approvals(f2)
early = load(os.path.join(P, S, "F1-early.jsonl"))        # the copy cut before any compaction, where the first row's answer comes from
n_plans, n_with = approvals(early)
trace["at_the_cut_before_any_compaction"] = {"cut_tokens": next(r for r in load(os.path.join(P, "ask", "control.jsonl")) if r["session"] == S)["cut_tokens"],
                                             "records_holding_the_words": sum(1 for r in early if pat.search(json.dumps(r.get("message"), ensure_ascii=False))),
                                             "approved_plans": n_plans, "approved_plans_holding_the_words": n_with,
                                             "holds_the_typed_rule": any(hashlib.sha256(t.encode()).hexdigest() == trace["typed_rule"]["sha256"]
                                                                         for ts, t in typed(os.path.join(P, S, "F1-early.jsonl")))}
out["replay_trace"] = trace

# ---- 4. every replay answer graded wrong and kept in the counts (freeze2.py lists the three left out)
wrong = []
for (s, k), r in sorted(grades.items()):
    if k == 0:
        continue
    q_all = json.load(open(os.path.join(P, "ask", "raw", "questions-%s.json" % s)))
    mine = [q for q in q_all if q["from_round"] <= k]
    reply = json.load(open(os.path.join(P, "ask", "raw", "answers-%s-r%d.json" % (s, k))))["reply"]
    for n, (q, item) in enumerate(zip(mine, r["items"]), 1):
        if item["grade"] == "wrong" and not (s == "27642e0f" and ((k == 2 and n == 6) or (k == 3 and n in (6, 7)))):
            wrong.append({"session": s, "after_round": k, "question": n, "rule_from_round": q["from_round"], "asked": q["question"],
                          "answer_key_written_by_a_model": q["answer"], "answer": numbered(reply, n)})
out["replay_wrong_answers_kept"] = wrong

json.dump(out, open(os.path.join(HERE, "results-examples.json"), "w"), indent=1, ensure_ascii=False)
print(json.dumps(out, indent=1, ensure_ascii=False))
