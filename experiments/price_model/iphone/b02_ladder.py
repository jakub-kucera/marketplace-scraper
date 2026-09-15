import sys, warnings, json
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd, lib, ph
warnings.filterwarnings("ignore")

d = pd.read_pickle("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/d.pkl")
ip = d[(d.kind == "iphone") & d.generation.notna() & d.price.notna()].copy().reset_index(drop=True)
ip["log2_storage"] = np.log2(ip.storage_gb.astype(float))
ip["complete"] = ip.storage_gb.notna()
ip["gen_tier"] = ip.gen_label.astype(str) + " " + ip.tier.astype(str)
ip["cfg"] = ip.gen_tier + " " + ip.storage_gb.astype("Int64").astype(str)
print("iphone modelled n", len(ip), "sellers", ip.seller.nunique(),
      "complete", int(ip.complete.sum()), "var(log)", round(ip.log_price.var(), 3))

C = ip[ip.complete].reset_index(drop=True)
print("complete-spec n", len(C), "sellers", C.seller.nunique())

FLAGS = ["battery_replaced","damage","scratches","mint_words","sealed_new","new_word","warranty",
         "invoice","vat_dph","esim","box","icloud_clear","locked","cz_region","eu_region",
         "usa_region","swap","urgent","dealer_pickup","multi_unit","bundle_other"]

res, oofs = [], {}
def rec(tag, frame, oof, note=""):
    m = lib.M(frame, oof); m["model"] = tag; m["note"] = note
    m["cov"] = 100*np.mean(~np.isnan(oof))
    res.append(m); oofs[tag] = (frame, oof)
    print(f"{tag:42s} n={m['n']:4d} cov={m['cov']:5.1f}% R2={m['r2']:+.3f} MedAPE={m['medape']:5.2f}% sd={m['sigma']:.3f} {note}")

# ---- baselines on the complete-spec set
y = C.log_price.values
g = C.seller.values
# global median (train-fold median)
from sklearn.model_selection import GroupKFold
acc = np.full((3, len(C)), np.nan)
for r in range(3):
    rng = np.random.RandomState(r); uniq = np.array(sorted(set(g)))
    remap = {u:i for u,i in zip(uniq, rng.permutation(len(uniq)))}
    gs = np.array([remap[v] for v in g])
    for tr, te in GroupKFold(5).split(C, y, gs):
        acc[r, te] = np.median(y[tr])
rec("median (global)", C, np.nanmean(acc, axis=0))

for kmin in (3, 5):
    rec(f"median by gen x tier x storage (k>={kmin})", C,
        lib.cv_config_median(C, ["gen_label","tier","storage_gb"], kmin=kmin))
    rec(f"median by gen x tier (k>={kmin})", C,
        lib.cv_config_median(C, ["gen_label","tier"], kmin=kmin))

# ---- ridge ladder, nested alpha, one-hot for everything categorical
specs = {
 "ridge: gen ordinal":              dict(num=["generation"]),
 "ridge: gen+tier ordinal":         dict(num=["generation","tier_ord"]),
 "ridge: ordinal (gen,tier,stor)":  dict(num=["generation","tier_ord","log2_storage"]),
 "ridge: dummies (gen_tier,stor)":  dict(cat=["gen_tier","storage_gb"]),
 "ridge: both":                     dict(num=["generation","tier_ord","log2_storage"], cat=["gen_tier","storage_gb"]),
 "ridge: ordinal+battery":          dict(num=["generation","tier_ord","log2_storage","battery_pct"]),
 "ridge: FULL (ord+bat+flags)":     dict(num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS),
 "ridge: FULL+colour":              dict(num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS, cat=["color"]),
 "ridge: FULL+gen_tier dummies":    dict(num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS, cat=["gen_tier"]),
}
alphas_used = {}
for tag, sp in specs.items():
    oof, al = lib.cv_ridge(C, sp, return_alphas=True)
    alphas_used[tag] = sorted(set(al))
    rec(tag, C, oof, note=f"alpha={sorted(set(al))}")

# ---- trees: ordinal / native categorical
rec("HGB: ordinal (gen,tier,stor)", C, lib.cv_hgb(C, num=["generation","tier_ord","log2_storage"]))
rec("HGB: dummies-equiv (native cat)", C, lib.cv_hgb(C, cat=["gen_tier","storage_gb"]))
rec("HGB: FULL", C, lib.cv_hgb(C, num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS))
rec("HGB: FULL+colour", C, lib.cv_hgb(C, num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS, cat=["color"]))

# ---- the same FULL ridge on ALL iphone rows (incomplete specs imputed + __na indicator)
oof_all = lib.cv_ridge(ip, dict(num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS))
rec("ridge: FULL, all iphone rows", ip, oof_all, note="incl. 37 no-storage")
oof_all_h = lib.cv_hgb(ip, num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS)
rec("HGB: FULL, all iphone rows", ip, oof_all_h)

np.save("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/oofs.npy",
        np.array([oofs[k][1] if len(oofs[k][1])==len(C) else np.full(len(C), np.nan) for k in oofs]))
import pickle
pickle.dump({k: (len(v[0]), v[1]) for k, v in oofs.items()},
            open("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/oofs.pkl","wb"))
C.to_pickle("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/C.pkl")
ip.to_pickle("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/ip.pkl")
pd.DataFrame(res).to_csv("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/ladder.csv", index=False)
