"""Idempotent collection validation and index setup."""
from .db import init_db,database
if __name__=='__main__':
    init_db()
    print('MongoDB collections and indexes ready:',database.name)
