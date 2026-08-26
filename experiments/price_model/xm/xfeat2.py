"""v1 vs v2 extractor coverage, title-only (the only text all three marketplaces have)."""
import pandas as pd, sys, importlib.util
sys.path.insert(0,'.')
import mbfeat as v1
spec = importlib.util.spec_from_file_location('mbfeat2','xm/mbfeat2.py'); v2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v2)

df = pd.read_pickle('xm/raw.pkl')
empty = pd.Series(['']*len(df))
F = {}
F['v1_title'] = pd.DataFrame([v1.extract(n,'') for n in df.name.fillna('')])
F['v2_title'] = pd.DataFrame([v2.extract(n,'') for n in df.name.fillna('')])
desc = (df.short_description.fillna('') + ' ' + df.full_description.fillna('')).tolist()
F['v1_all'] = pd.DataFrame([v1.extract(n,d) for n,d in zip(df.name.fillna(''), desc)])
F['v2_all'] = pd.DataFrame([v2.extract(n,d) for n,d in zip(df.name.fillna(''), desc)])

FIELDS = ['chip_brand','year','screen','ram_gb','ssd_gb']
BOOLS  = ['warranty','new','defect','top_word','scratches']
rows=[]
for key,f in F.items():
    for m in ['bazos','sbazar','vinted']:
        mask = (df.marketplace==m).values
        sub = f[mask]
        mb = sub[sub.kind=='macbook']
        r = {'variant':key,'marketplace':m,'n':len(sub),'macbook':round((sub.kind=='macbook').mean(),3),
             'n_mb':len(mb)}
        for c in FIELDS: r[c]=round(mb[c].notna().mean(),3)
        for c in BOOLS:  r[c]=round(mb[c].mean(),3)
        r['all5'] = round((mb[FIELDS].notna().all(axis=1)).mean(),3)
        rows.append(r)
t = pd.DataFrame(rows)
pd.set_option('display.width',250)
print(t.pivot_table(index='marketplace',columns='variant',values=FIELDS+['all5','macbook'],sort=False).to_string())
print()
print(t.to_string(index=False))
for k,f in F.items(): f.to_pickle(f'xm/F_{k}.pkl')
