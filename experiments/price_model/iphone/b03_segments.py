import sys, warnings
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd, lib, ph
warnings.filterwarnings("ignore")
from sklearn.linear_model import Ridge

d = pd.read_pickle("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/d.pkl")
ip = d[(d.kind == "iphone") & d.generation.notna() & d.price.notna()].copy().reset_index(drop=True)
ip["log2_storage"] = np.log2(ip.storage_gb.astype(float))
ip["gen_tier"] = ip.gen_label.astype(str) + " " + ip.tier.astype(str)
FLAGS = ["battery_replaced","damage","scratches","mint_words","sealed_new","new_word","warranty",
         "invoice","vat_dph","esim","box","icloud_clear","locked","cz_region","eu_region",
         "usa_region","swap","urgent","dealer_pickup","multi_unit","bundle_other"]
SPEC = dict(num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS)

# Protocol A on ALL iphone rows -- one model, then read it by segment.
oofA = lib.cv_ridge(ip, SPEC)
oofH = lib.cv_hgb(ip, num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS)
oofCfg = lib.cv_config_median(ip, ["gen_label","tier","storage_gb"], kmin=3)
np.save("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/oofA_ip.npy", oofA)
np.save("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/oofH_ip.npy", oofH)
np.save("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/oofCfg_ip.npy", oofCfg)

# seller prior-ad count, time-causal within the corpus window
ip = ip.sort_values("created").reset_index(drop=True)
ip["prior"] = ip.groupby("seller").cumcount()
vc = ip.seller.value_counts()
ip["seller_total"] = ip.seller.map(vc)

def seg(name, mask, oof=oofA):
    m = np.asarray(mask, bool)
    r = lib.M(ip, oof, m)
    r["segment"] = name; r["share"] = 100*m.mean()
    return r

rows = []
rows.append(seg("ALL iphone rows", np.ones(len(ip), bool)))
rows.append(seg("complete spec (gen+tier+storage)", ip.storage_gb.notna()))
rows.append(seg("incomplete (no storage)", ip.storage_gb.isna()))
rows.append(seg("battery stated", ip.battery_pct.notna()))
rows.append(seg("battery not stated", ip.battery_pct.isna()))
rows.append(seg("damage vocabulary", ip.damage))
rows.append(seg("no damage vocabulary", ~ip.damage))
for lo, hi in [(0,5000),(5000,10000),(10000,20000),(20000,10**9)]:
    rows.append(seg(f"price {lo}-{hi if hi<10**9 else 'max'}", (ip.price>=lo)&(ip.price<hi)))
for lo, hi, lab in [(4,11,"gen <=10.5 (X/XR/XS & older)"),(11,14,"gen 11-13"),(14,16,"gen 14-15"),(16,18,"gen 16-17")]:
    rows.append(seg(lab, (ip.generation>=lo)&(ip.generation<hi)))
for t in ["base","pro","pro max","plus","mini","se","max","air","e"]:
    m = ip.tier == t
    if m.sum() >= 12: rows.append(seg(f"tier {t}", m))
rows.append(seg("dealer-ish seller (>=5 ads in corpus)", ip.seller_total>=5))
rows.append(seg("private seller (1 ad in corpus)", ip.seller_total==1))
rows.append(seg("seller 2-4 ads", (ip.seller_total>=2)&(ip.seller_total<=4)))
rows.append(seg("dealer_pickup vocabulary", ip.dealer_pickup))
rows.append(seg("mint/new words", ip.mint_words|ip.new_word|ip.sealed_new))
S = pd.DataFrame(rows)[["segment","n","share","r2","medape","sigma"]]
pd.set_option("display.width", 200)
print("=== SEGMENTS, ridge FULL, protocol A (pooled OOF, seller-grouped, nested alpha)")
print(S.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

print("\n=== sigma by seller prior-ad count (time-causal, inside the 3.3-day window)")
bk = pd.cut(ip.prior, [-1,0,2,9,10**6], labels=["0 (first seen)","1-2","3-9","10+"])
for lab, gsub in ip.groupby(bk, observed=True):
    m = ip.index.isin(gsub.index)
    r = lib.M(ip, oofA, m); print(f"  prior={lab:15s} n={r['n']:4d} sigma={r['sigma']:.3f} MedAPE={r['medape']:5.2f}%")
print("\n=== sigma by seller TOTAL ads in corpus (not time-causal; the MacBook §5.6 cut)")
bk2 = pd.cut(ip.seller_total, [0,1,2,4,9,10**6], labels=["1","2","3-4","5-9","10+"])
for lab, gsub in ip.groupby(bk2, observed=True):
    m = ip.index.isin(gsub.index)
    r = lib.M(ip, oofA, m); print(f"  total={lab:6s} n={r['n']:4d} sellers={gsub.seller.nunique():3d} sigma={r['sigma']:.3f} MedAPE={r['medape']:5.2f}%")
print("\n=== sigma by spec completeness x battery")
for lab, m in [("complete+battery", ip.storage_gb.notna()&ip.battery_pct.notna()),
               ("complete, no battery", ip.storage_gb.notna()&ip.battery_pct.isna()),
               ("no storage", ip.storage_gb.isna())]:
    r = lib.M(ip, oofA, m); print(f"  {lab:22s} n={r['n']:4d} sigma={r['sigma']:.3f} MedAPE={r['medape']:5.2f}%")

print("\n=== ridge vs HGB vs config-median, key segments")
for lab, m in [("all", np.ones(len(ip),bool)), ("complete spec", ip.storage_gb.notna()),
               ("no storage", ip.storage_gb.isna()), ("price>=20k", ip.price>=20000),
               ("gen<=10.5", ip.generation<=10.5)]:
    a=lib.M(ip,oofA,m); b=lib.M(ip,oofH,m); c=lib.M(ip,oofCfg,m)
    print(f"  {lab:16s} n={a['n']:4d} ridge R2={a['r2']:+.3f}/{a['medape']:5.2f}%  "
          f"HGB {b['r2']:+.3f}/{b['medape']:5.2f}%  cfgmed(n={c['n']}) {c['r2']:+.3f}/{c['medape']:5.2f}%")
ip.to_pickle("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/ip2.pkl")
S.to_csv("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/segments.csv", index=False)
