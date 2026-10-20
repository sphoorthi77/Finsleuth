"""Trusted local setup: install bundled source models and 2,000 unchanged source rows."""
import argparse,hashlib,json
from .db import *
from .services import workspace_records,import_transactions,trusted_bundle
from ml.pipeline import features

def load_source(email):
    with MongoUnitOfWork() as db:
        admin=db.first(query(User).where(User.scope=='operational',User.email==email,User.role=='admin',User.status=='active'))
        if not admin:raise ValueError('Create the operational administrator first')
        info=json.loads((ROOT/'artifacts/dataset/manifest.json').read_text())
        dataset=db.first(query(Dataset).where(Dataset.scope=='operational',Dataset.digest==info['source']['sha256']))
        df=workspace_records()
        quality={**info['quality'],'imported_rows':len(df),'import_scope':'Latest 2000 unchanged source records; full archive available for import'}
        if not dataset:
            dataset=Dataset(scope='operational',name='Supplied archive — latest 2,000 records',source='Original user-supplied archive.zip; local development bootstrap',path=str(ROOT/'data/archive.zip'),digest=info['source']['sha256'],quality=quality,status='imported');db.add(dataset);db.flush()
        if db.first(query(Model).where(Model.scope=='operational')) and db.first(query(Deployment).where(Deployment.scope=='operational')):
            print('Source workspace already initialized. Existing work and deployment preserved.');return
        models=[]
        for report in info['reports']:
            path=ROOT/'artifacts/dataset'/report['artifact']
            model=Model(scope='operational',dataset_id=dataset.id,algorithm=report['algorithm'],path=str(path),digest=hashlib.sha256(path.read_bytes()).hexdigest(),report=report,threshold=report['threshold'],status='approved');db.add(model);models.append(model)
        db.flush();best=max(models,key=lambda x:x.report['validation_pr_auc']);bundle=trusted_bundle(best)
        scores=bundle['pipeline'].predict_proba(features(df))[:,1]
        db.add(Deployment(scope='operational',model_id=best.id,actor_id=admin.id,threshold=best.threshold))
        existing=set(db.find(query(Transaction.source_id).where(Transaction.scope=='operational')))
        missing=df[~df.transaction_id.astype(str).isin(existing)]
        import_transactions(db,missing,'operational',dataset.id);db.flush();by_id=dict(zip(df.transaction_id.astype(str),scores))
        scored=set(db.find(query(Prediction.transaction_id).where(Prediction.scope=='operational')))
        for transaction in db.find(query(Transaction).where(Transaction.scope=='operational',Transaction.dataset_id==dataset.id)):
            if transaction.source_id not in by_id or transaction.id in scored:continue
            db.add(Prediction(scope='operational',transaction_id=transaction.id,model_id=best.id,score=float(by_id[transaction.source_id]),threshold=best.threshold,explanation={'method':'not computed','contributions':[]}))
        audit(db,admin,'setup.source_bundle',dataset.id,{'rows':len(df),'source_rows':info['source']['rows'],'reason':'Explicit trusted local setup of supplied artifacts; high-recall setting has many false alarms'});db.commit()
        print('Registered bundled models and 2000 unchanged source records. No example cases were added to operational data.')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--admin-email',required=True);args=parser.parse_args();init_db();load_source(args.admin_email)
