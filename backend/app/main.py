import asyncio
import logging
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, DuplicateKeyError
from .scheduler import scheduler_loop
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request,Depends
from fastapi.responses import JSONResponse
from datetime import datetime,timezone
from .db import *
from .security import current,granted_dataset_ids,case_dataset_visible
from . import auth,transactions,cases,admin,operations
@asynccontextmanager
async def lifespan(app):
    # Create MongoDB indexes and detect replica-set transaction support.
    for attempt in range(6):
        try:init_db();break
        except ConnectionFailure:
            if attempt==5:raise RuntimeError("MongoDB unavailable. Start MongoDB or check MONGODB_URI, credentials and Atlas network access.")
            await asyncio.sleep(2)
    with MongoUnitOfWork() as db:
        for job in db.find(query(TrainingJob).where(TrainingJob.status=='running')):job.status='failed';job.error='Server restarted during training. Please restart the job.';job.completed_at=now()
        db.commit()
    task=asyncio.create_task(scheduler_loop())
    try:yield
    finally:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
app=FastAPI(title='Finsleuth API',version='0.1.0',lifespan=lifespan)
@app.exception_handler(ConnectionFailure)
async def database_unavailable(request,exc):
    logging.getLogger(__name__).error('MongoDB connectivity failed: %s',type(exc).__name__)
    return JSONResponse({'detail':'MongoDB is unavailable. Check the database service or connection settings, then retry.'},503)
@app.exception_handler(DuplicateKeyError)
async def duplicate_record(request,exc):
    return JSONResponse({'detail':'This record already exists. Refresh the page before retrying.'},409)
@app.middleware('http')
async def protect(request:Request,call_next):
    if request.method in ['POST','PATCH','DELETE','PUT'] and request.headers.get('x-finsleuth')!='1':return JSONResponse({'detail':'Missing request verification header'},403)
    response=await call_next(request);response.headers['X-Content-Type-Options']='nosniff';response.headers['Cache-Control']='no-store';return response
for router in [auth.router,transactions.router,cases.router,admin.router,operations.router]:app.include_router(router)
@app.get('/api/v1/health')
def public_health():
    database.command('ping')
    return {'status':'available','database':'connected'}
@app.get('/api/v1/overview')
def overview(start:str="",end:str="",channel:str="",user=Depends(current),db=Depends(get_db)):
    if user.role=='admin':
        users=list(db.find(query(User).where(User.scope==user.scope)))
        return {'metrics':[{'label':'Pending approvals','value':sum(u.status=='pending' for u in users),'to':'users'},{'label':'Active users','value':sum(u.status=='active' for u in users),'to':'users'},{'label':'Dataset versions','value':len(list(db.find(query(Dataset).where(Dataset.scope==user.scope)))),'to':'datasets'},{'label':'Model candidates','value':len(list(db.find(query(Model).where(Model.scope==user.scope)))),'to':'models'}]}
    selection=query(Case).where(Case.scope==user.scope)
    if user.role=='analyst':selection=selection.where(Case.owner_id==user.id)
    granted=granted_dataset_ids(db,user);cs=[c for c in db.find(selection) if case_dataset_visible(db,c,user,granted)];counts={s:sum(c.status==s for c in cs) for s in ['draft','submitted','returned','approved','closed','escalated']}
    if user.role=='manager':
        workload={}
        for c in cs:
            name=db.get(User,c.owner_id).name;workload[name]=workload.get(name,0)+int(c.status!='closed')
        turn=[]
        for c in cs:
            rev=db.first(query(Review).where(Review.case_id==c.id).order_by(Review.created_at))
            if rev and c.submitted_at and rev.created_at>=c.submitted_at:turn.append((datetime.fromisoformat(rev.created_at)-datetime.fromisoformat(c.submitted_at)).total_seconds()/3600)
        return {'metrics':[{'label':'Awaiting review','value':counts['submitted'],'to':'cases'},{'label':'Returned for evidence','value':counts['returned'],'to':'cases'},{'label':'Escalations','value':counts['escalated'],'to':'cases'},{'label':'Closed cases','value':counts['closed'],'to':'cases'}],'status':counts,'workload':workload,'review_hours':sum(turn)/len(turn) if turn else None,'overdue':sum(bool(c.due_date and c.due_date<now()[:10] and c.status!='closed') for c in cs)}
    selection=query(Transaction).where(Transaction.scope==user.scope,Transaction.dataset_id.in_(granted))
    if start:selection=selection.where(Transaction.timestamp>=start)
    if end:selection=selection.where(Transaction.timestamp<=end+'T23:59:59')
    if channel:selection=selection.where(Transaction.channel==channel)
    ts=list(db.find(selection));preds=transactions.latest(db,user.scope);trend={};channels={}
    for t in ts:
        day=t.timestamp[:10];trend.setdefault(day,{'date':day,'labelled':0,'flagged':0,'transactions':0});trend[day]['transactions']+=1;trend[day]['labelled']+=t.label
        p=preds.get(t.id);trend[day]['flagged']+=int(p is not None and p.score>=p.threshold);channels[t.channel]=channels.get(t.channel,0)+1
    return {'metrics':[{'label':'Recorded transactions','value':len(ts),'to':'transactions'},{'label':'Model-flagged records','value':sum(t.id in preds and preds[t.id].score>=preds[t.id].threshold for t in ts),'to':'transactions?risk=flagged'},{'label':'My open cases','value':sum(c.status!='closed' for c in cs),'to':'cases'},{'label':'Returned for evidence','value':counts['returned'],'to':'cases'}],'trend':list(trend.values()),'channels':channels,'status':counts}

# Serve the production frontend and backend from one origin, including SPA routes.
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
_frontend=ROOT/'frontend/dist'
if (_frontend/'index.html').is_file():
    app.mount('/assets',StaticFiles(directory=_frontend/'assets'),name='assets')
    @app.get('/{path:path}',include_in_schema=False)
    def frontend(path:str):
        if path.startswith('api/'):
            return JSONResponse({'detail':'Endpoint not found'},404)
        candidate=(_frontend/path).resolve()
        if candidate.is_relative_to(_frontend.resolve()) and candidate.is_file():return FileResponse(candidate)
        return FileResponse(_frontend/'index.html')
