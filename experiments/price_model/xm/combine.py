"""Build the pooled cross-marketplace MacBook dataset with price put on one basis."""
import pandas as pd, numpy as np, sys, importlib.util
sys.path.insert(0,'.')
spec = importlib.util.spec_from_file_location('mbfeat2','xm/mbfeat2.py'); v2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v2)

df = pd.read_pickle('xm/raw.pkl')
desc = (df.short_description.fillna('') + ' ' + df.full_description.fillna('')).tolist()
f = pd.DataFrame([v2.extract(n, d) for n, d in zip(df.name.fillna(''), desc)])
d = pd.concat([df.reset_index(drop=True), f], axis=1)
d = d[(d.kind == 'macbook') & d.price.notna()].copy()

# --- price on ONE basis: what the seller asks, no platform fee ------------------------
# Vinted stores total_item_price = seller_ask*1.05 + 18 (measured live 2026-08-26, n=96,
# max residual 0.005 CZK). Bazos and Sbazar store the seller's ask directly.
d['ask'] = np.where(d.marketplace == 'vinted', (d.price - 18) / 1.05, d.price)
d['log_ask'] = np.log(d.ask)

d['created'] = pd.to_datetime(d.created, utc=True)
d['chip_key'] = np.where(d.chip_brand.isna(), 'unknown',
                         d.chip_brand.astype(str) + d.chip_gen.astype('Int64').astype(str)
                         + '_' + d.chip_variant.astype(str))
d['spec'] = (d.family + '|' + d.chip_key + '|' + d.ram_gb.astype('Int64').astype(str)
             + '|' + d.ssd_gb.astype('Int64').astype(str) + '|' + d.screen.astype(str))
d['spec_ok'] = d[['chip_brand','ram_gb','ssd_gb','screen']].notna().all(axis=1) & (d.family != 'na')
d.to_pickle('xm/pool.pkl')

print("rows with usable price:", d.groupby('marketplace').size().to_dict())
print("\nfull-spec rows:", d[d.spec_ok].groupby('marketplace').size().to_dict())
print("\n--- raw median ask (CZK), no controls ---")
print(d.groupby('marketplace').ask.agg(n='size', median='median', mean='mean').round(0).to_string())

# The three queries do NOT share a price floor -> the raw medians are not comparable.
print("\n--- query price floors (bazos 5000 / vinted 2000 / sbazar 10000) ---")
for lo, hi in [(10000, 100000)]:
    w = d[(d.ask >= lo) & (d.ask <= hi)]
    print(f"common window {lo}-{hi}:")
    print(w.groupby('marketplace').ask.agg(n='size', median='median', mean='mean').round(0).to_string())

# Time window: Vinted/Sbazar only exist from 2026-08-23.
cut = pd.Timestamp('2026-08-23', tz='UTC')
print("\n--- same 3-day window, common price band ---")
w = d[(d.created >= cut) & (d.ask >= 10000) & (d.ask <= 100000)]
print(w.groupby('marketplace').ask.agg(n='size', median='median', mean='mean').round(0).to_string())
