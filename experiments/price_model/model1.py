import pandas as pd, numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold, GroupKFold
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.preprocessing import OrdinalEncoder

d = pd.read_pickle('mb/ds.pkl')

CAT = ['family','chip_key','chip_variant','town_g','chip_brand']
NUM = ['year','age','screen','ram_gb','ssd_gb','ram_log','storage_log','seller_ads','dow','days',
       'battery_pct','cycles','view_count']
BOOL= ['warranty','new','defect','battery_new','vat_dph','cz_kbd','us_kbd','touchbar','retina',
       'top_word','scratches','urgent','box','swap','is_dealer']

def make_X(df, cats=CAT):
    X = df[NUM].astype(float).copy()
    for c in BOOL: X[c] = df[c].astype(float)
    enc = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
    C = pd.DataFrame(enc.fit_transform(df[cats].astype(str)), columns=cats, index=df.index)
    return pd.concat([X, C], axis=1), [X.shape[1]+i for i in range(len(cats))]

X, cat_idx = make_X(d)
y = d.log_price.values
price = d.price.values

def evaluate(splits, label, drop_leaky=False):
    Xi = X.drop(columns=['view_count']) if drop_leaky else X
    ci = [Xi.columns.get_loc(c) for c in CAT]
    oof = np.full(len(d), np.nan)
    for tr, te in splits:
        m = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06, max_depth=None,
                                          min_samples_leaf=15, l2_regularization=1.0,
                                          categorical_features=ci, random_state=0)
        m.fit(Xi.iloc[tr], y[tr])
        oof[te] = m.predict(Xi.iloc[te])
    ok = ~np.isnan(oof)
    r2 = r2_score(y[ok], oof[ok])
    mae_log = mean_absolute_error(y[ok], oof[ok])
    mape = np.mean(np.abs(np.exp(oof[ok]) - price[ok]) / price[ok]) * 100
    medape = np.median(np.abs(np.exp(oof[ok]) - price[ok]) / price[ok]) * 100
    mae_czk = mean_absolute_error(price[ok], np.exp(oof[ok]))
    print(f"{label:42s} R2(log)={r2:6.3f}  MAE(log)={mae_log:5.3f}  MedAPE={medape:5.1f}%  MAPE={mape:5.1f}%  MAE={mae_czk:7.0f} Kc")
    return oof

print("=== SPLIT STRATEGY COMPARISON (same model, same features) ===\n")
kf = KFold(5, shuffle=True, random_state=0)
evaluate(list(kf.split(X)), "1. random 5-fold  (LEAKY)")

gkf = GroupKFold(5)
evaluate(list(gkf.split(X, y, groups=d.dupkey.fillna("NA").astype(str))), "2. grouped by relisting (name+seller)")
oof_seller = evaluate(list(gkf.split(X, y, groups=d.email_publisher_id.fillna(-1).astype(str))), "3. grouped by SELLER (honest)")

# time split: train on first 70% of days, test on last 30%
order = np.argsort(d.created.values)
cut = int(len(d)*0.7)
tr, te = order[:cut], order[cut:]
evaluate([(tr,te)], "4. time split (past->future, 70/30)")
np.save('mb/oof_seller.npy', oof_seller)
