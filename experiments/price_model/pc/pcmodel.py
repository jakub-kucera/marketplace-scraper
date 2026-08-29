import sys; sys.path.insert(0,'pc')
import pandas as pd, numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import OrdinalEncoder
from sklearn.model_selection import GroupKFold, KFold
from sklearn.metrics import r2_score

D = pd.read_pickle('pc/pc_feat.pkl')
D = D[D.kind=='desktop'].copy().reset_index(drop=True)
D['created']=pd.to_datetime(D.created,utc=True,format='mixed')
D = D.sort_values('created').reset_index(drop=True)
D['log_price']=np.log(D.price)
D['seller']=D.email_publisher_id.fillna(-1).astype(str) + '/' + D.phone_publisher_id.fillna(-1).astype(str)
D['ssd_log']=np.log(D.ssd_gb.astype(float))
D['ram_log']=np.log(D.ram_gb.astype(float))
D['days']=(D.created-D.created.min()).dt.days

NUM=['gpu_pro','gpu_gen','gpu_tier','gpu_suffix_rank','gpu_vram','gpu_num',
     'cpu_tier','cpu_gen','cpu_num','ram_gb','ram_log','ssd_gb','ssd_log','hdd_gb','ddr','days']
BOOL=['gaming','warranty','new','defect','with_monitor','prebuilt','watercool','wifi']
CAT=['gpu_vendor','gpu_series','gpu_suffix','cpu_vendor','gpu_model','cpu_model']

def make_X(df, num=NUM, boo=BOOL, cat=CAT):
    X=df[num].astype(float).copy()
    for c in boo: X[c]=df[c].astype(float)
    if cat:
        enc=OrdinalEncoder(handle_unknown='use_encoded_value',unknown_value=-1)
        X=pd.concat([X,pd.DataFrame(enc.fit_transform(df[cat].astype(str)),columns=cat,index=df.index)],axis=1)
    return X,[X.columns.get_loc(c) for c in cat]

def run(df, X, ci, groups, label, n_splits=5):
    y=df.log_price.values; oof=np.full(len(df),np.nan)
    for tr,te in GroupKFold(n_splits).split(X,y,groups):
        m=HistGradientBoostingRegressor(max_iter=300,learning_rate=.06,min_samples_leaf=10,
            l2_regularization=1.0,categorical_features=ci,random_state=0)
        m.fit(X.iloc[tr],y[tr]); oof[te]=m.predict(X.iloc[te])
    ok=~np.isnan(oof)
    print(f"  {label:44s} R2={r2_score(y[ok],oof[ok]):6.3f}  "
          f"MedAPE={np.median(np.abs(np.exp(oof[ok])-df.price.values[ok])/df.price.values[ok])*100:5.1f}%")
    return oof
