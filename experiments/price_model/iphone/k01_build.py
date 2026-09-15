import sys, warnings
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
import numpy as np, pandas as pd, ph, ipfeat, lib
warnings.filterwarnings("ignore")
B="/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
CSV="/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/data/ads19.csv"

df = ph.load(19, csv=CSV)
print("raw rows", len(df), "null price", int(df.price.isna().sum()))
print("window", df.created.min(), "->", df.created.max(),
      "days", round((df.created.max()-df.created.min()).total_seconds()/86400,3))
F = pd.DataFrame([ipfeat.extract(r["name"], r.get("short_description") or "") for _,r in df.iterrows()], index=df.index)
d = pd.concat([df, F], axis=1)
d["log_price"] = np.log(d.price.astype(float))
print("kind:", d.kind.value_counts().to_dict())
ip = d[d.kind=="iphone"].copy()
ip["log2_storage"] = np.log2(ip.storage_gb.astype(float))
ip["seller_total"] = ip.seller.map(ip.seller.value_counts())
print("iphone rows", len(ip), "sellers", ip.seller.nunique(),
      "complete-spec", int((ip.generation.notna()&ip.tier_ord.notna()&ip.storage_gb.notna()).sum()))

TRIM = ["damage","scratches","swap","new_word","warranty","mint_words","box","vat_dph","battery_replaced"]
SPEC = dict(num=["generation","tier_ord","log2_storage","battery_pct"], boo=TRIM)
oof, al = lib.cv_ridge(ip, SPEC, return_alphas=True)
m_all = lib.M(ip, oof); m_c = lib.M(ip, oof, ip.storage_gb.notna())
print("\nSHIP MODEL C, Protocol A (GroupKFold5 x seller, 3 repeats, pooled OOF, nested alpha)")
print(f"  all iPhone rows : n={m_all['n']} R2={m_all['r2']:.4f} MedAPE={m_all['medape']:.2f}% sigma={m_all['sigma']:.4f}")
print(f"  complete-spec   : n={m_c['n']} R2={m_c['r2']:.4f} MedAPE={m_c['medape']:.2f}% sigma={m_c['sigma']:.4f}")
print("  alphas chosen:", sorted(set(al)))
ip["oof"]=oof; ip["pred"]=np.exp(oof); ip["resid"]=ip.log_price-oof; ip["disc"]=1-ip.price/ip.pred
ip.to_pickle(B+"ip.pkl")
