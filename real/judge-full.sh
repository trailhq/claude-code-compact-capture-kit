#!/bin/bash
# The full meaning check on the 160 compacted SWE-chat transcripts. BUDGET caps this run's spend; POOL picks who pays.
exec bash "$HOME/compact-capture-kit/real/judge.sh" swechat "$HOME/compact-capture-kit/real/swe-chat-compacted.txt" "$HOME/compact-capture-kit/data/SWE-chat" \
  --workers 6 --budget "${BUDGET:-26}"
