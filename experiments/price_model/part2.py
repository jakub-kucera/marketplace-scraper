"""Idea 2: multi-score comparison of the big sellers, benchmarked leave-seller-out."""
import numpy as np, pandas as pd, re, mbfeat, seller_base, harness as H
from sklearn.model_selection import GroupKFold

d = seller_base.load()
X, ci = H.build_X(d)
y = d.log_price.values

# leave-one-seller-out market price: a seller's benchmark never includes their own ads
oof = np.full(len(d), np.nan)
for tr, te in GroupKFold(6).split(X, y, groups=d.seller):
    m = H.mk(ci); m.fit(X.iloc[tr], y[tr]); oof[te] = m.predict(X.iloc[te])
d['mkt_log'] = oof
d['mkt'] = np.exp(oof)
d['resid'] = d.log_price - d.mkt_log

DMG = re.compile(r'nefunk|praskl|prakl|rozbit|rozibt|ko lcd|poskozen|vadn|\bvada\b|na dily|nejde|'
                 r'nezapin|zatopen|polit|rozlit|nekompletni', re.I)
d['txt'] = (d.name.fillna('')+' '+d.short_description.fillna('')).map(mbfeat.strip_diacritics)
d['damaged'] = d.txt.str.contains(DMG)
d['spec_ok'] = d.year.notna()&(d.chip_key!='unknown')&d.ram_gb.notna()&d.ssd_gb.notna()
d['discloses'] = d.warranty | d.battery_pct.notna() | d.cycles.notna()
d['relisted'] = d.duplicated(subset=['seller','name'], keep=False)
d.to_pickle('mb/p2.pkl')

big = d[d.seller_total >= 25].copy()
rows = []
for s, g in big.groupby('seller'):
    n = len(g)
    rows.append(dict(
        seller=s, n=n,
        price_level=g.resid.mean()*100,            # % vs market (log approx)
        consistency=g.resid.std(),
        med_price=g.price.median(),
        med_year=g.year.median(),
        apple_pct=(g.chip_brand=='apple').mean()*100,
        spec_pct=g.spec_ok.mean()*100,
        disclose_pct=g.discloses.mean()*100,
        damaged_pct=g.damaged.mean()*100,
        relist_pct=g.relisted.mean()*100,
        configs=g.cfg.nunique() if 'cfg' in g else g.chip_key.nunique(),
        cheap_tail=(g.resid < g.resid.mean()-2*g.resid.std()).mean()*100,
    ))
S = pd.DataFrame(rows).set_index('seller').sort_values('price_level')
pd.set_option('display.width', 250)
print("=== BIG SELLERS (>=25 ads), benchmarked against a model that never saw them ===\n")
print(S.round(1).to_string())

print("\n\n=== READING THE SCORES ===")
print("price_level  : mean %% vs leave-seller-out market price. negative = systematically cheap")
print("consistency  : sd of residual. LOW = disciplined/formulaic pricing, HIGH = erratic (or varied stock)")
print("spec_pct     : %% of listings where year+chip+RAM+SSD all parse -> how well they describe stock")
print("disclose_pct : %% mentioning warranty / battery health / cycles")
print("cheap_tail   : %% of their own ads >2sd below their OWN mean -> do they ever discount?")

# composite: a sourcing score (buy-from-them attractiveness)
z = lambda c, invert=False: ((S[c]-S[c].mean())/S[c].std()) * (-1 if invert else 1)
S['SOURCING'] = (z('price_level', invert=True)*2.0     # cheap matters most
                 + z('spec_pct')*0.8                    # describable stock = scorable
                 + z('disclose_pct')*0.5
                 + z('damaged_pct', invert=True)*0.5
                 + z('cheap_tail')*0.7)                 # do they run real markdowns
print("\n\n=== COMPOSITE SOURCING SCORE (weights are a judgement call, stated not hidden) ===")
out = S[['n','price_level','consistency','spec_pct','disclose_pct','damaged_pct','cheap_tail','med_price','apple_pct','SOURCING']]
print(out.sort_values('SOURCING', ascending=False).round(1).to_string())
