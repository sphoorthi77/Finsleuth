"""Administrator-controlled dataset access for Bank Analysts and Compliance Managers."""
import os,tempfile
os.environ['FINSLEUTH_TEST_MOCK']='1'
os.environ['MONGODB_DATABASE']='finsleuth_test_access'
os.environ['ARTIFACT_DIR']=tempfile.mkdtemp()
import json,pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import database,init_db,MongoUnitOfWork,User,Case,CaseTransaction,Transaction,Dataset,Audit,query
from app.security import ph

CSV=(b'transaction_id,transaction_date,transaction_amount,is_fraud,sender_id,recipient_id,customer_id\n'
     b'a-1,2025-04-01,2500,0,AC-1,AC-2,C1\na-2,2025-04-02,900,1,AC-2,AC-3,C1\n')
PW='long-test-password'
def login(c,email):
    r=c.post('/api/v1/auth/login',json={'email':email,'password':PW});assert r.status_code==200,r.text
def new_client():return TestClient(app,headers={'X-Finsleuth':'1'})

@pytest.fixture()
def env():
    from app.security import attempts
    attempts.clear();database.client.drop_database(database.name);init_db()
    ids={}
    with MongoUnitOfWork() as db:
        for key,role in [('admin','admin'),('analyst','analyst'),('analyst2','analyst'),('manager','manager')]:
            u=User(name=key.title(),email=key+'@example.test',password_hash=ph.hash(PW),role=role,status='active',scope='operational');db.add(u);ids[key]=u.id
        db.commit()
    with TestClient(app,headers={'X-Finsleuth':'1'}) as admin:
        login(admin,'admin@example.test')
        r=admin.post('/api/v1/admin/datasets',files={'file':('d.csv',CSV,'text/csv')},data={'source':'Test fixture','access_user_ids':json.dumps([ids['analyst'],ids['manager']])});assert r.status_code==200,r.text
        d=r.json();assert sorted(d['allowed_users'])==sorted([ids['analyst'],ids['manager']])
        assert admin.post('/api/v1/admin/datasets/'+d['id']+'/import').status_code==200
        yield admin,d['id'],ids

def first_tx(c):
    items=c.get('/api/v1/transactions').json()['items'];return items

def test_unassigned_users_see_nothing_and_assigned_users_see_data(env):
    admin,did,ids=env
    with new_client() as a:
        login(a,'analyst@example.test');items=first_tx(a);assert len(items)==2
        assert a.get('/api/v1/graph?account=AC-2').json()['edges']
        assert a.get('/api/v1/accounts/AC-2').json()['count']==2
        assert a.get('/api/v1/metadata/transactions').json()['has_transfer_relationships']
    with new_client() as b:
        login(b,'analyst2@example.test')
        assert b.get('/api/v1/transactions').json()['total']==0
        tid=items[0]['id']
        assert b.get('/api/v1/transactions/'+tid).status_code==404
        assert b.post('/api/v1/transactions/'+tid+'/predict').status_code==404
        assert b.get('/api/v1/transactions/'+tid+'/alert').status_code==404
        assert b.patch('/api/v1/transactions/'+tid+'/alert',json={'status':'open'}).status_code==404
        assert b.get('/api/v1/graph?account=AC-2').json()['edges']==[]
        assert b.get('/api/v1/trace?source=AC-1&destination=AC-3').json()['paths']==[]
        assert b.get('/api/v1/accounts/AC-2').json()['count']==0
        assert b.get('/api/v1/metadata/transactions').json()['channels']==[]
        assert b.post('/api/v1/cases',json={'title':'Blocked case here','reason':'Should not be allowed','transaction_ids':[tid]}).status_code==404
        assert b.get('/api/v1/overview').json()['metrics'][0]['value']==0

def test_cases_and_exports_follow_access_and_revocation(env):
    admin,did,ids=env
    with new_client() as a,new_client() as m:
        login(a,'analyst@example.test');login(m,'manager@example.test')
        tid=first_tx(a)[0]['id']
        r=a.post('/api/v1/cases',json={'title':'Access controlled case','reason':'Review the transaction pattern','transaction_ids':[tid]});assert r.status_code==200,r.text;cid=r.json()['id']
        assert a.post(f'/api/v1/cases/{cid}/notes',json={'text':'Observation on the record.'}).status_code==200
        assert a.post(f'/api/v1/cases/{cid}/submit').status_code==200
        for c in (a,m):
            assert c.get(f'/api/v1/cases/{cid}').status_code==200
            assert c.get(f'/api/v1/cases/{cid}/report').status_code==200
            assert c.get(f'/api/v1/cases/{cid}/report.pdf').status_code==200
            assert cid in c.get('/api/v1/reports/compliance.csv').text
        assert len(m.get('/api/v1/cases').json())==1
        # Revoke the manager only.
        r=admin.put(f'/api/v1/admin/datasets/{did}/access',json={'user_ids':[ids['analyst']]});assert r.status_code==200 and r.json()['removed']==[ids['manager']]
        assert m.get('/api/v1/cases').json()==[]
        for path in ['','/report','/report.pdf','/attachments']:assert m.get(f'/api/v1/cases/{cid}{path}').status_code==404,path
        assert cid not in m.get('/api/v1/reports/compliance.csv').text
        assert m.get('/api/v1/reports/quality').json()['cases']==0
        assert m.post(f'/api/v1/cases/{cid}/review',json={'decision':'closed','rationale':'Manager access was revoked'}).status_code==404
        assert a.get(f'/api/v1/cases/{cid}').status_code==200
        # Revoke the analyst too: even the case owner loses the case and exports.
        assert admin.put(f'/api/v1/admin/datasets/{did}/access',json={'user_ids':[]}).status_code==200
        assert a.get(f'/api/v1/cases/{cid}').status_code==404 and a.get('/api/v1/cases').json()==[]
        assert a.get('/api/v1/transactions').json()['total']==0
        assert a.post(f'/api/v1/cases/{cid}/evidence',json={'kind':'transaction','reference':tid,'description':'Should be refused'}).status_code in (404,409)
        # Re-grant restores access.
        assert admin.put(f'/api/v1/admin/datasets/{did}/access',json={'user_ids':[ids['analyst'],ids['manager']]}).status_code==200
        assert m.get(f'/api/v1/cases/{cid}').status_code==200

def test_admin_only_validation_and_audit(env):
    admin,did,ids=env
    with new_client() as a:
        login(a,'analyst@example.test')
        assert a.put(f'/api/v1/admin/datasets/{did}/access',json={'user_ids':[ids['analyst']]}).status_code==403
        assert a.get(f'/api/v1/admin/datasets/{did}/access').status_code==403
        assert a.get('/api/v1/admin/access-users').status_code==403
    assert admin.put(f'/api/v1/admin/datasets/{did}/access',json={'user_ids':[ids['admin']]}).status_code==422
    assert admin.put(f'/api/v1/admin/datasets/{did}/access',json={'user_ids':['missing']}).status_code==422
    assert {u['role'] for u in admin.get('/api/v1/admin/access-users').json()}=={'analyst','manager'}
    assert sorted(admin.get(f'/api/v1/admin/datasets/{did}/access').json()['user_ids'])==sorted([ids['analyst'],ids['manager']])
    admin.put(f'/api/v1/admin/datasets/{did}/access',json={'user_ids':[ids['analyst'],ids['analyst2']]})
    admin.put(f'/api/v1/admin/datasets/{did}/access',json={'user_ids':[ids['analyst'],ids['analyst2']]})  # no-op: no extra event
    events=[e for e in admin.get('/api/v1/audit').json() if e['action'].startswith('dataset.access')]
    actions=sorted(e['action'] for e in events);assert actions==['dataset.access_changed','dataset.access_granted'],actions
    change=next(e for e in events if e['action']=='dataset.access_changed')
    assert change['details']['added']==[ids['analyst2']] and change['details']['removed']==[ids['manager']] and change['actor_name']=='Admin'
    # Managers' audit view stays limited to case events.
    with new_client() as m:
        login(m,'manager@example.test');assert not [e for e in m.get('/api/v1/audit').json() if e['action'].startswith('dataset.')]
