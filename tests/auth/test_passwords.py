"""Phase 3 test_passwords — hash/verify round-trip 不依赖 DB。"""
import unittest

from CorpAI.platform.auth.passwords import hash_password, verify_password


class TestPasswordHashing(unittest.TestCase):

    def test_hash_password_returns_pbkdf2_format(self):
        """hash 后应符合 `pbkdf2:sha256:<iter>:<salt_hex>:<dk_hex>` 格式。"""
        h = hash_password("mypassword123")
        parts = h.split(":")
        self.assertEqual(parts[0], "pbkdf2")
        self.assertEqual(parts[1], "sha256")
        self.assertEqual(int(parts[2]), 200_000)
        self.assertEqual(len(bytes.fromhex(parts[3])), 16, "salt 必须 16 bytes")
        self.assertGreaterEqual(len(bytes.fromhex(parts[4])), 32, "dk 至少 SHA-256 长")

    def test_verify_password_round_trip(self):
        h = hash_password("mypassword")
        self.assertTrue(verify_password("mypassword", h))

    def test_verify_wrong_password_returns_false(self):
        h = hash_password("mypassword")
        self.assertFalse(verify_password("wrong", h))
        self.assertFalse(verify_password("MyPassword", h))  # 大小写敏感

    def test_verify_malformed_hash_returns_false(self):
        self.assertFalse(verify_password("mypassword", "garbage"))
        self.assertFalse(verify_password("mypassword", "argon2:..."))
        self.assertFalse(verify_password("mypassword", ""))

    def test_hash_unique_per_call(self):
        """相同密码两次 hash 应产生不同结果(随机 salt)。"""
        h1 = hash_password("same")
        h2 = hash_password("same")
        self.assertNotEqual(h1, h2)
        # 但都验证通过
        self.assertTrue(verify_password("same", h1))
        self.assertTrue(verify_password("same", h2))


if __name__ == "__main__":
    unittest.main()
