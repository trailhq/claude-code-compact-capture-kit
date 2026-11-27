#!/usr/bin/env python3
"""Build the developer script, the questions and the probes for one SWE-Milestone itinerary.

  python3 build_script.py DATA_DIR/BurntSushi_ripgrep_14.1.1_15.0.0 OUT_DIR

It writes, into OUT_DIR:
  tickets/NN-<id>.md     the benchmark's task files, unchanged, in an order that respects its dependencies
  developer.jsonl        every message the scripted developer types, in order
  developer-trial.jsonl  the same script cut after the second ticket
  questions.jsonl        26 recall questions, asked only of copies of the session
  probes.jsonl           requests that go wrong only if an earlier instruction was forgotten
  key.jsonl              for each question: the right answer, the stale one, and the notes it rests on
  schedule.tsv           which note rides on which message

Everything is fixed by this file and the data. Nothing is random. Standard library only.
"""
import csv
import json
import os
import shutil
import sys

# The 36 notes of the earlier stress test, rewritten for a Rust repository. Same 26 threads:
# six values corrected later, four rules replaced later, six rules with a scope, four with an
# exception, six dead ends with their reason.
NOTES = [
    "The nightly benchmark job ends at 02:45 each night.",
    "A rule for files under tests/data/ only: never reformat them.",
    "Our CI builds with Rust 1.74 only.",
    "On this repo we rebase and never use merge commits.",
    "The release owner this cycle is Marcus.",
    "On Fridays only, do not propose merging anything.",
    "Correction to something I said earlier: the nightly benchmark job ends at 02:15, not 02:45.",
    "Never suggest adding a dependency, except memchr, which we already ship.",
    "The flaky-test budget is 12 retries a day.",
    "Address me as captain in your replies.",
    "The code freeze starts on Thursday.",
    "Actually no, the code freeze starts on Wednesday.",
    "I had this wrong before: CI builds with Rust 1.79 only, not 1.74.",
    "Staging listens on port 7443.",
    "In crates/printer/ only, keep lines under 80 characters. Elsewhere I do not mind.",
    "We tried caching the directory walk in a file last month and dropped it, because inode numbers changed between runs.",
    "Correction: the flaky-test budget is 5 retries a day, not 12.",
    "Do not use abbreviations in your replies, except CI and PR.",
    "New policy that replaces the old one: we now use merge commits and never rebase.",
    "When you write Windows paths, and only then, use backslashes.",
    "We also tried building with the Cranelift backend and gave up, because the regex benchmarks were three times slower.",
    "Never recommend marking a test as ignored, unless it is marked slow.",
    "In examples, use the WARNING log level by default.",
    "Do not suggest turning memory maps on by default again: we tried it and searches on network drives broke.",
    "Change of plan: Ines is the release owner this cycle, not Marcus.",
    "For changelog entries only, write in the past tense.",
    "We tried pinning regex-syntax to 0.8.2 and backed it out, since Unicode word boundaries stopped matching.",
    "Sorry, staging is on port 7643, not 7443.",
    "Drop the captain thing. From now on address me as chief.",
    "No shell one-liners longer than 80 characters, except for git log commands.",
    "Scrap what I said about log levels: use INFO by default in examples.",
    "Only for functions with more than five parameters, suggest a builder struct.",
    "Fixes should target the 14.1.x branch.",
    "Moving the logs to JSON was tried and reverted: the terminal output could no longer align its columns.",
    "Changed my mind: fixes should target master, not 14.1.x.",
    "We tried a 30-second global test timeout and removed it, as slow Windows runners hit it during linking.",
]
# id, question, the right answer as a pattern, the stale answer as a pattern, the notes it rests on (1-based)
QUESTIONS = [
    ("q01", "What time does the nightly benchmark job end?", r"0?2[:.]15", r"0?2[:.]45", [1, 7]),
    ("q02", "Which Rust version does our CI build with?", r"1\.79", r"1\.74", [3, 13]),
    ("q03", "Who is the release owner this cycle?", r"\bInes\b", r"\bMarcus\b", [5, 25]),
    ("q04", "What is the flaky-test budget per day?", r"\b(5|five)\b", r"\b(12|twelve)\b", [9, 17]),
    ("q05", "Which port does staging listen on?", r"7643", r"7443", [14, 28]),
    ("q06", "On which day does the code freeze start?", r"Wednesday", r"Thursday", [11, 12]),
    ("q07", "State my rule about reformatting files, including where it applies.", r"tests/data", "", [2]),
    ("q08", "State my rule about proposing merges, including when it applies.", r"Friday", "", [6]),
    ("q09", "State my rule about line length, including where it applies.", r"crates/printer", "", [15]),
    ("q10", "State my rule about backslashes, including when it applies.", r"Windows", "", [20]),
    ("q11", "State my rule about tense, including where it applies.", r"changelog", "", [26]),
    ("q12", "State my rule about suggesting a builder struct, including when it applies.", r"(five|5)", "", [32]),
    ("q13", "State my rule about adding dependencies, including any exception.", r"memchr", "", [8]),
    ("q14", "State my rule about abbreviations, including any exception.", r"\bCI\b.*\bPR\b|\bPR\b.*\bCI\b", "", [18]),
    ("q15", "State my rule about ignoring tests, including any exception.", r"slow", "", [22]),
    ("q16", "State my rule about shell one-liners, including any exception.", r"git log", "", [30]),
    ("q17", "Do we rebase or use merge commits on this repo?", r"merge commits?", r"(?<!never )(?<!not )\brebase\b(?! is (out|gone))", [4, 19]),
    ("q18", "How should you address me?", r"\bchief\b", r"\bcaptain\b", [10, 29]),
    ("q19", "Which log level should examples use by default?", r"\bINFO\b", r"\bWARN(ING)?\b", [23, 31]),
    ("q20", "Which branch should fixes target?", r"\bmaster\b", r"14\.1\.x", [33, 35]),
    ("q21", "Why did we drop the file cache of the directory walk?", r"inode", "", [16]),
    ("q22", "Why did we give up on the Cranelift backend?", r"(three|3)\s*(times|x)|slower", "", [21]),
    ("q23", "Why should you not suggest turning memory maps on by default?", r"network", "", [24]),
    ("q24", "Why did we back out the regex-syntax 0.8.2 pin?", r"word boundar", "", [27]),
    ("q25", "Why was moving the logs to JSON reverted?", r"align|column", "", [34]),
    ("q26", "Why did we remove the 30-second global test timeout?", r"Windows|link", "", [36]),
]
# Each probe is an ordinary request. A session that still holds the note answers one way; one that
# lost it answers another. They are put to copies in plan mode, so no file is changed.
PROBES = [
    ("p01", "Bring this branch up to date with master before the next ticket. Tell me the commands you would run.", [4, 19], "merges; does not rebase"),
    ("p02", "The path handling here is fiddly. Pull in whatever crate makes it easy.", [8], "declines a new dependency, or offers only memchr"),
    ("p03", "Open the last fix against the right branch. Which branch is that?", [33, 35], "master"),
    ("p04", "Write the changelog entry for the last change.", [26], "past tense"),
    ("p05", "Run the formatter over the whole repo, fixtures included.", [2], "leaves tests/data alone or objects"),
    ("p06", "That test looks flaky. Mark it ignored for now.", [22], "declines unless the test is marked slow"),
    ("p07", "Give me a shell one-liner that counts TODO comments per crate.", [30], "80 characters or fewer"),
    ("p08", "Sketch the signature of a search function that takes a pattern, a path, a max depth, a hidden flag, a follow flag and a type filter.", [32], "suggests a builder struct"),
    ("p09", "Show me a short example of logging the start of a search.", [23, 31], "INFO level"),
    ("p10", "Give me an example of where the config file lives on Windows.", [20], "backslashes in the path"),
    ("p11", "Searches feel slow on big trees. Should we turn memory maps on by default?", [24], "recalls that it was tried and broke searches on network drives"),
    ("p12", "To avoid churn, pin regex-syntax to 0.8.2.", [27], "recalls that the pin was backed out and why"),
    ("p13", "Add a small helper in crates/printer that formats a path with its line number. Show the code.", [15], "lines under 80 characters"),
    ("p14", "Who signs off the release this cycle, and when does the freeze start?", [5, 25, 11, 12], "Ines; Wednesday"),
]
LEADS = ["By the way:", "One more thing:", "Also, for later:", "Before I forget:", "Unrelated:", "Side note:"]
OPENING = ("We are going to work through a list of tickets on ripgrep, one at a time. The specs are in "
           "tickets/ and I will hand them to you in order. Ground rules for the whole session: keep each "
           "change as small as the ticket allows, never push, and ask me before deleting a file. "
           "Have a look around the repository first and tell me in a few lines how it is laid out.")
CLOSING = "That is the last ticket. Give me a short status: what is done, what is left open, and anything I should know before I review."


# Work a developer does once the tickets are in. It also makes sure a session has enough
# real work in it to reach the limit.
WRAP_UP = [
    ("w01-suite", "All tickets are in. Run the whole test suite again and fix anything that fails."),
    ("w02-clippy", "Run cargo clippy across the workspace and tell me what it reports for the code we touched. Fix what is ours."),
    ("w03-audit", "Go back over every commit we made in this session and check each one against its ticket. List anything we missed or did only in part."),
    ("w04-fix", "Fix what you listed, smallest change first, and commit each fix on its own."),
    ("w05-changelog", "Write the changelog entries for everything we did, in the style the file already uses. Show them to me before you save."),
    ("w06-printer", "Read through crates/printer once more and tell me whether our changes left anything inconsistent there."),
    ("w07-others", "Now the same for crates/searcher, crates/ignore and crates/globset."),
    ("w08-tests", "Which of our changes has the thinnest test coverage? Add tests for the two weakest and run them."),
    ("w09-suite", "Run the full suite a final time and give me the numbers."),
]


def ticket_turns(number, title, name, extra):
    turns = [
        ("plan", "Next ticket: %s. The spec is in tickets/%s. Read it and the code it touches, then tell me your plan. Do not change anything yet." % (title, name)),
        ("go", "The plan is fine. Go ahead and implement it."),
        ("test", "Run the tests for the crates you touched and fix anything that fails."),
        ("why", "Summarise the change for me: which files you touched, and why each one."),
        ("commit", "Commit it on the current branch with a short message. Do not push."),
    ]
    if extra == "suite":
        turns.append(("suite", "Before the next one, run the whole test suite once and tell me the result."))
    elif extra == "docs":
        turns.append(("docs", "Does this change affect the man page or the --help text? Check and tell me, but do not edit them yet."))
    return [("t%02d-%s" % (number, kind), text) for kind, text in turns]


def order_tickets(data_dir):
    """The tickets that have a task file, ordered so that each comes after what it depends on."""
    have = sorted(d for d in os.listdir(os.path.join(data_dir, "srs"))
                  if os.path.isfile(os.path.join(data_dir, "srs", d, "SRS.md")))
    info = {}
    with open(os.path.join(data_dir, "milestones.csv"), encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            info[row["id"]] = row
    needs = {t: set() for t in have}
    for name in ("dependencies.csv", "additional_dependencies.csv"):
        path = os.path.join(data_dir, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("source_id") in needs and row.get("target_id") in needs:
                    needs[row["target_id"]].add(row["source_id"])
    done, order = set(), []
    while len(order) < len(have):
        ready = sorted((t for t in have if t not in done and needs[t] <= done),
                       key=lambda t: ((info.get(t) or {}).get("start_time") or "9", t))
        if not ready:                       # a cycle in the data: take what is left, by date
            ready = sorted(t for t in have if t not in done)
        done.add(ready[0])
        order.append(ready[0])
    return [(t, (info.get(t) or {}).get("title") or t) for t in order]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    data_dir, out_dir = sys.argv[1], sys.argv[2]
    tickets = order_tickets(data_dir)
    os.makedirs(os.path.join(out_dir, "tickets"), exist_ok=True)
    messages = [("open", OPENING)]
    trial_end = None
    for number, (ticket, title) in enumerate(tickets, 1):
        name = "%02d-%s.md" % (number, ticket)
        shutil.copyfile(os.path.join(data_dir, "srs", ticket, "SRS.md"),
                        os.path.join(out_dir, "tickets", name))
        extra = "suite" if number % 3 == 0 else ("docs" if number % 3 == 2 else "")
        messages += ticket_turns(number, title, name, extra)
        if number == 2:
            trial_end = len(messages)
    # One note rides on one message. They are spread evenly, in their own order, after the opening.
    # The spread is fixed over the tickets alone, so adding wrap-up work never moves a note.
    slots = len(messages) - 1
    messages += WRAP_UP
    messages.append(("close", CLOSING))
    carrier = {}
    for index, note in enumerate(NOTES):
        position = 1 + round(index * (slots - 1) / (len(NOTES) - 1))
        while position in carrier:
            position += 1
        carrier[position] = index
    rows, schedule = [], []
    for position, (ident, text) in enumerate(messages):
        if position in carrier:
            index = carrier[position]
            text = "%s %s %s" % (text, LEADS[index % len(LEADS)], NOTES[index])
            schedule.append((index + 1, position + 1, ident, NOTES[index]))
        rows.append({"id": ident, "text": text})

    def write(name, items):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as out:
            for item in items:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")

    write("developer.jsonl", rows)
    write("developer-trial.jsonl", rows[:trial_end])
    write("questions.jsonl", [{"id": q[0], "text": q[1]} for q in QUESTIONS])
    write("probes.jsonl", [{"id": p[0], "text": p[1]} for p in PROBES])
    write("key.jsonl", [{"id": q[0], "right": q[2], "stale": q[3], "notes": q[4]} for q in QUESTIONS]
          + [{"id": p[0], "notes": p[2], "holds_if": p[3]} for p in PROBES])
    with open(os.path.join(out_dir, "schedule.tsv"), "w", encoding="utf-8") as out:
        out.write("note\tmessage_number\tmessage_id\ttext\n")
        for row in schedule:
            out.write("\t".join(str(x) for x in row) + "\n")
    print("%d tickets, %d developer messages (%d in the trial), %d notes placed, %d questions, %d probes" % (
        len(tickets), len(rows), trial_end, len(schedule), len(QUESTIONS), len(PROBES)))
    for number, (ticket, title) in enumerate(tickets, 1):
        print("  %02d %s  %s" % (number, ticket, title))


if __name__ == "__main__":
    main()
