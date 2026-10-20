"""Create the first operational administrator; never overwrite existing accounts."""
import argparse,getpass
from pathlib import Path
from .db import *
from .security import ph

def create_admin(email,name,password,reset=False):
    email=email.strip().lower()
    if len(password)<12 or '@' not in email or not name.strip():raise ValueError('Valid email, name and a password of at least 12 characters are required')
    with MongoUnitOfWork() as db:
        existing=db.first(query(User).where(User.scope=='operational',User.email==email))
        if existing:
            if existing.role!='admin' or existing.status!='active':raise ValueError('An account with this email exists but is not an active administrator. No account changed.')
            if reset:
                existing.password_hash=ph.hash(password)
                for session in db.find(query(Session).where(Session.user_id==existing.id)):db.delete(session)
                audit(db,existing,'admin.password_reset',existing.id,{'method':'Trusted host command'})
                db.commit()
            return False
        db.add(User(name=name,email=email,password_hash=ph.hash(password),role='admin',status='active',scope='operational',organisation='Local administrator',reason='Trusted local setup'));db.commit()
    return True

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--from-file',help='Local credentials file supplied with this project (trusted-host setup only)');parser.add_argument('--reset-password',action='store_true',help='Explicitly reset an existing active administrator and revoke sessions');args=parser.parse_args()
    init_db()
    if args.from_file:
        lines=Path(args.from_file).read_text().splitlines();values=dict(line.split(': ',1) for line in lines if ': ' in line)
        email=values['Email'];password=values['Password'];name='Finsleuth Administrator'
    else:
        email=input('Administrator email: ');name=input('Administrator name: ');password=getpass.getpass('Password (12+ characters): ')
    try:created=create_admin(email,name,password,reset=args.reset_password)
    except ValueError as e:raise SystemExit(str(e))
    print('Administrator created: '+email if created else 'Administrator password reset: '+email if args.reset_password else 'Administrator already exists. Existing password was preserved.')
