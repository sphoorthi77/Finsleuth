"""Leakage-aware experiments: require accuracy and fraud recall together."""
import json,time
from pathlib import Path
import numpy as np,pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import precision_recall_curve
from .data import load_dataset
from .pipeline import metrics

def history_features(df):
    d=df.copy();d['_time']=pd.to_datetime(df.transaction_date.astype(str)+' '+df.transaction_time.astype(str))
    d['_original_order']=np.arange(len(d))
    # Group simultaneous events so none can see another at the same instant.
    h=d.groupby(['customer_id','_time'],as_index=False).agg(group_count=('transaction_amount','size'),group_sum=('transaction_amount','sum'),group_mean=('transaction_amount','mean')).sort_values(['customer_id','_time'])
    g=h.groupby('customer_id',sort=False)
    h['previous_count']=g.group_count.cumsum()-h.group_count
    h['previous_mean_amount']=(g.group_sum.cumsum()-h.group_sum)/h.previous_count.replace(0,np.nan)
    h['previous_amount']=g.group_mean.shift(1)
    h['seconds_since_previous']=(h._time-g._time.shift(1)).dt.total_seconds()
    cols=['customer_id','_time','previous_count','previous_mean_amount','previous_amount','seconds_since_previous']
    d=d.merge(h[cols],on=['customer_id','_time'],how='left',validate='many_to_one').sort_values('_original_order')
    d['relative_to_history']=d.transaction_amount/d.previous_mean_amount.replace(0,np.nan)
    d.index=df.index
    return d

def threshold_at_accuracy(y,p,floor=.85):
    order=np.argsort(-p,kind='stable');yy=np.asarray(y)[order];pp=p[order]
    ends=np.r_[np.flatnonzero(pp[:-1]!=pp[1:]),len(pp)-1]
    tp=np.cumsum(yy)[ends];fp=ends+1-tp;positive=yy.sum();negative=len(yy)-positive
    accuracy=(tp+negative-fp)/len(yy);recall=tp/max(positive,1)
    ok=np.flatnonzero(accuracy>=floor)
    if not len(ok):raise ValueError('No threshold meets accuracy floor')
    k=ok[np.argmax(recall[ok])]
    return float(pp[ends[k]])

def run(source,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);start=time.time()
    df=load_dataset(source).sort_values('transaction_date',kind='stable').reset_index(drop=True)
    # Customer histories use earlier records only; labels never enter historical features.
    d=history_features(df);days=sorted(df.transaction_date.unique());c1=days[int(len(days)*.7)];c2=days[int(len(days)*.85)]
    train=df.transaction_date<c1;val=(df.transaction_date>=c1)&(df.transaction_date<c2);test=df.transaction_date>=c2
    selection=np.flatnonzero(val)[len(np.flatnonzero(val))//2:];early=np.flatnonzero(val)[:len(np.flatnonzero(val))//2]
    cats=['account_type','transaction_type','transaction_direction','merchant_category','state','has_loan','loan_type','channel','kyc_status']
    nums=['transaction_amount','credit_score','emi_amount','transaction_hour','previous_count','previous_mean_amount','previous_amount','seconds_since_previous','relative_to_history']
    x=d[nums+cats].copy();x['weekday']=pd.to_datetime(df.transaction_date).dt.dayofweek;x['log_amount']=np.log1p(x.transaction_amount)
    x['hour_sin']=np.sin(2*np.pi*x.transaction_hour/24);x['hour_cos']=np.cos(2*np.pi*x.transaction_hour/24)
    for c in cats:x[c]=x[c].fillna('Unknown').astype(str)
    for c in x.columns:
        if c not in cats:x[c]=pd.to_numeric(x[c],errors='coerce').replace([np.inf,-np.inf],np.nan).fillna(-1)
    y=df.is_fraud.astype(int);reports=[]
    for name,depth,weight in [('Context + history / unweighted',6,None),('Context + history / balanced',8,'Balanced')]:
        model=CatBoostClassifier(iterations=600,depth=depth,learning_rate=.05,auto_class_weights=weight,cat_features=cats,loss_function='Logloss',eval_metric='AUC',random_seed=42,verbose=False,thread_count=4,allow_writing_files=False,l2_leaf_reg=10)
        model.fit(x.loc[train],y.loc[train],eval_set=(x.iloc[early],y.iloc[early]),early_stopping_rounds=70)
        pv=model.predict_proba(x.iloc[selection])[:,1];threshold=threshold_at_accuracy(y.iloc[selection],pv,.85)
        validation=metrics(y.iloc[selection],pv,threshold)
        pt=model.predict_proba(x.loc[test])[:,1];measured=metrics(y.loc[test],pt,threshold)
        accepted=validation['accuracy']>=.85 and validation['recall']>=.85 and measured['accuracy']>=.85 and measured['recall']>=.85
        report={'experiment':name,'features':list(x.columns),'excluded':['transaction_id','raw customer_id','is_fraud','post-transaction account_balance','transaction_status'],'training_rows':int(train.sum()),'early_stopping_validation_rows':len(early),'threshold_validation_rows':len(selection),'test_rows':int(test.sum()),'threshold_policy':'Maximize validation recall subject to accuracy >=85%; no test-threshold selection','threshold':threshold,'validation':validation,'test':measured,'trees':model.tree_count_,'joint_85_percent_target_met':accepted,'evaluation_note':'Chronological split; same previously evaluated test partition. Historical features include no labels and use preceding customer records. Evaluation is repeated, not fresh independent evidence.'}
        reports.append(report);print(json.dumps(report),flush=True)
        model.save_model(str(output/(name.split('/')[1].strip()+'.cbm')))
        (output/'joint_benchmark.json').write_text(json.dumps({'reports':reports,'elapsed_seconds':time.time()-start,'training_source':'Original archive.zip read directly with zipfile; no synthetic training samples'},indent=2))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output');a=p.parse_args();run(a.source,a.output)
