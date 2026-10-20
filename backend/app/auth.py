from fastapi import APIRouter,Depends,Request,Response,HTTPException
from pydantic import BaseModel,Field
from typing import Literal
from .db import *
from .security import *
router=APIRouter(prefix='/api/v1')
class Register(BaseModel):
    name:str=Field(min_length=2,max_length=100);email:str=Field(min_length=5,max_length=150);password:str=Field(min_length=12,max_length=200)
    role:Literal['analyst','manager']='analyst';organisation:str=Field(min_length=2,max_length=150);reason:str=Field(min_length=5,max_length=1000)
class Login(BaseModel):email:str;password:str
@router.post('/auth/register')
def register(data:Register,request:Request,db=Depends(get_db)):
    rate_limit('register:'+request.client.host,10)
    email=data.email.strip().lower()
    if '@' not in email or '.' not in email.split('@')[-1]:raise HTTPException(422,'Enter a valid email')
    if db.first(query(User).where(User.scope=='operational',User.email==email)):raise HTTPException(409,'Email already registered')
    user=User(name=data.name,email=email,password_hash=ph.hash(data.password),role=data.role,organisation=data.organisation,reason=data.reason);db.add(user);db.flush();audit(db,user,'registration.pending',user.id);db.commit()
    return {'message':'Registration submitted. Administrator approval is required before sign-in.'}
@router.post('/auth/login')
def login(data:Login,request:Request,response:Response,db=Depends(get_db)):
    rate_limit('login:'+request.client.host,20)
    user=db.first(query(User).where(User.scope=='operational',User.email==data.email.strip().lower()))
    try:
        if not user:raise ValueError()
        ph.verify(user.password_hash,data.password)
    except Exception:raise HTTPException(401,'Email or password is incorrect')
    if user.status!='active':raise HTTPException(403,f'Your account is {user.status}; administrator approval is required')
    issue(db,user,response);audit(db,user,'auth.login',user.id);db.commit();return serialize(user)
@router.get('/auth/me')
def me(user=Depends(current)):return serialize(user)
@router.post('/auth/logout')
def logout(request:Request,response:Response,db=Depends(get_db)):
    session=db.get(Session,digest(request.cookies.get('fs_session','')))
    if session:db.delete(session);db.commit()
    response.delete_cookie('fs_session');return {'message':'Signed out'}
class DemoPersona(BaseModel):role:Literal['analyst','manager','admin']
@router.post('/auth/demo')
def demo(data:DemoPersona,request:Request,response:Response,db=Depends(get_db)):
    rate_limit('demo:'+request.client.host,15)
    if os.getenv('DEMO_ENABLED','true')!='true':raise HTTPException(403,'Demo disabled')
    token=request.cookies.get('fs_session','');session=db.get(Session,digest(token));previous=db.get(User,session.user_id) if session and session.expires>time.time() else None
    scope=previous.scope if previous and previous.scope.startswith('demo-') else 'demo-'+uid()
    from .services import seed_demo
    seed_demo(db,scope)
    user=db.first(query(User).where(User.scope==scope,User.email==data.role+'@demo.invalid'));issue(db,user,response);return serialize(user)
class UserDecision(BaseModel):
    status:Literal['active','rejected','suspended','deactivated'];role:Literal['analyst','manager','admin'];reason:str=Field(min_length=5,max_length=1000)
@router.get('/admin/users')
def users(q:str='',user=Depends(roles('admin')),db=Depends(get_db)):
    return [serialize(u) for u in db.find(query(User).where(User.scope==user.scope).order_by(User.created_at.desc())) if q.lower() in (u.name+' '+u.email).lower()]
@router.patch('/admin/users/{id}')
def update_user(id:str,data:UserDecision,user=Depends(roles('admin')),db=Depends(get_db)):
    obj=scoped(db,User,id,user)
    if obj.id==user.id:raise HTTPException(400,'Self changes to access or role are not permitted')
    old={'status':obj.status,'role':obj.role};obj.status=data.status;obj.role=data.role
    for s in db.find(query(Session).where(Session.user_id==id)):db.delete(s)
    audit(db,user,'user.access',id,{'before':old,'after':data.model_dump()});db.commit();return serialize(obj)
