import os
from pathlib import Path

def check(name, condition):
    if not condition: raise SystemExit("FAIL: "+name)
    print("PASS: "+name)
root=Path(__file__).parent
compose=(root/'docker-compose.yml').read_text()
docker=(root/'Dockerfile').read_text()
check('compose has AAC env', 'AAC_BASE_URL' in compose and 'WB_DATA_ROOT' in compose)
check('compose excludes qoder', 'qoder' not in compose.lower())
check('docker non-root', 'USER' in docker)
check('migration cli exists', (root/'scripts/migrate-legacy-tenant.py').exists())
check('auth module exists', (root/'wb_auth.py').exists())

import subprocess, tempfile, json
with tempfile.TemporaryDirectory() as td:
    src=Path(td)/"legacy"; src.mkdir(); (src/"secret.json").write_text("super-secret-token")
    out=subprocess.check_output(["python",str(root/"scripts/migrate-legacy-tenant.py"),"--source",str(src),"--target",str(Path(td)/"data"),"--owner-user-id","user-secret","--dry-run"],text=True)
    check("migration redacts identifiers", "super-secret-token" not in out and "user-sec…" in out)
