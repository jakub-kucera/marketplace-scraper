import sys, warnings
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
import numpy as np, pandas as pd, lib, ph
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")
s = ip[ip.battery_pct.notna() & ip.log2_storage.notna() & ip.tier_ord.notna() & ip.generation.notna()].copy()


def ols(X, y):
    X = np.asarray(X, float); y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    yh = X @ b
    r2 = 1 - ((y - yh) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return b, r2


def boot_coef(d, cols, y, pos=0, n=2000, seed=0):
    rng = np.random.RandomState(seed)
    idx_by = {}
    for i, sl in enumerate(d.seller.values):
        idx_by.setdefault(sl, []).append(i)
    sel = list(idx_by)
    Xf = d[cols].astype(float).values; yf = np.asarray(y, float)
    out = []
    for _ in range(n):
        pick = rng.choice(len(sel), len(sel), replace=True)
        rows = np.concatenate([idx_by[sel[j]] for j in pick])
        try:
            b, _ = ols(Xf[rows], yf[rows])
        except Exception:
            continue
        out.append(b[1 + pos])
    return float(np.mean(out)), float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


print("=" * 100)
print("BATTERY COEFFICIENT WITH AND WITHOUT GENERATION  (OLS on log price, seller-cluster bootstrap 2000)")
print(f"n = {len(s)} rows stating battery / {s.seller.nunique()} sellers")
print("=" * 100)
SETS = [("battery alone", ["battery_pct"]),
        ("battery + generation", ["battery_pct", "generation"]),
        ("battery + gen + tier + log2storage", ["battery_pct", "generation", "tier_ord", "log2_storage"])]
for lab, cols in SETS:
    b, r2 = ols(s[cols].astype(float).values, s.log_price.values)
    m, lo, hi = boot_coef(s, cols, s.log_price.values, 0)
    f = lambda v: 100 * (np.exp(v) - 1)
    print(f"  {lab:36s} battery {f(b[1]):+7.3f}%/pt  CI [{f(lo):+7.3f}, {f(hi):+7.3f}]   model R2={r2:.3f}")

D = pd.get_dummies(s.gen_label.astype(str), prefix="g", drop_first=True).astype(float)
GF = pd.concat([s[["battery_pct", "tier_ord", "log2_storage"]].astype(float).reset_index(drop=True),
                D.reset_index(drop=True)], axis=1)
GF["seller"] = s.seller.values
cols = [c for c in GF.columns if c != "seller"]
b, r2 = ols(GF[cols].values, s.log_price.values)
m, lo, hi = boot_coef(GF, cols, s.log_price.values, 0)
f = lambda v: 100 * (np.exp(v) - 1)
print(f"  {'GENERATION FIXED EFFECTS + tier + stor':36s} battery {f(b[1]):+7.3f}%/pt  CI [{f(lo):+7.3f}, {f(hi):+7.3f}]   model R2={r2:.3f}")

print("\n  how much of battery_pct is predictable from age/config alone:")
_, r2b = ols(s[["generation"]].astype(float).values, s.battery_pct.values)
_, r2c = ols(s[["generation", "tier_ord", "log2_storage"]].astype(float).values, s.battery_pct.values)
Dg = pd.get_dummies(s.gen_label.astype(str), drop_first=True).astype(float)
_, r2d = ols(Dg.values, s.battery_pct.values)
print(f"    R2(battery ~ generation)            = {r2b:.4f}")
print(f"    R2(battery ~ gen+tier+storage)      = {r2c:.4f}")
print(f"    R2(battery ~ generation DUMMIES)    = {r2d:.4f}")

print("\n  battery within the newest band is near-degenerate:")
for lab, m_ in [("gen>=17 (17/Air)", s.generation >= 16.5), ("gen 13-16", (s.generation >= 12.5) & (s.generation < 16.5)),
                ("gen<=12", s.generation < 12.5)]:
    v = s.battery_pct[m_]
    print(f"    {lab:18s} n={len(v):3d} mean {v.mean():.1f} sd {v.std():.2f} | share at 100%: {100*(v>=100).mean():.0f}%")

print("\n" + "=" * 100)
print("DROPPING battery FROM THE SHIP MODEL -- out-of-fold cost (Protocol A)")
print("=" * 100)
oofC = ip.oof.values
oofNB = np.load(B + "oof_nobat.npy") if __import__("os").path.exists(B + "oof_nobat.npy") else None
if oofNB is None:
    TRIM = ["damage", "scratches", "swap", "new_word", "warranty", "mint_words", "box", "vat_dph", "battery_replaced"]
    oofNB = lib.cv_ridge(ip, dict(num=["generation", "tier_ord", "log2_storage"], boo=TRIM))
    np.save(B + "oof_nobat.npy", oofNB)
mC = lib.M(ip, oofC); mN = lib.M(ip, oofNB)
print(f"  with battery    n={mC['n']} R2={mC['r2']:.4f} MedAPE={mC['medape']:.2f}% sigma={mC['sigma']:.4f}")
print(f"  without battery n={mN['n']} R2={mN['r2']:.4f} MedAPE={mN['medape']:.2f}% sigma={mN['sigma']:.4f}")
d = ph.cluster_bootstrap_delta(ip, oofC, oofNB, n=2000)
print(f"  C - no-battery  dR2 {d['dr2'][0]:+.4f} [{d['dr2'][1]:+.4f},{d['dr2'][2]:+.4f}]  "
      f"dMedAPE {d['dmedape'][0]:+.2f} [{d['dmedape'][1]:+.2f},{d['dmedape'][2]:+.2f}]")
# funnel effect
FL = 1000.0
gate = ip.gate.values
for lab, o in [("with battery", oofC), ("without battery", oofNB)]:
    r = ip.log_price.values - o
    print(f"  -25%% gated flags {lab:16s}: {int(((r<=np.log(.75))&gate).sum())}")
