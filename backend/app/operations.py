"""Alerts, private evidence attachments, reports, profile and workflow operations."""
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Request,Response
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from typing import Literal
import csv,io,json,hashlib,time,secrets,os
from datetime import datetime,timezone,timedelta
from pathlib import Path
from .db import *
from .security import current,roles,scoped,scoped_tx,granted_dataset_ids,case_dataset_visible,ph,digest,issue,rate_limit
from .cases import case_access,case_detail
router=APIRouter(prefix='/api/v1')

class AlertEdit(BaseModel):status:Literal['open','investigating','resolved'];assign_to_self:bool=True
@router.patch('/transactions/{id}/alert')
def update_alert(id:str,data:AlertEdit,user=Depends(roles('analyst')),db=Depends(get_db)):
    scoped_tx(db,id,user);a=db.first(query(Alert).where(Alert.scope==user.scope,Alert.transaction_id==id))
    if not a:a=Alert(scope=user.scope,transaction_id=id);db.add(a)
    if a.owner_id and a.owner_id!=user.id:raise HTTPException(403,'Alert assigned to another analyst')
    a.status=data.status;a.owner_id=user.id if data.assign_to_self else a.owner_id;a.updated_at=now();audit(db,user,'alert.updated',id,data.model_dump());db.commit();return serialize(a)
@router.get('/transactions/{id}/alert')
def alert(id:str,user=Depends(roles('analyst','manager')),db=Depends(get_db)):
    scoped_tx(db,id,user);a=db.first(query(Alert).where(Alert.scope==user.scope,Alert.transaction_id==id));return serialize(a) if a else {'status':'open','owner_id':None}
@router.get('/notifications')
def notifications(user=Depends(current),db=Depends(get_db)):
    return [serialize(n) for n in db.find(query(Notification).where(Notification.scope==user.scope,Notification.user_id==user.id).order_by(Notification.created_at.desc()).limit(100))]
@router.post('/notifications/{id}/read')
def read_notification(id:str,user=Depends(current),db=Depends(get_db)):
    n=scoped(db,Notification,id,user)
    if n.user_id!=user.id:raise HTTPException(403,'Notification belongs to another user')
    n.read=True;db.commit();return {'message':'Marked as read'}

class ProfileEdit(BaseModel):name:str=Field(min_length=2,max_length=100);organisation:str=Field(min_length=2,max_length=150)
@router.patch('/auth/profile')
def profile(data:ProfileEdit,user=Depends(current),db=Depends(get_db)):
    user.name=data.name;user.organisation=data.organisation;audit(db,user,'profile.updated',user.id);db.commit();return serialize(user)
class PasswordEdit(BaseModel):current_password:str;new_password:str=Field(min_length=12,max_length=200)
@router.post('/auth/password')
def password(data:PasswordEdit,response:Response,user=Depends(current),db=Depends(get_db)):
    if user.scope.startswith('demo-'):raise HTTPException(403,'Dataset personas do not have password credentials')
    try:ph.verify(user.password_hash,data.current_password)
    except Exception:raise HTTPException(403,'Current password is incorrect')
    user.password_hash=ph.hash(data.new_password)
    for s in db.find(query(Session).where(Session.user_id==user.id)):db.delete(s)
    audit(db,user,'password.changed',user.id);db.commit();issue(db,user,response);return {'message':'Password changed; other sessions revoked'}
@router.get('/auth/sessions')
def sessions(request:Request,user=Depends(current),db=Depends(get_db)):
    active=digest(request.cookies.get('fs_session',''))
    return [{'id':s.id,'expires':s.expires,'current':s.id==active} for s in db.find(query(Session).where(Session.user_id==user.id,Session.expires>time.time()))]
@router.delete('/auth/sessions/{id}')
def revoke(id:str,user=Depends(current),db=Depends(get_db)):
    s=db.get(Session,id)
    if not s or s.user_id!=user.id:raise HTTPException(404,'Session not found')
    db.delete(s);audit(db,user,'session.revoked',user.id);db.commit();return {'message':'Session revoked'}

@router.post('/cases/{id}/attachments')
async def upload_evidence(id:str,file:UploadFile=File(...),user=Depends(roles('analyst')),db=Depends(get_db)):
    case_access(db,id,user,True);rate_limit('attachment:'+user.id,10)
    raw=await file.read(10*1024*1024+1)
    if len(raw)>10*1024*1024:raise HTTPException(413,'Evidence is limited to 10 MB')
    ext=Path(file.filename or '').suffix.lower();types={'.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.txt':'text/plain','.csv':'text/csv'}
    if ext not in types:raise HTTPException(422,'Allowed evidence: PDF, PNG, JPG, TXT and CSV')
    if ext=='.pdf' and not raw.startswith(b'%PDF-'):raise HTTPException(422,'Invalid PDF signature')
    if ext in ['.png','.jpg','.jpeg']:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(raw)) as im:im.verify()
        except Exception:raise HTTPException(422,'Invalid image')
    if ext in ['.txt','.csv']:
        try:raw.decode('utf-8')
        except UnicodeError:raise HTTPException(422,'Text evidence must use UTF-8')
    folder=RUNTIME/'evidence';folder.mkdir(exist_ok=True);path=folder/(uid()+ext);path.write_bytes(raw)
    a=Attachment(scope=user.scope,case_id=id,author_id=user.id,filename=Path(file.filename).name[:180],path=str(path),digest=hashlib.sha256(raw).hexdigest(),media_type=types[ext],size=len(raw));db.add(a)
    db.add(Evidence(scope=user.scope,case_id=id,author_id=user.id,kind='attachment',reference=a.id,description='Uploaded document: '+a.filename));audit(db,user,'case.attachment_added',id,{'attachment_id':a.id,'sha256':a.digest});db.commit();return serialize(a)
@router.get('/cases/{id}/attachments')
def attachments(id:str,user=Depends(roles('analyst','manager')),db=Depends(get_db)):
    case_access(db,id,user);return [serialize(a) for a in db.find(query(Attachment).where(Attachment.case_id==id))]
@router.get('/attachments/{id}/download')
def download(id:str,user=Depends(roles('analyst','manager')),db=Depends(get_db)):
    a=scoped(db,Attachment,id,user);case_access(db,a.case_id,user)
    if not Path(a.path).is_file() or hashlib.sha256(Path(a.path).read_bytes()).hexdigest()!=a.digest:raise HTTPException(409,'Evidence integrity check failed')
    return FileResponse(a.path,media_type='application/octet-stream',filename=a.filename,headers={'X-Content-Type-Options':'nosniff'})

@router.get('/cases/{id}/report.pdf')
def report_pdf(id:str,user=Depends(roles('analyst','manager')),db=Depends(get_db)):
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from xml.sax.saxutils import escape
    case=case_access(db,id,user);data=case_detail(db,case);stream=io.BytesIO();styles=getSampleStyleSheet();flow=[]
    def paragraph(text,style='BodyText'):flow.append(Paragraph(escape(str(text)),styles[style]));flow.append(Spacer(1,10))
    paragraph('Finsleuth Investigation Report','Title');paragraph(data['title'],'Heading1');paragraph('Reference: '+id);paragraph('Status: '+data['status']+' | Assigned analyst: '+data['owner_name']);paragraph('Risk scores support investigation and are not proof of fraud.');paragraph(data['reason'])
    for t in data['transactions']:
        paragraph(t['source_id']+' | INR '+str(t['amount'])+' | '+t['timestamp'],'Heading2')
        for p in db.find(query(Prediction).where(Prediction.transaction_id==t['id'])):
            paragraph('Model '+p.model_id+' | Score '+str(round(p.score*100,2))+'% | Threshold '+str(p.threshold))
            for feature in p.explanation.get('contributions',[]):paragraph(feature['feature']+': '+str(feature['value'])+'; contribution '+str(round(feature['contribution'],6)))
    for title,items,key in [('Observations',data['notes'],'text'),('Evidence',data['evidence'],'description'),('Review decisions',data['reviews'],'rationale')]:
        paragraph(title,'Heading2')
        for item in items:paragraph(item['created_at']+' — '+item[key])
    paragraph('Exported '+now());SimpleDocTemplate(stream).build(flow);audit(db,user,'case.pdf_exported',id);db.commit()
    return Response(stream.getvalue(),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="Finsleuth-{id[:8]}.pdf"'})
@router.get('/reports/compliance.csv')
def compliance_csv(start:str='',end:str='',user=Depends(roles('analyst','manager')),db=Depends(get_db)):
    q=query(Case).where(Case.scope==user.scope)
    if user.role=='analyst':q=q.where(Case.owner_id==user.id)
    if start:q=q.where(Case.created_at>=start)
    if end:q=q.where(Case.created_at<=end+'T23:59:59')
    output=io.StringIO();w=csv.writer(output);w.writerow(['case_id','title','status','priority','analyst','created_at','due_date','review_count'])
    def safe(v):
        text=str(v);return "'"+text if text.startswith(('=','+','-','@')) else text
    granted=granted_dataset_ids(db,user)
    for c in db.find(q):
        if not case_dataset_visible(db,c,user,granted):continue
        w.writerow([safe(v) for v in [c.id,c.title,c.status,c.priority,db.get(User,c.owner_id).name,c.created_at,c.due_date,len(db.find(query(Review).where(Review.case_id==c.id)))]])
    audit(db,user,'report.csv_exported','compliance');db.commit();return Response(output.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="Finsleuth-compliance.csv"'})
@router.get('/reports/quality')
def quality(user=Depends(roles('manager')),db=Depends(get_db)):
    granted=granted_dataset_ids(db,user);cs=[c for c in db.find(query(Case).where(Case.scope==user.scope)) if case_dataset_visible(db,c,user,granted)];results={'cases':len(cs),'returned_cases':0,'missing_evidence':0,'overdue':0,'closed_with_rationale':0,'review_turnaround_hours':None};hours=[]
    for c in cs:
        reviews=db.find(query(Review).where(Review.case_id==c.id).order_by(Review.created_at))
        results['returned_cases']+=int(any(r.decision=='returned' for r in reviews));results['missing_evidence']+=int(not db.first(query(Evidence).where(Evidence.case_id==c.id)))
        results['overdue']+=int(bool(c.due_date and c.due_date<now()[:10] and c.status!='closed'));results['closed_with_rationale']+=int(c.status=='closed' and any(r.decision=='closed' and r.rationale for r in reviews))
        submitted=db.find(query(Audit).where(Audit.object_id==c.id,Audit.action=='case.submitted').order_by(Audit.created_at))
        for review in reviews:
            earlier=[a for a in submitted if a.created_at<=review.created_at]
            if earlier:hours.append((datetime.fromisoformat(review.created_at)-datetime.fromisoformat(earlier[-1].created_at)).total_seconds()/3600)
    results['review_turnaround_hours']=sum(hours)/len(hours) if hours else None;return results

class PolicyEdit(BaseModel):review_days:int=Field(ge=1,le=365);require_notes:bool=True;retention_days:int=Field(ge=1,le=365)
@router.get('/policy')
def policy(user=Depends(roles('admin','manager')),db=Depends(get_db)):
    p=db.first(query(Policy).where(Policy.scope==user.scope));return serialize(p) if p else {'review_days':7,'require_notes':True,'retention_days':30}
@router.patch('/policy')
def edit_policy(data:PolicyEdit,user=Depends(roles('admin','manager')),db=Depends(get_db)):
    p=db.first(query(Policy).where(Policy.scope==user.scope))
    if not p:p=Policy(scope=user.scope);db.add(p)
    if user.role!='admin' and data.retention_days!=p.retention_days:raise HTTPException(403,'Only administrators can change demo retention')
    for k,v in data.model_dump().items():setattr(p,k,v)
    audit(db,user,'policy.updated',p.id,data.model_dump());db.commit();return serialize(p)
@router.post('/admin/models/{id}/retire')
def retire(id:str,user=Depends(roles('admin')),db=Depends(get_db)):
    from .services import deployed
    m=scoped(db,Model,id,user);active,_=deployed(db,user.scope)
    if active and active.id==id:raise HTTPException(409,'Deploy a replacement before retiring the active model')
    m.status='retired';audit(db,user,'model.retired',id);db.commit();return serialize(m)

class RecoveryRequest(BaseModel):email:str
class RecoveryConfirm(BaseModel):token:str;password:str=Field(min_length=12,max_length=200)
@router.post('/auth/recovery/request')
def recovery_request(data:RecoveryRequest,request:Request,db=Depends(get_db)):
    import smtplib
    from email.message import EmailMessage
    rate_limit('recover:'+request.client.host,5,300)
    if not os.getenv('SMTP_HOST') or not os.getenv('SMTP_FROM'):raise HTTPException(503,'Password recovery email is not configured. Contact your administrator.')
    user=db.first(query(User).where(User.scope=='operational',User.email==data.email.strip().lower(),User.status=='active'))
    if user:
        token=secrets.token_urlsafe(48);db.add(PasswordReset(user_id=user.id,token_hash=digest(token),expires=time.time()+1800));db.commit()
        mail=EmailMessage();mail['Subject']='Finsleuth password recovery';mail['From']=os.environ['SMTP_FROM'];mail['To']=user.email
        base=os.getenv('PUBLIC_URL','http://localhost:8000');mail.set_content('Reset your password within 30 minutes: '+base+'/recover?token='+token+'\nIf you did not request this, ignore this email.')
        try:
            with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','587')),timeout=15) as server:
                server.starttls()
                if os.getenv('SMTP_USER'):server.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
                server.send_message(mail)
        except Exception:raise HTTPException(503,'Recovery email could not be delivered. Please contact your administrator.')
    return {'message':'If an active account matches, a recovery link has been sent.'}
@router.post('/auth/recovery/confirm')
def recovery_confirm(data:RecoveryConfirm,request:Request,db=Depends(get_db)):
    rate_limit('recover-confirm:'+request.client.host,10,300)
    reset=db.first(query(PasswordReset).where(PasswordReset.token_hash==digest(data.token),PasswordReset.used==False,PasswordReset.expires>time.time()))
    if not reset:raise HTTPException(400,'Recovery link is invalid or expired')
    user=db.get(User,reset.user_id)
    if not user or user.status!='active':raise HTTPException(400,'Recovery link is invalid or expired')
    user.password_hash=ph.hash(data.password);reset.used=True
    for session in db.find(query(Session).where(Session.user_id==user.id)):db.delete(session)
    audit(db,user,'password.recovered',user.id);db.commit();return {'message':'Password changed. Sign in with your new password.'}

class ScheduleInput(BaseModel):scheduled_at:datetime
@router.post('/admin/datasets/{id}/schedule')
def schedule(id:str,data:ScheduleInput,user=Depends(roles('admin')),db=Depends(get_db)):
    dataset=scoped(db,Dataset,id,user)
    if not dataset.quality['valid']:raise HTTPException(422,'Dataset validation failed')
    when=data.scheduled_at
    if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
    if when<=datetime.now(timezone.utc):raise HTTPException(422,'Choose a future date and time')
    job=TrainingJob(scope=user.scope,dataset_id=id,status='scheduled',scheduled_at=when.astimezone(timezone.utc).isoformat());db.add(job);audit(db,user,'training.scheduled',job.id,{'scheduled_at':job.scheduled_at});db.commit();return serialize(job)
@router.get('/metadata/transactions')
def transaction_metadata(user=Depends(roles('analyst','manager')),db=Depends(get_db)):
    granted=granted_dataset_ids(db,user);base={'scope':user.scope,'dataset_id':{'$in':granted}}
    return {'channels':sorted(database.transactions.distinct('channel',base)),'has_transfer_relationships':bool(database.transactions.find_one({**base,'sender':{'$ne':''},'recipient':{'$ne':''}}))}
@router.get('/admin/monitoring')
def monitoring(user=Depends(roles('admin')),db=Depends(get_db)):
    import numpy as np
    from ml.pipeline import metrics
    from .transactions import latest
    preds=latest(db,user.scope);rows=db.find(query(Transaction).where(Transaction.scope==user.scope));pairs=[(t,preds[t.id]) for t in rows if t.id in preds]
    result={'records':len(rows),'scored_records':len(pairs),'metrics':None,'warning':'Retrospective metrics against recorded dataset labels; not prospective bank outcomes.','input_shift':{}}
    if pairs:
        labels=np.array([t.label for t,p in pairs]);scores=np.array([p.score for t,p in pairs]);thresholds=np.array([p.threshold for t,p in pairs]);result['flagged']=int((scores>=thresholds).sum())
        if len(set(labels))==2:
            # Report only a single version/threshold together to avoid misleading mixed deployment metrics.
            versions={(p.model_id,p.threshold) for t,p in pairs}
            if len(versions)==1:result['metrics']=metrics(labels,scores,float(thresholds[0]))
            else:result['warning']+=' Mixed model versions/thresholds: aggregate performance suppressed.'
    profile=ROOT/'artifacts/dataset/input_profile.json'
    if profile.exists() and rows:
        baseline=json.loads(profile.read_text());current=[t.amount for t in rows];result['input_shift']={'baseline_mean_amount':baseline['mean_amount'],'current_mean_amount':float(np.mean(current)),'relative_mean_change':float((np.mean(current)-baseline['mean_amount'])/max(baseline['mean_amount'],1)),'interpretation':'Input change alone does not prove model performance degradation.'}
    return result
