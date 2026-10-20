from fastapi import APIRouter,Depends,HTTPException,Query
from .db import *
from .security import *
from .services import predict, trusted_bundle
from ml.pipeline import explain
router=APIRouter(prefix='/api/v1')
investigator=roles('analyst','manager')
def latest(db,scope):
    result={}
    for p in db.find(query(Prediction).where(Prediction.scope==scope).order_by(Prediction.created_at)):result[p.transaction_id]=p
    return result

def allowed_filter(db,user):
    return Transaction.dataset_id.in_(granted_dataset_ids(db,user))

def tx_json(t,p=None):
    d=serialize(t);d.pop('attributes',None);d['prediction']=serialize(p) if p else None;return d
@router.get('/transactions')
def transactions(q:str='',channel:str='',risk:str='',minimum:float=0,maximum:float=1e15,start:str='',end:str='',sort:str='risk',page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(investigator),db=Depends(get_db)):
    selection=query(Transaction).where(Transaction.scope==user.scope,allowed_filter(db,user),Transaction.amount>=minimum,Transaction.amount<=maximum)
    if channel:selection=selection.where(Transaction.channel==channel)
    if start:selection=selection.where(Transaction.timestamp>=start)
    if end:selection=selection.where(Transaction.timestamp<=end+'T23:59:59')
    if q:selection=selection.where((Transaction.source_id.ilike('%'+q+'%')) | (Transaction.customer.ilike('%'+q+'%')) | (Transaction.sender.ilike('%'+q+'%')) | (Transaction.recipient.ilike('%'+q+'%')))
    # Filter and paginate in MongoDB; avoid materialising the full dataset in Python.
    pipeline=[{'$match':selection.mongo_filter},
              {'$lookup':{'from':'predictions','localField':'_id','foreignField':'transaction_id','as':'prediction'}},
              {'$unwind':{'path':'$prediction','preserveNullAndEmptyArrays':True}},
              {'$sort':{'prediction.created_at':-1}},
              {'$group':{'_id':'$_id','row':{'$first':'$$ROOT'}}},
              {'$replaceRoot':{'newRoot':'$row'}}]
    if risk=='flagged':pipeline.append({'$match':{'prediction':{'$exists':True},'$expr':{'$gte':['$prediction.score','$prediction.threshold']}}})
    if risk in ['high','medium','low']:
        score='$prediction.score';threshold='$prediction.threshold';double={'$multiply':[threshold,2]}
        condition={'$gte':[score,double]} if risk=='high' else {'$and':[{'$gte':[score,threshold]},{'$lt':[score,double]}]} if risk=='medium' else {'$lt':[score,threshold]}
        pipeline.append({'$match':{'prediction':{'$exists':True},'$expr':condition}})
    if risk=='unscored':pipeline.append({'$match':{'prediction':{'$exists':False}}})
    ordering={'prediction.score':-1,'source_id':-1} if sort=='risk' else {'amount':-1,'source_id':-1} if sort=='amount' else {'timestamp':-1,'source_id':-1}
    pipeline.extend([{'$sort':ordering},{'$facet':{'count':[{'$count':'total'}],'items':[{'$skip':(page-1)*size},{'$limit':size},{'$project':{'attributes':0,'prediction.explanation':0}}]}}])
    result=list(database.transactions.aggregate(pipeline,allowDiskUse=True))[0]
    rows=[]
    for raw in result['items']:
        pred=raw.pop('prediction',None);raw['id']=raw.pop('_id');raw.pop('_rev',None)
        if pred:pred['id']=pred.pop('_id');pred.pop('_rev',None)
        raw['prediction']=pred;rows.append(raw)
    return {'items':rows,'total':result['count'][0]['total'] if result['count'] else 0,'page':page}
@router.get('/transactions/{id}')
def detail(id:str,user=Depends(investigator),db=Depends(get_db)):
    t=scoped_tx(db,id,user);d=serialize(t)
    d['predictions']=[serialize(p) for p in db.find(query(Prediction).where(Prediction.transaction_id==id).order_by(Prediction.created_at.desc()))]
    past=list(db.find(query(Transaction).where(Transaction.scope==user.scope,allowed_filter(db,user),Transaction.customer==t.customer,Transaction.timestamp<t.timestamp))) if t.customer else []
    import statistics
    d['history']={'count':len(past),'median_amount':statistics.median(x.amount for x in past) if past else None,'source':'Only earlier recorded transactions'}
    comparable=[x for x in past if x.channel==t.channel]
    d['similar_records']=[tx_json(x) for x in sorted(comparable,key=lambda x:abs(x.amount-t.amount))[:5]]
    d['similarity_basis']='Earlier activity for the same customer and channel, nearest recorded amount; not evidence of fraud.'
    return d
@router.post('/transactions/{id}/predict')
def prediction(id:str,user=Depends(roles('analyst')),db=Depends(get_db)):
    rate_limit('predict:'+user.id,30)
    t=scoped_tx(db,id,user)
    try:
        p=predict(db,t,user)
        if not p.explanation.get('contributions'):
            p.explanation=explain(trusted_bundle(db.get(Model,p.model_id)),t.attributes);db.commit()
        return serialize(p)
    except ValueError as e:raise HTTPException(409,str(e))
@router.get('/accounts/{account}')
def account(account:str,user=Depends(investigator),db=Depends(get_db)):
    rows=list(db.find(query(Transaction).where(Transaction.scope==user.scope,allowed_filter(db,user),(Transaction.customer==account)|(Transaction.sender==account)|(Transaction.recipient==account)).order_by(Transaction.timestamp)))
    return {'account':account,'count':len(rows),'total_recorded_amount':sum(t.amount for t in rows),'incoming':sum(t.amount for t in rows if t.recipient==account or (not t.recipient and t.customer==account and str(t.attributes.get('transaction_direction','')).lower()=='credit')),'outgoing':sum(t.amount for t in rows if t.sender==account or (not t.sender and t.customer==account and str(t.attributes.get('transaction_direction','')).lower()=='debit')),'transactions':[tx_json(t) for t in rows],'notice':'Amounts use explicit transfer endpoints, or the customer record’s Credit/Debit direction when endpoints are absent. Customer activity does not establish a counterparty or transfer path.'}

def edges(db,user,start,end,channel,minimum):
    selection=query(Transaction).where(Transaction.scope==user.scope,allowed_filter(db,user),Transaction.sender!='',Transaction.recipient!='',Transaction.amount>=minimum)
    if start:selection=selection.where(Transaction.timestamp>=start)
    if end:selection=selection.where(Transaction.timestamp<=end+'T23:59:59')
    if channel:selection=selection.where(Transaction.channel==channel)
    return list(db.find(selection.order_by(Transaction.timestamp).limit(5001)))
@router.get('/graph')
def graph(account:str,depth:int=Query(1,ge=1,le=3),start:str='',end:str='',channel:str='',minimum:float=0,user=Depends(investigator),db=Depends(get_db)):
    rows=edges(db,user,start,end,channel,minimum);nodes={account};selected={}
    for _ in range(depth):
        frontier=set(nodes)
        for t in rows[:5000]:
            if t.sender in frontier or t.recipient in frontier:
                if len(selected)>=200:break
                selected[t.id]=t;nodes.update([t.sender,t.recipient])
    return {'nodes':[{'id':n} for n in sorted(nodes)],'edges':[tx_json(t) for t in selected.values()],'limited':len(rows)>5000 or len(selected)>=200,'notice':'Edges represent recorded directed transfers. Connected does not mean fraudulent.'}
@router.get('/trace')
def trace(source:str,destination:str,depth:int=Query(4,ge=1,le=6),start:str='',end:str='',channel:str='',minimum:float=0,user=Depends(investigator),db=Depends(get_db)):
    rows=edges(db,user,start,end,channel,minimum);adj={}
    for t in rows[:5000]:adj.setdefault(t.sender,[]).append(t)
    paths=[];budget=[0]
    def walk(node,path,seen,last):
        budget[0]+=1
        if budget[0]>5000 or len(paths)>=20:return
        if node==destination and path:paths.append([tx_json(t) for t in path]);return
        if len(path)>=depth:return
        for t in adj.get(node,[]):
            if t.recipient not in seen and t.timestamp>=last:walk(t.recipient,path+[t],seen|{t.recipient},t.timestamp)
    walk(source,[],{source},'')
    return {'paths':paths,'limited':budget[0]>5000 or len(paths)>=20 or len(rows)>5000,'notice':'Chronological recorded paths, not proof that identical funds travelled through every edge.'}
