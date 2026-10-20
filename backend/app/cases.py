from datetime import timedelta,datetime,timezone,date
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel,Field
from typing import Literal
import json
from .db import *
from .security import *
router=APIRouter(prefix='/api/v1')
class CreateCase(BaseModel):
    title:str=Field(min_length=5,max_length=180);reason:str=Field(min_length=10,max_length=5000);transaction_ids:list[str]=Field(min_length=1,max_length=30);priority:Literal['low','medium','high']='medium';due_date:str=''
class TextInput(BaseModel):text:str=Field(min_length=3,max_length=5000)
class EvidenceInput(BaseModel):kind:Literal['transaction','prediction','account','path'];reference:str=Field(min_length=1,max_length=4000);description:str=Field(min_length=5,max_length=4000)
class Decision(BaseModel):decision:Literal['returned','approved','closed','escalated'];rationale:str=Field(min_length=10,max_length=5000)
class Assignment(BaseModel):owner_id:str;reason:str=Field(min_length=5,max_length=1000);priority:Literal['low','medium','high']='medium';due_date:str=''
def case_access(db,id,user,edit=False):
    c=scoped(db,Case,id,user)
    if user.role=='analyst' and c.owner_id!=user.id:raise HTTPException(403,'Case belongs to another analyst')
    if not case_dataset_visible(db,c,user):raise HTTPException(404,'Record not found')
    if edit and (user.role!='analyst' or c.status not in ['draft','returned']):raise HTTPException(409,'Only the assigned analyst can edit a draft or returned case')
    return c

def case_detail(db,c):
    d=serialize(c);owner=db.get(User,c.owner_id);d['owner_name']=owner.name
    d['transactions']=[serialize(db.get(Transaction,r.transaction_id)) for r in db.find(query(CaseTransaction).where(CaseTransaction.case_id==c.id))]
    for name,cls in [('notes',Note),('evidence',Evidence),('reviews',Review)]:d[name]=[serialize(r) for r in db.find(query(cls).where(cls.case_id==c.id).order_by(cls.created_at))]
    d['audit']=[serialize(r) for r in db.find(query(Audit).where(Audit.object_id==c.id).order_by(Audit.created_at))];return d
@router.get('/cases')
def cases(status:str='',priority:str='',analyst:str='',start:date|None=None,end:date|None=None,sort:str='updated',user=Depends(roles('analyst','manager')),db=Depends(get_db)):
    q=query(Case).where(Case.scope==user.scope)
    if user.role=='analyst':q=q.where(Case.owner_id==user.id)
    if status:q=q.where(Case.status==status)
    if priority:q=q.where(Case.priority==priority)
    if start and end and start>end:raise HTTPException(422,'Start date must be before end date')
    if start:q=q.where(Case.created_at>=start.isoformat())
    if end:q=q.where(Case.created_at<=end.isoformat()+'T23:59:59.999999')
    ordered=q.order_by(Case.created_at if sort=='oldest' else Case.updated_at.desc())
    granted=granted_dataset_ids(db,user)
    rows=[dict(serialize(c),owner_name=db.get(User,c.owner_id).name) for c in db.find(ordered) if case_dataset_visible(db,c,user,granted)]
    return [r for r in rows if analyst.lower() in r['owner_name'].lower()]
@router.post('/cases')
def create(data:CreateCase,user=Depends(roles('analyst')),db=Depends(get_db)):
    for id in data.transaction_ids:scoped_tx(db,id,user)
    policy=db.first(query(Policy).where(Policy.scope==user.scope))
    if not data.due_date:data.due_date=(datetime.now(timezone.utc)+timedelta(days=policy.review_days if policy else 7)).date().isoformat()
    c=Case(scope=user.scope,title=data.title,reason=data.reason,priority=data.priority,due_date=data.due_date,owner_id=user.id,creator_id=user.id);db.add(c);db.flush()
    for id in set(data.transaction_ids):
        db.add(CaseTransaction(scope=user.scope,case_id=c.id,transaction_id=id));db.add(Evidence(scope=user.scope,case_id=c.id,author_id=user.id,kind='transaction',reference=id,description='Primary transaction reference attached on case creation'))
    audit(db,user,'case.created',c.id);db.commit();return serialize(c)
@router.get('/cases/{id}')
def detail(id:str,user=Depends(roles('analyst','manager')),db=Depends(get_db)):return case_detail(db,case_access(db,id,user))
@router.post('/cases/{id}/notes')
def note(id:str,data:TextInput,user=Depends(roles('analyst')),db=Depends(get_db)):
    c=case_access(db,id,user,True);db.add(Note(scope=user.scope,case_id=id,author_id=user.id,text=data.text));c.updated_at=now();audit(db,user,'case.note_added',id);db.commit();return {'message':'Note saved'}
@router.post('/cases/{id}/evidence')
def evidence(id:str,data:EvidenceInput,user=Depends(roles('analyst')),db=Depends(get_db)):
    c=case_access(db,id,user,True)
    if data.kind=='transaction':scoped_tx(db,data.reference,user)
    if data.kind=='prediction':scoped_tx(db,scoped(db,Prediction,data.reference,user).transaction_id,user)
    if data.kind=='account':
        if not db.first(query(Transaction).where(Transaction.scope==user.scope,Transaction.dataset_id.in_(granted_dataset_ids(db,user)),(Transaction.sender==data.reference)|(Transaction.recipient==data.reference)|(Transaction.customer==data.reference))):raise HTTPException(422,'No recorded account found')
    if data.kind=='path':
        ids=data.reference.split(',')
        if not 1<=len(ids)<=6:raise HTTPException(422,'A path must have 1–6 transactions')
        tx=[scoped_tx(db,t.strip(),user) for t in ids]
        for a,b in zip(tx,tx[1:]):
            if a.recipient!=b.sender or a.timestamp>b.timestamp:raise HTTPException(422,'Path must be connected and chronological')
    db.add(Evidence(scope=user.scope,case_id=id,author_id=user.id,**data.model_dump()));c.updated_at=now();audit(db,user,'case.evidence_added',id,data.model_dump());db.commit();return {'message':'Evidence reference saved'}
@router.post('/cases/{id}/submit')
def submit(id:str,user=Depends(roles('analyst')),db=Depends(get_db)):
    c=case_access(db,id,user,True)
    policy=db.first(query(Policy).where(Policy.scope==user.scope))
    if (not policy or policy.require_notes) and not db.first(query(Note).where(Note.case_id==id)):raise HTTPException(422,'Add an investigation note before submitting')
    if not db.first(query(Evidence).where(Evidence.case_id==id)):raise HTTPException(422,'Evidence required')
    c.status='submitted';c.submitted_at=now();c.updated_at=now();audit(db,user,'case.submitted',id,case_detail(db,c));db.commit();return serialize(c)
@router.post('/cases/{id}/review')
def review(id:str,data:Decision,user=Depends(roles('manager')),db=Depends(get_db)):
    c=case_access(db,id,user)
    if c.status not in ['submitted','approved','escalated']:raise HTTPException(409,'Case is not in a reviewable state')
    if c.creator_id==user.id:raise HTTPException(403,'Cannot review your own case')
    old=c.status;c.status=data.decision;c.updated_at=now();db.add(Review(scope=user.scope,case_id=id,reviewer_id=user.id,decision=data.decision,rationale=data.rationale));audit(db,user,'case.reviewed',id,{'previous':old,**data.model_dump()});db.commit();return serialize(c)
@router.get('/analysts')
def analysts(user=Depends(roles('manager')),db=Depends(get_db)):
    return [{'id':u.id,'name':u.name} for u in db.find(query(User).where(User.scope==user.scope,User.role=='analyst',User.status=='active'))]
@router.patch('/cases/{id}/assignment')
def assign(id:str,data:Assignment,user=Depends(roles('manager')),db=Depends(get_db)):
    c=case_access(db,id,user);owner=scoped(db,User,data.owner_id,user)
    if owner.role!='analyst' or owner.status!='active':raise HTTPException(422,'Assign only to an active analyst')
    if c.status=='closed':raise HTTPException(409,'Closed cases cannot be reassigned')
    old=c.owner_id;c.owner_id=owner.id;c.priority=data.priority;c.due_date=data.due_date;c.updated_at=now();audit(db,user,'case.assigned',id,{'previous':old,**data.model_dump()});db.commit();return serialize(c)
@router.get('/cases/{id}/report')
def report(id:str,user=Depends(roles('analyst','manager')),db=Depends(get_db)):
    c=case_access(db,id,user);result=case_detail(db,c);result['notice']='Risk scores are model estimates, not proof of fraud.';result['isolated_dataset_workspace']=user.scope.startswith('demo-')
    tids=[t['id'] for t in result['transactions']];result['predictions']=[serialize(p) for p in db.find(query(Prediction).where(Prediction.transaction_id.in_(tids)))]
    audit(db,user,'case.report_exported',id);db.commit();return Response(json.dumps(result,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="Finsleuth-case-{id[:8]}.json"'})
