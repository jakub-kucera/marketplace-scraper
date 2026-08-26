import pandas as pd, sys
pd.set_option('display.width', 200)
df = pd.read_csv('xm/mb3.csv')
print(df.shape)
print(df.groupby('marketplace').size())
df['created'] = pd.to_datetime(df.created, utc=True)
print(df.groupby('marketplace').created.agg(['min','max']))
for m in ['bazos','vinted','sbazar']:
    s = df[df.marketplace==m]
    print('---', m, len(s))
    print(s[['name']].head(8).to_string())
