"""Reproducible training. All preprocessing fits on training data only."""
from pathlib import Path
import json, uuid,hashlib,time
from .data import load_dataset
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
import numpy as np
import pandas as pd
import joblib
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.metrics import precision_score, recall_score, f1_score, average_precision_score, roc_auc_score, confusion_matrix, accuracy_score, brier_score_loss, precision_recall_curve
from sklearn.inspection import permutation_importance

NUM=['transaction_amount','transaction_hour','weekday']
CAT=['transaction_type','transaction_direction','channel','merchant_category','account_type']
FEATURES=NUM+CAT

def validate(df):
    errors=[]
    required=['transaction_id','transaction_date','transaction_amount','is_fraud']
    for c in required:
        if c not in df: errors.append(f'Missing required column: {c}')
    invalid=set()
    def mark(mask, message):
        ids=df.index[mask].tolist(); invalid.update(ids)
        if ids: errors.append(f'{message}: {len(ids)} rows')
    if 'transaction_amount' in df:
        n=pd.to_numeric(df.transaction_amount,errors='coerce')
        mark(n.isna() | (n<0) | ~np.isfinite(n),'Invalid amount')
    if 'is_fraud' in df: mark(~df.is_fraud.isin([0,1]),'Labels must be 0 or 1')
    if 'transaction_date' in df: mark(pd.to_datetime(df.transaction_date,errors='coerce').isna(),'Invalid date')
    if 'transaction_time' in df:
        mark(~df.transaction_time.astype(str).str.match(r'^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$'),'Invalid transaction time (expected HH:MM or HH:MM:SS)')
    if 'transaction_id' in df:
        mark(df.transaction_id.isna() | df.transaction_id.astype(str).str.strip().eq(''),'Missing transaction ID')
        mark(df.transaction_id.duplicated(keep=False),'Duplicate transaction IDs')
    if 'transaction_hour' in df:
        h=pd.to_numeric(df.transaction_hour,errors='coerce');mark(h.isna() | ~h.between(0,23),'Invalid transaction hour')
    for c in ['sender_id','recipient_id']:
        if c in df: mark(df[c].isna() | df[c].astype(str).str.strip().eq(''),f'Missing {c}')
    return {'rows':len(df),'columns':list(df.columns),'missing':df.isna().sum().astype(int).to_dict(),'duplicates':int(df.duplicated().sum()),'invalid_rows':len(invalid),'valid_rows':len(df)-len(invalid),'label_counts':{str(k):int(v) for k,v in df.get('is_fraud',pd.Series(dtype=int)).value_counts().items()},'errors':errors,'valid':not errors,'policy':'Reject entire import on validation errors. No rows removed or labels changed.'}

def features(df):
    out=pd.DataFrame(index=df.index)
    out['transaction_amount']=pd.to_numeric(df['transaction_amount'],errors='coerce')
    ts=pd.to_datetime(df['transaction_date'],errors='coerce')
    out['transaction_hour']=pd.to_numeric(df['transaction_hour'],errors='coerce') if 'transaction_hour' in df else pd.to_numeric(df.transaction_time.astype(str).str.split(':').str[0],errors='coerce') if 'transaction_time' in df else ts.dt.hour
    out['weekday']=ts.dt.dayofweek
    for c in CAT:out[c]=df[c].fillna('Unknown').astype(str) if c in df else 'Unknown'
    return out[FEATURES]

def metrics(y,p,t):
    pred=p>=t;tn,fp,fn,tp=confusion_matrix(y,pred,labels=[0,1]).ravel()
    return {'precision':float(precision_score(y,pred,zero_division=0)),'recall':float(recall_score(y,pred,zero_division=0)),'f1':float(f1_score(y,pred,zero_division=0)),'pr_auc':float(average_precision_score(y,p)),'roc_auc':float(roc_auc_score(y,p)),'specificity':float(tn/max(tn+fp,1)),'false_positive_rate':float(fp/max(tn+fp,1)),'accuracy':float(accuracy_score(y,pred)),'brier_score':float(brier_score_loss(y,p)),'confusion_matrix':[[int(tn),int(fp)],[int(fn),int(tp)]]}

def operating_points(y,p,target_recall=.8):
    """Choose decision thresholds from validation only, with no test-set tuning."""
    precision,recall,thresholds=precision_recall_curve(y,p)
    f1=2*precision[:-1]*recall[:-1]/np.maximum(precision[:-1]+recall[:-1],1e-15)
    best=int(np.argmax(f1));eligible=np.flatnonzero(recall[:-1]>=target_recall);high=int(eligible[-1])
    def point(i):
        t=float(thresholds[i])
        return {'threshold':t,'validation_precision':float(precision[i]),'validation_recall':float(recall[i]),'validation_alert_rate':float(np.mean(p>=t))}
    return {'balanced':point(best),'high_recall':point(high)}

def train(csv,output,algorithms=None):
    started=time.time();df=load_dataset(csv);quality=validate(df)
    source_digest=hashlib.sha256(Path(csv).read_bytes()).hexdigest()
    if not quality['valid']:raise ValueError('; '.join(quality['errors']))
    df=df.sort_values('transaction_date',kind='stable').reset_index(drop=True)
    # Split by distinct timestamps: tied events cannot straddle partitions.
    dates=pd.to_datetime(df.transaction_date); unique=sorted(dates.unique())
    if len(unique)<20:raise ValueError('At least 20 distinct transaction timestamps required')
    cut1=unique[int(len(unique)*.7)];cut2=unique[int(len(unique)*.85)]
    masks=[dates<cut1,(dates>=cut1)&(dates<cut2),dates>=cut2]
    X=features(df);y=df.is_fraud.astype(int)
    for m in masks:
        if y[m].nunique()!=2:raise ValueError('Both labels required in each chronological split')
    tr,va,te=masks
    candidates={'Logistic Regression':LogisticRegression(max_iter=1000,class_weight='balanced',random_state=42),'Random Forest':RandomForestClassifier(n_estimators=160,max_depth=12,min_samples_leaf=10,class_weight='balanced',random_state=42,n_jobs=2)}
    from xgboost import XGBClassifier
    from catboost import CatBoostClassifier
    weight=float((y[tr]==0).sum()/max((y[tr]==1).sum(),1))
    candidates['XGBoost']=XGBClassifier(n_estimators=200,max_depth=4,learning_rate=.08,scale_pos_weight=weight,random_state=42,n_jobs=2)
    candidates['CatBoost']=CatBoostClassifier(iterations=250,depth=5,cat_features=CAT,learning_rate=.08,auto_class_weights='Balanced',random_seed=42,verbose=False,thread_count=2,allow_writing_files=False)
    out=Path(output);out.mkdir(parents=True,exist_ok=True);results=[]
    for name,model in candidates.items():
        if algorithms and name not in algorithms:continue
        prep=ColumnTransformer([('num',Pipeline([('impute',SimpleImputer(strategy='median')),('scale',StandardScaler())]),NUM),('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),CAT)])
        print('Training '+name+' on '+str(int(tr.sum()))+' records',flush=True)
        pipe=Pipeline([('preprocess','passthrough' if name=='CatBoost' else prep),('model',model)]);pipe.fit(X[tr],y[tr])
        validation_indices=X[va].index;mid=len(validation_indices)//2
        calibration_idx=validation_indices[:mid];selection_idx=validation_indices[mid:]
        if y.loc[calibration_idx].nunique()!=2 or y.loc[selection_idx].nunique()!=2:raise ValueError('Both validation halves need both labels')
        calibrated=CalibratedClassifierCV(FrozenEstimator(pipe),method='sigmoid')
        calibrated.fit(X.loc[calibration_idx],y.loc[calibration_idx]);pipe=calibrated
        pv=pipe.predict_proba(X.loc[selection_idx])[:,1];ys=y.loc[selection_idx]
        thresholds=[{'threshold':float(t),'f1':float(f1_score(ys,pv>=t,zero_division=0)),'precision':float(precision_score(ys,pv>=t,zero_division=0)),'recall':float(recall_score(ys,pv>=t,zero_division=0))} for t in np.unique(np.r_[np.arange(.001,.101,.001),np.arange(.15,1,.05)])]
        profiles=operating_points(ys,pv);threshold=profiles['high_recall']['threshold'];version=uuid.uuid4().hex
        reference=X[tr].sample(min(32,int(tr.sum())),random_state=42)
        bundle={'pipeline':pipe,'reference':reference,'features':FEATURES,'threshold':threshold,'version':version,'algorithm':name}
        joblib.dump(bundle,out/f'{version}.joblib',compress=3)
        importance_indices=X.loc[selection_idx].sample(min(10000,len(selection_idx)),random_state=42).index
        importance=permutation_importance(pipe,X.loc[importance_indices],y.loc[importance_indices],n_repeats=2,random_state=42,scoring='average_precision')
        pt=pipe.predict_proba(X[te])[:,1]
        for profile in profiles.values():profile['test_metrics']=metrics(y[te],pt,profile['threshold']);profile['test_alert_rate']=float(np.mean(pt>=profile['threshold']))
        calibration=[]
        for low in np.arange(0,1,.1):
            m=(pt>=low)&(pt<low+.1+1e-12)
            if m.any():calibration.append({'predicted':float(pt[m].mean()),'observed':float(y[te].to_numpy()[m].mean()),'count':int(m.sum())})
        report={'version':version,'algorithm':name,'threshold':threshold,'default_profile':'high_recall','operating_profiles':profiles,'metrics':metrics(y[te],pt,threshold),'validation_pr_auc':float(average_precision_score(ys,pv)),'thresholds_validation':thresholds,'calibration':calibration,'global_importance':dict(zip(FEATURES,importance.importances_mean.tolist())),'split':{'method':'chronological, timestamp groups, 70/15/15','train':int(tr.sum()),'validation':int(va.sum()),'test':int(te.sum()),'calibration':len(calibration_idx),'selection':len(selection_idx),'seed':42},'features':FEATURES,'excluded':'Identifiers, target, post-transaction balance and outcome; customer credit/loan fields excluded. No future history used.','source':{'filename':Path(csv).name,'sha256':source_digest,'rows':len(df),'generated_by_application':False},'calibration_method':'Sigmoid on earlier validation half; thresholds on later half','importance_sample_size':len(importance_indices),'limitations':'Offline results on user-supplied data. Verify dataset provenance and label construction before real-bank deployment.','artifact':f'{version}.joblib'}
        (out/f'{version}.json').write_text(json.dumps(report,indent=2));results.append(report)
        (out/'progress.json').write_text(json.dumps(results,indent=2))
        print(name+' complete: '+json.dumps(report['metrics']),flush=True)
    # Separate anomaly experiment; no fraud probability claims.
    iso=IsolationForest(n_estimators=80,random_state=42).fit(X.loc[tr,NUM].fillna(0))
    joblib.dump(iso,out/'isolation_forest.joblib')
    (out/'anomaly.json').write_text(json.dumps({'method':'Isolation Forest','test_average_precision':float(average_precision_score(y[te],-iso.score_samples(X.loc[te,NUM].fillna(0)))),'warning':'Anomaly score is not a fraud probability.'},indent=2))
    manifest={'reports':results,'quality':quality,'source':{'filename':Path(csv).name,'sha256':source_digest,'rows':len(df)},'elapsed_seconds':time.time()-started}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return results

def explain(bundle,row):
    """Exact interventional Shapley values over 8 raw features, fixed background.
    2^8 coalitions are evaluated. Additivity is checked against probability output.
    """
    import math
    x=features(pd.DataFrame([row])); bg=bundle['reference'];n=len(FEATURES)
    frames=[]
    for mask in range(1<<n):
        frame=bg.copy()
        for j,c in enumerate(FEATURES):
            if mask&(1<<j):frame[c]=x.iloc[0][c]
        frames.append(frame)
    p=bundle['pipeline'].predict_proba(pd.concat(frames,ignore_index=True))[:,1].reshape(1<<n,len(bg)).mean(axis=1)
    phi=[]
    for j,c in enumerate(FEATURES):
        val=0.
        for mask in range(1<<n):
            if mask&(1<<j):continue
            k=mask.bit_count();w=math.factorial(k)*math.factorial(n-k-1)/math.factorial(n)
            val+=w*(p[mask|(1<<j)]-p[mask])
        observed=x.iloc[0][c]
        phi.append({'feature':c,'value':observed.item() if hasattr(observed,'item') else observed,'contribution':float(val)})
    score=float(bundle['pipeline'].predict_proba(x)[0,1]);err=abs(float(p[0])+sum(v['contribution'] for v in phi)-score)
    if err>1e-6:raise ValueError('Explanation additivity check failed')
    return {'score':score,'base_value':float(p[0]),'contributions':sorted(phi,key=lambda v:abs(v['contribution']),reverse=True),'method':'Exact interventional Shapley on raw features; 32 training-background rows','additivity_error':err,'warning':'Contributions explain the model, not causal evidence.'}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--output',default='../artifacts/models');args=p.parse_args();print(json.dumps(train(args.csv,args.output),indent=2))
