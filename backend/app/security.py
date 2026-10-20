import hashlib,secrets,time,os
from collections import defaultdict,deque
from fastapi import Depends,HTTPException,Request,Response
from argon2 import PasswordHasher
from .db import get_db,User,Session,Dataset,Transaction,CaseTransaction,query,audit
ph=PasswordHasher();attempts=defaultdict(deque)
def digest(token):return hashlib.sha256(token.encode()).hexdigest()
def rate_limit(key,limit=20,seconds=60):
    q=attempts[key];t=time.time()
    while q and q[0]<t-seconds:q.popleft()
    if len(q)>=limit:raise HTTPException(429,'Too many requests. Please try again shortly.')
    q.append(t)
def issue(db,user,response):
    token=secrets.token_urlsafe(48);db.add(Session(id=digest(token),user_id=user.id,expires=time.time()+28800));db.commit()
    response.set_cookie('fs_session',token,httponly=True,samesite='strict',secure=os.getenv('COOKIE_SECURE','false')=='true',max_age=28800,path='/')
def current(request:Request,db=Depends(get_db)):
    token=request.cookies.get('fs_session','');session=db.get(Session,digest(token))
    if not session or session.expires<time.time():raise HTTPException(401,'Please sign in again')
    user=db.get(User,session.user_id)
    if not user or user.status!='active':raise HTTPException(403,'Account is not active')
    return user
def roles(*allowed):
    def check(u=Depends(current)):
        if u.role not in allowed:raise HTTPException(403,'Your role cannot perform this action')
        return u
    return check
def scoped(db,cls,id,user):
    obj=db.get(cls,id)
    if not obj or obj.scope!=user.scope:raise HTTPException(404,'Record not found')
    return obj

# ---- Administrator-controlled dataset access (Bank Analysts and Compliance Managers) ----
def granted_dataset_ids(db,user):
    """Dataset ids this user was explicitly granted by an administrator (same workspace only)."""
    if user.role not in ('analyst','manager'):return []
    return [d.id for d in db.find(query(Dataset).where(Dataset.scope==user.scope)) if user.id in (d.allowed_users or [])]
def transaction_allowed(db,t,user,granted=None):
    granted=granted_dataset_ids(db,user) if granted is None else granted
    return bool(t.dataset_id) and t.dataset_id in granted
def scoped_tx(db,id,user):
    """Transaction lookup that also enforces dataset access. Returns 404 so inaccessible records are not revealed."""
    t=scoped(db,Transaction,id,user)
    if not transaction_allowed(db,t,user):raise HTTPException(404,'Record not found')
    return t
def case_dataset_visible(db,case,user,granted=None):
    """A case is visible only when every transaction attached to it belongs to a dataset the user may access."""
    granted=granted_dataset_ids(db,user) if granted is None else granted
    links=db.find(query(CaseTransaction).where(CaseTransaction.case_id==case.id))
    if not links:return False
    for link in links:
        t=db.get(Transaction,link.transaction_id)
        if not t or not t.dataset_id or t.dataset_id not in granted:return False
    return True
