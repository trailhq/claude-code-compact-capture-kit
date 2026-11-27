#!/usr/bin/env python3
"""Measure, by counting only, what each compaction in a set of transcripts kept.

  python3 analyze_real.py SESSIONS_DIR [--all] [--out FILE.tsv]

For every automatic compaction (every compaction with --all) it reports the size,
the summary's length and section titles, how many of the typed messages appear in
the summary word for word, how many file paths from the work appear in it, and what
Claude Code put back after the summary. It prints numbers and the summary's section
titles. It prints no message text. Standard library only.
"""
import argparse
import collections
import glob
import json
import os
import re
import statistics
import sys

PATH_RE = re.compile(r"(?<![\w/.-])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,6}(?![\w/])")
HEAD_RE = re.compile(r"^\s{0,3}(?:#{1,4}\s+(?:\d{1,2}[.)]\s+)?|(?:\*\*)?\d{1,2}[.)]\s+)([A-Z][^:*\n]{2,60}?)\s*:?\**\s*$")


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def squash(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def is_typed(row):
    if row.get("type") != "user" or row.get("isMeta") or row.get("isCompactSummary"):
        return False
    if row.get("isSidechain") or row.get("toolUseResult") is not None:
        return False
    content = (row.get("message") or {}).get("content")
    if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    text = text_of(content).lstrip()
    return bool(text) and not text.startswith((
        "<command-name>", "<local-command-", "<command-message>", "<system-reminder>",
        "Caveat:", "[Request interrupted", "This session is being continued",
        # Written by Claude Code or by another session, not typed by the person:
        "<task-notification>", "Another Claude session sent a message", "<teammate-message",
        "<bash-input>", "<bash-stdout>", "<bash-stderr>", "<ide_opened_file>", "<ide_selection>",
        "/compact"))


def shingles(words, n=6):
    return {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def kept(message, summary_squashed, summary_shingles):
    """word-for-word, mostly, or absent: how a typed message shows up in the summary."""
    flat = squash(message)
    if len(flat) < 12:
        return "short"
    probe = flat if len(flat) <= 400 else flat[:400]
    if probe in summary_squashed:
        return "word for word"
    own = shingles(flat.split())
    share = len(own & summary_shingles) / len(own)
    return "mostly" if share >= 0.5 else "absent"


def tool_paths(row):
    """File paths in a tool call or its result, tagged edited, read or seen."""
    found = []
    content = (row.get("message") or {}).get("content")
    if not isinstance(content, list):
        return found
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            args = block.get("input") or {}
            path = args.get("file_path") or args.get("path") or args.get("notebook_path")
            if isinstance(path, str) and "/" in path:
                kind = "edited" if block.get("name") in ("Edit", "Write", "MultiEdit", "NotebookEdit") else "read"
                found.append((kind, path))
        elif block.get("type") == "tool_result":
            body = block.get("content")
            body = text_of(body) if not isinstance(body, str) else body
            for match in PATH_RE.findall(body[:200000]):
                found.append(("seen", match))
    return found


def sections(summary):
    out, current, count = [], None, 0
    for line in summary.split("\n"):
        match = HEAD_RE.match(line)
        if match:
            if current:
                out.append((current, count))
            current, count = match.group(1).strip(), 0
        else:
            count += len(line.split())
    if current:
        out.append((current, count))
    return out


def analyse(path, want_all):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    results = []
    typed_segments = [[]]           # typed messages, one list per stretch between compactions
    paths = collections.OrderedDict()
    version = model = ""
    earlier = []                    # (summary squashed, shingles) of earlier compactions here
    for index, row in enumerate(rows):
        version = row.get("version") or version
        if row.get("type") == "assistant" and not row.get("isSidechain"):
            name = (row.get("message") or {}).get("model") or ""
            if name and not name.startswith("<"):
                model = name
        if is_typed(row):
            typed_segments[-1].append(text_of((row.get("message") or {}).get("content")))
        if row.get("type") in ("assistant", "user") and not row.get("isSidechain"):
            for kind, found in tool_paths(row):
                base = found.rsplit("/", 1)[-1]
                rank = {"edited": 3, "read": 2, "seen": 1}
                if rank[kind] > rank.get(paths.get(base, ("", ""))[0], 0):
                    paths[base] = (kind, found)
        if not (row.get("type") == "system" and row.get("subtype") == "compact_boundary"):
            continue
        meta = row.get("compactMetadata") or {}
        summary, after_types, back = "", collections.Counter(), 0
        for later in rows[index + 1:index + 400]:
            if later.get("isCompactSummary") and not summary:
                summary = text_of((later.get("message") or {}).get("content"))
                continue
            if is_typed(later) or (later.get("type") == "system" and later.get("subtype") == "compact_boundary"):
                break
            if later.get("type") == "attachment":
                kind = ((later.get("attachment") or {}).get("type")) or "?"
                after_types[kind] += 1
                back += 1
        flat = squash(summary)
        grams = shingles(flat.split())
        verdicts = collections.Counter(kept(m, flat, grams) for m in typed_segments[-1])
        older = [m for seg in typed_segments[:-1] for m in seg]
        older_verdicts = collections.Counter(kept(m, flat, grams) for m in older)
        by_kind = collections.Counter()
        in_summary = collections.Counter()
        for base, (kind, _) in paths.items():
            if len(base) < 5:
                continue
            by_kind[kind] += 1
            if base.lower() in flat:
                in_summary[kind] += 1
        parts = sections(summary)
        manual = meta.get("trigger") == "manual"
        if want_all or not manual:
            preserved = (meta.get("preservedMessages") or {}).get("uuids") or []
            results.append({
                "project": os.path.basename(os.path.dirname(path)).split("-Desktop-")[-1],
                "session": os.path.basename(path)[:8], "time": (row.get("timestamp") or "")[:16],
                "version": version, "model": model,
                "kind": "manual" if manual else ("idle" if meta.get("precomputed") else "limit"),
                "order": len(earlier) + 1, "pre_tokens": meta.get("preTokens", ""),
                "post_tokens": meta.get("postTokens", ""), "summary_words": len(summary.split()),
                "sections": len(parts), "section_titles": " | ".join(t for t, _ in parts),
                "typed": len(typed_segments[-1]), "typed_word_for_word": verdicts["word for word"],
                "typed_mostly": verdicts["mostly"], "typed_absent": verdicts["absent"],
                "typed_too_short": verdicts["short"],
                "older_typed": len(older), "older_word_for_word": older_verdicts["word for word"],
                "older_mostly": older_verdicts["mostly"], "older_absent": older_verdicts["absent"],
                "kept_word_for_word_after": len(preserved),
                "paths_edited": by_kind["edited"], "paths_edited_in_summary": in_summary["edited"],
                "paths_read": by_kind["read"], "paths_read_in_summary": in_summary["read"],
                "paths_seen": by_kind["seen"], "paths_seen_in_summary": in_summary["seen"],
                "put_back_after": back,
                "put_back_kinds": ";".join("%s=%d" % kv for kv in after_types.most_common(8)),
            })
        earlier.append((flat, grams))
        typed_segments.append([])
        paths = collections.OrderedDict()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sessions_dir")
    parser.add_argument("--all", action="store_true", help="include manual compactions")
    parser.add_argument("--out", default="real_compactions.tsv")
    args = parser.parse_args()
    seen, rows = set(), []
    for path in sorted(glob.glob(os.path.join(args.sessions_dir, "**", "*.jsonl"), recursive=True)):
        for result in analyse(path, args.all):
            key = (result["time"], result["pre_tokens"])
            if key not in seen:          # the same compaction can sit in a copy of the session
                seen.add(key)
                rows.append(result)
    if not rows:
        sys.exit("No compactions found under %s" % args.sessions_dir)
    rows.sort(key=lambda r: r["time"])
    # A heading that shows up in only one or two summaries may be the person's own words,
    # so only headings shared by several summaries are written out or printed.
    counts = collections.Counter(t for r in rows for t in set(r["section_titles"].split(" | ")) if t)
    floor = 3 if len(rows) >= 6 else 2
    for r in rows:
        titles = [t for t in r["section_titles"].split(" | ") if t]
        r["section_titles"] = " | ".join(t for t in titles if counts[t] >= floor)
        r["other_headings"] = sum(1 for t in titles if counts[t] < floor)
    header = list(rows[0].keys())
    with open(args.out, "w", encoding="utf-8") as out:
        out.write("\t".join(header) + "\n")
        for row in rows:
            out.write("\t".join(str(row[k]) for k in header) + "\n")

    def share(part, whole):
        return "%d of %d" % (part, whole) + (" (%d%%)" % round(100 * part / whole) if whole else "")

    for kind in ("idle", "limit", "manual"):
        group = [r for r in rows if r["kind"] == kind]
        if not group:
            continue
        typed = sum(r["typed"] - r["typed_too_short"] for r in group)
        print("\n%s: %d compactions" % (kind, len(group)))
        print("  summary words: median %d" % statistics.median(r["summary_words"] for r in group))
        print("  typed since the last compaction, long enough to check: %d" % typed)
        print("    in the summary word for word: %s" % share(sum(r["typed_word_for_word"] for r in group), typed))
        print("    mostly there:                 %s" % share(sum(r["typed_mostly"] for r in group), typed))
        print("    absent as text:               %s" % share(sum(r["typed_absent"] for r in group), typed))
        older = sum(r["older_word_for_word"] + r["older_mostly"] + r["older_absent"] for r in group)
        if older:
            print("  typed before an earlier compaction: %d" % older)
            print("    word for word: %s; mostly: %s; absent as text: %s" % (
                share(sum(r["older_word_for_word"] for r in group), older),
                share(sum(r["older_mostly"] for r in group), older),
                share(sum(r["older_absent"] for r in group), older)))
        for label in ("edited", "read", "seen"):
            total = sum(r["paths_" + label] for r in group)
            print("  file names %-6s by name in the summary: %s" % (
                label, share(sum(r["paths_%s_in_summary" % label] for r in group), total)))
        print("  messages kept word for word after the summary: median %d" % statistics.median(
            r["kept_word_for_word_after"] for r in group))
        print("  things put back after the summary: median %d" % statistics.median(
            r["put_back_after"] for r in group))
        titles = collections.Counter(t for r in group for t in r["section_titles"].split(" | ") if t)
        print("  section titles (how many summaries have each): " + "; ".join(
            "%s %d" % kv for kv in titles.most_common(14)))
    print("\nWrote %s" % args.out)


if __name__ == "__main__":
    main()
