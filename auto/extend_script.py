#!/usr/bin/env python3
"""extend_script.py ISSUES_DIR OUT_DIR [2]

Adds more real ripgrep work to a developer script that build_script.py wrote, for a session whose
tickets ran out before the context limit. The new tickets are public upstream work that came after
the benchmark's range (14.1.1 to 15.0.0): the code changes in the 15.1.0 and 15.2.0 changelog, then
a few behaviour changes committed after 15.2.0. Ticket text is copied from the saved GitHub records
in ISSUES_DIR (issue-N.json from the issues API, cmp.json from the compare API); nothing is retyped.

Messages already in developer.jsonl are left exactly as they are; the new ones go after them.
No developer notes ride on the new messages: all of them were given during the first tickets.

With 2 as a third argument it adds a second, smaller round (more commits from after 15.2.0), for a
session that is still short of the limit after the first round.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_script import ticket_turns, CLOSING

# (slug, kind, sources). kind "issues": one or more saved issue or pull-request records.
# kind "commit": the upstream commit message, plus a linked record when one is saved.
EXTRA = [
    ("line-buffering", "issues", [3194]),
    ("cursor-hyperlink-alias", "issues", [3192]),
    ("ignore-file-probing-cost", "issues", [3293]),
    ("git-config-env-vars", "issues", [3275]),
    ("jj-stat-only-when-needed", "issues", [3212]),
    ("gitignore-multiple-roots", "issues", [3376, 3320, 3419]),
    ("walker-deadlock-on-panic", "commit", ["0d7054d8"]),
    ("dotfiles-ending-in-dot", "commit", ["7155f640", 3564]),
    ("globset-basename-regexes", "commit", ["d19650f4"]),
    ("empty-absolute-parent-matchers", "commit", ["2d4fa851", 3557]),
    ("unreachable-ignore-files", "commit", ["435f59fc"]),
    ("globset-impossible-literal-lengths", "commit", ["1752fb78"]),
    ("pool-capacity", "commit", ["020687a7"]),
]
EXTRA2 = [
    ("custom-filters-max-filesize", "commit", ["178cc027"]),
    ("linked-worktree-excludes", "commit", ["65e072fa"]),
    ("incremental-ignore-checking", "commit", ["b621e65b"]),
    ("is-hidden-routine", "commit", ["6e527e92", "626b8951"]),
    ("scratch-pools-empty-matchers", "commit", ["c5e744cb"]),
    ("doc-windows-paths-utf8", "commit", ["4c2362d3"]),
    ("cargo-homepage-field", "commit", ["756a945f"]),
]
MORE2 = ("A few more upstream changes landed while we were working. Same ground rules. The specs are in "
         "tickets/, numbered from %d. As before, if our branch already behaves that way, show me the "
         "evidence and add a test instead of changing code.")
MORE = ("More work came in after all: the fixes that went into the next two upstream releases, and a few "
        "from after them. Same ground rules as before. The new specs are in tickets/, numbered from %d. "
        "Some of these may already hold on our branch; when one does, show me the evidence and add a test "
        "instead of changing code.")
TASK = ("Task: make our branch behave as this upstream report describes. First check whether it already "
        "does. If it does, show the evidence and add a regression test. If it does not, fix it and add a test.")


def record(issues_dir, number):
    with open(os.path.join(issues_dir, "issue-%d.json" % number), encoding="utf-8") as handle:
        data = json.load(handle)
    if "title" not in data:
        sys.exit("issue-%d.json is not a saved GitHub record" % number)
    return data


def main():
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] != "2"):
        sys.exit(__doc__)
    issues_dir, out_dir = sys.argv[1], sys.argv[2]
    second = len(sys.argv) == 4
    mark, last, extra_list, more = ("y", "x-close", EXTRA2, MORE2) if second else ("x", "close", EXTRA, MORE)
    script = os.path.join(out_dir, "developer.jsonl")
    with open(script, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    if any(row["id"] == mark + "-more" for row in rows):
        sys.exit("developer.jsonl already has this round; nothing changed")
    if rows[-1]["id"] != last:
        sys.exit("developer.jsonl does not end with %s; nothing changed" % last)
    with open(os.path.join(issues_dir, "cmp.json"), encoding="utf-8") as handle:
        commits = json.load(handle)["commits"]
    first = 1 + max(int(row["id"][1:3]) for row in rows if row["id"][0] == "t" and row["id"][1:3].isdigit())
    new = [(mark + "-more", more % first)]
    for number, (slug, kind, sources) in enumerate(extra_list, first):
        parts, title = [], None
        for source in sources:
            if isinstance(source, int):
                data = record(issues_dir, source)
                what = "pull request" if "pull_request" in data else "issue"
                title = title or data["title"]
                parts.append("## Upstream %s #%d: %s\n\nSource: %s\n\n%s\n" % (
                    what, source, data["title"], data["html_url"], (data.get("body") or "").strip()))
            else:
                found = [c for c in commits if c["sha"].startswith(source)]
                if len(found) != 1:
                    sys.exit("commit %s not found in cmp.json" % source)
                message = found[0]["commit"]["message"].strip()
                title = title or message.split("\n")[0]
                parts.append("## Upstream commit %s\n\nSource: %s\n\n%s\n" % (
                    source, found[0]["html_url"], message))
        name = "%02d-%s.md" % (number, slug)
        with open(os.path.join(out_dir, "tickets", name), "w", encoding="utf-8") as out:
            out.write("# %s\n\n%s\n\n%s" % (title, TASK, "\n".join(parts)))
        extra = "suite" if number % 3 == 0 else ("docs" if number % 3 == 2 else "")
        new += ticket_turns(number, title.replace("`", ""), name, extra)
    new.append((mark + "-suite", "That is everything. Run the whole test suite one last time and give me the numbers."))
    new.append((mark + "-close", CLOSING))
    with open(script, "a", encoding="utf-8") as out:
        for ident, text in new:
            out.write(json.dumps({"id": ident, "text": text}, ensure_ascii=False) + "\n")
    print("%d tickets added (%d to %d), %d messages added, %d in the script now" % (
        len(extra_list), first, first + len(extra_list) - 1, len(new), len(rows) + len(new)))


if __name__ == "__main__":
    main()
