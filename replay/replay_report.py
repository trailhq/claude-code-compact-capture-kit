#!/usr/bin/env python3
"""replay_report.py ORIGINAL_JUDGE.jsonl REPLAY_JUDGE.jsonl : the same sessions and rounds, judged
twice: against the summary the original release wrote, and against the one today's release wrote in
the replay. Counts only."""
import collections, json, os, sys

def load(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        row = json.loads(line); out[(row["path"], row["order"])] = row
    return out

def state(item):
    if item.get("tail"):
        return "kept"
    return {"verbatim": "kept", "restated": "kept", "partly": "partly", "absent": "absent"}[item["in_summary"]]

def cell(items):
    c = collections.Counter(state(i) for i in items)
    n = len(items)
    return "%d/%d/%d of %d" % (c["kept"], c["partly"], c["absent"], n) if n else "none"

original, replay = load(sys.argv[1]), load(sys.argv[2])
keys = sorted(k for k in replay if k in original)
print("kept/partly/absent. 'rules' = rules and corrections that still matter; 'all' = every message that still matters.")
print("%-9s %-5s %-9s | %-22s %-22s | %-22s %-22s | words orig/replay" % ("session", "round", "size", "recent rules: original", "replay", "older rules: original", "replay"))
total = collections.defaultdict(list)
for key in keys:
    o, r = original[key], replay[key]
    def pick(c, where, rules):
        return [i for i in c["items"] if i["where"] == where and i.get("lasting") and (not rules or i.get("kind") in ("rule", "correction"))]
    size = "1M" if int(r.get("pre_tokens") or 0) >= 900000 else "under 200K"
    print("%-9s %-5d %-9s | %-22s %-22s | %-22s %-22s | %d/%d" % (
        os.path.basename(key[0])[:8], key[1], size, cell(pick(o, "recent", True)), cell(pick(r, "recent", True)),
        cell(pick(o, "older", True)), cell(pick(r, "older", True)), o["summary_words"], r["summary_words"]))
    for where in ("recent", "older"):
        for rules in (True, False):
            total[(size, key[1], where, rules, "original")] += pick(o, where, rules)
            total[(size, key[1], where, rules, "replay")] += pick(r, where, rules)
print()
for size in ("under 200K", "1M"):
    for rules in (True, False):
        print("%s, %s:" % (size, "rules and corrections that still matter" if rules else "every message that still matters"))
        for number in (1, 2, 3):
            print("  round %d | typed in this round: original %s, replay %s | typed in earlier rounds: original %s, replay %s" % (
                number, cell(total[(size, number, "recent", rules, "original")]), cell(total[(size, number, "recent", rules, "replay")]),
                cell(total[(size, number, "older", rules, "original")]), cell(total[(size, number, "older", rules, "replay")])))
