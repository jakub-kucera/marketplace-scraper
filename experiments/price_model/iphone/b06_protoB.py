import sys, warnings
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd, lib, ph
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/"
ip = pd.read_pickle(B+"ip2.pkl").sort_values("created").reset_index(drop=True)
FLAGS = ["battery_replaced","damage","scratches","mint_words","sealed_new","new_word","warranty",
         "invoice","vat_dph","esim","box","icloud_clear","locked","cz_region","eu_region",
         "usa_region","swap","urgent","dealer_pickup","multi_unit","bundle_other"]
SPEC = dict(num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS)

print("PROTOCOL B -- chronological past->future. The window is 3.30 days, so this measures")
print("almost nothing about drift, depreciation or seasonality; it is a sanity check only.\n")
for frac in (0.5, 0.7):
    k = int(len(ip)*frac)
    tr, te = ip.iloc[:k], ip.iloc[k:]
    f = lib.OheFit(**SPEC).fit(tr)
    a = lib._pick_alpha(tr, SPEC, tr.seller.values)
    m = Ridge(alpha=a).fit(f.transform(tr), tr.log_price.values)
    p = m.predict(f.transform(te))
    r = ph.metrics(te.log_price.values, p, te.price.values.astype(float))
    seen = te.seller.isin(set(tr.seller)).mean()
    print(f"frac={frac} train n={k} ({tr.created.min():%m-%d %H:%M}->{tr.created.max():%m-%d %H:%M}) "
          f"test n={r['n']} R2={r['r2']:+.3f} MedAPE={r['medape']:.2f}% sd={r['sigma']:.3f} alpha={a} "
          f"| {100*seen:.0f}% of test rows come from a seller already seen in train")
# day-by-day: how much of the corpus is even separable in time
ip["day"] = ip.created.dt.floor("D")
print("\nrows per day:", ip.groupby("day").size().to_dict())
print("median price per day:", ip.groupby("day").price.median().to_dict())
