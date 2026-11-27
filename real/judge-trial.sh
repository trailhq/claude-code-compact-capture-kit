#!/bin/bash
# The three-compaction trial of the meaning check: one at the 1M limit, one at the 200K limit, one manual.
exec bash "$HOME/compact-capture-kit/real/judge.sh" trial "$HOME/compact-capture-kit/real/swe-chat-trial3.txt" "$HOME/compact-capture-kit/data/SWE-chat" \
  --workers 3 --only "transcripts1/0d4c4262-2100-4779-8745-e855e0a78208.jsonl#2,transcripts1/2cae28a4-28e8-4bfa-9225-7682543f3664.jsonl#1,transcripts/1965f49a-6bb1-4b13-95f6-52f27fa5ae35.jsonl#1"
