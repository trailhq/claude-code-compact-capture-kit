#!/usr/bin/env python3
"""Summarise one compact-capture run.

Usage: python3 -I analyze_capture.py <folder with the capture files> [--full]

Reads only: the step-*.jsonl stream-json files, the three hook logs,
steps.tsv, launch.txt, version.txt, machine.txt, files.txt and
transcript.jsonl. Prints a plain-text report. Everything it reads is
treated as data and looked up defensively.
"""
import glob
import json
import os
import re
import sys

FACTS = [
    (1, "project codename", r"\bHERON\b"),
    (2, "invoice codename", r"\bOSPREY\b"),
    (3, "API header", r"KESTREL"),
    (4, "shell comment", r"#\s*lantern"),
    (5, "release train", r"\bMAGPIE\b"),
    (6, "staging port", r"\b4417\b"),
    (7, "why SQLite", r"(?i)no network|without (a )?network|network access|offline|no internet|can.t reach"),
    (8, "exact error line", r"E4107: checksum mismatch at offset 0x3fa2"),
    (9, "RETRY_LIMIT", r"(?<![\d.])7(?![\d.])"),
]
DETAILS = [
    (1, "scratch dir (output)", r"/var/tmp/hx-9931"),
    (2, "retried block (output)", r"(?<!\d)0?77(?!\d)"),
    (3, "slowest block (output)", r"(?<!\d)188(?!\d)"),
    (4, "blocks after (worked out)", r"(?<!\d)119(?!\d)"),
    (5, "build 0412 (big file)", r"03:40"),
    (6, "BATCH_SIZE two.py", r"(?<![\d.])64(?!\d)(?!\.\d)"),
    (7, "POOL_SIZE seven.py", r"(?<![\d.])12(?!\d)(?!\.\d)"),
]
UNKNOWN = re.compile(r"(?i)\bunknown\b|don.t know|do not know|not sure|no record|can.t recall|cannot recall")


def load_jsonl(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append({"_unparsed": line[:200]})
    return rows


def text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    parts.append(text_of(block.get("content")))
            elif isinstance(block, str):
                parts.append(block)
    return "\n".join(parts)


def numbered_answers(text):
    answers = {}
    pattern = re.compile(r"(?m)^\s*(?:\*\*)?(\d)[\).:](?:\*\*)?\s*(.*)$")
    matches = list(pattern.finditer(text or ""))
    for index, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        answers.setdefault(number, text[match.start(2):end].strip())
    return answers


def step_result(folder, label_part):
    """Final result message of the step whose file name holds label_part."""
    found = []
    for path in sorted(glob.glob(os.path.join(folder, f"step-*-{label_part}*.jsonl"))):
        rows = load_jsonl(path)
        results = [r for r in rows if r.get("type") == "result"]
        inits = [r for r in rows if r.get("type") == "system" and r.get("subtype") == "init"]
        if results:
            found.append((os.path.basename(path)[:-6], results[-1], inits[-1] if inits else {}))
    return found


def score(table, text):
    answers = numbered_answers(text)
    out = []
    for number, name, pattern in table:
        answer = answers.get(number, "")
        if re.search(pattern, answer):
            mark = "ok"
        elif UNKNOWN.search(answer) or not answer:
            mark = "--"
        else:
            mark = "??"
        out.append((number, name, mark, answer))
    return out


def main():
    folder = sys.argv[1]
    full = "--full" in sys.argv
    main_id = ""
    path = os.path.join(folder, "session-id.txt")
    if os.path.isfile(path):
        main_id = open(path).read().strip()

    print("=" * 72)
    for name in ("version.txt", "machine.txt", "launch.txt", "steps.tsv", "session-id.txt", "files.txt"):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            print(f"--- {name}")
            print(open(path, errors="replace").read().rstrip()[:3500])

    print("\n" + "=" * 72 + "\nSTEPS")
    previous_cost = 0.0
    for path in sorted(glob.glob(os.path.join(folder, "step-*.jsonl"))):
        label = os.path.basename(path)[:-6]
        rows = load_jsonl(path)
        print(f"\n### {label}: {len(rows)} messages")
        for row in rows:
            kind = row.get("type")
            if kind == "system" and row.get("subtype") == "init":
                keep = {k: row.get(k) for k in ("model", "claude_code_version", "permissionMode", "apiKeySource") if k in row}
                keep["session"] = "main" if row.get("session_id") == main_id else "copy " + str(row.get("session_id"))[:8]
                keep["tools"] = len(row.get("tools") or [])
                keep["mcp_servers"] = len(row.get("mcp_servers") or [])
                print("  init:", json.dumps(keep))
            elif kind == "system" and row.get("subtype") in ("compact_boundary", "status"):
                slim = {k: v for k, v in row.items() if k not in ("uuid", "session_id")}
                print("  system:", json.dumps(slim)[:1200])
            elif kind == "assistant":
                for block in (row.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        print("  tool_use:", block.get("name"), json.dumps(block.get("input"))[:260])
            elif kind == "result":
                usage = row.get("usage") or {}
                cost = row.get("total_cost_usd") or 0.0
                is_main = row.get("session_id") == main_id
                step_cost = cost - previous_cost if is_main else cost
                if is_main:
                    previous_cost = cost
                print("  result:", json.dumps({
                    "session": "main" if is_main else "copy",
                    "turns": row.get("num_turns"), "ms": row.get("duration_ms"),
                    "in": usage.get("input_tokens"), "cache_write": usage.get("cache_creation_input_tokens"),
                    "cache_read": usage.get("cache_read_input_tokens"), "out": usage.get("output_tokens"),
                    "cost_total": round(cost, 4), "cost_step_if_main": round(step_cost, 4),
                    "is_error": row.get("is_error"), "denials": len(row.get("permission_denials") or []),
                }))
                text = row.get("result") or ""
                limit = 6000 if full else 1500
                print("  TEXT:", text[:limit].replace("\n", "\n        "))
        err = path[:-6] + ".err"
        if os.path.isfile(err) and os.path.getsize(err):
            print("  STDERR:", open(err, errors="replace").read()[:1200].replace("\n", "\n        "))

    print("\n" + "=" * 72 + "\nHOOKS")
    for name in ("sessionstart.jsonl", "precompact.jsonl", "postcompact.jsonl"):
        rows = load_jsonl(os.path.join(folder, name))
        print(f"\n--- {name}: {len(rows)} records")
        for row in rows:
            slim = {k: v for k, v in row.items() if k not in ("transcript_path", "cwd", "compact_summary")}
            slim["session"] = "main" if row.get("session_id") == main_id else "copy"
            slim.pop("session_id", None)
            print("  ", json.dumps(slim)[:400])

    post = load_jsonl(os.path.join(folder, "postcompact.jsonl"))
    summary = ""
    for row in post:
        if isinstance(row.get("compact_summary"), str):
            summary = row["compact_summary"]
    if summary:
        body = re.search(r"<summary>(.*)</summary>", summary, re.S)
        analysis = re.search(r"<analysis>(.*)</analysis>", summary, re.S)
        print(f"\n--- compact summary: {len(summary)} characters, {len(summary.split())} words in all")
        if analysis:
            print(f"    <analysis> part: {len(analysis.group(1).split())} words")
        if body:
            print(f"    <summary> part:  {len(body.group(1).split())} words")
            heads = re.findall(r"(?m)^\s*(\d+)\.\s+([A-Z][^\n:]{2,60}):\s*$", body.group(1))
            print("    sections:", "; ".join(f"{n}. {h}" for n, h in heads))
        target = body.group(1) if body else summary
        print("\n--- planted facts found in the <summary> part (what stays in context)")
        for number, name, pattern in FACTS:
            hit = re.search(pattern, target)
            where = target[max(0, hit.start() - 60):hit.end() + 60].replace("\n", " ") if hit else ""
            print(f"  A{number} {name:26s} {'YES' if hit else 'no '}  {where}")
        for number, name, pattern in DETAILS:
            hit = re.search(pattern, target)
            where = target[max(0, hit.start() - 60):hit.end() + 60].replace("\n", " ") if hit else ""
            print(f"  B{number} {name:26s} {'YES' if hit else 'no '}  {where}")
        print("\n--- compact summary, in full")
        print(summary)

    print("\n" + "=" * 72 + "\nQUIZ A: nine planted facts")
    for when in ("quiz-before", "quiz-after"):
        for label, result, init in step_result(folder, when):
            where = "main session" if result.get("session_id") == main_id else "a copy"
            rows = score(FACTS, result.get("result") or "")
            total = sum(1 for r in rows if r[2] == "ok")
            print(f"\n  {label} (asked of {where}): {total}/9")
            for number, name, mark, answer in rows:
                print(f"     {number} [{mark}] {name:18s} {answer[:200]!r}")
    print("\n" + "=" * 72 + "\nQUIZ B: seven details nobody pointed out")
    for when in ("details-before", "details-after"):
        for label, result, init in step_result(folder, when):
            where = "main session" if result.get("session_id") == main_id else "a copy"
            rows = score(DETAILS, result.get("result") or "")
            total = sum(1 for r in rows if r[2] == "ok")
            print(f"\n  {label} (asked of {where}): {total}/7")
            for number, name, mark, answer in rows:
                print(f"     {number} [{mark}] {name:26s} {answer[:200]!r}")

    transcript = load_jsonl(os.path.join(folder, "transcript.jsonl"))
    print("\n" + "=" * 72 + f"\nTRANSCRIPT of the main session: {len(transcript)} lines")
    boundary = None
    for index, row in enumerate(transcript):
        if row.get("subtype") == "compact_boundary":
            boundary = index
            meta = row.get("compactMetadata") or {}
            print(f"  boundary at line {index}: {json.dumps(meta)[:700]}")
            keep = set((meta.get("preservedMessages") or {}).get("uuids") or [])
            for other in transcript:
                if other.get("uuid") in keep:
                    body = text_of((other.get("message") or {}).get("content"))
                    print(f"  message kept word for word: type={other.get('type')} {len(body)} characters: {body[:300]!r}")
    quiz_lines = [i for i, row in enumerate(transcript) if row.get("type") == "user" and "answer from what you already know" in text_of((row.get("message") or {}).get("content"))]
    print(f"  quiz prompts in the main transcript at lines: {quiz_lines} (boundary: {boundary})")
    if boundary is not None:
        print("\n--- tool calls before the boundary, in order")
        for index in range(0, boundary):
            row = transcript[index]
            if row.get("type") == "assistant":
                for block in (row.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        data = block.get("input") or {}
                        print(f"   {row.get('timestamp')} {block.get('name')} {data.get('file_path') or data.get('command')}")
        print("\n--- attachments from the boundary on")
        for index in range(boundary, len(transcript)):
            row = transcript[index]
            if row.get("type") == "attachment":
                attachment = row.get("attachment") or {}
                kind = attachment.get("type")
                if kind in ("file", "compact_file_reference", "nested_memory"):
                    content = attachment.get("content")
                    lines = None
                    if isinstance(content, dict):
                        lines = (content.get("file") or {}).get("numLines")
                    print(f"   line {index} {row.get('timestamp')} {kind}: {attachment.get('displayPath')} lines={lines}")
                elif kind == "instructions":
                    for item in attachment.get("files") or []:
                        print(f"   line {index} {row.get('timestamp')} instructions: {item.get('type')} {item.get('path')}")
                elif kind == "skill_listing":
                    print(f"   line {index} {row.get('timestamp')} skill_listing: {attachment.get('skillCount')} skills, isInitial={attachment.get('isInitial')}")
            elif row.get("type") == "user" and row.get("isCompactSummary"):
                body = text_of((row.get("message") or {}).get("content"))
                print(f"   line {index} summary message: {len(body)} characters, {len(body.split())} words")
                print("      first words:", repr(body[:160]))
                print("      last words: ", repr(body[-640:]))
            elif row.get("type") == "user" and not row.get("isMeta"):
                body = text_of((row.get("message") or {}).get("content"))
                if body and not body.startswith("<"):
                    print(f"   line {index} user prompt: {body[:110]!r}")
            elif row.get("type") == "assistant":
                for block in (row.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        data = block.get("input") or {}
                        print(f"   line {index} tool_use {block.get('name')} {data.get('file_path') or data.get('command')}")
                    elif isinstance(block, dict) and block.get("type") == "text":
                        print(f"   line {index} assistant: {block.get('text', '')[:160]!r}")


if __name__ == "__main__":
    main()
