#!/usr/bin/env python3
"""slice.py TRANSCRIPT ROUND OUT.jsonl [--carry NEW_SESSION.jsonl] [--no-thinking]

Builds the transcript for one replay round from a real session that was compacted several times.
Round k ends where the original session's k-th compaction happened. The original summary is left out.
  round 1: the original records before the first compaction.
  round k: the replayed session so far (--carry: its transcript after round k-1, with today's
           summary and what Claude Code put back after it, without the model's reply to the trigger
           message) followed by the original records between compactions k-1 and k.
Only conversation records are kept (user, assistant, attachment, system). Prints the size facts
and writes nothing else."""
import json, sys, uuid as uuidlib

KEEP = ("user", "assistant", "attachment", "system")


def load(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def boundary(row):
    return row.get("type") == "system" and row.get("subtype") == "compact_boundary"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    carry = sys.argv[sys.argv.index("--carry") + 1] if "--carry" in sys.argv else None
    if carry:
        args.remove(carry)
    no_thinking = "--no-thinking" in sys.argv
    source, number, out = args[0], int(args[1]), args[2]
    rows = load(source)
    cuts = [i for i, row in enumerate(rows) if boundary(row)]
    if number > len(cuts):
        sys.exit("The session has only %d compactions." % len(cuts))
    start = 0 if number == 1 else cuts[number - 2] + 1
    piece = rows[start:cuts[number - 1]]
    if number > 1:
        # Leave out the original summary and what Claude Code put back after it; the replay has its own.
        while piece and (piece[0].get("isCompactSummary") or piece[0].get("type") == "attachment"):
            piece.pop(0)
    piece = [r for r in piece if r.get("type") in KEEP and not r.get("isSidechain") and r.get("uuid")]
    # A placeholder reply that Claude Code wrote itself (no tokens used) can end the stretch. Today's
    # Claude Code would read the session's size from it and see an empty session, so it is left out.
    def empty_reply(row):
        usage = (row.get("message") or {}).get("usage") or {}
        return row.get("type") == "assistant" and not any(
            int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
    replies = [i for i, row in enumerate(piece) if row.get("type") == "assistant"]
    real = [i for i in replies if not empty_reply(piece[i])]
    late = set(i for i in replies if real and i > real[-1])       # empty replies after the last real one
    dropped = len(late)
    piece = [row for i, row in enumerate(piece) if i not in late]
    # A session file can end with records that hang from an older message, not from the end of the
    # conversation (seen in one session: 47 attachment records under a message 236 records back).
    # A resumed session follows the chain back from the last record, so it would load that shorter
    # branch. Such trailing records are left out, so the file ends on the real conversation.
    where = {row["uuid"]: i for i, row in enumerate(piece)}
    talk = [i for i, row in enumerate(piece) if row.get("type") in ("user", "assistant")]
    stray = set()
    if talk:
        tip = talk[-1]
        for i in range(tip + 1, len(piece)):
            at = i
            while True:
                parent = where.get(piece[at].get("parentUuid"))
                if parent is None or parent == tip or parent in stray or at == parent:
                    if parent in stray:
                        stray.add(i)
                    break
                if parent < tip:
                    stray.add(i)
                    break
                at = parent
    side_branch_dropped = len(stray)
    piece = [row for i, row in enumerate(piece) if i not in stray]
    if no_thinking:
        for row in piece:
            content = (row.get("message") or {}).get("content")
            if row.get("type") == "assistant" and isinstance(content, list):
                row["message"]["content"] = [b for b in content if not (
                    isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking"))] or [
                    {"type": "text", "text": "(thinking)"}]
    head = []
    if carry:
        head = [r for r in load(carry) if r.get("type") in KEEP and r.get("uuid")]
        last_summary = max((i for i, r in enumerate(head) if r.get("isCompactSummary")), default=None)
        if last_summary is None:
            sys.exit("The carried session holds no summary.")
        # Keep what Claude Code put back after its summary. Drop the model's reply to the trigger
        # message and everything after it; the original records take its place in the chain.
        reply = next((i for i in range(last_summary + 1, len(head)) if head[i].get("type") == "assistant"), len(head))
        hook = head[reply]["parentUuid"] if reply < len(head) else head[-1]["uuid"]
        head = head[:reply]
        session = head[-1].get("sessionId")
        for row in piece:
            row["sessionId"] = session
        if piece:
            piece[0]["parentUuid"] = hook
    # A record whose parent was dropped hangs under the record before it.
    seen = {r["uuid"] for r in head}
    before = head[-1]["uuid"] if head else None
    for row in piece:
        if row.get("parentUuid") not in seen and row.get("parentUuid") is not None:
            row["parentUuid"] = before
        elif row.get("parentUuid") is None and before is not None and not boundary(row):
            row["parentUuid"] = before
        seen.add(row["uuid"])
        before = row["uuid"]
    with open(out, "w", encoding="utf-8") as handle:
        for row in head + piece:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = rows[cuts[number - 1]].get("compactMetadata") or {}
    typed = sum(1 for r in piece if r.get("type") == "user" and isinstance((r.get("message") or {}).get("content"), str))
    print(json.dumps({"round": number, "records": len(head) + len(piece), "carried": len(head), "new": len(piece),
                      "original_trigger": meta.get("trigger"), "original_pre_tokens": meta.get("preTokens"),
                      "user_text_records": typed, "last_type": (piece[-1].get("type") if piece else None),
                      "empty_replies_dropped": dropped, "side_branch_dropped": side_branch_dropped}))


if __name__ == "__main__":
    main()
