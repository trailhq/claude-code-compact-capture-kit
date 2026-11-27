#!/usr/bin/env python3
"""analyze_swechat.py LIST DATA_DIR OUT.jsonl : run analyze_real's text match on listed transcripts.
Time-boxed and resumable. Writes counts only."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_real
lst, root, out = sys.argv[1:4]
done = set()
if os.path.exists(out):
    for l in open(out):
        try: done.add(json.loads(l)["path"])
        except Exception: pass
paths = [p.strip() for p in open(lst) if p.strip() and p.strip() not in done]
t0 = time.time(); n = 0
with open(out, "a") as o:
    for p in paths:
        if time.time() - t0 > float(os.environ.get("SCAN_SECONDS", "140")): break
        try: rows = list(analyze_real.analyse(os.path.join(root, p), True)); err = ""
        except Exception as e: rows = []; err = "%s: %s" % (type(e).__name__, str(e)[:120])
        o.write(json.dumps({"path": p, "rows": rows, "error": err}) + "\n"); o.flush(); n += 1
print("did", n, "left", len(paths) - n)
