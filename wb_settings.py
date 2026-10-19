"""Runtime settings for the gateway: panel password and API key override.

Everything lives in `accounts/settings.json` so a change made from the web
panel survives a restart without editing the launcher .bat files. The panel
password is never stored in clear text - only a PBKDF2-SHA256 digest.

Only the Python standard library is required.
"""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time

DEFAULT_PANEL_PASSWORD = "admin"
PBKDF2_ROUNDS = 120_000
SESSION_TTL = 7 * 24 * 3600

_lock = threading.RLock()


def settings_path(accounts_dir):
    return os.path.join(accounts_dir, "settings.json")


def _digest(password, salt_hex, rounds=PBKDF2_ROUNDS):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), rounds
    ).hex()


def load(accounts_dir):
    """Return the persisted settings, or an empty dict on a fresh install."""
    path = settings_path(accounts_dir)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return {}


def save(accounts_dir, data):
    """Atomic write so a crash cannot leave a half-written settings file."""
    with _lock:
        os.makedirs(accounts_dir, exist_ok=True)
        path = settings_path(accounts_dir)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path


def panel_password_is_default(accounts_dir):
    data = load(accounts_dir)
    if not data.get("panel_password_hash"):
        return True
    return data.get("panel_password_default") is True


def verify_panel_password(accounts_dir, password):
    """True when `password` opens the web panel."""
    password = password or ""
    data = load(accounts_dir)
    stored = data.get("panel_password_hash")
    if not stored:
        return password == DEFAULT_PANEL_PASSWORD
    if data.get("panel_password_default") is True:
        return password == DEFAULT_PANEL_PASSWORD
    salt = data.get("panel_password_salt")
    if not salt:
        return False
    rounds = int(data.get("panel_password_rounds") or PBKDF2_ROUNDS)
    try:
        given = _digest(password, salt, rounds)
    except Exception:
        return False
    return hmac.compare_digest(given, stored)


def set_panel_password(accounts_dir, password):
    with _lock:
        data = load(accounts_dir)
        if password == DEFAULT_PANEL_PASSWORD:
            data.pop("panel_password_salt", None)
            data.pop("panel_password_rounds", None)
            data["panel_password_hash"] = ""
            data["panel_password_default"] = True
        else:
            salt = secrets.token_hex(16)
            data["panel_password_salt"] = salt
            data["panel_password_rounds"] = PBKDF2_ROUNDS
            data["panel_password_hash"] = _digest(password, salt)
            data["panel_password_default"] = False
        save(accounts_dir, data)


def api_key_override(accounts_dir):
    """Return (key, is_set). `is_set` means the panel manages the key."""
    data = load(accounts_dir)
    if not data.get("api_key_set"):
        return None, False
    return str(data.get("api_key") or ""), True


def set_api_key(accounts_dir, key):
    with _lock:
        data = load(accounts_dir)
        data["api_key"] = key or ""
        data["api_key_set"] = True
        save(accounts_dir, data)


def ensure_launcher_key(accounts_dir):
    """Return the persisted LAN key, creating one on first use.

    LAN mode must never ship a well-known default: the gateway spends the
    account's own upstream quota, so anyone on the same network could drain it.
    The value is generated once and stored so clients keep working across
    restarts. Returns (key, created) so the caller can tell the user whether
    this run minted a fresh credential.
    """
    with _lock:
        data = load(accounts_dir)
        existing = str(data.get("launcher_key") or "").strip()
        if existing:
            return existing, False
        key = "wb-" + secrets.token_urlsafe(24)
        data["launcher_key"] = key
        save(accounts_dir, data)
        return key, True


# --------------------------------------------------------------- API keys
# Each key can use automatic routing or be bound to one upstream realm, so
# several clients can hit different exits at the same time without a global
# switch controlling API traffic.

REALMS = ("auto", "intl", "cn")


def normalize_key_realm(value):
    """Return the supported Key routing policy."""
    realm = str(value or "").strip().lower()
    return realm if realm in REALMS else "auto"


def _clean_key_entry(entry):
    """Normalize one stored key entry; returns None when unusable."""
    if not isinstance(entry, dict):
        return None
    key = str(entry.get("key") or "").strip()
    if not key:
        return None
    realm = normalize_key_realm(entry.get("realm"))
    # PATCH(wb-hub-key-accounts) 这个函数的返回字典是硬编码的白名单，
    # 不在这里放行的话 accounts 会被静默丢掉（面板看着存进去了，重启就没了）。
    accounts = entry.get("accounts")
    if isinstance(accounts, (list, tuple)):
        accounts = [str(x).strip() for x in accounts if str(x).strip()]
    else:
        accounts = []
    return {
        "id": str(entry.get("id") or secrets.token_hex(6)),
        "name": str(entry.get("name") or "").strip() or "未命名",
        "key": key,
        "realm": realm,
        "enabled": entry.get("enabled", True) is not False,
        "accounts": accounts,
    }


def api_keys(accounts_dir):
    """Every configured key, newest shape first.

    A settings file written by an older build only has the single
    `api_key`/`api_key_set` pair; that is surfaced as one unbound entry so
    upgrades keep working without a migration step.
    """
    data = load(accounts_dir)
    stored = data.get("api_keys")
    if isinstance(stored, list):
        out = []
        seen = set()
        for raw in stored:
            entry = _clean_key_entry(raw)
            if entry and entry["key"] not in seen:
                seen.add(entry["key"])
                out.append(entry)
        return out

    if data.get("api_key_set"):
        legacy = str(data.get("api_key") or "").strip()
        if legacy:
            return [{
                "id": "legacy",
                "name": "默认（自动路由）",
                "key": legacy,
                "realm": "auto",
                "enabled": True,
            }]
    return []


def set_api_keys(accounts_dir, keys):
    """Replace the whole key list. Returns the stored list."""
    with _lock:
        cleaned = []
        seen = set()
        for raw in keys or []:
            entry = _clean_key_entry(raw)
            if entry and entry["key"] not in seen:
                seen.add(entry["key"])
                cleaned.append(entry)
        data = load(accounts_dir)
        data["api_keys"] = cleaned
        # The single-key fields are now derived; drop them so there is one
        # source of truth and the list survives a restart.
        data.pop("api_key", None)
        data.pop("api_key_set", None)
        save(accounts_dir, data)
        return cleaned


def match_api_key(accounts_dir, supplied, extra_keys=()):
    """Find which configured key a request presented, if any.

    Returns a copy of the entry (with a `source` field) so the caller can read
    the bound realm, or None when nothing matches.
    """
    supplied = (supplied or "").strip()
    if not supplied:
        return None
    for entry in api_keys(accounts_dir):
        if entry["enabled"] and hmac.compare_digest(supplied, entry["key"]):
            out = dict(entry)
            out["source"] = "panel"
            return out
    for candidate in extra_keys:
        candidate = (candidate or "").strip()
        if candidate and hmac.compare_digest(supplied, candidate):
            return {
                "id": "launcher",
                "name": "启动参数",
                "key": candidate,
                "realm": "auto",
                "enabled": True,
                "source": "launcher",
            }
    return None


def auth_disabled(accounts_dir):
    """True when the operator switched API-key checking off entirely."""
    return load(accounts_dir).get("auth_disabled") is True


def set_auth_disabled(accounts_dir, disabled):
    with _lock:
        data = load(accounts_dir)
        data["auth_disabled"] = bool(disabled)
        save(accounts_dir, data)


class PanelSessions(object):
    """In-memory bearer tokens handed out after a successful panel login.

    Deliberately not persisted: restarting the gateway logs browsers out, which
    is the safer default for a LAN tool that people expose behind a port map.
    """

    def __init__(self, ttl=SESSION_TTL):
        self.ttl = ttl
        self._tokens = {}
        self._lock = threading.RLock()

    def create(self):
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[token] = time.time() + self.ttl
        return token

    def valid(self, token):
        if not token:
            return False
        with self._lock:
            expiry = self._tokens.get(token)
            if not expiry:
                return False
            if expiry < time.time():
                self._tokens.pop(token, None)
                return False
            return True

    def revoke(self, token):
        if not token:
            return
        with self._lock:
            self._tokens.pop(token, None)

    def revoke_all(self):
        with self._lock:
            self._tokens.clear()


def account_aliases(accounts_dir):
    """# PATCH(wb-hub-account-alias) 账号别名表：uid -> 别名。空值会被丢掉，等于该号用回上游昵称。"""
    data = load(accounts_dir)
    raw = data.get("account_aliases")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        uid = str(key or "").strip()
        name = str(value or "").strip()
        if uid and name:
            out[uid] = name
    return out


def model_config(accounts_dir):
    """# PATCH(wb-hub-model-config) 面板可配置的模型列表：按 realm 存 hidden / order。

    返回 {"intl": {"hidden": [...], "order": [...]}, "cn": {...}}，缺省为空。
    - hidden: 需要从列表隐藏的模型 id
    - order : 期望的展示顺序（未列出的按默认顺序追加）
    """
    data = load(accounts_dir)
    raw = data.get("model_config")
    out = {}
    if not isinstance(raw, dict):
        return out
    for realm in ("intl", "cn"):
        entry = raw.get(realm)
        if not isinstance(entry, dict):
            continue
        hidden = [str(x).strip() for x in (entry.get("hidden") or [])
                  if str(x).strip()]
        order = [str(x).strip() for x in (entry.get("order") or [])
                 if str(x).strip()]
        out[realm] = {"hidden": hidden, "order": order}
    return out


def set_model_config(accounts_dir, realm, hidden, order):
    """# PATCH(wb-hub-model-config) 整体覆盖某个 realm 的模型显隐/顺序配置。"""
    realm = str(realm or "").strip().lower()
    if realm not in ("intl", "cn"):
        raise ValueError("realm must be intl or cn")
    data = load(accounts_dir)
    raw = data.get("model_config")
    if not isinstance(raw, dict):
        raw = {}
    seen = set()
    clean_hidden = []
    for x in (hidden or []):
        v = str(x).strip()
        if v and v not in seen:
            seen.add(v)
            clean_hidden.append(v)
    clean_order, seen2 = [], set()
    for x in (order or []):
        v = str(x).strip()
        if v and v not in seen2:
            seen2.add(v)
            clean_order.append(v)
    raw[realm] = {"hidden": clean_hidden, "order": clean_order}
    data["model_config"] = raw
    save(accounts_dir, data)
    return raw[realm]


def set_account_aliases(accounts_dir, mapping):
    """整体覆盖别名表（面板每次提交全量）。"""
    data = load(accounts_dir)
    raw = mapping if isinstance(mapping, dict) else {}
    out = {}
    for key, value in raw.items():
        uid = str(key or "").strip()
        name = str(value or "").strip()
        if uid and name:
            out[uid] = name
    data["account_aliases"] = out
    save(accounts_dir, data)
    return out


def oauth_config(env=None):
    env = env or os.environ
    return {
        "aac_base_url": str(env.get("AAC_BASE_URL") or "").rstrip("/"),
        "aac_public_base_url": str(env.get("AAC_PUBLIC_BASE_URL") or env.get("AAC_BASE_URL") or "").rstrip("/"),
        "client_id": str(env.get("AAC_CLIENT_ID") or "workbuddy2api-hub"),
        "redirect_uri": str(env.get("AAC_REDIRECT_URI") or ""),
        "auth_mode": str(env.get("WB_AUTH_MODE") or "hybrid").strip().lower(),
    }

from dataclasses import dataclass

@dataclass(frozen=True)
class KeyPrincipal:
    key_id: str
    owner_user_id: str
    app_id: str
    scope: str
    label: str = ""
    expires_at: float = 0.0
    last_used_at: float = 0.0
    principal_type: str = "api-key"
    role: str = "user"

class AuthzError(Exception):
    def __init__(self, code="WB_TENANT_FORBIDDEN", message=None, status=403):
        self.code = code; self.status = status
        super().__init__(message or code)

def _key_file(tenant_dir):
    return os.path.join(tenant_dir, ".api-keys.json")

def issue_user_api_key(tenant_dir, owner_user_id, label, expires_at=None):
    os.makedirs(tenant_dir, mode=0o700, exist_ok=True)
    credential = "wbk_" + secrets.token_urlsafe(32)
    now = time.time()
    record = {"key_id": secrets.token_hex(12), "owner_user_id": str(owner_user_id), "app_id": "workbuddy2api-hub", "scope": "user", "key_hash": hashlib.sha256(credential.encode()).hexdigest(), "label": str(label or "").strip()[:120], "enabled": True, "expires_at": float(expires_at or now + 365*24*3600), "last_used_at": 0.0}
    records = _load_key_records(tenant_dir); records.append(record); _save_key_records(tenant_dir, records)
    metadata = dict(record); metadata.pop("key_hash", None)
    return {"credential": credential, "metadata": metadata}

def resolve_api_key(credential, app_id, now=None, tenant_dir=None):
    credential = str(credential or "").strip()
    if not credential: return None
    digest = hashlib.sha256(credential.encode()).hexdigest(); now = float(time.time() if now is None else now)
    dirs = [tenant_dir] if tenant_dir else []
    for directory in dirs:
        for record in _load_key_records(directory):
            if record.get("app_id") != app_id or not record.get("enabled") or float(record.get("expires_at") or 0) <= now: continue
            if hmac.compare_digest(str(record.get("key_hash") or ""), digest):
                return KeyPrincipal(str(record.get("key_id")), str(record.get("owner_user_id")), str(record.get("app_id")), str(record.get("scope") or "user"), str(record.get("label") or ""), float(record.get("expires_at") or 0), float(record.get("last_used_at") or 0), "api-key", "admin" if record.get("scope") == "app" else "user")
    return None

def authorize_route(principal, route, method, *, resource_owner_id=None):
    if principal is None: raise AuthzError("WB_AUTH_REQUIRED")
    if getattr(principal, "principal_type", "") == "local-admin": return None
    role = getattr(principal, "role", "user")
    if resource_owner_id and role != "admin" and str(resource_owner_id) != str(getattr(principal, "workbuddy_user_id", "")):
        raise AuthzError()
    if route in ("settings", "scheduler", "realm") and role != "admin" and method not in ("GET", "HEAD"):
        raise AuthzError("WB_WORKBUDDY_ADMIN_REQUIRED")
    return None

def _load_key_records(tenant_dir):
    try:
        with open(_key_file(tenant_dir), encoding="utf-8") as fh: data=json.load(fh)
        return data if isinstance(data,list) else []
    except (FileNotFoundError, ValueError, OSError): return []

def _save_key_records(tenant_dir, records):
    path=_key_file(tenant_dir); tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as fh: json.dump(records,fh,ensure_ascii=False,indent=2); fh.write("\n")
    os.chmod(tmp,0o600); os.replace(tmp,path)
