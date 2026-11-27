#!/bin/bash
# fetch_swechat.sh LIST : download the SWE-chat transcripts named in LIST (one path per line).
# Needs the Hugging Face CLI, logged in, with the dataset's conditions accepted.
set -u
LIST="${1:?give the list file}"
DEST="$HOME/compact-capture-kit/data/SWE-chat"
if command -v hf > /dev/null 2>&1; then HF=(hf download); else HF=(huggingface-cli download); fi
total=$(grep -c . "$LIST"); echo "asking for $total files into $DEST"
grep . "$LIST" | xargs -n 40 "${HF[@]}" SALT-NLP/SWE-chat --repo-type dataset --local-dir "$DEST" > "$DEST/fetch.log" 2>&1
have=0; while read -r p; do [ -s "$DEST/$p" ] && have=$((have+1)); done < <(grep . "$LIST")
echo "done: $have of $total files present, $(du -shc "$DEST"/transcripts* 2>/dev/null | tail -1 | cut -f1) on disk"
[ "$have" = "$total" ] || echo "some files are missing; see $DEST/fetch.log"
