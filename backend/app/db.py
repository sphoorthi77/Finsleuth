"""MongoDB persistence with PyMongo.

The small repository query builder compiles filters to native MongoDB queries.
There is no SQLAlchemy, SQL database, or SQL emulation. A request-scoped identity
map tracks document changes. Replica sets/Atlas use atomic multi-document writes;
standalone local MongoDB supports single-document atomic writes only.
"""
import os,uuid,re,copy
from datetime import datetime,timezone
from pathlib import Path
from pymongo import MongoClient,ASCENDING,DESCENDING
from pymongo.errors import DuplicateKeyError
from fastapi import HTTPException
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[2]
load_dotenv(ROOT/'backend/.env')
load_dotenv(ROOT/'.env')
RUNTIME=Path(os.getenv('ARTIFACT_DIR',str(ROOT/'artifacts/runtime')));RUNTIME.mkdir(parents=True,exist_ok=True)
def uid():return uuid.uuid4().hex
def now():return datetime.now(timezone.utc).isoformat()

class Filter:
    def __init__(self,value):self.value=value
    def __or__(self,other):return Filter({'$or':[self.value,other.value]})
    def __and__(self,other):return Filter({'$and':[self.value,other.value]})

class DocField:
    def __init__(self,default=None,required=False,kind=None):self.default=default;self.required=required;self.kind=kind
    def __set_name__(self,owner,name):self.owner=owner;self.name=name
    @property
    def key(self):return '_id' if self.name=='id' else self.name
    def __get__(self,obj,owner=None):return self if obj is None else obj.__dict__.get(self.name)
    def __set__(self,obj,value):obj.__dict__[self.name]=value
    def __eq__(self,v):return Filter({self.key:{'$eq':v}})
    def __ne__(self,v):return Filter({self.key:{'$ne':v}})
    def __lt__(self,v):return Filter({self.key:{'$lt':v}})
    def __le__(self,v):return Filter({self.key:{'$lte':v}})
    def __gt__(self,v):return Filter({self.key:{'$gt':v}})
    def __ge__(self,v):return Filter({self.key:{'$gte':v}})
    def in_(self,values):return Filter({self.key:{'$in':list(values)}})
    def ilike(self,pattern):return self._pattern(pattern,True)
    def like(self,pattern):return self._pattern(pattern,False)
    def _pattern(self,pattern,ignore):
        # Escape all user regex characters; '%' is the repository wildcard.
        expression='^'+'.*'.join(re.escape(v) for v in pattern.split('%'))+'$'
        return Filter({self.key:{'$regex':expression,**({'$options':'i'} if ignore else {})}})
    def desc(self):return (self.key,DESCENDING)

class Record:
    id=DocField(default=uid,required=True,kind=str)
    collection=''
    references={}
    @classmethod
    def fields(cls):
        result={}
        for base in reversed(cls.__mro__):result.update({k:v for k,v in vars(base).items() if isinstance(v,DocField)})
        return result
    def __init__(self,**values):
        allowed=self.fields()
        if set(values)-set(allowed):raise ValueError('Unknown fields: '+str(set(values)-set(allowed)))
        for k,f in allowed.items():
            default=f.default() if callable(f.default) else copy.deepcopy(f.default)
            setattr(self,k,values.get(k,default))
    def document(self):return {('_id' if k=='id' else k):copy.deepcopy(getattr(self,k)) for k in self.fields()}
    @classmethod
    def from_document(cls,data):return cls(**{('id' if k=='_id' else k):v for k,v in data.items() if k!='_rev'})
class Scoped(Record):
    scope=DocField(default='operational',required=True,kind=str)
    created_at=DocField(default=now,required=True,kind=str)
class User(Scoped):
    collection='users'
    name=DocField(required=True,kind=str);email=DocField(required=True,kind=str);password_hash=DocField(required=True,kind=str)
    role=DocField(required=True,kind=str);status=DocField(default='pending',kind=str);organisation=DocField(default='',kind=str);reason=DocField(default='',kind=str)
class Session(Record):
    collection='user_sessions'
    user_id=DocField(required=True,kind=str);expires=DocField(required=True,kind=float)
    references={'user_id':'User'}
class Dataset(Scoped):
    collection='dataset_versions'
    name=DocField(required=True,kind=str);source=DocField(required=True,kind=str);path=DocField(required=True,kind=str);digest=DocField(required=True,kind=str)
    quality=DocField(required=True,kind=dict);status=DocField(default='validated',kind=str)
    allowed_users=DocField(default=list,kind=list)
class TrainingJob(Scoped):
    collection='training_jobs'
    dataset_id=DocField(required=True,kind=str);status=DocField(required=True,kind=str);error=DocField(default='',kind=str);completed_at=DocField(default='',kind=str);scheduled_at=DocField(default='',kind=str)
    references={'dataset_id':'Dataset'}
class Model(Scoped):
    collection='model_versions'
    dataset_id=DocField();algorithm=DocField(required=True,kind=str);path=DocField(required=True,kind=str);digest=DocField(required=True,kind=str)
    report=DocField(required=True,kind=dict);threshold=DocField(required=True,kind=float);status=DocField(default='validated',kind=str)
    references={'dataset_id':'Dataset'}
class Deployment(Scoped):
    collection='model_deployments'
    model_id=DocField(required=True,kind=str);actor_id=DocField(required=True,kind=str);threshold=DocField(required=True,kind=float)
    references={'model_id':'Model','actor_id':'User'}
class Transaction(Scoped):
    collection='transactions'
    source_id=DocField(required=True,kind=str);dataset_id=DocField();timestamp=DocField(required=True,kind=str);amount=DocField(required=True,kind=float);channel=DocField(required=True,kind=str)
    customer=DocField(default='',kind=str);sender=DocField(default='',kind=str);recipient=DocField(default='',kind=str);label=DocField(required=True,kind=int);attributes=DocField(required=True,kind=dict)
    references={'dataset_id':'Dataset'}
class Prediction(Scoped):
    collection='predictions'
    transaction_id=DocField(required=True,kind=str);model_id=DocField(required=True,kind=str);score=DocField(required=True,kind=float);threshold=DocField(required=True,kind=float);explanation=DocField(required=True,kind=dict)
    references={'transaction_id':'Transaction','model_id':'Model'}
class Case(Scoped):
    collection='cases'
    title=DocField(required=True,kind=str);reason=DocField(required=True,kind=str);status=DocField(default='draft',kind=str);priority=DocField(default='medium',kind=str);due_date=DocField(default='',kind=str)
    owner_id=DocField(required=True,kind=str);creator_id=DocField(required=True,kind=str);updated_at=DocField(default=now,kind=str);submitted_at=DocField(default='',kind=str)
    references={'owner_id':'User','creator_id':'User'}
class CaseTransaction(Scoped):
    collection='case_transactions'
    case_id=DocField(required=True,kind=str);transaction_id=DocField(required=True,kind=str)
    references={'case_id':'Case','transaction_id':'Transaction'}
class Note(Scoped):
    collection='case_notes'
    case_id=DocField(required=True,kind=str);author_id=DocField(required=True,kind=str);text=DocField(required=True,kind=str)
    references={'case_id':'Case','author_id':'User'}
class Evidence(Scoped):
    collection='case_evidence'
    case_id=DocField(required=True,kind=str);author_id=DocField(required=True,kind=str);kind=DocField(required=True,kind=str);reference=DocField(required=True,kind=str);description=DocField(required=True,kind=str)
    references={'case_id':'Case','author_id':'User'}
class Review(Scoped):
    collection='case_reviews'
    case_id=DocField(required=True,kind=str);reviewer_id=DocField(required=True,kind=str);decision=DocField(required=True,kind=str);rationale=DocField(required=True,kind=str)
    references={'case_id':'Case','reviewer_id':'User'}
class Audit(Scoped):
    collection='audit_events'
    actor_id=DocField();action=DocField(required=True,kind=str);object_id=DocField(required=True,kind=str);details=DocField(default=dict,kind=dict)
    references={'actor_id':'User'}
class Alert(Scoped):
    collection='transaction_alerts'
    transaction_id=DocField(required=True,kind=str);owner_id=DocField();status=DocField(default='open',kind=str);updated_at=DocField(default=now,kind=str)
    references={'transaction_id':'Transaction','owner_id':'User'}
class Notification(Scoped):
    collection='notifications'
    user_id=DocField(required=True,kind=str);message=DocField(required=True,kind=str);link=DocField(default='',kind=str);read=DocField(default=False,kind=bool)
    references={'user_id':'User'}
class Attachment(Scoped):
    collection='attachments'
    case_id=DocField(required=True,kind=str);author_id=DocField(required=True,kind=str);filename=DocField(required=True,kind=str);path=DocField(required=True,kind=str);digest=DocField(required=True,kind=str);media_type=DocField(required=True,kind=str);size=DocField(required=True,kind=int)
    references={'case_id':'Case','author_id':'User'}
class Policy(Scoped):
    collection='workflow_policies'
    review_days=DocField(default=7,kind=int);require_notes=DocField(default=True,kind=bool);retention_days=DocField(default=30,kind=int)
class PasswordReset(Record):
    collection='password_resets'
    user_id=DocField(required=True,kind=str);token_hash=DocField(required=True,kind=str);expires=DocField(required=True,kind=float);used=DocField(default=False,kind=bool)
    references={'user_id':'User'}
MODELS=[User,Session,Dataset,TrainingJob,Model,Deployment,Transaction,Prediction,Case,CaseTransaction,Note,Evidence,Review,Audit,Alert,Notification,Attachment,Policy,PasswordReset]

class MongoQuery:
    def __init__(self,target):
        self.model=target.owner if isinstance(target,DocField) else target
        self.projection=target if isinstance(target,DocField) else None
        self.filters=[];self.sort=[];self.maximum=0
    def where(self,*filters):self.filters.extend(f.value for f in filters);return self
    def order_by(self,*fields):self.sort.extend((f.key,ASCENDING) if isinstance(f,DocField) else f for f in fields);return self
    def limit(self,n):self.maximum=n;return self
    @property
    def mongo_filter(self):return {'$and':self.filters} if self.filters else {}
def query(target):return MongoQuery(target)

# Mocks are test-only and cannot be accidentally enabled in an application process.
MOCK=os.getenv('FINSLEUTH_TEST_MOCK')=='1'
if MOCK:
    import sys
    if 'pytest' not in sys.modules:raise RuntimeError('Mock MongoDB is restricted to pytest')
    import mongomock
    client=mongomock.MongoClient()
else:
    client=MongoClient(os.getenv('MONGODB_URI','mongodb://127.0.0.1:27017'),serverSelectionTimeoutMS=5000,tz_aware=True)
database=client[os.getenv('MONGODB_DATABASE','finsleuth')]
USE_TRANSACTIONS=False

def init_db():
    global USE_TRANSACTIONS
    database.command('ping')
    if not MOCK:
        hello=client.admin.command('hello')
        USE_TRANSACTIONS=bool(hello.get('setName') or hello.get('msg')=='isdbgrid')
        if os.getenv('MONGODB_REQUIRE_TRANSACTIONS','false')=='true' and not USE_TRANSACTIONS:raise RuntimeError('A MongoDB replica set or Atlas is required for atomic multi-document transactions')
    for model in MODELS:
        if not MOCK:
            bson_types={str:'string',float:'double',int:'int',dict:'object',bool:'bool',list:'array'}
            properties={'_rev':{'bsonType':['int','long']}}
            required=['_id']
            for name,field in model.fields().items():
                key='_id' if name=='id' else name
                if field.kind:properties[key]={'bsonType':[bson_types[field.kind]]+([] if field.required else ['null'])}
                if field.required:required.append(key)
            validator={'$jsonSchema':{'bsonType':'object','required':sorted(set(required)),'properties':properties}}
            if model.collection not in database.list_collection_names():database.create_collection(model.collection,validator=validator)
            else:database.command({'collMod':model.collection,'validator':validator,'validationLevel':'strict'})
        collection=database[model.collection]
        collection.create_index([('scope',1),('created_at',-1)])
    database.users.create_index([('scope',1),('email',1)],unique=True)
    database.transactions.create_index([('scope',1),('source_id',1)],unique=True)
    database.transactions.create_index([('scope',1),('timestamp',1)])
    for key in ['sender','recipient','customer']:database.transactions.create_index([('scope',1),(key,1),('timestamp',1)])
    database.case_transactions.create_index([('case_id',1),('transaction_id',1)],unique=True)
    database.predictions.create_index([('transaction_id',1),('model_id',1),('threshold',1)],unique=True)
    database.cases.create_index([('scope',1),('owner_id',1),('status',1)])
    database.transaction_alerts.create_index([('scope',1),('transaction_id',1)],unique=True)
    database.workflow_policies.create_index('scope',unique=True)
    database.notifications.create_index([('user_id',1),('read',1),('created_at',-1)])
    database.password_resets.create_index('token_hash',unique=True)
    database.user_sessions.create_index('user_id')
    for name in ['case_evidence','case_notes','case_reviews']:database[name].create_index('case_id')
    database.audit_events.create_index([('scope',1),('object_id',1),('created_at',1)])
    database.schema_versions.update_one({'_id':'001-mongodb'},{'$setOnInsert':{'created_at':now(),'description':'Initial MongoDB collections and indexes'}},upsert=True)

class MongoUnitOfWork:
    def __init__(self):self.tracked={};self.original={};self.revisions={};self.deleted=set();self.mongo_session=None;self.flushing=False
    def __enter__(self):return self
    def __exit__(self,typ,value,tb):
        if self.mongo_session:
            if self.mongo_session.in_transaction:self.mongo_session.abort_transaction()
            self.mongo_session.end_session()
    @property
    def options(self):return {'session':self.mongo_session} if self.mongo_session else {}
    def _start_write(self):
        if USE_TRANSACTIONS:
            if not self.mongo_session:self.mongo_session=client.start_session()
            if not self.mongo_session.in_transaction:self.mongo_session.start_transaction()
    def _key(self,obj):return (type(obj),obj.id)
    def add(self,obj):
        key=self._key(obj)
        if key not in self.tracked:self.tracked[key]=obj;self.original[key]=None;self.revisions[key]=0
    def _loaded(self,cls,doc):
        key=(cls,doc['_id'])
        if key in self.tracked:return self.tracked[key]
        obj=cls.from_document(doc);self.tracked[key]=obj;self.original[key]=obj.document();self.revisions[key]=doc.get('_rev',0);return obj
    def get(self,cls,id):
        if (cls,id) in self.deleted:return None
        if (cls,id) in self.tracked:return self.tracked[(cls,id)]
        doc=database[cls.collection].find_one({'_id':id},**self.options)
        return self._loaded(cls,doc) if doc else None
    def find(self,q):
        self.flush()
        cursor=database[q.model.collection].find(q.mongo_filter,**self.options)
        if q.sort:cursor=cursor.sort(q.sort)
        if q.maximum:cursor=cursor.limit(q.maximum)
        rows=[self._loaded(q.model,d) for d in cursor]
        return [getattr(r,q.projection.name) for r in rows] if q.projection is not None else rows
    def first(self,q):
        rows=self.find(q.limit(1));return rows[0] if rows else None
    def delete(self,obj):
        if not isinstance(obj,Session):raise HTTPException(403,'Historical records cannot be deleted through this repository')
        self.deleted.add(self._key(obj))
    def _validate(self,obj):
        for k,f in obj.fields().items():
            value=getattr(obj,k)
            if f.required and value is None:raise ValueError(f'Missing required {type(obj).__name__}.{k}')
            if value is not None and f.kind and not isinstance(value,f.kind):
                if f.kind is float and isinstance(value,int):setattr(obj,k,float(value))
                else:raise ValueError(f'Invalid type for {type(obj).__name__}.{k}')
        for name,target in obj.references.items():
            value=getattr(obj,name)
            if value is None:continue
            referenced=self.get(globals()[target],value)
            if not referenced:raise ValueError(f'Missing referenced {target}')
            if isinstance(obj,Scoped) and isinstance(referenced,Scoped) and obj.scope!=referenced.scope:raise ValueError('Cross-workspace references are forbidden')
    def flush(self):
        if self.flushing:return
        self.flushing=True
        try:
            changed=[(k,o) for k,o in self.tracked.items() if k not in self.deleted and o.document()!=self.original[k]]
            for key,obj in changed:self._validate(obj)
            if changed or self.deleted:self._start_write()
            for key,obj in changed:
                before=self.original[key];document=obj.document();collection=database[obj.collection]
                if before is None:
                    collection.insert_one({**document,'_rev':1},**self.options);self.revisions[key]=1
                else:
                    if isinstance(obj,(Audit,Note,Evidence,Attachment,Review,Deployment,Transaction,Dataset)):
                        # Dataset status may advance after validation; source/data metadata cannot change.
                        allowed={'status','allowed_users'} if isinstance(obj,Dataset) else set()
                        if any(document[k]!=before.get(k) and k not in allowed for k in document):raise HTTPException(409,'Stored source/evidence/history is immutable')
                    if isinstance(obj,Prediction) and any(document[k]!=before.get(k) for k in ['transaction_id','model_id','score','threshold']):raise HTTPException(409,'Original prediction cannot be rewritten')
                    rev=self.revisions[key];document['_rev']=rev+1
                    updated=collection.replace_one({'_id':obj.id,'_rev':rev},document,**self.options)
                    if updated.matched_count!=1:raise HTTPException(409,'Record changed in another request. Refresh and retry.')
                    self.revisions[key]=rev+1
                self.original[key]=obj.document()
            for cls,id in list(self.deleted):database[cls.collection].delete_one({'_id':id},**self.options);self.tracked.pop((cls,id),None);self.original.pop((cls,id),None)
            self.deleted.clear()
        except DuplicateKeyError:raise HTTPException(409,'A record with the same unique reference already exists')
        finally:self.flushing=False
    def commit(self):
        self.flush()
        if self.mongo_session and self.mongo_session.in_transaction:self.mongo_session.commit_transaction()
    def refresh(self,obj):
        doc=database[obj.collection].find_one({'_id':obj.id},**self.options)
        if not doc:raise ValueError('Record no longer exists')
        obj.__dict__.update(type(obj).from_document(doc).__dict__);key=self._key(obj);self.original[key]=obj.document();self.revisions[key]=doc.get('_rev',0)
    def ping(self):return database.command('ping')

def get_db():
    with MongoUnitOfWork() as db:yield db

def serialize(obj):return {k:copy.deepcopy(getattr(obj,k)) for k in obj.fields() if k not in ['password_hash','path','digest']}
def audit(db,user,action,object_id,details=None):
    db.add(Audit(scope=user.scope,actor_id=user.id,action=action,object_id=object_id,details=details or {}))
    if action.startswith('case.'):
        case=db.get(Case,object_id)
        if case:
            recipients=[case.owner_id]
            if action=='case.submitted':recipients=[u.id for u in db.find(query(User).where(User.scope==user.scope,User.role=='manager',User.status=='active'))]
            for recipient in set(recipients):
                if recipient!=user.id:db.add(Notification(scope=user.scope,user_id=recipient,message=case.title+': '+action.replace('case.','').replace('_',' '),link='/app/cases/'+case.id))
