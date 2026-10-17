#!/usr/bin/env python3
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wb_tenants import migrate_legacy_accounts
p=argparse.ArgumentParser(); p.add_argument('--source',required=True); p.add_argument('--target',required=True); p.add_argument('--owner-user-id',required=True); p.add_argument('--dry-run',action='store_true'); a=p.parse_args()
r=migrate_legacy_accounts(a.source, os.path.join(a.target,'tenants',a.owner_user_id), a.owner_user_id, dry_run=a.dry_run)
print(json.dumps({'owner_user_id':r['owner_user_id'][:8]+'…','files':r['files'],'bytes':r['bytes'],'dry_run':r['dry_run']}, ensure_ascii=False))
