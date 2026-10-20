from ml.data import load_dataset
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Form,BackgroundTasks
from pydantic import BaseModel,Field
import hashlib,io,traceback,json
import pandas as pd
from .db import *
from .security import *
from .services import trusted_bundle,import_transactions,deployed
from ml.pipeline import validate,train,features
router=APIRouter(prefix='/api/v1')
import json as _json
def parse_user_ids(db,user,raw):
    """Accept a JSON list or comma-separated ids; only active Bank Analysts / Compliance Managers of this workspace."""
    raw=(raw or '').strip()
    if not raw:return []
    try:ids=_json.loads(raw) if raw.startswith('[') else [x.strip() for x in raw.split(',') if x.strip()]
    except ValueError:raise HTTPException(422,'Invalid user list')
    return validate_user_ids(db,user,ids)
def validate_user_ids(db,user,ids):
    if not isinstance(ids,list) or not all(isinstance(i,str) for i in ids):raise HTTPException(422,'Invalid user list')
    result=[]
    for i in dict.fromkeys(ids):
        u=db.get(User,i)
        if not u or u.scope!=user.scope or u.status!='active' or u.role not in ('analyst','manager'):raise HTTPException(422,'Access can only be granted to active Bank Analysts and Compliance Managers')
        result.append(i)
    return result
def access_names(db,ids):
    out={}
    for i in ids:
        u=db.get(User,i);out[i]=(u.name+' ('+u.role+')') if u else i
    return out
@router.get('/admin/access-users')
def access_users(user=Depends(roles('admin')),db=Depends(get_db)):
    return [{'id':u.id,'name':u.name,'email':u.email,'role':u.role} for u in db.find(query(User).where(User.scope==user.scope,User.status=='active')) if u.role in ('analyst','manager')]
@router.get('/admin/datasets/{id}/access')
def get_access(id:str,user=Depends(roles('admin')),db=Depends(get_db)):
    d=scoped(db,Dataset,id,user);return {'dataset_id':id,'user_ids':list(d.allowed_users or [])}
class AccessUpdate(BaseModel):user_ids:list[str]
@router.put('/admin/datasets/{id}/access')
def set_access(id:str,data:AccessUpdate,user=Depends(roles('admin')),db=Depends(get_db)):
    d=scoped(db,Dataset,id,user);new=validate_user_ids(db,user,data.user_ids);old=list(d.allowed_users or [])
    added=[i for i in new if i not in old];removed=[i for i in old if i not in new]
    if added or removed:
        d.allowed_users=new
        audit(db,user,'dataset.access_granted' if added and not removed else 'dataset.access_revoked' if removed and not added else 'dataset.access_changed',id,{'previous':old,'current':new,'added':added,'removed':removed,'users':access_names(db,list(dict.fromkeys(old+new))),'context':'update'});db.commit()
    return {'dataset_id':id,'user_ids':new,'added':added,'removed':removed}
@router.get('/admin/datasets')
def datasets(user=Depends(roles('admin')),db=Depends(get_db)):return [serialize(d) for d in db.find(query(Dataset).where(Dataset.scope==user.scope).order_by(Dataset.created_at.desc()))]
@router.post('/admin/datasets')
async def upload(file:UploadFile=File(...),source:str=Form(...),access_user_ids:str=Form(''),user=Depends(roles('admin')),db=Depends(get_db)):
    rate_limit('upload:'+user.id,5)
    grant=parse_user_ids(db,user,access_user_ids)
    if not file.filename.lower().endswith(('.csv','.zip')):raise HTTPException(422,'Upload a CSV or a ZIP containing one CSV')
    data=await file.read(150*1024*1024+1)
    if len(data)>150*1024*1024:raise HTTPException(413,'Dataset upload must be under 150 MB')
    id=uid();extension=Path(file.filename).suffix.lower();path=RUNTIME/(id+extension);path.write_bytes(data)
    try:df=load_dataset(path)
    except Exception:raise HTTPException(422,'Unable to parse CSV')
    quality=validate(df)
    d=Dataset(id=id,scope=user.scope,name=file.filename[:200],source=source[:1000],path=str(path),digest=hashlib.sha256(data).hexdigest(),quality=quality,status='validated' if quality['valid'] else 'rejected',allowed_users=grant);db.add(d);audit(db,user,'dataset.validated',id,{'valid':quality['valid']})
    audit(db,user,'dataset.access_granted',id,{'previous':[],'current':grant,'added':grant,'removed':[],'users':access_names(db,grant),'context':'upload'});db.commit();return serialize(d)
@router.post('/admin/datasets/{id}/import')
def confirm(id:str,user=Depends(roles('admin')),db=Depends(get_db)):
    d=scoped(db,Dataset,id,user)
    if d.status!='validated':raise HTTPException(409,'Dataset must be valid and not previously imported')
    df=load_dataset(d.path)
    existing=set(db.find(query(Transaction.source_id).where(Transaction.scope==user.scope)))
    if existing.intersection(df.transaction_id.astype(str)):raise HTTPException(409,'Transaction IDs already exist. No records imported.')
    import_transactions(db,df,user.scope,id);d.status='imported';audit(db,user,'dataset.imported',id,{'rows':len(df)});db.commit();return {'message':f'{len(df)} rows imported; 0 dropped'}
def training_worker(job_id,actor_id):
    with MongoUnitOfWork() as db:
        job=db.get(TrainingJob,job_id);dataset=db.get(Dataset,job.dataset_id);user=db.get(User,actor_id)
        try:
            output=RUNTIME/job.id;reports=train(dataset.path,output)
            for report in reports:
                path=output/report['artifact'];db.add(Model(scope=job.scope,dataset_id=dataset.id,algorithm=report['algorithm'],path=str(path),digest=hashlib.sha256(path.read_bytes()).hexdigest(),report=report,threshold=report['threshold']))
            job.status='completed';audit(db,user,'training.completed',job.id)
        except Exception as exc:
            job.status='failed';job.error=str(exc)[:500];audit(db,user,'training.failed',job.id,{'error':job.error})
        job.completed_at=now();db.commit()
@router.post('/admin/datasets/{id}/train')
def start_train(id:str,background:BackgroundTasks,user=Depends(roles('admin')),db=Depends(get_db)):
    rate_limit('train:'+user.id,2,300);d=scoped(db,Dataset,id,user)
    if not d.quality['valid']:raise HTTPException(422,'Dataset is invalid')
    if db.first(query(TrainingJob).where(TrainingJob.scope==user.scope,TrainingJob.status=='running')):raise HTTPException(409,'A training job is already running')
    job=TrainingJob(scope=user.scope,dataset_id=id,status='running');db.add(job);db.flush();audit(db,user,'training.started',job.id);db.commit();background.add_task(training_worker,job.id,user.id);return serialize(job)
@router.get('/admin/jobs')
def jobs(user=Depends(roles('admin')),db=Depends(get_db)):return [serialize(j) for j in db.find(query(TrainingJob).where(TrainingJob.scope==user.scope).order_by(TrainingJob.created_at.desc()))]
@router.get('/models')
def models(user=Depends(roles('admin')),db=Depends(get_db)):
    model,threshold=deployed(db,user.scope);q=query(Model).where(Model.scope==user.scope)
    if user.role=='manager':q=q.where(Model.status=='approved')
    return {'items':[serialize(m) for m in db.find(q)],'active_id':model.id if model else None,'threshold':threshold,'deployments':[serialize(d) for d in db.find(query(Deployment).where(Deployment.scope==user.scope).order_by(Deployment.created_at.desc()))]}
class ModelAction(BaseModel):reason:str=Field(min_length=10,max_length=1000);threshold:float|None=Field(default=None,gt=0,lt=1)
@router.post('/admin/models/{id}/approve')
def approve(id:str,data:ModelAction,user=Depends(roles('admin')),db=Depends(get_db)):
    m=scoped(db,Model,id,user)
    if not m.report.get('metrics'):raise HTTPException(422,'Evaluation missing')
    try:trusted_bundle(m)
    except ValueError as e:raise HTTPException(409,str(e))
    m.status='approved';audit(db,user,'model.approved',id,data.model_dump());db.commit();return serialize(m)
@router.post('/admin/models/{id}/deploy')
def deploy(id:str,data:ModelAction,user=Depends(roles('admin')),db=Depends(get_db)):
    m=scoped(db,Model,id,user)
    if m.status!='approved':raise HTTPException(409,'Approve model before deployment')
    try:
        b=trusted_bundle(m);scores=b['pipeline'].predict_proba(b['reference'].iloc[:1]);assert scores.shape==(1,2)
    except Exception:raise HTTPException(409,'Model smoke test failed; previous deployment retained')
    previous,_=deployed(db,user.scope);threshold=data.threshold or m.threshold
    db.add(Deployment(scope=user.scope,model_id=id,actor_id=user.id,threshold=threshold));audit(db,user,'model.deployed',id,{'previous':previous.id if previous else None,**data.model_dump()});db.commit();return {'message':'Model deployed after integrity and inference checks'}
@router.get('/admin/health')
def health(user=Depends(roles('admin')),db=Depends(get_db)):
    db.ping();model,_=deployed(db,user.scope);loaded=False
    if model:
        try:trusted_bundle(model);loaded=True
        except Exception:pass
    return {'api':'available','database':'connected','engine':'MongoDB','atomic_multi_document_writes':__import__('app.db',fromlist=['USE_TRANSACTIONS']).USE_TRANSACTIONS,'model_integrity':loaded,'model_id':model.id if model else None,'running_jobs':len(list(db.find(query(TrainingJob).where(TrainingJob.scope==user.scope,TrainingJob.status=='running')))),'upload_limit_mb':150,'session_hours':8,'authentication_rate_limit':'20 attempts per minute per IP','backup_status':'Not configured','demo':user.scope.startswith('demo-')}
@router.get('/audit')
def audit_list(q:str='',date_from:str='',date_to:str='',user=Depends(roles('admin','manager')),db=Depends(get_db)):
    from datetime import date,timedelta
    selection=query(Audit).where(Audit.scope==user.scope)
    if user.role=='manager':selection=selection.where(Audit.action.like('case.%'))
    if q:selection=selection.where(Audit.action.ilike('%'+q+'%'))
    try:
        if date_from:selection=selection.where(Audit.created_at>=date.fromisoformat(date_from).isoformat())
        if date_to:selection=selection.where(Audit.created_at<(date.fromisoformat(date_to)+timedelta(days=1)).isoformat())
        if date_from and date_to and date_from>date_to:raise ValueError()
    except ValueError:raise HTTPException(422,'Use valid dates with the start on or before the end')
    result=[]
    for event in db.find(selection.order_by(Audit.created_at.desc()).limit(200)):
        # Legacy seed events are retained for traceability, but never appear as real actions.
        illustrative=event.action=='case.demo_example' or bool(event.details.get('illustrative'))
        if illustrative and not user.scope.startswith('demo-'):continue
        actor=db.get(User,event.actor_id) if event.actor_id else None
        case=db.get(Case,event.object_id) if event.action.startswith('case.') else None
        row=serialize(event)
        row['actor_name']=actor.name if actor and actor.scope==user.scope else 'System' if not event.actor_id else 'Recorded user '+event.actor_id
        row['object_title']=case.title if case and case.scope==user.scope else event.object_id
        row['case_id']=case.id if case and case.scope==user.scope else None
        row['demonstration']=user.scope.startswith('demo-')
        row['description']='Demonstration case prepared' if illustrative else event.action.replace('.', ' · ').replace('_',' ').capitalize()
        result.append(row)
    return result

@router.post('/admin/datasets/{id}/score')
def score_dataset(id:str,user=Depends(roles('admin')),db=Depends(get_db)):
    """Bounded, restartable inference batches; never train or alter source labels."""
    d=scoped(db,Dataset,id,user)
    if d.status!='imported':raise HTTPException(409,'Import this dataset before scoring its records')
    model,threshold=deployed(db,user.scope)
    if not model:raise HTTPException(409,'Deploy an approved model before scoring')
    try:bundle=trusted_bundle(model)
    except ValueError as exc:raise HTTPException(409,str(exc))
    done=database.predictions.distinct('transaction_id',{'scope':user.scope,'model_id':model.id,'threshold':threshold})
    selection={'scope':user.scope,'dataset_id':id,'_id':{'$nin':done}}
    pending=list(database.transactions.find(selection).sort('_id',1).limit(1000))
    if pending:
        try:scores=bundle['pipeline'].predict_proba(features(pd.DataFrame([t['attributes'] for t in pending])))[:,1]
        except Exception:raise HTTPException(422,'Dataset features are incompatible with the deployed model. Check its feature schema.')
        for t,score in zip(pending,scores):db.add(Prediction(scope=user.scope,transaction_id=t['_id'],model_id=model.id,score=float(score),threshold=threshold,explanation={'method':'not computed','contributions':[]}))
        audit(db,user,'dataset.scored',id,{'rows':len(pending),'model_id':model.id});db.commit()
    remaining=max(0,database.transactions.count_documents(selection)-len(pending))
    return {'processed':len(pending),'remaining':remaining,'message':f'{len(pending)} records scored; {remaining} remaining. Analysts can inspect saved scores and request explanations.'}
