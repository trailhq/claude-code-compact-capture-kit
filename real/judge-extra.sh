#!/bin/bash
# Two extra runs of the meaning check on public SWE-chat data, on the subscription:
#  second: a different model (Sonnet 5.5) judges a sample of 50 compactions, to compare with the first judge
#  queued: the messages people typed while Claude was working, which the first run did not see
set -u
R="$HOME/compact-capture-kit/real"; D="$HOME/compact-capture-kit/data/SWE-chat"
export POOL=plan
bash "$R/judge.sh" second "$R/second-judge.txt" "$D" --workers 5 --budget 12 --model claude-sonnet-5-5
bash "$R/judge.sh" queued "$R/swe-chat-compacted.txt" "$D" --workers 5 --budget 25 --queued
