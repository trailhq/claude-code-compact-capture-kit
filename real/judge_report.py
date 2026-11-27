#!/usr/bin/env python3
"""judge_report.py JUDGE.jsonl [--by-order] [--exclude PATHS.json] : counts from the meaning check. Prints no message text."""
import collections, json, statistics, sys

lines = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
if "--exclude" in sys.argv:           # a JSON list of transcript paths to leave out
    skip = set(json.load(open(sys.argv[sys.argv.index("--exclude") + 1])))
    lines = [c for c in lines if c["path"] not in skip]
by_order = "--by-order" in sys.argv


def band(c):
    size = int(c.get("pre_tokens") or 0)
    if c["trigger"] == "manual":
        return "manual"
    if c.get("idle"):
        return "auto, idle"
    if size >= 900000:
        return "auto, 900K or more"
    if size < 200000:
        return "auto, under 200K"
    return "auto, 200K to 900K"


def state(item):
    if item.get("tail"):
        return "kept"                     # still in the context word for word after the summary
    return {"verbatim": "kept", "restated": "kept", "partly": "partly", "absent": "absent"}[item["in_summary"]]


def pct(part, whole):
    return "%d of %d (%d%%)" % (part, whole, round(100 * part / whole)) if whole else "0 of 0"


def table(title, comps, where):
    items = [i for c in comps for i in c["items"] if i["where"] == where and (i.get("tail") or "kind" in i)]
    if not items:
        return
    print("\n  %s: %d messages in %d compactions" % (title, len(items), sum(1 for c in comps if any(i["where"] == where for i in c["items"]))))
    kinds = collections.Counter(i.get("kind", "tail") for i in items)
    for kind in ("rule", "correction", "task", "question", "info", "ack", "tail"):
        group = [i for i in items if i.get("kind", "tail") == kind]
        if not group:
            continue
        s = collections.Counter(state(i) for i in group)
        print("    %-10s %4d | kept %-16s partly %-14s absent %s" % (
            kind, len(group), pct(s["kept"], len(group)), pct(s["partly"], len(group)), pct(s["absent"], len(group))))
    lasting = [i for i in items if i.get("lasting") and i.get("kind") in ("rule", "correction")]
    s = collections.Counter(state(i) for i in lasting)
    print("    rules and corrections that still matter: %d | kept %s | partly %s | absent %s" % (
        len(lasting), pct(s["kept"], len(lasting)), pct(s["partly"], len(lasting)), pct(s["absent"], len(lasting))))
    every = [i for i in items if i.get("lasting")]
    s = collections.Counter(state(i) for i in every)
    print("    every message that still matters:        %d | kept %s | partly %s | absent %s" % (
        len(every), pct(s["kept"], len(every)), pct(s["partly"], len(every)), pct(s["absent"], len(every))))
    per = []
    for c in comps:
        mine = [i for i in c["items"] if i["where"] == where and i.get("lasting") and i.get("kind") in ("rule", "correction")]
        if mine:
            per.append(sum(1 for i in mine if state(i) != "kept") / len(mine))
    if per:
        print("    per compaction, share of such rules not fully kept: median %d%%, compactions with at least one: %s" % (
            round(100 * statistics.median(per)), pct(sum(1 for x in per if x > 0), len(per))))


print("%d compactions judged, %d messages, $%.2f" % (
    len(lines), sum(len(c["items"]) for c in lines), sum(c.get("cost", 0) for c in lines)))
# Does the judge agree with the plain text match where the answer is known?
known = [i for c in lines for i in c["items"] if i["match"] == "word for word" and "in_summary" in i]
agree = sum(1 for i in known if i["in_summary"] in ("verbatim", "restated"))
print("check: messages the text match found word for word, which the judge also calls kept: %s" % pct(agree, len(known)))
# The same compaction can sit in two copies of one session; count it once.
unique, seen_keys = [], set()
for c in lines:
    mark = (c.get("time"), c.get("pre_tokens"))
    if mark not in seen_keys:
        seen_keys.add(mark); unique.append(c)
if len(unique) != len(lines):
    print("%d of these are copies of another and are counted once: %d distinct compactions" % (len(lines) - len(unique), len(unique)))
lines = unique
groups = collections.defaultdict(list)
for c in lines:
    key = band(c) + ((", compaction %s" % ("1" if c["order"] == 1 else "2 or later")) if by_order else "")
    groups[key].append(c)
for key in sorted(groups):
    comps = groups[key]
    print("\n%s: %d compactions, %d sessions" % (key, len(comps), len({c["path"] for c in comps})))
    table("typed since the last compaction", comps, "recent")
    table("typed before an earlier compaction (a sample of up to 40 each)", comps, "older")
