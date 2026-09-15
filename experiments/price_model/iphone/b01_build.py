import sys, warnings
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone")
import numpy as np, pandas as pd
import ph, ipfeat

CSV = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/data/ads19.csv"
df = ph.load(19, csv=CSV)
print("raw rows", len(df), "cols", list(df.columns))
print("null price", df.price.isna().sum(), "price_type", df.price_type.value_counts().to_dict())
print("marketplace", df.marketplace.value_counts().to_dict())
print("status", df.status.value_counts().to_dict())
print("window", df.created.min(), "->", df.created.max(),
      "days", (df.created.max()-df.created.min()).total_seconds()/86400)

rows = [ipfeat.extract(r["name"], r.get("short_description") or "") for _, r in df.iterrows()]
F = pd.DataFrame(rows, index=df.index)
d = pd.concat([df, F], axis=1)
d["log_price"] = np.log(d.price.astype(float))
d.to_pickle("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/d.pkl")

print("\n-- kind --"); print(d.kind.value_counts().to_dict())
ip = d[d.kind == "iphone"]
print("iphone rows", len(ip))
for f in ["generation","tier_ord","storage_gb","battery_pct","color","warranty_months","grade_letter","grade_ten","cycles"]:
    print(f"  {f:18s} all={100*d[f].notna().mean():5.1f}%  iphone={100*ip[f].notna().mean():5.1f}%")
print("gen+tier+storage jointly (iphone):",
      round(100*(ip.generation.notna()&ip.tier_ord.notna()&ip.storage_gb.notna()).mean(),1))
print("\nmarket structure:", ph.market_structure(d))
print("median price", d.price.median(), "var(log)", round(d.log_price.var(),3))
