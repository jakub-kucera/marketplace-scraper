"""Run the Bazos-built extractor (mbfeat) on all three marketplaces, title-only and full-text."""
import pandas as pd, numpy as np, sys
sys.path.insert(0, '.')
import mbfeat

df = pd.read_csv('xm/mb3.csv')
df['short_description'] = df.short_description.fillna('')
df['full_description'] = df.full_description.fillna('')
df['text_all'] = (df.name.fillna('') + ' || ' + df.short_description + ' || ' + df.full_description)

def featurise(names, descs):
    return pd.DataFrame([mbfeat.extract(n, d) for n, d in zip(names, descs)])

title_only = featurise(df.name.fillna(''), pd.Series(['']*len(df)))
full_text  = featurise(df.name.fillna(''), df.short_description + ' ' + df.full_description)

FIELDS = ['chip_brand','chip_gen','chip_variant','year','screen','ram_gb','ssd_gb']
def cov(f, mask):
    sub = f[mask.values]
    out = {'n': len(sub)}
    out['kind=macbook'] = (sub.kind=='macbook').mean()
    out['family known'] = (~sub.family.isin(['na','macbook_unspec'])).mean()
    for c in ['chip_brand','year','screen','ram_gb','ssd_gb']:
        out[c] = sub[c].notna().mean()
    for c in ['warranty','new','defect','battery_pct','cycles','top_word','scratches','box','cz_kbd']:
        v = sub[c]
        out[c] = v.notna().mean() if c in ('battery_pct','cycles') else v.mean()
    return out

rows = []
for m in ['bazos','sbazar','vinted']:
    mask = df.marketplace==m
    r = cov(title_only, mask); r['marketplace']=m; r['text']='title only'; rows.append(r)
    r = cov(full_text, mask);  r['marketplace']=m; r['text']='title+desc'; rows.append(r)
t = pd.DataFrame(rows).set_index(['marketplace','text'])
pd.set_option('display.width', 250); pd.set_option('display.float_format', lambda x: f'{x:.2f}')
print(t.to_string())

df.to_pickle('xm/raw.pkl'); title_only.to_pickle('xm/f_title.pkl'); full_text.to_pickle('xm/f_full.pkl')
