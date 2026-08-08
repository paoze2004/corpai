"""
Phase 3 密码哈希 — stdlib-only PBKDF2-HMAC-SHA256。

ADR-005 §密码哈希原本推荐 argon2-cffi;Phase 3 用户决定"不引新 auth 依赖",
改用 PBKDF2(200k 迭代)— OWASP 2023 推荐 600k,本计划妥协到 200k(无新 dep)。
Phase 6+ 可换 Argon2id,届时只改这一文件,接口不变。

输出格式:`pbkdf2:sha256:<iter>:<salt_hex>:<dk_hex>`(便于版本化升级)
"""
import hashlib
import secrets

# OWASP 2023 PBKDF2-SHA256 推荐 ≥600,000;Phase 3 200k(无新 dep 妥协)
ITERATIONS = 200_000
SALT_SIZE = 16  # bytes


def hash_password(password: str) -> str:
    """PBKDF2 哈希。随机 16-byte salt + 200k 迭代 SHA256."""
    salt = secrets.token_bytes(SALT_SIZE)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2:sha256:{ITERATIONS}:{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """verify:解析 stored,重算 hash,secrets.compare_digest 防时序攻击。"""
    try:
        algo, hash_name, iters, salt_hex, hash_hex = stored.split(":")
        if algo != "pbkdf2" or hash_name != "sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iters),
        )
        return secrets.compare_digest(dk, expected)
    except Exception:
        return False


__all__ = ["hash_password", "verify_password", "ITERATIONS"]
