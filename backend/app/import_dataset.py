from ml.data import load_dataset
"""Operational dataset import/training CLI for files above browser upload limits.
Run only as a trusted machine operator, like the secure administrator bootstrap.
"""
import argparse,hashlib,shutil
import pandas as pd
from .db import *
from .services import import_transactions
from .admin import training_worker
from ml.pipeline import validate
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--admin-email',required=True);p.add_argument('--source',required=True);p.add_argument('--import-transactions',action='store_true');p.add_argument('--train',action='store_true');a=p.parse_args()
    init_db()
    df=load_dataset(a.csv);report=validate(df)
    if not report['valid']:raise SystemExit(str(report['errors']))
    with MongoUnitOfWork() as db:
        user=db.first(query(User).where(User.scope=='operational',User.email==a.admin_email,User.role=='admin',User.status=='active'))
        if not user:raise SystemExit('Provide the email of an active operational administrator')
        if a.import_transactions:
            old=set(db.find(query(Transaction.source_id).where(Transaction.scope=='operational')))
            if old.intersection(df.transaction_id.astype(str)):raise SystemExit('Duplicate transaction IDs; no import performed')
        path=RUNTIME/(uid()+Path(a.csv).suffix.lower());shutil.copyfile(a.csv,path)
        d=Dataset(scope='operational',name=Path(a.csv).name,source=a.source,path=str(path),digest=hashlib.sha256(path.read_bytes()).hexdigest(),quality=report,status='validated');db.add(d);db.flush()
        if a.import_transactions:import_transactions(db,df,'operational',d.id);d.status='imported'
        audit(db,user,'dataset.cli_registered',d.id,{'rows':len(df),'imported':a.import_transactions})
        job=None
        if a.train:job=TrainingJob(scope='operational',dataset_id=d.id,status='running');db.add(job)
        db.commit();print('Dataset version:',d.id)
        if job:
            training_worker(job.id,user.id);db.refresh(job);print('Training job:',job.status,job.error)
            if job.status=='failed':raise SystemExit(1)
    print('Review candidates in the administrator UI, then approve and deploy.')
