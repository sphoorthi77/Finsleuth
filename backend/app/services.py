from pathlib import Path
import hashlib,json
import pandas as pd
import joblib
from .db import *
from ml.pipeline import features,explain
from ml.data import load_dataset
from functools import lru_cache

def trusted_bundle(model):
    path=Path(model.path)
    if not path.is_file():
        # Bundled models can move with a new release directory; hashes remain authoritative.
        candidate=ROOT/'artifacts/dataset'/path.name
        if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest()==model.digest:path=candidate
        else:raise ValueError('Model artefact missing; administrator must deploy a valid model')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=model.digest:raise ValueError('Model integrity validation failed')
    return joblib.load(path)

def deployed(db,scope):
    dep=db.first(query(Deployment).where(Deployment.scope==scope).order_by(Deployment.created_at.desc()))
    return (db.get(Model,dep.model_id),dep.threshold) if dep else (None,None)

def predict(db,transaction,user):
    model,threshold=deployed(db,user.scope)
    if not model:raise ValueError('No approved model deployed. Ask the administrator to train, approve and deploy a model.')
    previous=db.first(query(Prediction).where(Prediction.transaction_id==transaction.id,Prediction.model_id==model.id,Prediction.threshold==threshold).order_by(Prediction.created_at.desc()))
    if previous:return previous
    b=trusted_bundle(model);explanation=explain(b,transaction.attributes)
    p=Prediction(scope=user.scope,transaction_id=transaction.id,model_id=model.id,score=explanation['score'],threshold=threshold,explanation=explanation)
    db.add(p);db.flush();audit(db,user,'prediction.created',p.id,{'model_id':model.id});db.commit();return p

def import_transactions(db,df,scope,dataset_id):
    def objects():
        for values in df.itertuples(index=False,name=None):
            row=dict(zip(df.columns,values));clean={k:None if pd.isna(v) else v for k,v in row.items()}
            ts=pd.Timestamp(row['transaction_date'])
            if 'transaction_time' in row and pd.notna(row['transaction_time']):
                clock=str(row['transaction_time']);ts=ts.normalize()+pd.to_timedelta(clock+':00' if len(clock.split(':'))==2 else clock)
            yield Transaction(scope=scope,source_id=str(row['transaction_id']),dataset_id=dataset_id,timestamp=ts.isoformat(),amount=float(row['transaction_amount']),channel=str(row.get('channel','Unknown')),customer=str(row.get('customer_id','')),sender=str(row.get('sender_id','')),recipient=str(row.get('recipient_id','')),label=int(row['is_fraud']),attributes=clean)
    if len(df)<=5000:
        for obj in objects():db.add(obj)
        return
    # The entire input has already passed validation. Large imports commit in bounded
    # batches; on failure the dataset is marked failed and its inserted count is audited.
    dataset=db.get(Dataset,dataset_id)
    if not dataset or dataset.scope!=scope:raise ValueError('Dataset scope mismatch')
    batch=[];inserted=0
    try:
        db.flush()
        for obj in objects():
            batch.append({**obj.document(),'_rev':1})
            if len(batch)==2000:
                db._start_write();database.transactions.insert_many(batch,ordered=True,**db.options);db.commit();inserted+=len(batch);batch=[]
        if batch:db._start_write();database.transactions.insert_many(batch,ordered=True,**db.options);db.commit();inserted+=len(batch)
    except Exception:
        if db.mongo_session and db.mongo_session.in_transaction:db.mongo_session.abort_transaction()
        dataset.status='failed';db.commit()
        raise ValueError(f'Import failed after {inserted} confirmed rows. Existing rows were preserved; inspect this dataset version before retrying.')

def seed_demo(db,scope):
    """Idempotent staged repair for new and partially initialized demo workspaces."""
    if not scope.startswith('demo-'):raise ValueError('Demo data requires an isolated scope')
    info=json.loads((ROOT/'artifacts/dataset/manifest.json').read_text())
    for role,name in [('analyst','Aarav · Demo analyst'),('manager','Meera · Demo reviewer'),('admin','Dev · Demo administrator')]:
        if not db.first(query(User).where(User.scope==scope,User.email==role+'@demo.invalid')):
            db.add(User(scope=scope,name=name,email=role+'@demo.invalid',password_hash='demo-no-password-login',role=role,status='active',organisation='Demo bank',reason='Isolated demo persona'))
    if not db.first(query(User).where(User.scope==scope,User.email=='applicant@demo.invalid')):
        db.add(User(scope=scope,name='Riya · Demo applicant',email='applicant@demo.invalid',password_hash='demo-no-password-login',role='analyst',status='pending',organisation='Demo bank',reason='Review financial transaction alerts in the demo'))
    db.flush();admin=db.first(query(User).where(User.scope==scope,User.role=='admin'))
    dataset=db.first(query(Dataset).where(Dataset.scope==scope,Dataset.digest==info['source']['sha256']))
    if not dataset:
        dataset=Dataset(scope=scope,name='Supplied banking archive',source='User-provided archive.zip; source labels retained',path=str(ROOT/'data/archive.zip'),digest=info['source']['sha256'],quality=info['quality'],status='imported');db.add(dataset);db.flush()
    # Demo personas are isolated, so the demo analyst and reviewer are pre-granted the demo dataset.
    demo_users=[u.id for u in db.find(query(User).where(User.scope==scope,User.status=='active')) if u.role in ('analyst','manager')]
    if sorted(dataset.allowed_users or [])!=sorted(demo_users):dataset.allowed_users=demo_users
    candidates=[]
    for report in info['reports']:
        existing=db.first(query(Model).where(Model.scope==scope,Model.algorithm==report['algorithm']))
        if existing:candidates.append(existing);continue
        path=ROOT/'artifacts/dataset'/report['artifact']
        m=Model(scope=scope,dataset_id=dataset.id,algorithm=report['algorithm'],path=str(path),digest=hashlib.sha256(path.read_bytes()).hexdigest(),report=report,threshold=report['threshold'],status='approved');db.add(m);candidates.append(m)
    db.flush();best=next((m for m in candidates if m.algorithm.startswith('Hybrid')),None) or max(candidates,key=lambda m:m.report['validation_pr_auc'])
    if not db.first(query(Deployment).where(Deployment.scope==scope)):
        db.add(Deployment(scope=scope,model_id=best.id,actor_id=admin.id,threshold=best.threshold));db.flush()
    sample=workspace_records().iloc[::4].copy()
    existing=set(db.find(query(Transaction.source_id).where(Transaction.scope==scope)))
    missing=sample[~sample.transaction_id.astype(str).isin(existing)]
    if len(missing):import_transactions(db,missing,scope,dataset.id);db.flush()
    rows=list(db.find(query(Transaction).where(Transaction.scope==scope).order_by(Transaction.source_id)))
    scored=set(db.find(query(Prediction.transaction_id).where(Prediction.scope==scope)))
    pending=[t for t in rows if t.id not in scored]
    if pending:
        bundle=trusted_bundle(best);scores=bundle['pipeline'].predict_proba(features(pd.DataFrame([t.attributes for t in pending])))[:,1]
        for t,score in zip(pending,scores):db.add(Prediction(scope=scope,transaction_id=t.id,model_id=best.id,score=float(score),threshold=best.threshold,explanation={'method':'not computed','contributions':[]}))
    if not db.first(query(Case).where(Case.scope==scope)):seed_demo_cases(db,scope,rows)
    db.flush()
    for person in db.find(query(User).where(User.scope==scope,User.status=='active')):
        if not db.first(query(Notification).where(Notification.scope==scope,Notification.user_id==person.id)):
            db.add(Notification(scope=scope,user_id=person.id,message='Your demo workspace is ready. Explore the supplied records and example investigations.',link='/app'))
    if not db.first(query(Audit).where(Audit.scope==scope,Audit.action=='demo.ready')):
        audit(db,admin,'demo.ready',scope,{'models':len(candidates),'transaction_rows':len(rows),'purpose':'Isolated demonstration prepared; sample cases are illustrative'})
    db.commit()

@lru_cache(maxsize=1)
def workspace_records():
    # Source records only. Sample selected chronologically, never by fraud label.
    df=load_dataset(ROOT/'data/archive.zip')
    return df.sort_values(['transaction_date','transaction_time'],kind='stable').tail(2000).copy()


def seed_demo_cases(db,scope,rows):
    """Clearly labelled workflow examples, only inside isolated demo accounts."""
    from datetime import timedelta,datetime,timezone
    if not scope.startswith('demo-'):raise ValueError('Example cases are restricted to demo scopes')
    analyst=db.first(query(User).where(User.scope==scope,User.role=='analyst',User.status=='active'))
    manager=db.first(query(User).where(User.scope==scope,User.role=='manager',User.status=='active'))
    titles=['Large transfer context review','Unusual channel activity','Account history verification','High-value payment review','Customer clarification pending','Transaction evidence completed','Repeat payment assessment','Escalated account review']
    stages=['submitted','submitted','returned','approved','draft','closed','submitted','escalated']
    for i,(title,stage) in enumerate(zip(titles,stages)):
        stamp=(datetime.now(timezone.utc)-timedelta(days=8-i)).isoformat()
        case=Case(scope=scope,title='Demo · '+title,reason='Illustrative investigation scenario linked to a supplied dataset transaction. Not a real finding of fraud.',status=stage,priority='high' if i%3==0 else 'medium',due_date=(datetime.now(timezone.utc)+timedelta(days=i-2)).date().isoformat(),owner_id=analyst.id,creator_id=analyst.id,created_at=stamp,updated_at=stamp,submitted_at=stamp if stage!='draft' else '')
        db.add(case);db.flush();t=rows[i]
        db.add(CaseTransaction(scope=scope,case_id=case.id,transaction_id=t.id))
        db.add(Note(scope=scope,case_id=case.id,author_id=analyst.id,text='DEMO SCENARIO: inspect the recorded amount, source label and model score separately before reaching a conclusion. This example note is not a bank investigation.',created_at=stamp))
        db.add(Evidence(scope=scope,case_id=case.id,author_id=analyst.id,kind='transaction',reference=t.id,description='Original dataset transaction linked to a demonstration workflow. No source facts changed.'))
        if stage in ['returned','approved','closed','escalated']:
            db.add(Review(scope=scope,case_id=case.id,reviewer_id=manager.id,decision=stage,rationale='DEMO REVIEW: illustrative decision for testing the review workflow, not a determination about the customer.',created_at=(datetime.fromisoformat(stamp)+timedelta(hours=4+i)).isoformat()))
        db.add(Audit(scope=scope,actor_id=analyst.id,action='case.demo_example',object_id=case.id,details={'illustrative':True},created_at=stamp))
        if stage=='submitted':db.add(Notification(scope=scope,user_id=manager.id,message='Demo review ready: '+title,link='/app/cases/'+case.id))
