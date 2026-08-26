import pandas as pd, numpy as np, mbfeat
pd.set_option('display.width',220)
df = pd.read_csv('mb/macbook_ads.csv')
b = df[df.marketplace=='bazos'].copy()
feats = pd.DataFrame([mbfeat.extract(r['name'], r['short_description']) for _,r in b.iterrows()], index=b.index)
d = pd.concat([b[['id','name','price','view_count','publish_date','location','email_publisher_id','phone_publisher_id','short_description']], feats], axis=1)
d.to_pickle('mb/feat.pkl')

print("=== kind ==="); print(d['kind'].value_counts())
print("\n=== family (macbook only) ===")
mb = d[d.kind=='macbook']
print(mb['family'].value_counts())
print("\n=== extraction coverage on macbook rows (n=%d) ===" % len(mb))
for c in ['chip_brand','chip_gen','year','screen','ram_gb','ssd_gb','battery_pct','cycles']:
    print(f"  {c:13s} {mb[c].notna().mean()*100:5.1f}%")
print("\n=== chip ===")
print(mb.groupby(['chip_brand','chip_gen','chip_variant']).agg(n=('id','size'), med=('price','median')).sort_values('n',ascending=False).head(20))
print("\n=== ram ==="); print(mb.ram_gb.value_counts().sort_index())
print("\n=== ssd ==="); print(mb.ssd_gb.value_counts().sort_index())
print("\n=== screen ==="); print(mb.screen.value_counts().sort_index())
print("\n=== year ==="); print(mb.year.value_counts().sort_index())
