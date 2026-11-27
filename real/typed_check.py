#!/usr/bin/env python3
"""typed_check.py LIST DATA_DIR OUT.json : what do the 'typed' messages in these transcripts look like?
Groups them by how they start, so machine-written ones can be told from a person's."""
import json, os, re, sys, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_real as A
lst, root, out = sys.argv[1:4]
t0 = time.time(); heads = collections.Counter(); n = 0; lens = []; files = collections.Counter()
exact = collections.Counter()
for p in [x.strip() for x in open(lst) if x.strip()]:
    if time.time() - t0 > 140: print('time box hit at', p); break
    with open(os.path.join(root, p), 'rb') as fh:
        for raw in fh:
            if b'"type":"user"' not in raw and b'"type": "user"' not in raw: continue
            try: row = json.loads(raw)
            except Exception: continue
            if not A.is_typed(row): continue
            text = A.text_of((row.get('message') or {}).get('content')).strip()
            n += 1; lens.append(len(text)); files[p] += 1
            m = re.match(r'\s*(<[a-zA-Z_:-]+>|\[[^\]]{1,40}\]|#+ |/[a-z-]+|Base directory for this skill|Caveat:|This session is being continued|Stop hook|[A-Z][A-Z _-]{6,40}:)', text)
            heads[m.group(1) if m else ('plain: under 200 chars' if len(text) < 200 else 'plain: 200 to 2000' if len(text) < 2000 else 'plain: over 2000')] += 1
            exact[A.squash(text)[:80]] += 1
lens.sort()
res = {'typed': n, 'files': len(files), 'median_chars': lens[len(lens)//2] if lens else 0,
       'heads': heads.most_common(40), 'repeated_exact_openings': [(k, v) for k, v in exact.most_common(25) if v >= 15],
       'top_files': files.most_common(5)}
json.dump(res, open(out, 'w'), indent=1)
print(json.dumps(res, indent=1)[:6000])
