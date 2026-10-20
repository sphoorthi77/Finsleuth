"""Start frontend and test-only backend together, then run real Chromium checks."""
from pathlib import Path
import os,subprocess,sys,time,urllib.request
root=Path(__file__).resolve().parents[1];children=[];logs=[]
try:
    env=dict(os.environ,FINSLEUTH_BROWSER_QA='1')
    for name,args,cwd in [('backend',[sys.executable,'-m','pytest','tests/test_browser_host.py','-s'],root/'backend'),('frontend',['npm','run','dev'],root/'frontend')]:
        log=open(root/(name+'-browser-qa.log'),'w');logs.append(log);children.append(subprocess.Popen(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT))
    for url in ['http://127.0.0.1:8000/api/v1/health','http://127.0.0.1:5173']:
        for attempt in range(60):
            try:
                with urllib.request.urlopen(url,timeout=1) as r:
                    if r.status==200:break
            except Exception:time.sleep(.5)
        else:raise RuntimeError('QA server unavailable: '+url)
    result=subprocess.run(['npm','run','test:e2e','--',*sys.argv[1:]],cwd=root/'frontend');sys.exit(result.returncode)
finally:
    for child in children:child.terminate()
    for log in logs:log.close()
