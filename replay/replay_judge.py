#!/usr/bin/env python3
"""replay_judge.py LIST DATA_DIR REPLAY_OUT_DIR [--rounds 3]

The meaning check (real/judge.py) applied to the replayed summaries. For each session and round k
it takes the messages the person typed in the original session before its k-th compaction, and the
summary today's Claude Code wrote for that round in the replay, and asks the same judge the same
questions. Results: REPLAY_OUT_DIR/judge/judge.jsonl, in the format judge_report.py reads.
The messages kept word for word after a summary are not looked up here, so every message is judged
against the summary text alone. POOL=api or plan, as for judge.py."""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "real"))
import analyze_real as A
import judge as J

args = [a for a in sys.argv[1:] if not a.startswith("--")]
rounds = int(sys.argv[sys.argv.index("--rounds") + 1]) if "--rounds" in sys.argv else 3
if "--rounds" in sys.argv:
    args.remove(str(rounds))
listing, data_dir, replay_dir = args
out_dir = os.path.join(os.path.abspath(replay_dir), "judge")
os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)
os.makedirs(os.path.join(out_dir, "cwd"), exist_ok=True)
system_file = os.path.join(out_dir, "system-prompt.txt")
open(system_file, "w", encoding="utf-8").write(J.SYSTEM)
pool = os.environ.get("POOL", "plan")
if pool == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("STOP: POOL=api but ANTHROPIC_API_KEY is not set in this environment.")
cfg = {"claude": ["npx", "-y", "@anthropic-ai/claude-code@2.1.327"], "model": "claude-opus-5-5", "effort": "medium",
       "pool": pool, "out_dir": out_dir, "cwd": os.path.join(out_dir, "cwd")}
result_file = os.path.join(out_dir, "judge.jsonl")
done = set()
if os.path.exists(result_file):
    for line in open(result_file, encoding="utf-8"):
        row = json.loads(line); done.add((row["path"], row["order"]))


def replay_summary(path):
    summary, meta = "", {}
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") == "system" and row.get("subtype") == "compact_boundary":
                meta = row.get("compactMetadata") or {}
            if row.get("isCompactSummary"):
                summary = A.text_of((row.get("message") or {}).get("content"))
    return summary, meta


spent = 0.0
for rel in [p.strip() for p in open(listing) if p.strip() and not p.startswith("#")]:
    name = os.path.basename(rel)[:8]
    original = J.compactions(os.path.join(data_dir, rel))
    for comp in original[:rounds]:
        k = comp["order"]
        new = os.path.join(replay_dir, name, "round-%d.jsonl" % k)
        if (rel, k) in done or not os.path.exists(new):
            continue
        summary, meta = replay_summary(new)
        if not summary:
            continue
        flat = A.squash(summary); grams = A.shingles(flat.split())
        comp = dict(comp, summary=summary, summary_words=len(summary.split()), version="2.1.327 (replay)",
                    trigger=meta.get("trigger") or "auto", idle=False, pre_tokens=meta.get("preTokens", comp["pre_tokens"]))
        comp["items"] = [dict(item, match=A.kept(item["text"], flat, grams), tail=False) for item in comp["items"]]
        line, cost = J.judge_one(cfg, system_file, rel, comp)
        spent += cost
        if line is None:
            print("STOP: a call failed for %s round %d. See %s/judge.log" % (name, k, out_dir)); sys.exit(1)
        with open(result_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
        print("%s %s round %d judged, %d messages, $%.2f so far" % (time.strftime("%H:%M:%S"), name, k, len(line["items"]), spent), flush=True)
print("== done, $%.2f" % spent)
