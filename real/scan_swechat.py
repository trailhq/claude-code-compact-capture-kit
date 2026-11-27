#!/usr/bin/env python3
"""scan_swechat.py LIST DATA_DIR OUT.tsv : find compaction records in the listed transcripts.
Writes counts and metadata only, never message text. Resumes: files already in OUT are skipped."""
import json, os, sys, time
lst, root, out = sys.argv[1], sys.argv[2], sys.argv[3]
done = set()
if os.path.exists(out):
    for l in open(out):
        done.add(l.split('\t')[0])
paths = [p.strip() for p in open(lst) if p.strip()]
t0 = time.time()
with open(out, 'a') as o:
    if not done:
        o.write('path\tkind\tline\ttimestamp\tversion\ttrigger\tpre_tokens\tpost_tokens\tduration_ms\tprecomputed\tsummary_words\tfile_lines\tfile_mb\n')
    for p in paths:
        if p in done: continue
        if time.time() - t0 > float(os.environ.get('SCAN_SECONDS', '150')): break
        f = os.path.join(root, p); n = 0; rows = []; want_summary = None
        try:
            with open(f, 'rb') as fh:
                for raw in fh:
                    n += 1
                    hit = b'compact_boundary' in raw or b'isCompactSummary' in raw
                    if not hit: continue
                    try: d = json.loads(raw)
                    except Exception: continue
                    if d.get('type') == 'system' and d.get('subtype') == 'compact_boundary':
                        m = d.get('compactMetadata') or d.get('compact_metadata') or {}
                        rows.append([p, 'boundary', n, d.get('timestamp', ''), d.get('version', ''), m.get('trigger', ''),
                                     m.get('preTokens', m.get('pre_tokens', '')), m.get('postTokens', m.get('post_tokens', '')),
                                     m.get('durationMs', m.get('duration_ms', '')), m.get('precomputed', ''), ''])
                    elif d.get('isCompactSummary') and rows and rows[-1][-1] == '':
                        c = (d.get('message') or {}).get('content')
                        if isinstance(c, list): c = ' '.join(x.get('text', '') for x in c if isinstance(x, dict))
                        rows[-1][-1] = len((c or '').split())
        except Exception as e:
            rows = [[p, 'error', 0, '', '', type(e).__name__, '', '', '', '', '']]
        mb = round(os.path.getsize(f) / 1e6, 1) if os.path.exists(f) else 0
        if not rows: rows = [[p, 'none', 0, '', '', '', '', '', '', '', '']]
        for r in rows: o.write('\t'.join(str(x) for x in r + [n, mb]) + '\n')
        o.flush()
left = len([p for p in paths if p not in done]) 
print('scanned this call; files in list', len(paths))
