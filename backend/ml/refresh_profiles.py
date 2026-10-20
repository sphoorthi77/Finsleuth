"""Re-evaluate fixed pipelines at validation-selected operating points. No retraining."""
import json,uuid,joblib,numpy as np
from pathlib import Path
from .data import load_dataset
from .pipeline import features,operating_points,metrics

def refresh(source,folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text())
    df=load_dataset(source).sort_values('transaction_date',kind='stable').reset_index(drop=True)
    dates=sorted(df.transaction_date.unique());cut1=dates[int(len(dates)*.7)];cut2=dates[int(len(dates)*.85)]
    validation=df[(df.transaction_date>=cut1)&(df.transaction_date<cut2)];selection=validation.iloc[len(validation)//2:];test=df[df.transaction_date>=cut2]
    for report in manifest['reports']:
        old=report['version'];bundle=joblib.load(folder/report['artifact']);pipe=bundle['pipeline']
        pv=pipe.predict_proba(features(selection))[:,1];profiles=operating_points(selection.is_fraud,pv)
        pt=pipe.predict_proba(features(test))[:,1]
        for profile in profiles.values():
            profile['test_metrics']=metrics(test.is_fraud,pt,profile['threshold']);profile['test_alert_rate']=float(np.mean(pt>=profile['threshold']))
        new=uuid.uuid4().hex;report['previous_metrics']=report['metrics'];report['previous_threshold']=report['threshold'];report['operating_profiles']=profiles;report['default_profile']='high_recall';report['threshold']=profiles['high_recall']['threshold'];report['metrics']=profiles['high_recall']['test_metrics'];report['version']=new;report['artifact']=new+'.joblib'
        report['evaluation_note']='Fixed fitted estimator; exact precision-recall thresholds selected on validation only. 80% validation recall target. Test set was reported in prior release: repeated evaluation, not a fresh independent test.'
        report['limitations']='High-recall screening flags many legitimate transactions. Review precision and false-positive rate; this does not improve underlying ranking quality.'
        bundle['version']=new;bundle['threshold']=report['threshold'];joblib.dump(bundle,folder/report['artifact'],compress=3)
        (folder/(new+'.json')).write_text(json.dumps(report,indent=2));(folder/(old+'.joblib')).unlink();(folder/(old+'.json')).unlink()
        print(report['algorithm'],json.dumps({'high_recall':profiles['high_recall'],'balanced':profiles['balanced']}),flush=True)
    manifest['decision_policy']='80% validation recall target; lowest alert volume that meets target. Optional balanced F1 profile.'
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2));(folder/'progress.json').write_text(json.dumps(manifest['reports'],indent=2))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('folder');a=p.parse_args();refresh(a.source,a.folder)
