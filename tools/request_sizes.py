"""Read request sizes around /compact from Claude Code session transcripts.

Usage: python3 -I request_sizes.py <output csv> <label>=<transcript.jsonl> ...

A request's size is input_tokens + cache_creation_input_tokens +
cache_read_input_tokens of an assistant message. Each message is counted once.
"""
import csv
import json
import sys


def read(path):
    seen, events = set(), []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") == "system" and row.get("subtype") == "compact_boundary":
                meta = row.get("compactMetadata") or {}
                events.append(("boundary", meta.get("preTokens"), meta.get("postTokens"), meta.get("durationMs")))
            elif row.get("type") == "assistant":
                message = row.get("message") or {}
                usage = message.get("usage") or {}
                if not usage or message.get("id") in seen:
                    continue
                seen.add(message.get("id"))
                size = sum(usage.get(key) or 0 for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                events.append(("request", size))
    return events


def main():
    target = sys.argv[1]
    out = []
    for item in sys.argv[2:]:
        label, path = item.split("=", 1)
        events = read(path)
        requests = [e[1] for e in events if e[0] == "request"]
        at = next((i for i, e in enumerate(events) if e[0] == "boundary"), None)
        row = {"session": label, "first_request": requests[0] if requests else "", "requests": len(requests)}
        if at is not None:
            before = [e[1] for e in events[:at] if e[0] == "request"]
            after = [e[1] for e in events[at:] if e[0] == "request"]
            row.update({"last_request_before": before[-1], "first_request_after": after[0],
                        "pre_tokens": events[at][1], "post_tokens": events[at][2], "compaction_ms": events[at][3]})
        else:
            row.update({"last_request_before": "", "first_request_after": "", "pre_tokens": "", "post_tokens": "",
                        "compaction_ms": "", "all_requests": " ".join(str(r) for r in requests)})
        out.append(row)
    fields = ["session", "requests", "first_request", "last_request_before", "first_request_after", "pre_tokens", "post_tokens",
              "compaction_ms", "all_requests"]
    with open(target, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    for row in out:
        print({k: v for k, v in row.items() if v != ""})


if __name__ == "__main__":
    main()
