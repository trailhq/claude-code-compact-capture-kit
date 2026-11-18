"""Count right answers by where each fact came from, for the size ladder.

Usage: python3 ladder_kinds.py <ladder-out folder> <output csv>

It reuses the scoring of analyze_ladder.py and adds one thing: the kind of
each fact. A fact is "typed" if the user typed it, "file" if it sits in an
instruction file, "claude" if Claude put it into a reply before the
compaction, "read" if it was only ever in the output of a Read call, and
"script" if it was only ever in the output of a Bash call.

The kinds are not taken on trust. check_kinds() looks each planted value up
in the main transcript, in everything before the last compaction, and stops
the script if a value turns up somewhere its kind says it should not. An
earlier version hard-coded the table outliers as "claude", which was true of
the 2.1.285 run and false of the 2.1.311 run.

Two sizes are written for each compaction. pre_tokens is Claude Code's own
count, from the compaction record. request_before is the size of the first
quiz request sent to a copy just before, so it includes the quiz prompt.

One rule differs from analyze_ladder.py. When a reply gives a numbered answer
twice, the later one counts. At the largest size Claude gave two answers wrong
and corrected them in the same reply. Both counts are printed.
"""
import csv
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import analyze_ladder as al  # noqa: E402

KIND_A = {1: "file", 2: "file", 3: "file", 4: "typed", 5: "typed", 6: "typed", 7: "typed", 8: "claude", 9: "claude"}
KIND_B = {1: "script", 2: "claude", 3: "script", 4: "claude", 5: "claude", 6: "claude", 7: "claude"}
KIND_TASK = {"aside": "typed", "finding": "claude", "error": "claude", "output": "script", "needle": "read"}
ORDER = ["typed", "file", "claude", "read", "script"]

# One value per quiz fact, as it appears in the session. Instruction-file facts are left out:
# their text reaches Claude as an attachment, not as a message.
VALUE_A = {4: "# lantern", 5: "MAGPIE", 6: "4417", 7: "no network", 8: "E4107: checksum mismatch at offset 0x3fa2", 9: "RETRY_LIMIT = 7"}
VALUE_B = {1: "/var/tmp/hx-9931", 2: "077", 3: "2.4 s", 4: "119", 5: "03:40", 6: "BATCH_SIZE = 64", 7: "POOL_SIZE = 12"}


def seen_where(path, values):
    """Where each value appears before the last compaction: user text, Claude's reply text, or a tool's output."""
    all_rows = list(al.rows(path))
    last = max((i for i, row in enumerate(all_rows) if row.get("subtype") == "compact_boundary"), default=len(all_rows))
    tool_of, where = {}, {value: set() for value in values}
    for row in all_rows[:last]:
        if row.get("type") not in ("user", "assistant"):
            continue
        content = (row.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        for block in blocks:
            kind = block.get("type")
            if kind == "tool_use":
                tool_of[block.get("id")] = block.get("name")
                continue
            if kind == "text":
                source, text = ("typed" if row["type"] == "user" else "claude"), block.get("text") or ""
            elif kind == "tool_result":
                inner = block.get("content")
                text = inner if isinstance(inner, str) else str(inner)
                source = {"Read": "read", "Bash": "script"}.get(tool_of.get(block.get("tool_use_id")), "tool")
            else:
                continue
            for value in values:
                if value in text:
                    where[value].add(source)
    return where


def check_kinds(folder, expected):
    """Stop if a planted value was seen somewhere its kind says it was not."""
    facts = [(f"a{n}", VALUE_A[n], KIND_A[n]) for n in VALUE_A] + [(f"b{n}", VALUE_B[n], KIND_B[n]) for n in VALUE_B]
    facts += [(f"task {unit} {kind}", value, KIND_TASK[kind]) for (unit, _k), (kind, value) in sorted(expected.items())]
    where = seen_where(os.path.join(folder, "transcript.jsonl"), [value for _n, value, _k in facts])
    wrong = []
    for name, value, kind in facts:
        seen = where[value]
        if kind == "typed":
            ok = "typed" in seen
        elif kind == "claude":
            ok = "claude" in seen and "typed" not in seen
        else:                                   # read or script: in that tool's output and nowhere in the talk
            ok = seen == {kind}
        if not ok:
            wrong.append(f"{name} ({value}) is filed as {kind} but was seen in {sorted(seen)}")
    if wrong:
        sys.exit("kinds do not match the transcript:\n  " + "\n  ".join(wrong))
    print(f"kinds checked against the transcript: {len(facts)} facts")


def numbered_last(text):
    answers = {}
    matches = list(re.finditer(r"(?m)^\s*(?:\*\*)?(\d{1,2})[\).:](?:\*\*)?\s*(.*)$", text or ""))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        answers[int(match.group(1))] = text[match.start(2):end].strip()
    return answers


def pre_tokens(folder, name, mode):
    """Claude Code's own count before the compaction, from the compaction record."""
    path = os.path.join(folder, "transcript.jsonl" if mode == "main" else f"transcript-{name}.jsonl")
    found = None
    for row in al.rows(path):
        if row.get("subtype") == "compact_boundary":
            found = (row.get("compactMetadata") or {}).get("preTokens")
    return found


def request_size(result):
    usage = result.get("usage") or {}
    return sum(usage.get(key) or 0 for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def main():
    folder, target = sys.argv[1], sys.argv[2]
    checkpoints = al.tsv(os.path.join(folder, "checkpoints.tsv"))
    answers = al.tsv(os.path.join(folder, "answers.tsv"))
    expected = {(int(r["unit"]), int(r["number"])): (r["kind"], r["expected"]) for r in answers}
    check_kinds(folder, expected)
    results = {}
    for path in sorted(glob.glob(os.path.join(folder, "step-*.jsonl"))):
        label = os.path.basename(path)[:-6].split("-", 2)[2]
        found = [r for r in al.rows(path) if r.get("type") == "result"]
        results[label] = found[-1] if found else {}

    def reply(label):
        return (results.get(label) or {}).get("result") or ""

    out = []
    for cp in checkpoints:
        name, tasks = cp["name"], int(cp["tasks"])
        for rule, reader in (("first answer counts", al.numbered), ("later answer counts", numbered_last)):
            count = {kind: [0, 0, 0] for kind in ORDER}   # asked, right before, right after
            for part, table, kinds in (("a", al.FACTS, KIND_A), ("b", al.DETAILS, KIND_B)):
                before, after = reader(reply(f"{name}-before-{part}")), reader(reply(f"{name}-after-{part}"))
                for number, _label, pattern in table:
                    kind = kinds[number]
                    count[kind][0] += 1
                    count[kind][1] += al.mark(pattern, before.get(number, "")) == "ok"
                    count[kind][2] += al.mark(pattern, after.get(number, "")) == "ok"
            first = 1
            while first <= tasks:
                last = min(first + 2, tasks)
                before = reader(reply(f"{name}-before-u{first}-{last}"))
                after = reader(reply(f"{name}-after-u{first}-{last}"))
                for unit in range(first, last + 1):
                    for k in range(1, 6):
                        task_kind, value = expected[(unit, k)]
                        kind = KIND_TASK[task_kind]
                        pattern = al.token_pattern(task_kind, value)
                        number = (unit - first) * 5 + k
                        count[kind][0] += 1
                        count[kind][1] += al.mark(pattern, before.get(number, "")) == "ok"
                        count[kind][2] += al.mark(pattern, after.get(number, "")) == "ok"
                first = last + 1
            size = request_size(results.get(f"{name}-before-a") or {})
            counted = pre_tokens(folder, name, cp["mode"])
            for kind in ORDER:
                asked, right_before, right_after = count[kind]
                out.append({"checkpoint": name, "tasks_done": tasks, "pre_tokens": counted, "request_before": size, "rule": rule,
                            "kind": kind, "asked": asked, "right_before": right_before, "right_after": right_after})

    with open(target, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)
    for rule in ("first answer counts", "later answer counts"):
        print(rule)
        for cp in checkpoints:
            rows = [r for r in out if r["checkpoint"] == cp["name"] and r["rule"] == rule]
            total_asked = sum(r["asked"] for r in rows)
            total_after = sum(r["right_after"] for r in rows)
            total_before = sum(r["right_before"] for r in rows)
            parts = ", ".join(f"{r['kind']} {r['right_after']}/{r['asked']}" for r in rows)
            print(f"  {cp['name']} pre_tokens={rows[0]['pre_tokens']:,} request_before={rows[0]['request_before']:,} before {total_before}/{total_asked} after {total_after}/{total_asked}: {parts}")


if __name__ == "__main__":
    main()
