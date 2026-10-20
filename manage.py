"""One cross-platform command for setup, admin recovery and serving the built app."""
from pathlib import Path
import argparse,os,subprocess,sys,shutil,secrets
ROOT=Path(__file__).resolve().parent

def run(args,cwd=ROOT):subprocess.run([str(x) for x in args],cwd=cwd,check=True)
def ensure_credentials():
    path=ROOT/'LOCAL_ADMIN.txt'
    if not path.exists():
        # A separate random password per installation; no universal password in the ZIP.
        with path.open('x',encoding='utf-8') as f:
            f.write('Email: admin@finsleuth.local\nPassword: '+secrets.token_urlsafe(20)+'\n')
        if os.name!='nt':path.chmod(0o600)
    print('Administrator email: admin@finsleuth.local. Password: open '+str(path),flush=True)

def main():
    parser=argparse.ArgumentParser(description='Finsleuth project management')
    parser.add_argument('command',choices=['setup','serve','reset-admin'])
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=int(os.getenv('PORT','8000')))
    args=parser.parse_args()
    if sys.version_info[:2] not in [(3,12),(3,13)]:parser.error('Use standard Python 3.13 or 3.12')
    python=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if args.command=='setup':
        if not python.exists():run([sys.executable,'-m','venv',ROOT/'.venv'])
        req='requirements-windows-py313.txt' if os.name=='nt' and sys.version_info[:2]==(3,13) else 'requirements.txt'
        run([python,'-m','pip','install','-r',ROOT/'backend'/req])
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        if not npm:raise SystemExit('Install Node.js with npm, then rerun setup.')
        run([npm,'ci'],ROOT/'frontend');run([npm,'run','build'],ROOT/'frontend')
        if not (ROOT/'backend/.env').exists():shutil.copyfile(ROOT/'backend/.env.example',ROOT/'backend/.env')
        run([python,'-m','app.setup_db'],ROOT/'backend')
        ensure_credentials()
        run([python,'-m','app.bootstrap','--from-file',ROOT/'LOCAL_ADMIN.txt'],ROOT/'backend')
        run([python,'-m','app.load_source','--admin-email','admin@finsleuth.local'],ROOT/'backend')
        print('Setup complete. Run: python manage.py serve')
    elif args.command=='reset-admin':
        if not python.exists():raise SystemExit('Run python manage.py setup first.')
        ensure_credentials()
        run([python,'-m','app.bootstrap','--from-file',ROOT/'LOCAL_ADMIN.txt','--reset-password'],ROOT/'backend')
        print('Administrator credentials now match LOCAL_ADMIN.txt. Other accounts and data were preserved.')
    else:
        if not python.exists() or not (ROOT/'frontend/dist/index.html').exists():raise SystemExit('Run python manage.py setup first.')
        print(f'Open http://localhost:{args.port} — press Ctrl+C to stop.',flush=True)
        run([python,'-m','uvicorn','app.main:app','--host',args.host,'--port',args.port],ROOT/'backend')
if __name__=='__main__':
    try:main()
    except subprocess.CalledProcessError as exc:raise SystemExit(f'Command failed ({exc.returncode}). Read the error above, correct the setting, and rerun. Existing data is retained.')
