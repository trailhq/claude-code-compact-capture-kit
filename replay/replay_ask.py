#!/usr/bin/env python3
"""replay_ask.py LIST DATA_DIR REPLAY_OUT_DIR ORIGINAL_JUDGE.jsonl [--control]

Study 3, the questions. For each replayed session:
  1. Take the rules and corrections the person typed in rounds 1 to 3 that the meaning check marked
     as still mattering (from ORIGINAL_JUDGE.jsonl; the text comes from the original transcript).
  2. One model call writes, for each, a question that does not give the instruction away, and the
     answer key.
  3. After each round k, a new copy of the replayed session (compacted k times) is asked the
     questions about rounds 1 to k. With --control, the three small sessions are also asked the
     round-1 questions on a copy made before any compaction.
  4. One model call grades the answers against the key: right, partly, wrong or unknown.
Results: REPLAY_OUT_DIR/ask/ask.jsonl (grades only) and ask/raw/ (questions, answers, prompts).
The subscription pays (the key is hidden). It can be run again; finished pieces are skipped."""
import json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "real"))
import judge as J

args = [a for a in sys.argv[1:] if not a.startswith("--")]
control = "--control" in sys.argv
listing, data_dir, replay_dir, judge_file = args
out_dir = os.path.join(os.path.abspath(replay_dir), "ask")
os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)
os.makedirs(os.path.join(out_dir, "cwd"), exist_ok=True)
CLAUDE = ["npx", "-y", "@anthropic-ai/claude-code@2.1.327"]
MODEL = "claude-opus-5-5"
MAX_RULES = 12          # per round

WRITE = """You get numbered instructions that a person typed to a coding assistant during a long working session.

For each one, write a question the person could ask later to check whether the assistant still knows it. The question must name the subject, but must not give away the instruction or hint at the answer. It must not be answerable from general knowledge, or by guessing yes or no.

Also write the answer: one sentence that states what the person asked for, with its specifics.

If an instruction is too vague or too tied to one moment to test this way, set question to an empty string.

Reply with a JSON array and nothing else: [{"n": 1, "question": "...", "answer": "..."}]"""

GRADE = """You grade answers. Each numbered item has a QUESTION, the KEY (what the person had actually asked for) and the ANSWER an assistant gave.

Grade each:
  right: the answer states the substance of the key, with its specifics.
  partly: the right direction, but a needed specific is missing, vague or changed.
  wrong: the answer states something else as fact.
  unknown: the answer says it does not know.

Reply with a JSON array and nothing else: [{"n": 1, "grade": "right"}]"""

ASK = ("A few questions about this session, to check what you still know of it. Answer each from what you know "
       "of this session, in one or two sentences. If you do not know, answer exactly: not known. Do not use "
       "tools or look anything up. Number your answers to match the questions.\n\n")

for name, text in (("write-system.txt", WRITE), ("grade-system.txt", GRADE)):
    open(os.path.join(out_dir, name), "w", encoding="utf-8").write(text)
cfg = {"claude": CLAUDE, "model": MODEL, "effort": "medium", "pool": "plan", "out_dir": out_dir, "cwd": os.path.join(out_dir, "cwd")}
env = {k: v for k, v in os.environ.items() if k not in J.PARENT_VARIABLES + ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "6000"     # an answer to these questions is short; two copies ran to 100,000 tokens
judged = {}
for line in open(judge_file, encoding="utf-8"):
    row = json.loads(line); judged[(row["path"], row["order"])] = row
result_file = os.path.join(out_dir, "ask.jsonl")
done = set()
if os.path.exists(result_file):
    for line in open(result_file, encoding="utf-8"):
        row = json.loads(line); done.add((row["session"], row["asked_after_round"]))
spent = 0.0


def recorded_size(path):
    total = 0
    for line in open(path, encoding="utf-8", errors="replace"):
        if '"usage"' not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        usage = (row.get("message") or {}).get("usage") if row.get("type") == "assistant" else None
        if usage:
            size = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
            total = size or total
    return total


def array(text):
    start, end = text.find("["), text.rfind("]")
    try:
        return json.loads(text[start:end + 1], strict=False) if start >= 0 and end > start else None
    except ValueError:
        return None


def model_call(system_name, material, tag):
    global spent
    for attempt in (1, 2):
        reply, cost, usage, problem = J.ask(cfg, os.path.join(out_dir, system_name), material, "%s-%d" % (tag, attempt))
        spent += cost or 0.0
        rows = None if problem else array(reply)
        if rows:
            return rows
    return None


def ask_session(transcript, prompt, cwd, tag):
    global spent
    argv = CLAUDE + ["-p", prompt, "--resume", transcript, "--fork-session", "--tools", "", "--strict-mcp-config",
                     "--disable-slash-commands", "--setting-sources", "project", "--model", MODEL, "--effort", "medium",
                     "--output-format", "stream-json", "--verbose"]
    try:
        run = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
        out = run.stdout
    except subprocess.TimeoutExpired:
        out = ""
    data, said = {}, []
    for line in out.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") == "result":
            data = row
        elif row.get("type") == "assistant":
            for block in (row.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                    said.append(block["text"])
    # The final result can come back empty when the reply was spread over several messages.
    if not data.get("result") and said and not data.get("is_error"):
        data["result"] = "\n".join(said)
    spent += data.get("total_cost_usd") or 0.0
    with open(os.path.join(out_dir, "raw", tag + ".json"), "w", encoding="utf-8") as handle:
        json.dump({"prompt": prompt, "reply": data.get("result"), "cost": data.get("total_cost_usd"),
                   "usage": data.get("usage"), "is_error": data.get("is_error"), "messages": len(said)}, handle, ensure_ascii=False)
    return None if (data.get("is_error") or not data.get("result")) else data["result"]


for rel in [p.strip() for p in open(listing) if p.strip() and not p.startswith("#")]:
    name = os.path.basename(rel)[:8]
    home = os.path.join(os.path.abspath(replay_dir), name)
    if not os.path.exists(os.path.join(home, "round-3.jsonl")):
        print("%s: not replayed through three rounds, skipped" % name); continue
    key_file = os.path.join(out_dir, "raw", "questions-%s.json" % name)
    if os.path.exists(key_file):
        questions = json.load(open(key_file, encoding="utf-8"))
    else:
        comps = J.compactions(os.path.join(data_dir, rel))[:3]
        rules = []
        for comp in comps:
            labels = judged.get((rel, comp["order"]))
            if not labels or len(labels["items"]) != len(comp["items"]):
                print("%s round %d: no matching judgement, skipped" % (name, comp["order"])); continue
            mine = [item["text"] for item, label in zip(comp["items"], labels["items"])
                    if item["where"] == "recent" and label.get("lasting") and label.get("kind") in ("rule", "correction")]
            rules += [(comp["order"], text) for text in mine[:MAX_RULES]]
        if not rules:
            print("%s: no rules or corrections to ask about" % name)
            json.dump([], open(key_file, "w")); continue
        material = "\n\n".join("--- instruction %d ---\n%s" % (n, J.clip(text)) for n, (_, text) in enumerate(rules, 1))
        written = model_call("write-system.txt", material, "write-" + name)
        if not written or len(written) != len(rules):
            print("STOP: could not write the questions for %s" % name); sys.exit(1)
        questions = [{"from_round": rules[i][0], "question": str(w.get("question") or ""), "answer": str(w.get("answer") or "")}
                     for i, w in enumerate(written)]
        questions = [q for q in questions if q["question"].strip()]
        json.dump(questions, open(key_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%s: %d questions (%s by round)" % (name, len(questions), [sum(1 for q in questions if q["from_round"] == k) for k in (1, 2, 3)]), flush=True)
    stages = [(k, os.path.join(home, "round-%d.jsonl" % k)) for k in (1, 2, 3)]
    # The control copy is only possible where the uncompacted session is far below today's limit;
    # a session recorded near 1M would be compacted as soon as it is resumed.
    if control and 0 < recorded_size(os.path.join(home, "F1.jsonl")) < 300000:
        stages.insert(0, (0, os.path.join(home, "F1.jsonl")))
    for asked_after, transcript in stages:
        mine = [q for q in questions if q["from_round"] <= max(asked_after, 1)]
        if (name, asked_after) in done or not mine or "%s:%d" % (name, asked_after) in os.environ.get("ASK_SKIP", "").split(","):
            continue
        prompt = ASK + "\n".join("%d) %s" % (n, q["question"]) for n, q in enumerate(mine, 1))
        answer = ask_session(transcript, prompt, os.path.join(home, "cwd"), "answers-%s-r%d" % (name, asked_after))
        if answer is None:
            print("%s after round %d: the copy did not answer, skipped" % (name, asked_after)); continue
        material = "ANSWERS GIVEN (numbered by the assistant)\n%s\n\nITEMS\n%s" % (answer, "\n\n".join(
            "%d. QUESTION: %s\n   KEY: %s" % (n, q["question"], q["answer"]) for n, q in enumerate(mine, 1)))
        grades = model_call("grade-system.txt", material, "grade-%s-r%d" % (name, asked_after))
        if not grades or len(grades) != len(mine):
            print("%s after round %d: grading failed, skipped" % (name, asked_after)); continue
        line = {"session": name, "asked_after_round": asked_after,
                "items": [{"from_round": q["from_round"], "grade": str(g.get("grade"))} for q, g in zip(mine, grades)]}
        with open(result_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
        print("%s %s asked after round %d: %s, $%.2f so far" % (time.strftime("%H:%M:%S"), name, asked_after,
              dict(__import__("collections").Counter(i["grade"] for i in line["items"])), spent), flush=True)
print("== done, $%.2f" % spent)
