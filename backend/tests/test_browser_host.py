"""Opt-in browser QA host using a test-only Mongo substitute and supplied dataset.
Run: FINSLEUTH_BROWSER_QA=1 python -m pytest tests/test_browser_host.py -s
Never use this host for operational persistence.
"""
import os,tempfile
import pytest
@pytest.mark.skipif(os.getenv('FINSLEUTH_BROWSER_QA')!='1',reason='Opt-in browser QA host')
def test_serve_browser_qa():
    os.environ['FINSLEUTH_TEST_MOCK']='1';os.environ['MONGODB_DATABASE']='finsleuth_browser_test';os.environ['ARTIFACT_DIR']=tempfile.mkdtemp()
    from app.main import app
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8000)
