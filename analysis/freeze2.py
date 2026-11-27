#!/usr/bin/env python3
"""freeze2.py : the numbers the post takes from the replay of real sessions, recomputed in one pass.
Writes results-replay.json. Prints counts, plus the text of answers graded wrong (public SWE-chat data)."""
import collections, csv, json, os, sys
KIT = os.path.expanduser(os.environ.get("KIT", "~/compact-capture-kit"))
P = os.path.join(KIT, "replay", "out-proto")
out = {}
def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
def state(item):
    if item.get("tail"):
        return "kept"
    return {"verbatim": "kept", "restated": "kept", "partly": "partly", "absent": "absent"}[item["in_summary"]]

rows = [r for r in csv.DictReader(open(os.path.join(P, "rounds.tsv")), delimiter="\t") if r["trigger"] == "auto" and r["pre_tokens"]]
out["rounds"] = [{"session": r["session"], "round": int(r["round"]), "original_pre_tokens": int(r["original_pre_tokens"]),
                  "pre_tokens": int(r["pre_tokens"]), "post_tokens": int(r["post_tokens"]), "seconds": round(int(r["duration_ms"]) / 1000, 1),
                  "kept_after": int(r["kept_after"]), "version": r["version"]} for r in rows]
big = sorted({r["session"] for r in out["rounds"] if r["pre_tokens"] >= 900000}); small = sorted({r["session"] for r in out["rounds"] if r["pre_tokens"] < 900000})
out["sessions_1m"], out["sessions_small"] = big, small
print("replayed compactions:", len(out["rounds"]), "| 1M sessions", big, "| small", small)
for size, names in (("1M", big), ("small", small)):
    rs = [r for r in out["rounds"] if r["session"] in names]
    print("  %s: pre %d to %d, post %d to %d, seconds %.0f to %.0f, versions %s" % (size, min(r["pre_tokens"] for r in rs), max(r["pre_tokens"] for r in rs),
          min(r["post_tokens"] for r in rs), max(r["post_tokens"] for r in rs), min(r["seconds"] for r in rs), max(r["seconds"] for r in rs), sorted({r["version"] for r in rs})))

# the same messages against two summaries
orig = {(c["path"], c["order"]): c for c in load(os.path.join(KIT, "real", "judge-swechat", "judge.jsonl"))}
rep = {(c["path"], c["order"]): c for c in load(os.path.join(P, "judge", "judge.jsonl"))}
table = collections.defaultdict(lambda: collections.Counter()); words = collections.defaultdict(list); models = {}
for key in sorted(k for k in rep if k in orig):
    name = os.path.basename(key[0])[:8]; size = "1M" if name in big else "small"
    for label, c in (("original", orig[key]), ("replay", rep[key])):
        words[(size, label)].append(c["summary_words"])
        for where in ("recent", "older"):
            for i in c["items"]:
                if i["where"] == where and i.get("lasting") and i.get("kind") in ("rule", "correction"):
                    table[(size, key[1], where, label)][state(i)] += 1
    models[name] = orig[key].get("version")
out["two_summaries"] = {"%s|round %d|%s|%s" % k: dict(v) for k, v in table.items()}
out["summary_words"] = {"%s|%s" % k: [min(v), max(v)] for k, v in words.items()}
out["original_versions"] = models
for size in ("1M", "small"):
    for rnd in (1, 2, 3):
        cells = []
        for where in ("recent", "older"):
            for label in ("original", "replay"):
                t = table[(size, rnd, where, label)]; n = sum(t.values())
                cells.append("%s %s %d/%d/%d of %d" % (where, label, t["kept"], t["partly"], t["absent"], n))
        print("  %s round %d | %s" % (size, rnd, " | ".join(cells)))
print("  summary words:", out["summary_words"], "| original releases:", models)

# questions
last = {}
for r in load(os.path.join(P, "ask", "ask.jsonl")):
    last[(r["session"], r["asked_after_round"])] = r
tab = collections.defaultdict(collections.Counter); per_session = collections.defaultdict(collections.Counter)
raw_tab = collections.defaultdict(collections.Counter)
# Re-read on 20 Nov 2026 by the assistant model that ran this analysis, not by a person: every answer graded wrong. In three, the user had replaced the rule later
# and Claude gave the newer one, so the key was out of date, not the answer. Those questions are left out
# from the round in which the rule was replaced onwards. Numbers are positions in the list asked that round.
#   27642e0f, question 6: "give hourly updates" (round 2, 14:02) was replaced by "15min updates" (round 2, 16:31).
#   27642e0f, question 7: "cancel emem0 ... use gpt 5" (round 2) was replaced in round 3 ("run mem0 baseline in the night ... no beam").
STALE_KEYS = {("27642e0f", 2): {6}, ("27642e0f", 3): {6, 7}}
dropped = []
for (s, k), r in last.items():
    if s == "27642e0f" and k == 0:
        continue          # not a control: resuming the uncut 1M session compacted it at once
    for n, i in enumerate(r["items"], 1):
        since = 0 if k == 0 else k - i["from_round"] + 1
        size = "1M" if s in big else "small"
        raw_tab[(size, since)][i["grade"]] += 1
        if n in STALE_KEYS.get((s, k), ()):
            dropped.append({"session": s, "after_round": k, "question": n, "grade": i["grade"], "since": since})
            continue
        tab[(size, since)][i["grade"]] += 1
        per_session[(s, since)][i["grade"]] += 1
ctl = load(os.path.join(P, "ask", "control.jsonl"))
for r in ctl:
    for i in r["items"]:
        tab[("1M", 0)][i["grade"]] += 1
        per_session[(r["session"], 0)][i["grade"]] += 1
for r in ctl:
    for i in r["items"]:
        raw_tab[("1M", 0)][i["grade"]] += 1
out["questions"] = {"%s|%d" % k: {g: v[g] for g in ("right", "partly", "wrong", "unknown")} for k, v in sorted(tab.items())}
out["questions_as_graded"] = {"%s|%d" % k: {g: v[g] for g in ("right", "partly", "wrong", "unknown")} for k, v in sorted(raw_tab.items())}
out["questions_dropped_for_stale_keys"] = dropped
print("dropped for stale keys:", dropped)
out["questions_per_session"] = {"%s|%d" % k: dict(v) for k, v in sorted(per_session.items())}
out["control_cuts"] = {r["session"]: r["cut_tokens"] for r in ctl}
nq = {}
for name in big + small:
    f = os.path.join(P, "ask", "raw", "questions-%s.json" % name)
    if os.path.exists(f):
        qs = json.load(open(f)); nq[name] = [sum(1 for q in qs if q["from_round"] == k) for k in (1, 2, 3)]
# The question files restate what SWE-chat users typed, so they are not in this repository.
# Without them, this block keeps the counts already frozen in results-replay.json.
RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results-replay.json")
if not nq and os.path.exists(RESULTS):
    nq = json.load(open(RESULTS)).get("questions_written", {})
out["questions_written"] = nq
print("questions written per session by round:", nq, "| total", sum(sum(v) for v in nq.values()))
for k, v in out["questions"].items():
    print("  %-8s right %2d partly %2d wrong %2d not known %2d | of %d" % (k, v["right"], v["partly"], v["wrong"], v["unknown"], sum(v.values())))
print("  control cuts:", out["control_cuts"])
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results-replay.json"), "w"), indent=1)

# the answers graded wrong, to read by hand
if "--wrong" in sys.argv:
    import re
    if not os.path.isdir(os.path.join(P, "ask", "raw")):
        sys.exit("--wrong needs replay/out-proto/ask/raw/, which is not published. Run replay-ask.sh on your own copy of the sessions first.")
    for (s, k), r in sorted(last.items()):
        if s not in big or (s == "27642e0f" and k == 0):
            continue
        qs = json.load(open(os.path.join(P, "ask", "raw", "questions-%s.json" % s)))
        mine = [q for q in qs if q["from_round"] <= k] if k else qs
        ans_file = os.path.join(P, "ask", "raw", "answers-%s-r%d.json" % (s, k))
        reply = json.load(open(ans_file)).get("reply", "") if os.path.exists(ans_file) else ""
        for n, (q, item) in enumerate(zip(mine, r["items"]), 1):
            if item["grade"] != "wrong":
                continue
            m = re.search(r"(?m)^\s*%d[\).:]\s*(.+?)(?=^\s*%d[\).:]|\Z)" % (n, n + 1), reply, flags=re.S)
            print("\n--- %s after round %d, question %d (rule from round %d)" % (s, k, n, q["from_round"]))
            print("Q:", q["question"][:400]); print("KEY:", q["answer"][:500]); print("ANSWER:", (m.group(1).strip()[:700] if m else "[could not isolate answer %d]" % n))
