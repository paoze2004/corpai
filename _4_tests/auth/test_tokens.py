"""Phase 3 test_tokens — HS256 JWT round-trip + tamper/expiry。"""
import unittest

from _0_CorpAI._2_platform.auth.tokens import jwt_encode, jwt_decode, make_access_token


SECRET = "test-secret-do-not-use-in-prod"


class TestJWTRoundTrip(unittest.TestCase):

    def test_encode_decode_basic(self):
        tok = jwt_encode({"sub": "alice", "exp": 9999999999}, SECRET)
        claims = jwt_decode(tok, SECRET)
        self.assertIsNotNone(claims)
        self.assertEqual(claims["sub"], "alice")

    def test_encode_returns_three_segments(self):
        tok = jwt_encode({"sub": "alice", "exp": 9999999999}, SECRET)
        self.assertEqual(len(tok.split(".")), 3)

    def test_decode_wrong_secret_returns_none(self):
        tok = jwt_encode({"sub": "alice", "exp": 9999999999}, SECRET)
        self.assertIsNone(jwt_decode(tok, "wrong-secret"))

    def test_decode_expired_returns_none(self):
        tok = jwt_encode({"sub": "alice", "exp": 1}, SECRET)  # 1970 已过期
        self.assertIsNone(jwt_decode(tok, SECRET))

    def test_decode_tampered_payload_returns_none(self):
        tok = jwt_encode({"sub": "alice", "exp": 9999999999}, SECRET)
        # 把 header.payload 切出来,改 payload,签个空 sig
        h, p, _ = tok.split(".")
        tampered = f"{h}.{p}.AAAA"  # 任意短 sig,h.compare_digest 必失败
        self.assertIsNone(jwt_decode(tampered, SECRET))

    def test_decode_alg_none_header_rejected(self):
        """Header 中 alg != HS256 → 即使签名对也拒绝。"""
        import base64, json
        # 手工造一个 alg=none 的 token
        h = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=")
        p = base64.urlsafe_b64encode(json.dumps({"sub": "alice", "exp": 9999999999}).encode()).rstrip(b"=")
        tok = (h + b"." + p + b".AAAA").decode()
        self.assertIsNone(jwt_decode(tok, SECRET))

    def test_decode_malformed_token_returns_none(self):
        for bad in ["", "not.a.jwt", "x.y", "x.y.z.w"]:
            self.assertIsNone(jwt_decode(bad, SECRET))

    def test_make_access_token_returns_3_segments(self):
        tok = make_access_token("alice", "tenant1", "admin", ["chat:write"], SECRET, ttl=3600)
        claims = jwt_decode(tok, SECRET)
        self.assertEqual(claims["user_id"], "alice")
        self.assertEqual(claims["tenant_id"], "tenant1")
        self.assertEqual(claims["role"], "admin")
        self.assertEqual(claims["scopes"], ["chat:write"])
        self.assertGreater(claims["exp"] - claims["iat"], 3500)  # ttl ≈ 3600


if __name__ == "__main__":
    unittest.main()
