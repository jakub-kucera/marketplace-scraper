import numpy as np, seller_base, harness as H
d = seller_base.load(); X, ci = H.build_X(d)
base = H.replay(d, X, ci, start_frac=.30, step=150)
np.save('mb/base_causal.npy', base)
print("done", np.isnan(base).sum(), "unscored of", len(base))
