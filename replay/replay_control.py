#!/usr/bin/env python3
"""replay_control.py LIST DATA_DIR REPLAY_OUT_DIR ORIGINAL_JUDGE.jsonl

A before-compaction check for the replayed sessions that were recorded near 1M tokens. Resuming such
a session whole triggers a compaction at once, so the session is cut earlier: at the last message the
person typed while the recorded size was still under 850,000 tokens. A copy of that cut, not compacted,
is asked the round-1 questions whose rule was typed before the cut, and the answers are graded as in
replay_ask.py. Results: REPLAY_OUT_DIR/ask/control.jsonl (grades only) and ask/raw/. The subscription pays."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "real"))
import analyze_real as A
import judge as J

listing, data_dir, replay_dir, judge_file = sys.argv[1:5]
out_dir = os.path.join(os.path.abspath(replay_dir), "ask")
CLAUDE = ["npx", "-y", "@anthropic-ai/claude-code@2.1.327"]
MODEL = "claude-opus-5-5"
LIMIT = 850000
MAX_RULES = 12
ASK = ("A few questions about this session, to check what you still know of it. Answer each from what you know "
       "of this session, in one or two sentences. If you do not know, answer exactly: not known. Do not use "
       "tools or look anything up. Number your answers to match the questions.\n\n")
cfg = {"claude": CLAUDE, "model": MODEL, "effort": "medium", "pool": "plan", "out_dir": out_dir, "cwd": os.path.join(out_dir, "cwd")}
env = {k: v for k, v in os.environ.items() if k not in J.PARENT_VARIABLES + ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "6000"
judged = {}
for line in open(judge_file, encoding="utf-8"):
    row = json.loads(line); judged[(row["path"], row["order"])] = row
result_file = os.path.join(out_dir, "control.jsonl")
done = set(json.loads(l)["session"] for l in open(result_file)) if os.path.exists(result_file) else set()


def size_of(row):
    usage = (row.get("message") or {}).get("usage") if row.get("type") == "assistant" else None
    return sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")) if usage else 0


for rel in [p.strip() for p in open(listing) if p.strip() and not p.startswith("#")]:
    name = os.path.basename(rel)[:8]
    home = os.path.join(os.path.abspath(replay_dir), name)
    first = os.path.join(home, "F1.jsonl")
    key_file = os.path.join(out_dir, "raw", "questions-%s.json" % name)
    if name in done or not os.path.exists(first) or not os.path.exists(key_file):
        continue
    rows = [json.loads(l) for l in open(first, encoding="utf-8")]
    sizes, size = [], 0
    for row in rows:
        size = size_of(row) or size
        sizes.append(size)
    if sizes[-1] < 300000:
        continue                                   # small sessions already have this check
    cut = max((i for i, row in enumerate(rows) if A.is_typed(row) and i > 0 and sizes[i - 1] <= LIMIT), default=None)
    if cut is None:
        print("%s: no place to cut, skipped" % name); continue
    early = os.path.join(home, "F1-early.jsonl")
    with open(early, "w", encoding="utf-8") as handle:
        for row in rows[:cut]:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    typed_before = {A.squash(A.text_of((r.get("message") or {}).get("content"))) for r in rows[:cut] if A.is_typed(r)}
    # The same rules, in the same order, as replay_ask.py took for the questions.
    rules = []
    for comp in J.compactions(os.path.join(data_dir, rel))[:3]:
        labels = judged.get((rel, comp["order"]))
        if not labels or len(labels["items"]) != len(comp["items"]):
            continue
        mine = [item["text"] for item, label in zip(comp["items"], labels["items"])
                if item["where"] == "recent" and label.get("lasting") and label.get("kind") in ("rule", "correction")]
        rules += [(comp["order"], text) for text in mine[:MAX_RULES]]
    questions = json.load(open(key_file, encoding="utf-8"))
    if len(rules) != len(questions):
        # replay_ask.py dropped the rules it could not turn into a question; the writer's saved reply says which.
        written, keep = [], []
        try:
            raw = json.load(open(os.path.join(out_dir, "raw", "write-%s-1.json" % name), encoding="utf-8"))["reply"]
            written = json.loads(raw[raw.find("["):raw.rfind("]") + 1], strict=False)
            keep = [i for i, w in enumerate(written) if str(w.get("question") or "").strip()]
        except (OSError, ValueError, KeyError):
            pass
        if (len(written) != len(rules) or len(keep) != len(questions)
                or any(str(written[i].get("question")) != questions[j]["question"] for j, i in enumerate(keep))):
            print("%s: %d rules but %d questions, so they cannot be matched; skipped" % (name, len(rules), len(questions))); continue
        rules = [rules[i] for i in keep]
    mine = [q for q, (order, text) in zip(questions, rules) if order == 1 and A.squash(text) in typed_before]
    if not mine:
        print("%s: no round-1 rule was typed before the cut, skipped" % name); continue
    if os.environ.get("CONTROL_DRY"):
        print("%s: would cut at %d tokens, %d of the round-1 questions apply" % (name, sizes[cut - 1], len(mine))); continue
    prompt = ASK + "\n".join("%d) %s" % (n, q["question"]) for n, q in enumerate(mine, 1))
    argv = CLAUDE + ["-p", prompt, "--resume", early, "--fork-session", "--tools", "", "--strict-mcp-config",
                     "--disable-slash-commands", "--setting-sources", "project", "--model", MODEL, "--effort", "medium",
                     "--output-format", "stream-json", "--verbose"]
    print("%s: cut at %d tokens, %d of the round-1 questions apply" % (name, sizes[cut - 1], len(mine)), flush=True)
    try:
        out = subprocess.run(argv, cwd=os.path.join(home, "cwd"), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1200).stdout
    except subprocess.TimeoutExpired:
        out = ""
    data, said, compacted = {}, [], False
    for line in out.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") == "result":
            data = row
        elif row.get("type") == "system" and row.get("subtype") == "compact_boundary":
            compacted = True
        elif row.get("type") == "assistant":
            for block in (row.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                    said.append(block["text"])
    answer = data.get("result") or ("\n".join(said) if not data.get("is_error") else "")
    with open(os.path.join(out_dir, "raw", "control-%s.json" % name), "w", encoding="utf-8") as handle:
        json.dump({"prompt": prompt, "reply": answer, "usage": data.get("usage"), "is_error": data.get("is_error"), "compacted": compacted}, handle, ensure_ascii=False)
    if compacted or not answer:
        print("%s: %s; no check for this session" % (name, "the copy was compacted" if compacted else "the copy did not answer")); continue
    material = "ANSWERS GIVEN (numbered by the assistant)\n%s\n\nITEMS\n%s" % (answer, "\n\n".join(
        "%d. QUESTION: %s\n   KEY: %s" % (n, q["question"], q["answer"]) for n, q in enumerate(mine, 1)))
    grades = None
    for attempt in (1, 2):
        reply, cost, usage, problem = J.ask(cfg, os.path.join(out_dir, "grade-system.txt"), material, "grade-control-%s-%d" % (name, attempt))
        start, end = reply.find("["), reply.rfind("]")
        try:
            grades = json.loads(reply[start:end + 1], strict=False)
        except ValueError:
            grades = None
        if grades and len(grades) == len(mine):
            break
    if not grades or len(grades) != len(mine):
        print("%s: grading failed" % name); continue
    line = {"session": name, "cut_tokens": sizes[cut - 1], "items": [{"grade": str(g.get("grade"))} for g in grades]}
    with open(result_file, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")
    print("%s before any compaction: %s" % (name, dict(__import__("collections").Counter(i["grade"] for i in line["items"]))), flush=True)
print("== done")
