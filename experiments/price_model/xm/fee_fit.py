import json, numpy as np
rows = json.load(open("xm/vinted_probe.json"))
p = np.array([r["price"] for r in rows]); t = np.array([r["total"] for r in rows])
A = np.vstack([p, np.ones_like(p)]).T
(slope, inter), res, *_ = np.linalg.lstsq(A, t - p, rcond=None)
pred = slope*p + inter
print(f"n={len(rows)}  fee = {slope:.6f} * price + {inter:.4f}   max abs resid = {np.abs(t-p-pred).max():.4f}")
# exact-model check: fee = 0.05*price + 18
exact = 0.05*p + 18
print("max |fee - (0.05p+18)| =", round(float(np.abs(t-p-exact).max()), 6))
print("ratio total/price: mean %.5f  min %.5f  max %.5f" % ((t/p).mean(), (t/p).min(), (t/p).max()))
noninteger_price = sum(1 for r in rows if abs(r["price"] - round(r["price"])) > 1e-9)
noninteger_total = sum(1 for r in rows if abs(r["total"] - round(r["total"])) > 1e-9)
print(f"non-integer price: {noninteger_price}/{len(rows)} = {noninteger_price/len(rows):.0%}")
print(f"non-integer total: {noninteger_total}/{len(rows)} = {noninteger_total/len(rows):.0%}")
print("currencies:", set(r["currency"] for r in rows))
# recovery error if we invert stored rounded total
rec = (np.round(t) - 18)/1.05
print("recovered seller-ask vs true price: max abs err = %.4f CZK, mean abs err = %.4f" % (np.abs(rec-p).max(), np.abs(rec-p).mean()))
