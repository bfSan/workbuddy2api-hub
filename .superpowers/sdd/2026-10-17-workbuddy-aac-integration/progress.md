# SDD ledger — plan: docs/superpowers/verification/2026-10-17-workbuddy-aac-integration.md

Task 1: complete — request-scoped TenantRuntime now supplies AccountPool, settings, usage and scheduler through ContextVar proxies; OAuth and standalone API Key requests select the runtime.

Task 2: complete — tenant-index.json resolves API Key owners without browser sessions, stores only SHA-256 fingerprints, rejects unknown/expired/duplicate-owner keys, and manager-issued keys register atomically.

Task 3: complete — usage rows auto-record tenant/owner metadata; keep-alive request reset prevents identity leakage; regression coverage added for upstream pool selection and scheduler proxy.

Verification: all non-browser _test_*.py scripts passed; py_compile and git diff --check passed. Browser pagination remains unavailable because playwright is not installed.

Ruling: retain legacy global pool/settings/scheduler as local-admin compatibility fallback while request-scoped AAC/API-Key traffic uses tenant runtime — this preserves the explicitly requested local panel and rescue administrator; cost if wrong is that legacy local-admin data remains outside AAC tenant storage until operators migrate it.
