import os,tempfile
from pathlib import Path
os.environ['FINSLEUTH_TEST_MOCK']='1'
os.environ['MONGODB_DATABASE']='finsleuth_test'
os.environ['ARTIFACT_DIR']=tempfile.mkdtemp()
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import database,init_db,MongoUnitOfWork,query,User,Case,Model,Prediction
from app.security import ph
from ml.pipeline import validate
import pandas as pd
@pytest.fixture()
def client():
    from app.security import attempts
    attempts.clear()
    database.client.drop_database(database.name);init_db()
    with TestClient(app,headers={'X-Finsleuth':'1'}) as c:yield c

def demo(c,role='analyst'):
    r=c.post('/api/v1/auth/demo',json={'role':role});assert r.status_code==200,r.text;return r.json()
def test_auth_approval_status_rbac(client):
    c=client
    r=c.post('/api/v1/auth/register',json={'name':'Test Analyst','email':'analyst@example.test','password':'long-test-password','role':'analyst','organisation':'Testing','reason':'Investigate test records'});assert r.status_code==200
    assert c.post('/api/v1/auth/login',json={'email':'analyst@example.test','password':'long-test-password'}).status_code==403
    with MongoUnitOfWork() as db:
        admin=User(name='Admin',email='admin@example.test',password_hash=ph.hash('long-admin-password'),role='admin',status='active',scope='operational');db.add(admin);db.commit()
    assert c.post('/api/v1/auth/login',json={'email':'admin@example.test','password':'long-admin-password'}).status_code==200
    users=c.get('/api/v1/admin/users').json();uid=next(u['id'] for u in users if u['role']=='analyst')
    assert c.patch('/api/v1/admin/users/'+uid,json={'status':'active','role':'analyst','reason':'Approved for testing'}).status_code==200
    assert c.post('/api/v1/auth/login',json={'email':'analyst@example.test','password':'long-test-password'}).status_code==200
    assert c.get('/api/v1/admin/users').status_code==403
    with MongoUnitOfWork() as db:u=db.get(User,uid);u.status='suspended';db.commit()
    assert c.get('/api/v1/overview').status_code==403

def test_prediction_explanation_case_review_and_isolation(client):
    c=client;analyst=demo(c);tx=c.get('/api/v1/transactions?size=1').json()['items'][0]
    p=c.post(f"/api/v1/transactions/{tx['id']}/predict");assert p.status_code==200,p.text
    prediction=p.json();assert 0<=prediction['score']<=1
    ex=prediction['explanation'];assert len(ex['contributions'])==8;assert ex['additivity_error']<1e-6
    assert abs(ex['base_value']+sum(v['contribution'] for v in ex['contributions'])-prediction['score'])<1e-6
    assert c.post(f"/api/v1/transactions/{tx['id']}/predict").json()['id']==prediction['id']
    r=c.post('/api/v1/cases',json={'title':'Investigate test transfer','reason':'Review transaction pattern and uncertainty','transaction_ids':[tx['id']]});assert r.status_code==200,r.text;case=r.json();cid=case['id']
    assert c.post(f'/api/v1/cases/{cid}/submit').status_code==422
    assert c.post(f'/api/v1/cases/{cid}/notes',json={'text':'Observed a high model signal. Requires manual assessment.'}).status_code==200
    assert c.post(f'/api/v1/cases/{cid}/submit').status_code==200
    assert c.post(f'/api/v1/cases/{cid}/notes',json={'text':'Cannot change submitted evidence'}).status_code==409
    assert c.post(f'/api/v1/cases/{cid}/review',json={'decision':'closed','rationale':'Unauthorized analyst review'}).status_code==403
    manager=demo(c,'manager');assert manager['scope']==analyst['scope']
    assert c.post(f'/api/v1/cases/{cid}/review',json={'decision':'returned','rationale':'Provide more historical context before a decision'}).status_code==200
    demo(c);assert c.post(f'/api/v1/cases/{cid}/notes',json={'text':'Added context from available earlier transactions.'}).status_code==200
    assert c.post(f'/api/v1/cases/{cid}/submit').status_code==200
    demo(c,'manager');assert c.post(f'/api/v1/cases/{cid}/review',json={'decision':'closed','rationale':'Insufficient corroborating evidence for further action'}).status_code==200
    report=c.get(f'/api/v1/cases/{cid}/report');assert report.status_code==200;assert report.json()['isolated_dataset_workspace'];assert len(report.json()['reviews'])==2
    demo(c,'admin');assert c.get('/api/v1/transactions').status_code==403
    with TestClient(app,headers={'X-Finsleuth':'1'}) as other:
        demo(other);assert other.get(f'/api/v1/cases/{cid}').status_code==404;assert other.get(f"/api/v1/transactions/{tx['id']}").status_code==404

def test_graph_paths_and_import_model_lifecycle(client):
    c=client;demo(c)
    g=c.get('/api/v1/graph?account=CUST000001&depth=2').json();assert g['edges']==[]
    trace=c.get('/api/v1/trace?source=AC-001&destination=AC-004&depth=4').json();assert trace['paths']==[]
    for path in trace['paths']:
        for a,b in zip(path,path[1:]):assert a['recipient']==b['sender'] and a['timestamp']<=b['timestamp']
    assert c.get('/api/v1/graph?account=AC-001&depth=100').status_code==422
    demo(c,'admin');models=c.get('/api/v1/models').json();old=models['active_id'];other=next(m for m in models['items'] if m['id']!=old)
    r=c.post('/api/v1/admin/models/'+other['id']+'/deploy',json={'reason':'Testing controlled model deployment'});assert r.status_code==200,r.text
    assert c.get('/api/v1/models').json()['active_id']==other['id']
    assert c.post('/api/v1/admin/models/'+old+'/deploy',json={'reason':'Rollback to previously approved model'}).status_code==200
    assert len(c.get('/api/v1/models').json()['deployments'])==3
    bad=b'transaction_id,transaction_date,transaction_amount,is_fraud\nbad,notdate,-5,7\n'
    r=c.post('/api/v1/admin/datasets',files={'file':('bad.csv',bad,'text/csv')},data={'source':'Test fixture'});assert r.status_code==200;d=r.json();assert d['status']=='rejected';assert d['quality']['invalid_rows']==1
    assert c.post('/api/v1/admin/datasets/'+d['id']+'/import').status_code==409
    valid=b'transaction_id,transaction_date,transaction_amount,is_fraud\nimport-1,2025-04-01,2500,0\n'
    r=c.post('/api/v1/admin/datasets',files={'file':('good.csv',valid,'text/csv')},data={'source':'Test fixture'});d=r.json();assert d['quality']['valid']
    assert c.post('/api/v1/admin/datasets/'+d['id']+'/import').status_code==200
    assert c.post('/api/v1/admin/datasets/'+d['id']+'/import').status_code==409
    assert c.get('/api/v1/audit').json()

def test_validation_and_missing_model(client):
    report=validate(pd.DataFrame({'transaction_id':['a','a'],'transaction_date':['2025-01-01','invalid'],'transaction_amount':[10,-1],'is_fraud':[0,4]}));assert not report['valid'];assert report['invalid_rows']==2
    demo(client,'admin');m=client.get('/api/v1/models').json()['items'][0]
    with MongoUnitOfWork() as db:model=db.get(Model,m['id']);model.path='/nonexistent/model.joblib';db.commit()
    assert client.post('/api/v1/admin/models/'+m['id']+'/deploy',json={'reason':'Must fail on missing artefact'}).status_code==409

def test_csrf_header_and_logout(client):
    demo(client);assert client.get('/api/v1/auth/me').status_code==200
    assert client.post('/api/v1/auth/logout',headers={'X-Finsleuth':'0'}).status_code==403
    assert client.post('/api/v1/auth/logout').status_code==200
    assert client.get('/api/v1/auth/me').status_code==401

def test_training_registration_approval_and_deployment(client):
    from app.db import ROOT
    c=client;demo(c,'admin')
    from ml.data import load_dataset
    data=load_dataset(ROOT/'data/archive.zip').iloc[:30000].to_csv(index=False).encode()
    r=c.post('/api/v1/admin/datasets',files={'file':('training_fixture.csv',data,'text/csv')},data={'source':'Subset of uploaded source dataset'});assert r.status_code==200
    dataset=r.json()
    r=c.post('/api/v1/admin/datasets/'+dataset['id']+'/train');assert r.status_code==200,r.text
    jobs=c.get('/api/v1/admin/jobs').json();assert jobs[0]['status']=='completed',jobs
    models=c.get('/api/v1/models').json()['items'];new=[m for m in models if m['dataset_id']==dataset['id']];assert len(new)==4
    model=new[0]
    assert c.post('/api/v1/admin/models/'+model['id']+'/deploy',json={'reason':'Must require explicit approval'}).status_code==409
    assert c.post('/api/v1/admin/models/'+model['id']+'/approve',json={'reason':'Dataset testing only; not real-bank deployment'}).status_code==200
    assert c.post('/api/v1/admin/models/'+model['id']+'/deploy',json={'reason':'Deploy validated dataset candidate for test'}).status_code==200

def test_mongodb_reference_scope_unique_indexes_and_optimistic_lock(client):
    from app.db import Transaction,CaseTransaction,Note,Audit
    from fastapi import HTTPException
    c=client;demo(c)
    user=c.get('/api/v1/auth/me').json();tx=c.get('/api/v1/transactions?size=1').json()['items'][0]
    # Unique indexes are present and enforced by Mongo's test substitute.
    assert any(x.get('unique') for x in database.users.index_information().values())
    with MongoUnitOfWork() as db:
        db.add(User(scope=user['scope'],name='Duplicate',email=user['email'],password_hash='test',role='analyst',status='active'))
        with pytest.raises(HTTPException,match='same unique reference'):db.commit()
    with MongoUnitOfWork() as db:
        t=db.get(Transaction,tx['id']);t.amount+=1
        with pytest.raises(HTTPException,match='immutable'):db.commit()
    # A cross-scope reference is rejected before being written.
    with MongoUnitOfWork() as db:
        db.add(Case(scope='operational',title='Wrong scope',reason='Forbidden',owner_id=user['id'],creator_id=user['id']))
        with pytest.raises(ValueError,match='Cross-workspace'):db.commit()
    with MongoUnitOfWork() as a, MongoUnitOfWork() as b:
        ua=a.get(User,user['id']);ub=b.get(User,user['id']);ua.name='First update';a.commit();ub.name='Stale update'
        with pytest.raises(HTTPException,match='another request'):b.commit()
    # Regex metacharacters in user searches are treated literally.
    assert c.get('/api/v1/transactions?q=%5B').json()['total']==0

def test_documents_alerts_notifications_reports_and_settings(client):
    c=client;u=demo(c);tx=c.get('/api/v1/transactions?size=1').json()['items'][0]
    assert c.patch('/api/v1/transactions/'+tx['id']+'/alert',json={'status':'investigating','assign_to_self':True}).status_code==200
    assert c.get('/api/v1/transactions/'+tx['id']+'/alert').json()['status']=='investigating'
    cid=c.post('/api/v1/cases',json={'title':'Document evidence test','reason':'Review source transaction and available evidence','transaction_ids':[tx['id']]}).json()['id']
    uploaded=c.post('/api/v1/cases/'+cid+'/attachments',files={'file':('observation.txt',b'Recorded observation from source dataset.','text/plain')});assert uploaded.status_code==200,uploaded.text
    attachment=uploaded.json();download=c.get('/api/v1/attachments/'+attachment['id']+'/download');assert download.status_code==200 and b'Recorded observation' in download.content
    assert c.post('/api/v1/cases/'+cid+'/attachments',files={'file':('fake.pdf',b'not a pdf','application/pdf')}).status_code==422
    c.post('/api/v1/cases/'+cid+'/notes',json={'text':'Document and transaction references attached.'})
    assert c.post('/api/v1/cases/'+cid+'/submit').status_code==200
    assert c.get('/api/v1/cases/'+cid+'/report.pdf').content.startswith(b'%PDF-')
    assert c.get('/api/v1/reports/compliance.csv').status_code==200
    demo(c,'manager');notices=c.get('/api/v1/notifications').json();assert notices
    assert c.post('/api/v1/notifications/'+notices[0]['id']+'/read').status_code==200
    assert c.get('/api/v1/reports/quality').json()['cases']==9
    assert c.patch('/api/v1/policy',json={'review_days':10,'require_notes':True,'retention_days':30}).status_code==200
    assert c.patch('/api/v1/auth/profile',json={'name':'Updated reviewer','organisation':'Dataset review team'}).status_code==200
    assert c.get('/api/v1/auth/sessions').json()
    assert c.get('/api/v1/admin/monitoring').status_code==403
    demo(c,'admin');models=c.get('/api/v1/models').json();old=next(m for m in models['items'] if m['id']!=models['active_id'])
    assert c.post('/api/v1/admin/models/'+old['id']+'/retire').json()['status']=='retired'
    assert c.post('/api/v1/admin/models/'+models['active_id']+'/retire').status_code==409
    dataset=c.get('/api/v1/admin/datasets').json()[0]
    assert c.post('/api/v1/admin/datasets/'+dataset['id']+'/schedule',json={'scheduled_at':'2099-01-01T00:00:00Z'}).json()['status']=='scheduled'

def test_password_recovery_is_one_use_and_revokes_sessions(client,monkeypatch):
    import smtplib,re
    sent=[]
    class Mailbox:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def starttls(self):pass
        def login(self,*a):pass
        def send_message(self,message):sent.append(message.get_content())
    monkeypatch.setattr(smtplib,'SMTP',Mailbox);monkeypatch.setenv('SMTP_HOST','test.invalid');monkeypatch.setenv('SMTP_FROM','test@example.test')
    with MongoUnitOfWork() as db:db.add(User(name='Recovery Test',email='recovery@example.test',password_hash=ph.hash('original-password-123'),role='analyst',status='active'));db.commit()
    assert client.post('/api/v1/auth/login',json={'email':'recovery@example.test','password':'original-password-123'}).status_code==200
    assert client.post('/api/v1/auth/recovery/request',json={'email':'recovery@example.test'}).status_code==200
    token=re.search(r'token=([^\s]+)',sent[0]).group(1)
    assert client.post('/api/v1/auth/recovery/confirm',json={'token':token,'password':'replacement-password-123'}).status_code==200
    assert client.get('/api/v1/auth/me').status_code==401
    assert client.post('/api/v1/auth/recovery/confirm',json={'token':token,'password':'another-password-123'}).status_code==400
    assert client.post('/api/v1/auth/login',json={'email':'recovery@example.test','password':'replacement-password-123'}).status_code==200

def test_bootstrap_and_service_failure_response(client,monkeypatch):
    from app.bootstrap import create_admin
    from pymongo.errors import ServerSelectionTimeoutError
    assert create_admin('setup@finsleuth.local','Setup Administrator','initial-password-123')
    assert not create_admin('setup@finsleuth.local','Setup Administrator','replacement-password-123')
    assert client.post('/api/v1/auth/login',json={'email':'setup@finsleuth.local','password':'initial-password-123'}).status_code==200
    assert client.get('/api/v1/health').json()['database']=='connected'
    original=database.command
    def unavailable(*a,**kw):raise ServerSelectionTimeoutError('test unavailable')
    monkeypatch.setattr(database,'command',unavailable)
    response=client.get('/api/v1/health');assert response.status_code==503;assert 'MongoDB' in response.json()['detail']
    monkeypatch.setattr(database,'command',original)

def test_role_page_apis_and_demo_population(client):
    c=client;demo(c)
    for path in ['/overview','/transactions','/cases','/notifications','/auth/sessions','/metadata/transactions','/accounts/CUST078683','/graph?account=CUST078683','/trace?source=CUST078683&destination=CUST021280']:
        r=c.get('/api/v1'+path);assert r.status_code==200,(path,r.text)
    assert len(c.get('/api/v1/cases').json())==8
    assert all(x['title'].startswith('Demo ·') for x in c.get('/api/v1/cases').json())
    demo(c,'manager')
    for path in ['/overview','/cases','/reports/quality','/reports/compliance.csv','/audit','/policy','/notifications']:
        r=c.get('/api/v1'+path);assert r.status_code==200,(path,r.text)
    demo(c,'admin')
    for path in ['/overview','/admin/users','/admin/datasets','/admin/jobs','/models','/audit','/admin/health','/admin/monitoring','/policy']:
        r=c.get('/api/v1'+path);assert r.status_code==200,(path,r.text)
    assert c.get('/api/v1/cases').status_code==403
    assert c.post('/api/v1/auth/logout').status_code==200
    assert c.get('/api/v1/models').status_code==401

def test_recall_operating_point_uses_validation_curve():
    import numpy as np
    from ml.pipeline import operating_points
    labels=np.array([1,0,1,0,1,0,1,0,1,0]);scores=np.array([.9,.8,.7,.6,.5,.4,.3,.2,.1,0.])
    p=operating_points(labels,scores)['high_recall']
    assert p['validation_recall']>=.8
    assert p['threshold']==.3
    assert p['validation_alert_rate']==.7

def test_operational_source_setup_is_idempotent_and_has_no_demo_cases(client):
    from app.bootstrap import create_admin
    from app.load_source import load_source
    create_admin('local@finsleuth.local','Local administrator','local-password-123')
    load_source('local@finsleuth.local');load_source('local@finsleuth.local')
    assert database.transactions.count_documents({'scope':'operational'})==2000
    assert database.model_versions.count_documents({'scope':'operational'})==5
    assert database.cases.count_documents({'scope':'operational'})==0
    assert database.model_deployments.count_documents({'scope':'operational'})==1

def test_word_queue_filters_account_directions_and_risk_bands(client):
    c=client;user=demo(c)
    for band in ['high','medium','low']:
        r=c.get('/api/v1/transactions?risk='+band);assert r.status_code==200,r.text
        for row in r.json()['items']:
            p=row['prediction'];ratio=p['score']/p['threshold']
            assert (ratio>=2 if band=='high' else 1<=ratio<2 if band=='medium' else ratio<1)
    source=database.transactions.find_one({'scope':user['scope'],'attributes.transaction_direction':'Credit'})
    account=source['customer'];rows=list(database.transactions.find({'scope':user['scope'],'customer':account}))
    r=c.get('/api/v1/accounts/'+account);assert r.status_code==200
    assert r.json()['incoming']==sum(t['amount'] for t in rows if t['attributes']['transaction_direction']=='Credit')
    assert r.json()['outgoing']==sum(t['amount'] for t in rows if t['attributes']['transaction_direction']=='Debit')
    detail=c.get('/api/v1/transactions/'+source['_id']).json();assert 'similar_records' in detail
    demo(c,'manager')
    r=c.get('/api/v1/cases?priority=high&analyst=Aarav&sort=oldest');assert r.status_code==200
    assert r.json() and all(v['priority']=='high' and 'Aarav' in v['owner_name'] for v in r.json())
    assert c.get('/api/v1/cases?start=2099-01-01').json()==[]
    assert c.get('/api/v1/cases?start=2026-02-01&end=2026-01-01').status_code==422
    assert c.get('/api/v1/cases?start=not-a-date').status_code==422

def test_registration_admin_reset_and_demo_repair(client):
    from app.bootstrap import create_admin
    c=client
    body={'name':'Test Applicant','email':'applicant@test.local','password':'safe-testing-password','role':'admin','organisation':'Test Bank','reason':'Review transactions'}
    assert c.post('/api/v1/auth/register',json=body).status_code==422
    body['role']='analyst';assert c.post('/api/v1/auth/register',json=body).status_code==200
    create_admin('admin@finsleuth.local','Administrator','old-admin-password')
    assert c.post('/api/v1/auth/login',json={'email':'admin@finsleuth.local','password':'old-admin-password'}).status_code==200
    create_admin('admin@finsleuth.local','Administrator','new-admin-password',reset=True)
    assert c.get('/api/v1/auth/me').status_code==401
    assert c.post('/api/v1/auth/login',json={'email':'admin@finsleuth.local','password':'old-admin-password'}).status_code==401
    assert c.post('/api/v1/auth/login',json={'email':'admin@finsleuth.local','password':'new-admin-password'}).status_code==200
    assert any(u['email']=='applicant@test.local' for u in c.get('/api/v1/admin/users').json())
    user=demo(c)
    # Reproduce the partial initialization visible in the user's screenshots.
    database.model_deployments.delete_many({'scope':user['scope']})
    database.model_versions.delete_many({'scope':user['scope']})
    database.cases.delete_many({'scope':user['scope']})
    demo(c,'admin')
    assert len(c.get('/api/v1/models').json()['items'])==5
    demo(c,'manager');assert len(c.get('/api/v1/cases').json())==8
    demo(c);assert len(c.get('/api/v1/cases').json())==8
    assert c.get('/api/v1/overview?start=2099-01-01').json()['metrics'][0]['value']==0

def test_uploaded_data_scored_shared_and_recorded_graph(client):
    c=client
    demo(c,'admin')
    content=b'transaction_id,transaction_date,transaction_time,transaction_amount,is_fraud,sender_id,recipient_id,channel\nOWN-001,2026-10-20,10:30:00,3000,0,BANK-A,BANK-B,API\nOWN-002,2026-10-20,11:15:00,2000,1,BANK-B,BANK-C,API\n'
    grant=[u['id'] for u in c.get('/api/v1/admin/access-users').json()]
    assert len(grant)==2  # demo Bank Analyst and Compliance Manager
    d=c.post('/api/v1/admin/datasets',files={'file':('bank.csv',content,'text/csv')},data={'source':'User test fixture; not training data','access_user_ids':','.join(grant)}).json()
    assert d['quality']['valid'] and sorted(d['allowed_users'])==sorted(grant),d
    assert c.post('/api/v1/admin/datasets/'+d['id']+'/import').status_code==200
    score=c.post('/api/v1/admin/datasets/'+d['id']+'/score');assert score.status_code==200,score.text
    assert score.json()['processed']==2 and score.json()['remaining']==0
    assert c.post('/api/v1/admin/datasets/'+d['id']+'/score').json()['processed']==0
    demo(c)
    rows=c.get('/api/v1/transactions?q=OWN-').json()['items'];assert len(rows)==2 and all(r['prediction'] for r in rows)
    graph=c.get('/api/v1/graph?account=BANK-A&depth=2').json();assert len(graph['edges'])==2
    paths=c.get('/api/v1/trace?source=BANK-A&destination=BANK-C').json()['paths'];assert len(paths)==1 and len(paths[0])==2
    demo(c,'manager');assert len(c.get('/api/v1/transactions?q=OWN-').json()['items'])==2
    # Administrator revokes access: the uploaded records disappear from the analyst's view.
    demo(c,'admin');assert c.put('/api/v1/admin/datasets/'+d['id']+'/access',json={'user_ids':[]}).status_code==200
    demo(c);assert c.get('/api/v1/transactions?q=OWN-').json()['items']==[]


def test_manager_model_denial_and_readable_filtered_audit(client):
    c=client;demo(c,'manager')
    assert c.get('/api/v1/models').status_code==403
    assert c.get('/api/v1/admin/monitoring').status_code==403
    events=c.get('/api/v1/audit').json()
    assert events and all(e['description'] and e['actor_name'] and e['demonstration'] for e in events)
    assert all(e['case_id'] for e in events)
    assert c.get('/api/v1/audit?date_from=2100-01-01').json()==[]
    assert c.get('/api/v1/audit?date_from=bad').status_code==422
    assert c.get('/api/v1/audit?date_from=2026-02-02&date_to=2026-01-01').status_code==422
    demo(c,'admin');assert c.get('/api/v1/models').status_code==200
