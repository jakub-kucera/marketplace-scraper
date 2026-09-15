import sys, warnings
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd, lib
from sklearn.linear_model import Ridge
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/"
ip = pd.read_pickle(B+"ip2.pkl")
FLAGS = ["battery_replaced","damage","scratches","mint_words","sealed_new","new_word","warranty",
         "invoice","vat_dph","esim","box","icloud_clear","locked","cz_region","eu_region",
         "usa_region","swap","urgent","dealer_pickup","multi_unit","bundle_other"]
SPEC = dict(num=["generation","tier_ord","log2_storage","battery_pct"], boo=FLAGS, scale=False)

def fit(df, alpha=1.0):
    f = lib.OheFit(**SPEC).fit(df)
    X = f.transform(df)
    m = Ridge(alpha=alpha).fit(X, df.log_price.values)
    return dict(zip(f.cols_, m.coef_))

base = fit(ip)
# seller-cluster bootstrap of the coefficients
idx_by = {}
for i, s in enumerate(ip.seller.values): idx_by.setdefault(s, []).append(i)
sellers = list(idx_by); rng = np.random.RandomState(0)
draws = []
for _ in range(600):
    pick = rng.choice(len(sellers), len(sellers), replace=True)
    rows = np.concatenate([idx_by[sellers[j]] for j in pick])
    try: draws.append(fit(ip.iloc[rows]))
    except Exception: pass
D = pd.DataFrame(draws)
print("bootstrap reps", len(D), " (fit on full corpus for reporting only; accuracy figures are OOF)")
out=[]
for k, v in base.items():
    col = D[k].dropna() if k in D else pd.Series(dtype=float)
    lo, hi = (np.percentile(col,2.5), np.percentile(col,97.5)) if len(col)>50 else (np.nan, np.nan)
    out.append(dict(feature=k, beta=v, pct=100*(np.exp(v)-1),
                    lo=100*(np.exp(lo)-1) if lo==lo else np.nan,
                    hi=100*(np.exp(hi)-1) if hi==hi else np.nan,
                    share=100*float(pd.to_numeric(ip[k], errors="coerce").mean()) if k in ip.columns else np.nan))
O = pd.DataFrame(out).sort_values("beta", ascending=False)
pd.set_option("display.width", 200)
print(O.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
O.to_csv(B+"coefs.csv", index=False)

# generation step per year: map generation -> release year
REL = {4:2010,4.5:2011,5:2012,5.5:2013,5.2:2013,6:2014,6.5:2015,7:2016,8:2017,10:2017,
       10.2:2018,10.5:2018,11:2019,12:2020,13:2021,14:2022,15:2023,16:2024,17:2025}
ip2 = ip.copy(); ip2["rel_year"] = ip2.generation.map(REL)
print("\nrelease-year mapping coverage:", ip2.rel_year.notna().mean())
b_gen = base["generation"]
# mean years per generation step over the observed support
sup = ip2.dropna(subset=["rel_year"]).sort_values("generation")
gens = sorted(sup.generation.unique())
yrs = [REL[g] for g in gens]
slope_years = np.polyfit(gens, yrs, 1)[0]
print(f"1 generation step = {slope_years:.2f} release years over the observed ladder")
print(f"generation coefficient {b_gen:+.4f} log/step = {100*(np.exp(b_gen)-1):+.1f}% per step "
      f"= {100*(np.exp(b_gen/slope_years)-1):+.1f}% per release year")
# direct: regress on release year instead of generation ordinal
SPEC2 = dict(num=["rel_year","tier_ord","log2_storage","battery_pct"], boo=FLAGS, scale=False)
f2 = lib.OheFit(**SPEC2).fit(ip2); m2 = Ridge(alpha=1.0).fit(f2.transform(ip2), ip2.log_price.values)
c2 = dict(zip(f2.cols_, m2.coef_))
print(f"direct release-year coefficient: {100*(np.exp(c2['rel_year'])-1):+.1f}% per year "
      f"(MacBook depreciation is -8.3%/yr, i.e. newer = +9.0%/yr)")
