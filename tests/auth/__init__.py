"""Phase 3 Auth 测试套件。

- test_passwords.py — PBKDF2 hash/verify round-trip
- test_tokens.py — JWT encode/decode + tamper/expiry
- test_scopes.py — 4 角色 × 5 scope 权限矩阵
- test_audit.py — write_audit_log + DB raise
- test_login_flow.py — 端到端 /admin/api/login
- test_fail_closed.py — DB 不可达 → 401/403/500

所有测试零 DB 依赖(`conftest.py` 的 `database_pool_available` 仅用于 skip DB 集成 case)。
"""
