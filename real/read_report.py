#!/usr/bin/env python3
"""read_report.py READ.jsonl [READ2.jsonl ...] : counts from the full reading. Prints no session text."""
import collections, json, sys

lines = []
for path in sys.argv[1:]:
    lines += [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def band(c):
    size = int(c.get("pre_tokens") or 0)
    if c["trigger"] == "manual":
        return "manual"
    if c.get("idle"):
        return "auto, idle"
    return "auto, 900K or more" if size >= 900000 else ("auto, under 200K" if size < 200000 else "auto, 200K to 900K")


def pct(part, whole):
    return "%d of %d (%d%%)" % (part, whole, round(100 * part / whole)) if whole else "0 of 0"


def rows(title, items, field, names):
    print("  " + title)
    for name in names:
        group = [i for i in items if i[field] == name]
        if not group:
            continue
        c = collections.Counter(i["label"] for i in group)
        kept = c["verbatim"] + c["restated"]
        print("    %-17s %4d | kept %-16s partly %-14s lost %-14s contradicted %d" % (
            name, len(group), pct(kept, len(group)), pct(c["partly"], len(group)), pct(c["lost"], len(group)), c["contradicted"]))


print("%d compactions read, %d key items, $%.2f, %.1fM tokens read, %d tool results cut" % (
    len(lines), sum(len(c["items"]) for c in lines), sum(c["cost"] for c in lines),
    sum(c["input_tokens"] for c in lines) / 1e6, sum(c["results_cut"] for c in lines)))
groups = collections.defaultdict(list)
for c in lines:
    groups[band(c)].append(c)
groups["ALL"] = lines
for key in sorted(groups):
    comps = groups[key]
    live = [i for c in comps for i in c["items"] if i["in_force"]]
    gone = [i for c in comps for i in c["items"] if not i["in_force"]]
    print("\n%s: %d compactions, %d items in force, %d no longer in force" % (key, len(comps), len(live), len(gone)))
    rows("in force, by where the item came from", live, "origin", ("user", "instruction_file", "claude", "tool_output", "earlier_summary"))
    rows("in force, by kind", live, "kind", ("rule", "correction", "decision", "fact", "state", "open"))
    c = collections.Counter(i["label"] for i in gone)
    print("  no longer in force: left out %s, shown as still current %s" % (pct(c["dropped"], len(gone)), pct(c["stale"], len(gone))))
