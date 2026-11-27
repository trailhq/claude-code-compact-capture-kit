"""Who the 383 SWE-chat compactions come from, and three checks that do not pool users.

Run:  KIT=<this repo> python3 analysis/freeze4.py   (needs pyarrow, and SWE-chat's sessions.parquet in data/SWE-chat/)
Reads real/judge-swechat/judge.jsonl (labels only) and the SWE-chat index (sessions.parquet).
Writes results-clusters.json. User and repository ids from the index are counted, never written out.
"""
import collections
import json
import os
import statistics

import pyarrow.parquet as pq

KIT = os.environ.get("KIT", os.path.expanduser("~/compact-capture-kit"))
head = open(os.path.join(KIT, "analysis/freeze1.py")).read().split("\nskip = ")[0]
ns = {}
exec(compile(head, "freeze1-helpers", "exec"), ns)
R, load, dedupe, band, state = ns["R"], ns["load"], ns["dedupe"], ns["band"], ns["state"]

skip = set(json.load(open(os.path.join(R, "swe-chat-not-claude.json"))))
raw = load(os.path.join(R, "judge-swechat", "judge.jsonl"))
lines = dedupe([c for c in raw if c["path"] not in skip])
index = pq.read_table(os.path.join(KIT, "data/SWE-chat/sessions.parquet"),
                      columns=["session_id", "repo_id", "owner_id", "user_id", "agent", "kind", "strategy", "created_at", "api_call_count"]).to_pylist()
by = {r["session_id"]: r for r in index}


def sid(c):
    return os.path.basename(c["path"])[:-6]


def user(c):
    return by[sid(c)]["user_id"]


def rules(c, where):
    return [i for i in c["items"] if i["where"] == where and (i.get("tail") or "kind" in i)
            and i.get("lasting") and i.get("kind") in ("rule", "correction")]


def tally(items):
    s = collections.Counter(state(i) for i in items)
    return {"n": len(items), "kept": s["kept"], "partly": s["partly"], "absent": s["absent"]}


def typed(c, where):
    return sum(1 for i in c["items"] if i["where"] == where)


out = {}
claude_code = [r for r in index if r["agent"] == "Claude Code"]
rule = [r for r in claude_code if not r["kind"] and (r["api_call_count"] or 0) >= 300
        and "2026-06-01" <= str(r["created_at"])[:10] <= "2026-09-30"]
out["index"] = {"sessions": len(index), "claude_code_sessions": len(claude_code),
                "selection_rule_sessions": len(rule), "selection_rule_repositories": len({r["repo_id"] for r in rule}),
                "selection_rule_strategies": dict(collections.Counter(str(r["strategy"]) for r in rule))}

per_user = collections.Counter(user(c) for c in lines)
top = per_user.most_common(1)[0][0]
out["who"] = {"compactions": len(lines), "sessions": len({c["path"] for c in lines}),
              "repositories": len({by[sid(c)]["repo_id"] for c in lines}), "owners": len({by[sid(c)]["owner_id"] for c in lines}),
              "users": len(per_user), "compactions_by_user_top6": [n for _, n in per_user.most_common(6)],
              "created_first": min(str(by[sid(c)]["created_at"])[:10] for c in lines),
              "created_last": max(str(by[sid(c)]["created_at"])[:10] for c in lines)}
out["bands"] = {}
for b in ("manual", "auto_under_200k", "auto_200k_900k", "auto_900k_plus", "auto_idle"):
    comps = [c for c in lines if band(c) == b]
    cu = collections.Counter(user(c) for c in comps)
    out["bands"][b] = {"compactions": len(comps), "users": len(cu), "top_user_compactions": cu.most_common(1)[0][1],
                       "median_messages_typed_since_last_compaction": statistics.median([typed(c, "recent") for c in comps])}

for name, keep in (("top_user", lambda c: user(c) == top), ("everyone_else", lambda c: user(c) != top)):
    comps = [c for c in lines if keep(c)]
    out[name] = {"compactions": len(comps), "sessions": len({c["path"] for c in comps}), "users": len({user(c) for c in comps}),
                 "recent": tally([i for c in comps for i in rules(c, "recent")]),
                 "older": tally([i for c in comps for i in rules(c, "older")])}

g = collections.defaultdict(lambda: {"recent": [], "older": []})
for c in lines:
    for where in ("recent", "older"):
        g[user(c)][where] += rules(c, where)
both = [v for v in g.values() if len(v["recent"]) >= 5 and len(v["older"]) >= 5]
pairs = sorted(([sum(1 for i in v["recent"] if state(i) == "kept"), len(v["recent"]),
                 sum(1 for i in v["older"] if state(i) == "kept"), len(v["older"])] for v in both), key=lambda p: -p[1] - p[3])
rs = [p[0] / p[1] for p in pairs]
os_ = [p[2] / p[3] for p in pairs]
out["user_by_user"] = {"users_with_5_recent_and_5_older_rules": len(pairs),
                       "recent_share_higher": sum(1 for a, b in zip(rs, os_) if a > b),
                       "median_recent_share": round(statistics.median(rs), 3), "median_older_share": round(statistics.median(os_), 3),
                       "mean_recent_share": round(statistics.mean(rs), 3), "mean_older_share": round(statistics.mean(os_), 3),
                       "kept_recent_of_n_kept_older_of_n": pairs}

per_session = collections.defaultdict(list)
for c in lines:
    per_session[c["path"]].append(c)
heavy = max(per_session.items(), key=lambda kv: sum(len(rules(c, "older")) for c in kv[1]))
heavy_older = [i for c in heavy[1] for i in rules(c, "older")]
rest_older = [i for c in lines if c["path"] != heavy[0] for i in rules(c, "older")]
out["one_session"] = {"id": os.path.basename(heavy[0])[:8], "compactions": len(heavy[1]), "older": tally(heavy_older),
                      "most_older_messages_at_one_compaction": max(typed(c, "older") for c in heavy[1]),
                      "all_other_sessions_older": tally(rest_older)}

out["by_order"] = {}
for label, pick in (("1", lambda o: o == 1), ("2", lambda o: o == 2), ("3", lambda o: o == 3), ("4+", lambda o: o >= 4)):
    comps = [c for c in lines if pick(c["order"])]
    older = [i for c in comps for i in rules(c, "older")]
    out["by_order"][label] = {
        "compactions": len(comps), "users": len({user(c) for c in comps}),
        "recent": tally([i for c in comps for i in rules(c, "recent")]), "older": tally(older),
        "older_top_user": tally([i for c in comps if user(c) == top for i in rules(c, "older")]),
        "older_everyone_else": tally([i for c in comps if user(c) != top for i in rules(c, "older")]),
        "older_without_the_one_session": tally([i for c in comps if c["path"] != heavy[0] for i in rules(c, "older")]),
        "users_with_older_rules": len({user(c) for c in comps if rules(c, "older")})}

out["recent_by_messages_typed_since_last_compaction"] = {}
for label, lo, hi in (("1-9", 1, 9), ("10-19", 10, 19), ("20-39", 20, 39), ("40+", 40, 10 ** 9)):
    comps = [c for c in lines if lo <= typed(c, "recent") <= hi]
    out["recent_by_messages_typed_since_last_compaction"][label] = {
        "compactions": len(comps), "users": len({user(c) for c in comps}),
        "all": tally([i for c in comps for i in rules(c, "recent")]),
        "top_user": tally([i for c in comps if user(c) == top for i in rules(c, "recent")]),
        "everyone_else": tally([i for c in comps if user(c) != top for i in rules(c, "recent")])}

def quoted(items):
    return {"n": len(items), "word_for_word": sum(1 for i in items if i.get("match") == "word for word"),
            "mostly": sum(1 for i in items if i.get("match") == "mostly")}


# A plain text search, with no model: is the typed message quoted in the summary?
out["text_search"] = {
    "recent": quoted([i for c in lines for i in c["items"] if i["where"] == "recent"]),
    "older": quoted([i for c in lines for i in c["items"] if i["where"] == "older"]),
    "first_compaction_recent": quoted([i for c in lines if c["order"] == 1 for i in c["items"] if i["where"] == "recent"]),
    "second_compaction_recent": quoted([i for c in lines if c["order"] == 2 for i in c["items"] if i["where"] == "recent"]),
    "second_compaction_older": quoted([i for c in lines if c["order"] == 2 for i in c["items"] if i["where"] == "older"]),
}

replay = ["0d4c4262", "27642e0f", "73009f6a", "cd25197e", "2cae28a4", "5a7b375c", "ede0cb33"]
names = {}
out["replay_sessions"] = []
for short in replay:
    full = [s for s in by if s.startswith(short)]
    u = by[full[0]]["user_id"] if full else None
    names.setdefault(u, "user %d" % (len(names) + 1))
    out["replay_sessions"].append({"session": short, "user": names[u], "is_top_user": u == top})
out["replay_users"] = len(names)

json.dump(out, open(os.path.join(KIT, "analysis/results-clusters.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
