import os
import subprocess
import sys
import time


scripts = [
    'etl/load_transactions.py',
    'etl/load_identity.py',
    'etl/load_closed_cases.py',
    'etl/embed_documents.py',
    'etl/load_case_pack.py',
    'etl/validate_load.py'
]

for script in scripts:
    print(f'\n========== RUNNING {script} ==========')
    res = subprocess.run([sys.executable, script])
    if res.returncode != 0:
        print(f'FAILED: {script} exited with {res.returncode}')
        sys.exit(res.returncode)
