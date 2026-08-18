"""
Phase 3 自实现 HS256 JWT — stdlib-only。

设计原则(无 PyJWT 依赖):
- 只支持 HS256(不读 header 信任 alg → 防 alg=none / kid confusion 攻击)
- `jwt_decode` 任何异常(wrong secret、expired、tampered、malformed)返 None,不抛
- secret 从 env `AUTH_JWT_SECRET` 读,未设时 fail-closed(dependencies.get_jwt_secret raise)

Token shape:`<base64url(header)>.<base64url(payload)>.<base64url(sig)>`
- header: `{"alg":"HS256","typ":"JWT"}`
- payload: `{"user_id","tenant_id","role","scopes","iat","exp"}`
- sig: HMAC-SHA256(header.payload, secret)
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64u_encode(b: bytes) -> bytes:
    """base64url 编码去掉 padding(标准 JWT 格式)。"""
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def _b64u_decode(s: str) -> bytes:
    """base64url 解码补回 padding(`-len(s) % 4` 始终 1..3)。"""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64u_decode_str(s: str) -> str:
    return _b64u_decode(s).decode("utf-8")


def jwt_encode(payload: dict, secret: str) -> str:
    """编码 payload → `header.payload.sig` 三段。"""
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64u_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64u_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), h + b"." + p, hashlib.sha256).digest()
    return (h + b"." + p + b"." + _b64u_encode(sig)).decode("ascii")


def jwt_decode(token: str, secret: str) -> dict | None:
    """解码 token。任何失败 → None(raise 不抛)。"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h_b64, p_b64, s_b64 = parts
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")
        expected_sig = hmac.new(
            secret.encode("utf-8"), signing_input, hashlib.sha256,
        ).digest()
        actual_sig = _b64u_decode(s_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        # 再 header sanity-check:alg 必须是 HS256(防 alg confusion)
        header = json.loads(_b64u_decode_str(h_b64))
        if header.get("alg") != "HS256":
            return None
        payload: dict[str, Any] = json.loads(_b64u_decode_str(p_b64))
        # 过期检查
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def make_access_token(
    user_id: str,
    tenant_id: str,
    role: str,
    scopes: list[str],
    secret: str,
    ttl: int = 7200,
) -> str:
    """构造 access_token(默认 2 小时 TTL)。"""
    now = int(time.time())
    return jwt_encode(
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "scopes": scopes,
            "iat": now,
            "exp": now + ttl,
        },
        secret,
    )


__all__ = ["jwt_encode", "jwt_decode", "make_access_token"]
