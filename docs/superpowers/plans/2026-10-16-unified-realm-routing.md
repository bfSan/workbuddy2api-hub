# Unified Realm Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow one OpenAI-compatible gateway endpoint to select domestic or international WorkBuddy accounts from their detected credentials, without requiring a manual panel realm switch.

**Architecture:** Keep per-realm credential and catalog sources, but add strict account realm detection, a unified model registry, and a route planner that produces ordered realm candidates. The upstream executor selects a concrete account only after planning, derives the upstream URL from that account's realm, and performs bounded failover before any streamed bytes are sent.

**Tech Stack:** Python 3.9+ standard library, existing `urllib`, JSON settings files, existing script-style regression tests, static HTML dashboard.

**Spec:** `docs/superpowers/specs/2026-10-16-unified-realm-routing-design.md`

## Global Constraints

- Account credentials with conflicting or unknown issuer/domain evidence are `realm=unknown` and are never selected automatically.
- API Key realm values are `auto`, `intl`, or `cn`; legacy empty values migrate to `auto`.
- `CURRENT_REALM` remains only for panel/legacy view compatibility and must not select the upstream for chat or Responses requests.
- A request may fail over before streaming output starts; after the first streamed frame, it must not be replayed.
- Access tokens, refresh tokens, and Authorization headers must never be written to logs or usage files.
- The implementation continues to use Python standard library only.

## Review Focus

- A shared model must route the same way regardless of `CURRENT_REALM`; pin this in the mixed-account routing test in Task 5.
- An issuer/domain conflict must quarantine the account instead of sending its token to either host; pin this in the realm detector test in Task 1.
- An exclusive model must reject an incompatible hard Key policy before any upstream call; pin this in the route planner test in Task 3.
- A 429 must try another account/realm before returning an error, while a streamed first frame must prevent replay; pin both in Task 5 executor tests.
- `/v1/models` must expose the union while `?realm=` still filters it; pin both in Task 6 API tests.

### Task 1: Harden credential realm detection

**Files:**
- Modify: `wb_accounts.py:96-170` (realm config, token claim helpers, `Account.__init__`, persistence/public fields)
- Create: `_test_realm_detection.py`

**Interfaces:**
- Produces `detect_account_realm(token: str, domain: str = "", stored_realm: str = "") -> tuple[str, str, str]`, returning `(realm, source, error)` where realm is `intl`, `cn`, or `unknown`.
- `Account` exposes `realm_source` and `realm_error` and persists them as `realmSource` and `realmError`.
- Existing `get_realm_config()` continues to accept only `intl` and `cn`; unknown accounts never call it for upstream traffic.

- [ ] **Step 1: Write failing detector and account tests**

  Add script-style checks for: international issuer/domain, domestic issuer/domain, missing evidence, conflicting issuer/domain, stored realm being overridden by explicit token evidence, and persistence of `realmSource`/`realmError`.

- [ ] **Step 2: Run the focused test and verify it fails**

  Run `python3 _test_realm_detection.py`.
  Expected: FAIL because `detect_account_realm` and the new account fields do not exist.

- [ ] **Step 3: Implement strict detection**

  Add normalized issuer/domain matching, return `unknown` for missing or conflicting evidence, and update `Account.__init__` to recompute realm on load/import/refresh. Do not default ambiguous credentials to `intl`.

- [ ] **Step 4: Run focused and existing account tests**

  Run `python3 _test_realm_detection.py` and `python3 _test_model_cooldown.py`.
  Expected: PASS with existing cooldown behavior unchanged.

- [ ] **Step 5: Commit**

  ```bash
  git add wb_accounts.py _test_realm_detection.py
  git commit -m "feat: detect WorkBuddy account realms strictly"
  ```

### Task 2: Add the unified model registry

**Files:**
- Create: `wb_model_registry.py`
- Modify: `wb_proxy.py:1170-1415, 1580-1610, 1720-1910` to feed per-realm catalog snapshots into the registry
- Create: `_test_model_registry.py`

**Interfaces:**
- `build_registry(realm_entries: dict[str, list[tuple[str, dict]]]) -> dict[str, dict]` returns one record per model ID with `realms`, `variants`, and merged metadata.
- `model_realms(registry: dict[str, dict], model_id: str) -> tuple[str, ...]` returns deterministic `("intl", "cn")` order for shared models.
- `merged_entries(registry: dict[str, dict]) -> list[tuple[str, dict]]` returns public model entries while preserving per-realm metadata under `x_workbuddy` fields.
- Existing `fetch_models(realm=...)` remains available for panel and cache callers.

- [ ] **Step 1: Write failing registry tests**

  Cover a shared model with different credits, an international-only model, a domestic-only model, stale metadata overridden by live metadata, and deterministic merged ordering.

- [ ] **Step 2: Run the focused test and verify it fails**

  Run `python3 _test_model_registry.py`.
  Expected: FAIL because `wb_model_registry.py` is absent.

- [ ] **Step 3: Implement registry merge functions**

  Normalize IDs, retain each realm variant, select live metadata over snapshot/static metadata within each realm, and expose a merged record without discarding regional differences.

- [ ] **Step 4: Integrate registry construction without changing request routing**

  Add a proxy helper that loads both cached/live realm catalogs and builds the registry. Keep per-realm hidden/order configuration intact; do not remove `fetch_models(realm=...)`.

- [ ] **Step 5: Run focused and model configuration tests**

  Run `python3 _test_model_registry.py` and `python3 _test_model_config.py`.
  Expected: PASS; existing per-realm sync behavior remains unchanged.

- [ ] **Step 6: Commit**

  ```bash
  git add wb_model_registry.py wb_proxy.py _test_model_registry.py
  git commit -m "feat: add unified domestic and international model registry"
  ```

### Task 3: Add deterministic cross-realm route planning

**Files:**
- Create: `wb_routing.py`
- Modify: `wb_accounts.py:455-505, 640-685` to expose realm-aware health snapshots and route affinity helpers
- Create: `_test_route_planner.py`

**Interfaces:**
- `RouteCandidate` is an immutable record with `realm: str` and `reason: str`.
- `plan_realms(model_id: str, model_realms: tuple[str, ...], key_realm: str = "auto", affinity_realm: Optional[str] = None, healthy_realms: tuple[str, ...] = ()) -> list[RouteCandidate]` returns ordered candidates or raises `ValueError` for an incompatible hard policy.
- `AccountPool.realm_health(model: Optional[str] = None, allow: Optional[set[str]] = None) -> dict[str, int]` counts ready accounts by known realm.
- `SessionAffinity.get_route(key) -> Optional[dict]` and `bind_route(key, realm, uid)` support `{realm, uid}` while keeping `get/bind` compatibility for existing callers.

- [ ] **Step 1: Write failing planner and affinity tests**

  Assert: exclusive model routing, shared-model affinity preference, deterministic healthy-region ordering, `auto` fallback, `intl`/`cn` hard policy conflicts, unknown accounts excluded, and `{realm, uid}` affinity expiry.

- [ ] **Step 2: Run focused tests and verify failure**

  Run `python3 _test_route_planner.py`.
  Expected: FAIL because the planner and new pool methods do not exist.

- [ ] **Step 3: Implement `wb_routing.py`**

  Filter candidates by model availability and hard Key policy, prefer valid affinity, prefer healthy realms, and use a stable hash tie-break for shared models so `CURRENT_REALM` is never consulted.

- [ ] **Step 4: Implement realm health and route affinity**

  Count enabled, token-bearing, non-cooled accounts by realm, honor the allowed UID set, and persist only in-memory route affinity with the existing TTL/size limits.

- [ ] **Step 5: Run focused, cooldown, and syntax tests**

  Run `python3 _test_route_planner.py`, `python3 _test_model_cooldown.py`, and `python3 -m py_compile wb_routing.py wb_accounts.py`.
  Expected: PASS.

- [ ] **Step 6: Commit**

  ```bash
  git add wb_routing.py wb_accounts.py _test_route_planner.py
  git commit -m "feat: plan unified WorkBuddy realm routes"
  ```

### Task 4: Migrate API Key semantics to `auto`

**Files:**
- Modify: `wb_settings.py:143-258` (realm constants, key normalization, legacy migration)
- Modify: `wb_proxy.py:170-200, 3460-3515` (Key policy lookup and request realm compatibility)
- Create: `_test_api_key_realm.py`

**Interfaces:**
- `wb_settings.REALMS` becomes `("auto", "intl", "cn")`.
- `wb_settings.normalize_key_realm(value: Optional[str]) -> str` returns `auto`, `intl`, or `cn`.
- `wb_settings.api_keys()` returns normalized entries; legacy single-key and blank realm entries are surfaced as `realm="auto"`.
- `Handler._key_realm()` returns `auto`, `intl`, or `cn`; `_request_realm()` returns only an explicit hard constraint and never falls back to `CURRENT_REALM` for API data requests.

- [ ] **Step 1: Write failing migration tests**

  Cover legacy single Key, blank realm, explicit `auto`, hard `intl`, hard `cn`, disabled keys, and persistence through `set_api_keys()`.

- [ ] **Step 2: Run the focused test and verify it fails**

  Run `python3 _test_api_key_realm.py`.
  Expected: FAIL because blank values are currently represented as empty strings.

- [ ] **Step 3: Implement normalization and compatibility**

  Normalize on read and write, keep stored data backward compatible, and update panel-facing settings so `auto` is shown as “自动路由”.

- [ ] **Step 4: Run focused and usage tests**

  Run `python3 _test_api_key_realm.py` and `python3 _test_usage_key.py`.
  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add wb_settings.py wb_proxy.py _test_api_key_realm.py
  git commit -m "feat: make API key realm policy auto by default"
  ```

### Task 5: Integrate account-selected upstream execution

**Files:**
- Modify: `wb_proxy.py:2259-2335` (`open_upstream`), `wb_proxy.py:4219-4248`, `wb_proxy.py:4370-4390` (chat/Responses call sites)
- Modify: `wb_accounts.py:649-685` if the executor needs a unified account iterator
- Create: `_test_unified_routing.py`

**Interfaces:**
- `open_upstream(payload: dict, session_key: Optional[str] = None, target_realm: Optional[str] = None, allow: Optional[set[str]] = None, key_realm: str = "auto") -> tuple[IO, Account]` keeps the existing return shape.
- The executor obtains model realms from the unified registry, calls `plan_realms`, then selects a concrete account for each candidate realm.
- The selected account's `realm` is the only source for `get_realm_config(account.realm)["chat_upstream"]`.

- [ ] **Step 1: Write failing fake-upstream tests**

  Use in-memory CN/intl accounts and a patched `urllib.request.urlopen` to assert: shared model routing ignores `CURRENT_REALM`, exclusive models use one host, an incompatible hard policy returns before network access, 429 rotates within realm then across realm, account allow-lists are honored, and an already-emitted stream is never retried.

- [ ] **Step 2: Run the focused test and verify it fails**

  Run `python3 _test_unified_routing.py`.
  Expected: FAIL because `open_upstream` still receives one target realm and cannot plan across both pools.

- [ ] **Step 3: Implement pre-stream route planning**

  Build the registry snapshot, resolve the Key policy, obtain route affinity, and iterate candidates. For each candidate call the existing model-aware account picker; bind the successful `{realm, uid}` route.

- [ ] **Step 4: Implement bounded failover**

  Preserve current cooldown semantics: 429 is model-scoped, 401/403 is account-scoped, transient network errors use existing retry rules, and at most one cross-realm failover is attempted before the response begins.

- [ ] **Step 5: Update chat and Responses callers**

  Pass the normalized Key policy instead of using `CURRENT_REALM` as a default. Keep explicit `X-Realm`/query realm as a hard compatibility constraint only when it is `intl` or `cn`.

- [ ] **Step 6: Run focused and existing routing tests**

  Run `python3 _test_unified_routing.py`, `python3 _test_model_cooldown.py`, and `python3 -m py_compile wb_proxy.py wb_accounts.py wb_routing.py wb_model_registry.py`.
  Expected: PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add wb_proxy.py wb_accounts.py _test_unified_routing.py
  git commit -m "feat: route requests through detected WorkBuddy accounts"
  ```

### Task 6: Expose the unified model list and preserve realm filters

**Files:**
- Modify: `wb_proxy.py:1580-1610, 896-980, 3550-3610` (`fetch_models`, settings view, `/v1/models`)
- Modify: `dashboard.html:277-307, 517-540, 780-875` (realm banner, Key editor, model loading copy)
- Modify: `_test_model_config.py` and create `_test_models_endpoint.py`

**Interfaces:**
- `/v1/models` with no realm query returns the registry union and `realm="auto"`.
- `/v1/models?realm=intl|cn` returns only that variant and keeps the existing response shape.
- `/settings/models` retains per-realm hidden/order editing and adds a unified summary.
- The dashboard labels the realm switch as a view filter and shows Key policy `auto` as automatic routing.

- [ ] **Step 1: Write failing endpoint and compatibility tests**

  Assert union IDs, regional variant metadata, `?realm=cn` filtering, no dependence on `CURRENT_REALM`, and legacy per-realm model settings remaining editable.

- [ ] **Step 2: Run focused tests and verify failure**

  Run `python3 _test_models_endpoint.py` and the relevant model configuration test.
  Expected: FAIL because `/v1/models` currently defaults to one realm.

- [ ] **Step 3: Implement union response**

  Build the registry from both realm snapshots/live data, apply per-realm visibility rules, and serialize merged entries with `x_workbuddy.realms` and `x_workbuddy.variants` extension fields.

- [ ] **Step 4: Update dashboard semantics**

  Remove wording that claims the banner changes the gateway upstream. Keep the switch for account/task/model view filtering and preserve existing pagination and Key account binding behavior.

- [ ] **Step 5: Run browser and endpoint checks**

  Run `python3 _test_models_endpoint.py`, `python3 _test_model_config.py`, `_test_pagination_browser.py` when Playwright is available, and `node _test_model_rates.mjs`.
  Expected: PASS; the UI still filters rows correctly and model badges retain current behavior.

- [ ] **Step 6: Commit**

  ```bash
  git add wb_proxy.py dashboard.html _test_model_config.py _test_models_endpoint.py
  git commit -m "feat: expose unified domestic and international models"
  ```

### Task 7: Record actual route metadata and update operator documentation

**Files:**
- Modify: `wb_proxy.py:238-330, 324-345, 4219-4470` (usage/error metadata and call sites)
- Modify: `README.md` sections 1.4, 2.1, 4, and 5
- Create or extend: `_test_route_usage.py`

**Interfaces:**
- `record_usage(..., account=None, route_reason="", retry_count=0, failover=False)` records selected realm from the account plus route metadata.
- `record_error(..., realm="", account="", route_reason="", retry_count=0, failover=False)` records the same metadata without secrets.
- Usage rows retain legacy fields so existing dashboard aggregation continues to work.

- [ ] **Step 1: Write failing metadata tests**

  Assert actual account realm is recorded even when `CURRENT_REALM` differs, route reason/failover fields survive JSONL serialization, and no token-like header/value appears.

- [ ] **Step 2: Implement metadata propagation**

  Thread route metadata from `open_upstream` to chat/Responses success and error paths. Keep historical rows readable when fields are absent.

- [ ] **Step 3: Update README and dashboard help text**

  Document one Base URL, automatic account realm detection, `auto`/`intl`/`cn` Key policies, model union behavior, and the fact that panel realm is a view filter.

- [ ] **Step 4: Run focused and existing usage tests**

  Run `python3 _test_route_usage.py` and `python3 _test_usage_key.py`.
  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add wb_proxy.py README.md _test_route_usage.py
  git commit -m "docs: explain automatic cross-realm routing"
  ```

### Task 8: Full verification and rollout guard

**Files:**
- Modify: `scripts/package-image.sh` only if the new tests are not already included by its test discovery
- Modify: `docker-compose.yml` only if a documented feature flag is needed
- Create: no new product files unless verification exposes a concrete issue

**Interfaces:**
- Optional environment flag `WB_AUTO_REALM_ROUTING=0` disables cross-realm failover while leaving account realm detection and union model discovery available.
- The default is enabled after all tests pass.

- [ ] **Step 1: Run the complete local suite**

  Run:

  ```bash
  python3 -m py_compile wb_proxy.py wb_accounts.py wb_settings.py wb_catalog.py wb_model_registry.py wb_routing.py
  python3 _test_realm_detection.py
  python3 _test_model_registry.py
  python3 _test_route_planner.py
  python3 _test_api_key_realm.py
  python3 _test_unified_routing.py
  python3 _test_models_endpoint.py
  python3 _test_route_usage.py
  python3 _test_model_config.py
  python3 _test_model_cooldown.py
  python3 _test_usage_key.py
  node _test_model_rates.mjs
  ```

  Expected: every script exits 0 and no token or credential appears in output.

- [ ] **Step 2: Run packaging/deployment checks**

  Run `scripts/package-image.sh` if Docker is available; otherwise run its test phase only and report the environment limitation.

- [ ] **Step 3: Review the final diff**

  Confirm that `CURRENT_REALM` is absent from API route selection, all new fields are backward-compatible, and the README/UI agree with the actual behavior.

- [ ] **Step 4: Commit verification adjustments when needed**

  ```bash
  git add scripts/package-image.sh docker-compose.yml
  git commit -m "chore: verify unified realm routing rollout"
  ```

  If verification required no packaging or deployment changes, leave the files untouched and do not create an empty commit.

