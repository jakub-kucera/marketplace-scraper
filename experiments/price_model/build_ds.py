import pandas as pd, numpy as np, re, mbfeat

df = pd.read_csv('mb/macbook_ads.csv')
b = df[df.marketplace=='bazos'].copy()
feats = pd.DataFrame([mbfeat.extract(r['name'], r['short_description']) for _,r in b.iterrows()], index=b.index)
d = pd.concat([b.reset_index(drop=True), feats.reset_index(drop=True)], axis=1)
d = d[d.kind=='macbook'].copy()

d['created'] = pd.to_datetime(d.created, utc=True)
d['publish_date'] = pd.to_datetime(d.publish_date, utc=True, errors='coerce')
d['log_price'] = np.log(d.price)

# seller size = how many ads this email publisher posted in the corpus (dealer proxy)
cnt = d.groupby('email_publisher_id').id.transform('size')
d['seller_ads'] = cnt.fillna(1)
d['is_dealer'] = (d.seller_ads >= 10) | d.vat_dph

# region from "Praha 10, 108 00" -> "Praha"
def region(loc):
    if not isinstance(loc,str): return 'unknown'
    town = loc.split(',')[0].strip()
    town = re.sub(r'\s*\d+$','',town)
    return town
d['town'] = d.location.map(region)
top_towns = d.town.value_counts().head(15).index
d['town_g'] = np.where(d.town.isin(top_towns), d.town, 'other')

d['dow'] = d.created.dt.dayofweek
d['week'] = d.created.dt.isocalendar().week.astype(int)
d['days'] = (d.created - d.created.min()).dt.days

# chip encoded as ordered capability tiers
d['chip_key'] = np.where(d.chip_brand.isna(), 'unknown',
                  d.chip_brand.astype(str) + d.chip_gen.astype('Int64').astype(str) + '_' + d.chip_variant.astype(str))
d['storage_log'] = np.log(d.ssd_gb.astype(float))
d['ram_log'] = np.log(d.ram_gb.astype(float))
d['age'] = 2026 - d.year

# dedup key for grouped CV: same seller + same title = the same physical listing relisted
d['dupkey'] = d.email_publisher_id.astype(str) + '||' + d.name.str.lower().str.strip()
d.to_pickle('mb/ds.pkl')
print(d.shape)
print("unique dupkeys:", d.dupkey.nunique(), " unique sellers:", d.email_publisher_id.nunique())
print("dealer share: %.1f%%" % (d.is_dealer.mean()*100))
print(d[['price','year','ram_gb','ssd_gb','screen','seller_ads']].describe().round(1))
