from pathlib import Path
import importlib.util
import pandas as pd
from ml.joint_benchmark import history_features

def test_history_excludes_simultaneous_and_future_events():
    frame=pd.DataFrame({'customer_id':['a']*4,'transaction_date':['2025-01-01']*4,'transaction_time':['10:00','10:00','11:00','12:00'],'transaction_amount':[10.,30.,100.,9999.]})
    result=history_features(frame)
    assert result.previous_count.tolist()==[0,0,2,3]
    assert result.previous_mean_amount.iloc[2]==20
    assert result.previous_amount.iloc[2]==20
    assert result.seconds_since_previous.iloc[2]==3600
    frame.loc[3,'transaction_amount']=1
    pd.testing.assert_frame_equal(result.iloc[:3],history_features(frame).iloc[:3])

def test_setup_credentials_are_unique_local_and_idempotent(tmp_path):
    spec=importlib.util.spec_from_file_location('manage_release',Path(__file__).resolve().parents[2]/'manage.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.ROOT=tmp_path
    module.ensure_credentials();first=(tmp_path/'LOCAL_ADMIN.txt').read_text()
    module.ensure_credentials();assert (tmp_path/'LOCAL_ADMIN.txt').read_text()==first
    assert 'Email: admin@finsleuth.local' in first
    assert len(first.split('Password: ')[1].strip())>=20
