"""Read a CSV or CSV inside a ZIP without extracting the archive."""
from pathlib import Path
from zipfile import ZipFile
import pandas as pd

def load_dataset(path):
    path=Path(path)
    if path.suffix.lower()=='.zip':
        with ZipFile(path) as archive:
            members=[i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith('.csv')]
            if len(members)!=1:raise ValueError('ZIP must contain exactly one CSV dataset')
            if members[0].file_size>1024*1024*1024:raise ValueError('Uncompressed CSV exceeds 1 GB')
            with archive.open(members[0]) as stream:return pd.read_csv(stream)
    return pd.read_csv(path)
