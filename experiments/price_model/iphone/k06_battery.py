import sys, warnings
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
import numpy as np, pandas as pd, ipfeat, lib, ph
from sklearn.linear_model import Ridge
from scipy import stats
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")
bl = ip.apply(lambda r: ipfeat.norm(f"{r['name']} || {r.short_description or ''}"), axis=1)

rep = bl.str.contains(r"nova bater\w*|vymenen\w* bater\w*|novou bater\w*|vymena bater", regex=True)
b100 = ip.battery_pct >= 99
st = ip.battery_pct.notna()
print("SWAPPED CELL REPORTING >=99%%: %d rows (%.2f%% of corpus)" % (int((rep & b100).sum()), 100 * (rep & b100).mean()))
print("  battery>=99 overall: %d (%.1f%% of the %d rows that state one)" % (int(b100.sum()), 100 * b100.sum() / st.sum(), int(st.sum())))
print("  mean resid  battery>=99 & replaced %+.3f (n=%d) | battery>=99 not replaced %+.3f (n=%d)"
      % (ip.resid[rep & b100].mean(), int((rep & b100).sum()), ip.resid[b100 & ~rep].mean(), int((b100 & ~rep).sum())))

print("\n" + "=" * 100)
print("TASK 4 -- IS battery_pct CONFOUNDED WITH GENERATION?")
print("=" * 100)
s = ip[st]
r, p = stats.pearsonr(s.battery_pct, s.generation)
rs, ps = stats.spearmanr(s.battery_pct, s.generation)
print(f"  n stating battery = {len(s)} ({100*st.mean():.1f}% coverage)")
print(f"  corr(battery_pct, generation): Pearson r={r:+.3f} (p={p:.2e})   Spearman rho={rs:+.3f} (p={ps:.2e})")
print(f"  corr on ALL modelled rows treating missing as its own thing is undefined -- restricted to the {len(s)} stating rows")
print("\n  mean battery by generation band:")
band = pd.cut(s.generation, [0, 10.5, 12.5, 14.5, 16.5, 20], labels=["<=X/XR/XS", "11-12", "13-14", "15-16", "17/Air"])
print(s.groupby(band).battery_pct.agg(["count", "mean", "median", "std"]).to_string())
print("\n  P(battery stated | generation band)  -- informative missingness:")
bandall = pd.cut(ip.generation, [0, 10.5, 12.5, 14.5, 16.5, 20], labels=["<=X/XR/XS", "11-12", "13-14", "15-16", "17/Air"])
print(ip.groupby(bandall).apply(lambda d: pd.Series({"n": len(d), "pct_stated": 100 * d.battery_pct.notna().mean()})).to_string())

print("\n  --- coefficient of battery_pct WITH and WITHOUT generation in the model (OLS, log price, stating rows only)")
import statsmodels.api as sm
X1 = sm.add_constant(s[["battery_pct"]].astype(float))
m1 = sm.OLS(s.log_price.values, X1).fit(cov_type="cluster", cov_kwds={"groups": s.seller.values})
X2 = sm.add_constant(s[["battery_pct", "generation"]].astype(float))
m2 = sm.OLS(s.log_price.values, X2).fit(cov_type="cluster", cov_kwds={"groups": s.seller.values})
X3 = sm.add_constant(s[["battery_pct", "generation", "tier_ord", "log2_storage"]].astype(float))
m3 = sm.OLS(s.log_price.values, X3).fit(cov_type="cluster", cov_kwds={"groups": s.seller.values})
for lab, m in [("battery alone", m1), ("+ generation", m2), ("+ gen,tier,storage", m3)]:
    b = m.params["battery_pct"]; se = m.bse["battery_pct"]
    print(f"    {lab:22s} battery coef {b:+.5f} log/pt = {100*(np.exp(b)-1):+.3f}%/pt  "
          f"[{100*(np.exp(b-1.96*se)-1):+.3f}, {100*(np.exp(b+1.96*se)-1):+.3f}]  R2={m.rsquared:.3f}")
print("\n    (seller-clustered SEs, n=%d, %d sellers)" % (len(s), s.seller.nunique()))
print("    variance of battery_pct explained by generation alone: R2 = %.4f" %
      sm.OLS(s.battery_pct.values, sm.add_constant(s[["generation"]].astype(float))).fit().rsquared)
print("    ... by gen+tier+storage: R2 = %.4f" %
      sm.OLS(s.battery_pct.values, sm.add_constant(s[["generation", "tier_ord", "log2_storage"]].astype(float))).fit().rsquared)

print("\n  --- does DROPPING battery from the ship model cost anything out-of-fold?")
TRIM = ["damage", "scratches", "swap", "new_word", "warranty", "mint_words", "box", "vat_dph", "battery_replaced"]
SPEC_C = dict(num=["generation", "tier_ord", "log2_storage", "battery_pct"], boo=TRIM)
SPEC_NB = dict(num=["generation", "tier_ord", "log2_storage"], boo=TRIM)
oofC = ip.oof.values
oofNB = lib.cv_ridge(ip, SPEC_NB)
mC = lib.M(ip, oofC); mN = lib.M(ip, oofNB)
print(f"    with battery    R2={mC['r2']:.4f} MedAPE={mC['medape']:.2f}% sigma={mC['sigma']:.4f}")
print(f"    without battery R2={mN['r2']:.4f} MedAPE={mN['medape']:.2f}% sigma={mN['sigma']:.4f}")
d = ph.cluster_bootstrap_delta(ip, oofC, oofNB, n=2000)
print(f"    C - no-battery  dR2 {d['dr2'][0]:+.4f} [{d['dr2'][1]:+.4f},{d['dr2'][2]:+.4f}]  "
      f"dMedAPE {d['dmedape'][0]:+.2f} [{d['dmedape'][1]:+.2f},{d['dmedape'][2]:+.2f}]")
np.save(B + "oof_nobat.npy", oofNB)
print("\n  --- within-generation battery coefficient (gen fixed effects, stating rows)")
D = pd.get_dummies(s.gen_label.astype(str), prefix="g", drop_first=True).astype(float)
X4 = sm.add_constant(pd.concat([s[["battery_pct", "tier_ord", "log2_storage"]].astype(float).reset_index(drop=True),
                                D.reset_index(drop=True)], axis=1))
m4 = sm.OLS(s.log_price.values, X4).fit(cov_type="cluster", cov_kwds={"groups": s.seller.values})
b, se = m4.params["battery_pct"], m4.bse["battery_pct"]
print(f"    gen FIXED EFFECTS + tier + storage: battery {100*(np.exp(b)-1):+.3f}%/pt "
      f"[{100*(np.exp(b-1.96*se)-1):+.3f}, {100*(np.exp(b+1.96*se)-1):+.3f}]  R2={m4.rsquared:.3f}")
