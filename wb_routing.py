"""Pure route planning helpers for the unified WorkBuddy gateway."""

import hashlib
from dataclasses import dataclass


REALMS = ("intl", "cn")


@dataclass(frozen=True)
class RouteCandidate:
    realm: str
    reason: str


def _stable_order(model_id, realms):
    realms = list(realms)
    if len(realms) < 2:
        return realms
    digest = hashlib.sha256(str(model_id or "").encode("utf-8")).digest()
    pivot = int.from_bytes(digest[:4], "big") % len(realms)
    return realms[pivot:] + realms[:pivot]


def plan_realms(model_id, model_realms, key_realm="auto", affinity_realm=None,
                healthy_realms=()):
    """Return ordered realm candidates without consulting global UI state."""
    available = [realm for realm in REALMS if realm in set(model_realms or ())]
    if not available:
        raise ValueError("model %s is unavailable in all known realms" % model_id)

    policy = str(key_realm or "auto").strip().lower()
    if policy not in ("auto",) + REALMS:
        policy = "auto"
    if policy != "auto":
        if policy not in available:
            raise ValueError("model %s is unavailable in %s realm" % (model_id, policy))
        return [RouteCandidate(policy, "key-policy")]

    healthy = [realm for realm in available if realm in set(healthy_realms or ())]
    ordered = []
    if affinity_realm in available and affinity_realm in healthy:
        ordered.append(RouteCandidate(affinity_realm, "affinity"))

    stable_pool = _stable_order(model_id, healthy or available)
    for realm in stable_pool:
        if realm in [candidate.realm for candidate in ordered]:
            continue
        ordered.append(RouteCandidate(realm, "health" if healthy else "stable"))

    for realm in available:
        if realm not in [candidate.realm for candidate in ordered]:
            ordered.append(RouteCandidate(realm, "failover"))
    return ordered
