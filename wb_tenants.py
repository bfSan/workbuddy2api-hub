"""Tenant-scoped WorkBuddy data roots and explicit legacy migration."""
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time

APP_ID = "workbuddy2api-hub"


class TenantError(Exception):
    def __init__(self, code, message=None, status=403):
        self.code = code
        self.status = status
        super().__init__(message or code)


def _safe_component(value, field):
    value = str(value or "").strip()
    if not value or value in (".", "..") or "/" in value or "\\" in value or ".." in value:
        raise ValueError("%s is invalid" % field)
    return value


def _mkdir_private(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    try: os.chmod(path, 0o700)
    except OSError: pass


class TenantFileStore:
    def __init__(self, path, owner_user_id, app_id=APP_ID):
        self.path = path
        self.owner_user_id = owner_user_id
        self.app_id = app_id
        _mkdir_private(os.path.dirname(path))
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh: data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError, OSError): return {}
    def save(self, data):
        record = dict(data or {})
        record["app_id"] = self.app_id
        record["owner_user_id"] = self.owner_user_id
        _mkdir_private(os.path.dirname(self.path))
        fd, tmp = tempfile.mkstemp(prefix=".tenant-", dir=os.path.dirname(self.path), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2); fh.write("\n")
            os.chmod(tmp, 0o600); os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        return record


class TenantRuntime:
    def __init__(self, root, aac_user_id, workbuddy_user_id, app_id=APP_ID):
        self.root = root
        self.aac_user_id = aac_user_id
        self.workbuddy_user_id = workbuddy_user_id
        self.app_id = app_id
        _mkdir_private(root)
        _mkdir_private(os.path.join(root, "accounts")); _mkdir_private(os.path.join(root, "usage"))
        self.accounts = os.path.join(root, "accounts")
        self.settings = TenantFileStore(os.path.join(root, "settings.json"), workbuddy_user_id, app_id)
        self.usage = os.path.join(root, "usage")
        self.usage_log = os.path.join(self.usage, "usage.jsonl")
        self.usage_summary = os.path.join(self.usage, "usage-summary.json")
        self._pool = None
        self._pool_lock = threading.RLock()
        self._scheduler = None
        self._scheduler_lock = threading.RLock()
        self.scheduler_state = TenantFileStore(os.path.join(root, "scheduler.json"), workbuddy_user_id, app_id)
        self.user = TenantFileStore(os.path.join(root, "user.json"), workbuddy_user_id, app_id)
        if not self.user.load(): self.user.save({"aac_user_id": aac_user_id, "workbuddy_user_id": workbuddy_user_id, "role": "user", "status": "active", "created_at": time.time()})

    @property
    def pool(self):
        """Load credentials only when this tenant handles a request."""
        with self._pool_lock:
            if self._pool is None:
                import wb_accounts
                self._pool = wb_accounts.AccountPool(self.accounts)
                self._pool.load()
            return self._pool

    @property
    def scheduler(self):
        with self._scheduler_lock:
            if self._scheduler is None:
                from wb_scheduler import Scheduler
                self._scheduler = Scheduler(self.pool)
                self._scheduler.start()
            return self._scheduler


class TenantRuntimeManager:
    def __init__(self, data_root, app_id=APP_ID, max_cached=256):
        self.data_root = os.path.abspath(data_root)
        self.app_id = _safe_component(app_id, "app_id")
        self.tenants_root = os.path.join(self.data_root, "tenants")
        _mkdir_private(self.data_root); _mkdir_private(self.tenants_root)
        self.max_cached = max_cached
        self._cache = {}; self._lock = threading.RLock()
        self.index_path = os.path.join(self.data_root, "tenant-index.json")
    def get_or_create(self, aac_user_id, workbuddy_user_id):
        aac_user_id = _safe_component(aac_user_id, "aac_user_id"); workbuddy_user_id = _safe_component(workbuddy_user_id, "workbuddy_user_id")
        key = workbuddy_user_id
        with self._lock:
            runtime = self._cache.get(key)
            if runtime: return runtime
            root = os.path.join(self.tenants_root, aac_user_id)
            runtime = TenantRuntime(root, aac_user_id, workbuddy_user_id, self.app_id)
            self._cache[key] = runtime
            while len(self._cache) > self.max_cached: self._cache.pop(next(iter(self._cache)))
            return runtime

    def _load_index(self):
        try:
            with open(self.index_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError, OSError):
            return {}

    def _save_index(self, data):
        fd, tmp = tempfile.mkstemp(prefix=".tenant-index-", dir=self.data_root, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2); fh.write("\n")
            os.chmod(tmp, 0o600); os.replace(tmp, self.index_path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def register_api_key_owner(self, credential, runtime):
        if not credential or runtime is None: return None
        digest = hashlib.sha256(str(credential).encode()).hexdigest()
        with self._lock:
            index = self._load_index()
            owner = {"aac_user_id": runtime.aac_user_id, "workbuddy_user_id": runtime.workbuddy_user_id}
            existing = index.get(digest)
            if existing and (existing.get("aac_user_id"), existing.get("workbuddy_user_id")) != (owner["aac_user_id"], owner["workbuddy_user_id"]):
                raise TenantError("WB_API_KEY_OWNER_CONFLICT", "api key is already bound to another tenant", 409)
            index[digest] = owner
            self._save_index(index)
        return runtime

    def issue_api_key(self, runtime, label, expires_at=None):
        import wb_settings
        issued = wb_settings.issue_user_api_key(runtime.root, runtime.workbuddy_user_id, label, expires_at=expires_at)
        self.register_api_key_owner(issued.get("credential"), runtime)
        return issued

    def resolve_api_key_tenant(self, credential):
        """Resolve a user key without a browser session, failing closed."""
        credential = str(credential or "").strip()
        if not credential: return None
        digest = hashlib.sha256(credential.encode()).hexdigest()
        with self._lock:
            index = self._load_index()
            entry = index.get(digest)
            if entry:
                try:
                    runtime = self.get_or_create(entry["aac_user_id"], entry["workbuddy_user_id"])
                    import wb_settings
                    if wb_settings.resolve_api_key(credential, self.app_id, tenant_dir=runtime.root):
                        return runtime
                except (KeyError, ValueError, OSError):
                    pass
            # Rebuild lazily for keys created by older versions or direct API use.
            for aac_id in os.listdir(self.tenants_root) if os.path.isdir(self.tenants_root) else []:
                root = os.path.join(self.tenants_root, aac_id)
                if not os.path.isdir(root): continue
                user = TenantFileStore(os.path.join(root, "user.json"), "unknown", self.app_id).load()
                wb_id = str(user.get("workbuddy_user_id") or "")
                if not wb_id: continue
                runtime = self.get_or_create(aac_id, wb_id)
                import wb_settings
                principal = wb_settings.resolve_api_key(credential, self.app_id, tenant_dir=runtime.root)
                if principal:
                    index[digest] = {"aac_user_id": aac_id, "workbuddy_user_id": wb_id}
                    self._save_index(index)
                    return runtime
        return None

    def assert_owner(self, resource_owner_id, principal):
        if getattr(principal, "principal_type", "") == "local-admin": return None
        if str(resource_owner_id or "") != str(getattr(principal, "workbuddy_user_id", "")):
            raise TenantError("WB_TENANT_FORBIDDEN", "resource belongs to another tenant", 403)
        return None


def migrate_legacy_accounts(source_dir, target_tenant_dir, owner_user_id, *, dry_run=False):
    owner_user_id = _safe_component(owner_user_id, "owner_user_id")
    source_dir = os.path.abspath(source_dir); target_tenant_dir = os.path.abspath(target_tenant_dir)
    if not os.path.isdir(source_dir): raise TenantError("WB_LEGACY_SOURCE_MISSING", "legacy source is missing", 404)
    if os.path.exists(target_tenant_dir): raise TenantError("WB_TENANT_TARGET_EXISTS", "target tenant already exists", 409)
    files = []
    for root, dirs, names in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in names:
            src = os.path.join(root, name)
            if os.path.isfile(src): files.append(os.path.relpath(src, source_dir))
    result = {"owner_user_id": owner_user_id, "files": len(files), "bytes": sum(os.path.getsize(os.path.join(source_dir, f)) for f in files), "dry_run": bool(dry_run)}
    if dry_run: return result
    parent = os.path.dirname(target_tenant_dir); _mkdir_private(parent)
    staging = tempfile.mkdtemp(prefix=".tenant-migrate-", dir=parent)
    try:
        _mkdir_private(staging)
        for rel in files:
            src = os.path.join(source_dir, rel); dst = os.path.join(staging, rel)
            _mkdir_private(os.path.dirname(dst)); shutil.copy2(src, dst); os.chmod(dst, 0o600)
        TenantFileStore(os.path.join(staging, "migration.json"), owner_user_id).save({"owner_user_id": owner_user_id, "source_sha256": hashlib.sha256("\n".join(sorted(files)).encode()).hexdigest(), "completed_at": time.time()})
        os.replace(staging, target_tenant_dir)
    finally:
        if os.path.exists(staging): shutil.rmtree(staging, ignore_errors=True)
    return result
