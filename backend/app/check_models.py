"""Verify the supplied fitted artifacts in the selected Python environment; no MongoDB needed."""
from pathlib import Path
import json,platform
import joblib
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
def check():
    manifest=json.loads((ROOT/'artifacts/dataset/manifest.json').read_text())
    results=[]
    for report in manifest['reports']:
        bundle=joblib.load(ROOT/'artifacts/dataset'/report['artifact'])
        probabilities=bundle['pipeline'].predict_proba(bundle['reference'])
        if probabilities.shape!=(len(bundle['reference']),2) or not np.isfinite(probabilities).all() or not ((probabilities>=0)&(probabilities<=1)).all():
            raise RuntimeError('Invalid predictions from '+report['algorithm'])
        if abs(bundle['threshold']-report['threshold'])>1e-12:raise RuntimeError('Model/report threshold mismatch')
        results.append({'algorithm':report['algorithm'],'status':'loaded and predicted','rows':len(bundle['reference'])})
    print(json.dumps({'python':platform.python_version(),'models':results},indent=2))
    return results
if __name__=='__main__':check()
