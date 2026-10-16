"""Unified model metadata for the domestic and international exits."""

from collections import OrderedDict


REALM_ORDER = ("intl", "cn")


def build_registry(realm_entries):
    """Build ``model_id -> {realms, variants, metadata}`` records.

    Each realm's input is already ordered and already reflects that realm's
    catalog precedence.  When a realm repeats an ID, the later entry wins so
    a freshly fetched entry can replace a cached/static one.
    """
    registry = OrderedDict()
    for realm in REALM_ORDER:
        for model_id, metadata in (realm_entries or {}).get(realm, []) or []:
            model_id = str(model_id or "").strip()
            if not model_id:
                continue
            if realm not in REALM_ORDER:
                continue
            record = registry.setdefault(model_id, {
                "id": model_id,
                "realms": [],
                "variants": {},
            })
            record["variants"][realm] = dict(metadata or {})
            if realm not in record["realms"]:
                record["realms"].append(realm)
    for record in registry.values():
        base_realm = next((r for r in REALM_ORDER if r in record["variants"]), None)
        base = dict(record["variants"].get(base_realm) or {})
        record["metadata"] = base
        record["realms"] = tuple(record["realms"])
    return dict(registry)


def model_realms(registry, model_id):
    """Return known realms for a model in stable preference order."""
    record = (registry or {}).get(str(model_id or "").strip()) or {}
    known = set(record.get("realms") or ())
    return tuple(realm for realm in REALM_ORDER if realm in known)


def merged_entries(registry):
    """Return OpenAI-style entries with regional metadata extensions."""
    out = []
    for model_id, record in (registry or {}).items():
        metadata = dict(record.get("metadata") or {})
        metadata["x_workbuddy"] = {
            "realms": list(model_realms(registry, model_id)),
            "variants": {
                realm: dict(record.get("variants", {}).get(realm) or {})
                for realm in model_realms(registry, model_id)
            },
        }
        out.append((model_id, metadata))
    return out
