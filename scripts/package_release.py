"""Build and verify a standard Windows-compatible source ZIP."""
from pathlib import Path
import zipfile,hashlib,json
root=Path(__file__).resolve().parents[1]
output=root.parent/'Finsleuth_Final_Fixed.zip'
excluded={'node_modules','venv','__pycache__','.pytest_cache','.git','dist','test-results','playwright-report','runtime','backups','restored','.vite','raw'}
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=False) as archive:
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():continue
        if any(part in excluded or part.startswith('.venv') for part in path.relative_to(root).parts):continue
        if any(part.startswith('.') and part not in {'.gitignore','.env.example'} for part in path.relative_to(root).parts):continue
        if path.name in {'logo.png','LOCAL_ADMIN.txt'}:continue
        if path.suffix in {'.pyc','.log','.tsbuildinfo','.docx','.doc'} or path.name=='.env':continue
        info=zipfile.ZipInfo(str(Path(root.name)/path.relative_to(root)).replace('\\','/'))
        info.create_system=0;info.external_attr=0x20;info.compress_type=zipfile.ZIP_DEFLATED
        archive.writestr(info,path.read_bytes())
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    names=archive.namelist()
    assert not any('docker' in n.lower() or n.endswith('.docx') or '/Start-' in n for n in names)
    assert sum(n.endswith('.joblib') for n in names)==6
    manifest=json.loads(archive.read('Finsleuth/artifacts/dataset/manifest.json'))
    assert hashlib.sha256(archive.read('Finsleuth/data/archive.zip')).hexdigest()==manifest['source']['sha256']
    for report in manifest['reports']:assert 'Finsleuth/artifacts/dataset/'+report['artifact'] in names
    assert 'Finsleuth/manage.py' in names
print(json.dumps({'file':str(output),'bytes':output.stat().st_size,'files':len(names),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
