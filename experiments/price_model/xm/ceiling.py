"""Is the Vinted/Sbazar gap the extractor's fault, or is the information simply absent?
Recall is measured only on rows where the signal is visibly present in the title."""
import pandas as pd, re, sys, importlib.util
sys.path.insert(0,'.')
spec = importlib.util.spec_from_file_location('mbfeat2','xm/mbfeat2.py'); v2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v2)
df = pd.read_pickle('xm/raw.pkl')
f  = pd.read_pickle('xm/F_v2_title.pkl')
d = pd.concat([df.reset_index(drop=True), f.add_prefix('x_')], axis=1)
d = d[d.x_kind=='macbook'].copy()
d['t'] = d.name.fillna('').map(v2.norm)

probes = {
  'year':   (r'\b(200[6-9]|201\d|202[0-6])\b', 'x_year'),
  'screen': (r'\b1[1-7](\.\d)?\s*("|palc|inch|in\b|cal)', 'x_screen'),
  'capacity(any gb/tb)': (r'\d\s*(gb|tb)\b', None),
  'chip':   (r'\bm[1-9]\b|\bi[3579]\b|core ?2', 'x_chip_brand'),
}
rows=[]
for m in ['bazos','sbazar','vinted']:
    s = d[d.marketplace==m]
    r = {'marketplace':m, 'n_macbook':len(s), 'title_chars':round(s.name.str.len().mean())}
    for lab,(pat,col) in probes.items():
        present = s.t.str.contains(pat, regex=True)
        r[f'{lab} in title'] = round(present.mean(),3)
        if col:
            r[f'{lab} recall|present'] = round(s.loc[present, col].notna().mean(),3)
        else:
            got = s[['x_ram_gb','x_ssd_gb']].notna().any(axis=1)
            r[f'{lab} recall|present'] = round(got[present].mean(),3)
    rows.append(r)
pd.set_option('display.width',250)
print(pd.DataFrame(rows).set_index('marketplace').T.to_string())
