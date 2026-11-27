#!/bin/bash
# The full reading on 24 SWE-chat compactions.
set -u
R="$HOME/compact-capture-kit/real"
bash "$R/read.sh" swechat "$R/read-swechat.txt" "$HOME/compact-capture-kit/data/SWE-chat" --workers 3 --budget "${BUDGET_PUBLIC:-75}"
