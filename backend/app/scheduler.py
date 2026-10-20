"""Single-process persisted training schedule. Use one API worker."""
import asyncio
import logging
from .db import *
from .admin import training_worker
async def scheduler_loop():
    while True:
        try:
            with MongoUnitOfWork() as db:
                running=db.first(query(TrainingJob).where(TrainingJob.status=='running'))
                job=None if running else db.first(query(TrainingJob).where(TrainingJob.status=='scheduled',TrainingJob.scheduled_at<=now()).order_by(TrainingJob.scheduled_at))
                if job:
                    admin=db.first(query(User).where(User.scope==job.scope,User.role=='admin',User.status=='active'))
                    if admin:job.status='running';db.commit();await asyncio.to_thread(training_worker,job.id,admin.id)
                    else:job.status='failed';job.error='No active administrator remains in this workspace';job.completed_at=now();db.commit()
        except asyncio.CancelledError:raise
        except Exception:
            # Persisted jobs remain visible and can be retried after service recovery.
            logging.getLogger(__name__).exception("Training scheduler iteration failed")
        await asyncio.sleep(30)
