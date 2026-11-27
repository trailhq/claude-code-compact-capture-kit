#!/usr/bin/env python3
"""freeze1.py : every number the post takes from the real-session study (SWE-chat and the author's own
sessions), recomputed from the judged files in one pass. Prints counts only, never message text.
Writes results-real.json next to this file."""
import collections, json, os, statistics, sys
KIT = os.path.expanduser(os.environ.get("KIT", "~/compact-capture-kit"))
R = os.path.join(KIT, "real")
out = {}

def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

def band(c):
    size = int(c.get("pre_tokens") or 0)
    if c["trigger"] == "manual":
        return "manual"
    if c.get("idle"):
        return "auto_idle"
    if size >= 900000:
        return "auto_900k_plus"
    if size < 200000:
        return "auto_under_200k"
    return "auto_200k_900k"

def state(item):
    if item.get("tail"):
        return "kept"
    return {"verbatim": "kept", "restated": "kept", "partly": "partly", "absent": "absent"}[item["in_summary"]]

def dedupe(lines):
    unique, seen = [], set()
    for c in lines:
        mark = (c.get("time"), c.get("pre_tokens"))
        if mark not in seen:
            seen.add(mark); unique.append(c)
    return unique

def tally(items):
    s = collections.Counter(state(i) for i in items)
    return {"n": len(items), "kept": s["kept"], "partly": s["partly"], "absent": s["absent"]}

def meaning(lines):
    res = {"compactions": len(lines), "sessions": len({c["path"] for c in lines}),
           "messages": sum(len(c["items"]) for c in lines), "bands": {}}
    groups = collections.defaultdict(list)
    for c in lines:
        groups[band(c)].append(c)
    groups["all"] = lines
    for key, comps in groups.items():
        b = {"compactions": len(comps), "sessions": len({c["path"] for c in comps})}
        for where in ("recent", "older"):
            items = [i for c in comps for i in c["items"] if i["where"] == where and (i.get("tail") or "kind" in i)]
            rules = [i for i in items if i.get("lasting") and i.get("kind") in ("rule", "correction")]
            every = [i for i in items if i.get("lasting")]
            per = []
            for c in comps:
                mine = [i for i in c["items"] if i["where"] == where and i.get("lasting") and i.get("kind") in ("rule", "correction")]
                if mine:
                    per.append(sum(1 for i in mine if state(i) != "kept") / len(mine))
            b[where] = {"messages": len(items), "rules_that_matter": tally(rules), "every_message_that_matters": tally(every),
                        "by_kind": {k: tally([i for i in items if i.get("kind") == k]) for k in ("rule", "correction", "task", "question", "info", "ack")},
                        "compactions_with_rules": len(per), "compactions_with_a_rule_not_fully_kept": sum(1 for x in per if x > 0)}
        res["bands"][key] = b
    return res

skip = set(json.load(open(os.path.join(R, "swe-chat-not-claude.json"))))
raw = load(os.path.join(R, "judge-swechat", "judge.jsonl"))
claude = [c for c in raw if c["path"] not in skip]
lines = dedupe(claude)
known = [i for c in lines for i in c["items"] if i["match"] == "word for word" and "in_summary" in i]  # the 383 counted compactions (20 Nov: was all 425 judged lines)
out["swechat_meaning"] = meaning(lines)
out["swechat_meaning"].update({
    "judged_lines": len(raw), "not_claude_lines": len(raw) - len(claude), "claude_lines": len(claude),
    "duplicates": len(claude) - len(lines), "versions": sorted({c["version"] for c in lines}, key=lambda v: [int(x) for x in v.split(".")])[::max(1, len({c["version"] for c in lines}) - 1)],
    "first_time": min(c["time"] for c in lines), "last_time": max(c["time"] for c in lines),
    "text_match_agreement": {"agree": sum(1 for i in known if i["in_summary"] in ("verbatim", "restated")), "of": len(known)},
    "summary_words_median": {b: statistics.median([c["summary_words"] for c in lines if band(c) == b]) for b in ("auto_900k_plus", "auto_200k_900k", "auto_under_200k", "manual")},
    "summary_words_range": [min(c["summary_words"] for c in lines), max(c["summary_words"] for c in lines)],
    "summary_words_median_all": statistics.median([c["summary_words"] for c in lines]),
    "auto_200k_900k_sizes": sorted(c["pre_tokens"] for c in lines if band(c) == "auto_200k_900k"),
    "order_counts": dict(collections.Counter(min(c["order"], 4) for c in lines)),
})
# sizes of the automatic compactions, for the histogram
sizes = [int(c["pre_tokens"]) for c in lines if c["trigger"] == "auto"]
out["swechat_auto_sizes"] = sorted(sizes)
out["swechat_manual_sizes"] = sorted(int(c["pre_tokens"]) for c in lines if c["trigger"] == "manual")

# messages typed while Claude was working
q = dedupe([c for c in load(os.path.join(R, "judge-queued", "judge.jsonl")) if c["path"] not in skip])
out["swechat_queued"] = meaning(q)

# second judge
first = {(c["path"], c["order"]): c for c in raw}
pairs = collections.Counter(); n = 0; lasting = collections.Counter(); rule = collections.Counter(); both_rule = collections.Counter()
split = {"first": collections.Counter(), "second": collections.Counter()}
second = load(os.path.join(R, "judge-second", "judge.jsonl"))
for c in second:
    f = first.get((c["path"], c["order"]))
    if not f or len(f["items"]) != len(c["items"]):
        continue
    for a, b in zip(f["items"], c["items"]):
        if a.get("tail") or b.get("tail") or "kind" not in a or "kind" not in b:
            continue
        n += 1
        pairs["same" if state(a) == state(b) else "different"] += 1
        if {state(a), state(b)} == {"kept", "absent"}:
            pairs["kept_vs_absent"] += 1
        lasting[(bool(a.get("lasting")), bool(b.get("lasting")))] += 1
        ra, rb = a["kind"] in ("rule", "correction"), b["kind"] in ("rule", "correction")
        rule[(ra, rb)] += 1
        for name, x in (("first", a), ("second", b)):
            if x["kind"] in ("rule", "correction") and x.get("lasting"):
                split[name][(a["where"], state(x))] += 1
        if ra and rb and a.get("lasting") and b.get("lasting"):
            both_rule["same" if state(a) == state(b) else "different"] += 1
            if {state(a), state(b)} == {"kept", "absent"}:
                both_rule["kept_vs_absent"] += 1
out["second_judge"] = {"compactions": len(second), "messages": n, "same_state": pairs["same"], "kept_vs_absent_flips": pairs["kept_vs_absent"],
    "lasting_both": lasting[(True, True)], "lasting_first_only": lasting[(True, False)], "lasting_second_only": lasting[(False, True)], "lasting_neither": lasting[(False, False)],
    "rule_same_call": rule[(True, True)] + rule[(False, False)],
    "rules_that_matter": {name: {where: {s: split[name][(where, s)] for s in ("kept", "partly", "absent")} for where in ("recent", "older")} for name in split},
    "both_call_it_a_rule_that_matters": dict(both_rule)}

# the full reading
def reading(path):
    comps = load(path)
    res = {"compactions": len(comps), "items": sum(len(c["items"]) for c in comps), "tokens_read": sum(c["input_tokens"] for c in comps), "bands": {}}
    groups = collections.defaultdict(list)
    for c in comps:
        groups[band(c)].append(c)
    groups["all"] = comps
    for key, cs in groups.items():
        live = [i for c in cs for i in c["items"] if i["in_force"]]
        gone = [i for c in cs for i in c["items"] if not i["in_force"]]
        b = {"compactions": len(cs), "in_force": len(live), "withdrawn": len(gone),
             "withdrawn_shown_as_current": sum(1 for i in gone if i["label"] == "stale"),
             "contradicted": sum(1 for i in live if i["label"] == "contradicted"), "by_origin": {}}
        for origin in ("user", "instruction_file", "claude", "tool_output", "earlier_summary"):
            g = [i for i in live if i["origin"] == origin]
            c2 = collections.Counter(i["label"] for i in g)
            b["by_origin"][origin] = {"n": len(g), "kept": c2["verbatim"] + c2["restated"], "partly": c2["partly"], "lost": c2["lost"], "contradicted": c2["contradicted"]}
        res["bands"][key] = b
    return res
out["swechat_reading"] = reading(os.path.join(R, "read-swechat", "read.jsonl"))
# The author's own sessions are private, so their labels are not in this repository.
# Without them, the two "own" blocks keep the counts already frozen in results-real.json.
RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results-real.json")
frozen = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {}
own_read, own_judge = os.path.join(R, "read-own", "read.jsonl"), os.path.join(R, "judge-own", "judge.jsonl")
out["own_reading"] = reading(own_read) if os.path.exists(own_read) else frozen["own_reading"]
out["own_meaning"] = meaning(dedupe(load(own_judge))) if os.path.exists(own_judge) else frozen["own_meaning"]
json.dump(out, open(RESULTS, "w"), indent=1)

def show(t):
    return "%d/%d/%d of %d" % (t["kept"], t["partly"], t["absent"], t["n"]) + (" (%d%%/%d%%/%d%%)" % tuple(round(100 * t[k] / t["n"]) for k in ("kept", "partly", "absent")) if t["n"] else "")
m = out["swechat_meaning"]
print("SWE-chat: %d judged lines, %d not Claude, %d duplicates -> %d distinct compactions in %d sessions, %d messages judged; %s to %s; versions %s" % (
    m["judged_lines"], m["not_claude_lines"], m["duplicates"], m["compactions"], m["sessions"], m["messages"], m["first_time"][:10], m["last_time"][:10], m["versions"]))
print("text match agreement: %(agree)d of %(of)d" % m["text_match_agreement"], "| summary words median", m["summary_words_median"], "range", m["summary_words_range"], "| by order", m["order_counts"])
for name, block in (("TYPED", out["swechat_meaning"]), ("QUEUED", out["swechat_queued"]), ("OWN", out["own_meaning"])):
    print("\n%s: %d compactions, %d sessions" % (name, block["compactions"], block["sessions"]))
    for b in ("auto_900k_plus", "auto_200k_900k", "auto_under_200k", "auto_idle", "manual", "all"):
        if b not in block["bands"]:
            continue
        x = block["bands"][b]
        print("  %-16s %3d comps | rules that matter: recent %s | older %s" % (b, x["compactions"], show(x["recent"]["rules_that_matter"]), show(x["older"]["rules_that_matter"])))
        print("  %-16s           | every msg that matters: recent %s | older %s | comps with rules %d, with one not fully kept %d" % ("", show(x["recent"]["every_message_that_matters"]), show(x["older"]["every_message_that_matters"]), x["recent"]["compactions_with_rules"], x["recent"]["compactions_with_a_rule_not_fully_kept"]))
print("\nsecond judge:", json.dumps(out["second_judge"]))
for name in ("swechat_reading", "own_reading"):
    r = out[name]
    print("\n%s: %d compactions, %d items, %.1fM tokens" % (name, r["compactions"], r["items"], r["tokens_read"] / 1e6))
    for b, x in r["bands"].items():
        print("  %-16s %2d comps, in force %d, withdrawn %d (shown as current %d), contradicted %d | " % (b, x["compactions"], x["in_force"], x["withdrawn"], x["withdrawn_shown_as_current"], x["contradicted"]) +
              " ; ".join("%s %d/%d/%d of %d" % (o, v["kept"], v["partly"], v["lost"], v["n"]) for o, v in x["by_origin"].items() if v["n"]))
import bisect
s = out["swechat_auto_sizes"]
print("\nautomatic sizes: n=%d; under 200K %d; 200K-900K %d; 900K+ %d" % (len(s), bisect.bisect_left(s, 200000), bisect.bisect_left(s, 900000) - bisect.bisect_left(s, 200000), len(s) - bisect.bisect_left(s, 900000)))
