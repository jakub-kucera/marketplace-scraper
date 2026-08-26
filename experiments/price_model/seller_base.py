"""Seller identity + time-causal history. Shared foundation for the three analyses."""
import pandas as pd, numpy as np

def load():
    d = pd.read_pickle('mb/ds.pkl').copy()
    d['created'] = pd.to_datetime(d.created, utc=True)
    d = d.sort_values('created').reset_index(drop=True)

    # --- seller key: email id, else phone id, else a per-row unique (never merged) ---
    key = pd.Series(index=d.index, dtype=object)
    has_e = d.email_publisher_id.notna()
    key[has_e] = 'e' + d.loc[has_e, 'email_publisher_id'].astype(int).astype(str)
    has_p = ~has_e & d.phone_publisher_id.notna()
    key[has_p] = 'p' + d.loc[has_p, 'phone_publisher_id'].astype(int).astype(str)
    rest = key.isna()
    key[rest] = ['x%d' % i for i in d.index[rest]]
    d['seller'] = key

    # --- TIME-CAUSAL history: what was knowable when this ad appeared ---
    d['prior_ads'] = d.groupby('seller').cumcount()          # ads from this seller seen BEFORE
    d['is_new_seller'] = d.prior_ads == 0

    # full-corpus size, for descriptive tiering only (explicitly not a model feature)
    d['seller_total'] = d.groupby('seller').id.transform('size')
    d['tier'] = pd.cut(d.seller_total, [0, 2, 9, 49, 10**6],
                       labels=['private (1-2)', 'small (3-9)', 'medium (10-49)', 'large (50+)'])
    return d

if __name__ == '__main__':
    d = load()
    print("=== SELLER KEY ===")
    print(f"rows {len(d)}, sellers {d.seller.nunique()}, "
          f"email-keyed {d.seller.str.startswith('e').sum()}, phone-keyed {d.seller.str.startswith('p').sum()}, "
          f"unkeyed {d.seller.str.startswith('x').sum()}")
    print("\n=== TIERS (full-corpus size) ===")
    t = d.groupby('tier', observed=True).agg(ads=('id','size'), sellers=('seller','nunique'),
        med_price=('price','median'), dph=('vat_dph','mean'), warr=('warranty','mean'),
        apple=('chip_brand', lambda s: (s=='apple').mean()))
    t['ads_pct'] = (t.ads/len(d)*100).round(1)
    print(t.round(3).to_string())
    print("\n=== TIME-CAUSAL: how often is the seller unknown at scoring time? ===")
    print(f"  ads whose seller had NO prior ad: {d.is_new_seller.sum()} ({d.is_new_seller.mean()*100:.1f}%)")
    for lo,hi,lab in [(0,0,'0 prior'),(1,2,'1-2 prior'),(3,9,'3-9 prior'),(10,49,'10-49'),(50,10**6,'50+')]:
        m=(d.prior_ads>=lo)&(d.prior_ads<=hi)
        print(f"  {lab:9s}: {m.sum():5d} ads ({m.mean()*100:4.1f}%)")
    # second half only (a realistic steady state, after history accumulates)
    h=d.iloc[len(d)//2:]
    print(f"\n  in the SECOND HALF of the window: new-seller ads {h.is_new_seller.mean()*100:.1f}%")
