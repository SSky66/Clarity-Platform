"""
白盒单元测试 — 直接测 core/security.py 内部函数
不经过 HTTP 接口，验证密码哈希和 JWT 生成的内部逻辑
"""

import pytest
from datetime import datetime, timedelta
import jwt

from core.security import (
    hash_password,
    verify_password,
    create_access_token,
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)


class TestHashPassword:
    """密码哈希函数测试"""

    def test_hash_produces_different_output(self):
        """相同密码哈希后结果不同（bcrypt 自动加盐）"""
        password = "SamePassword123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2
        assert hash1.startswith("$2")
        assert hash2.startswith("$2")

    def test_hash_is_not_plaintext(self):
        """哈希结果不能是明文密码"""
        password = "secret123"
        hashed = hash_password(password)
        assert hashed != password


class TestVerifyPassword:
    """密码验证函数测试"""

    def test_verify_correct_password(self):
        """正确密码验证通过"""
        password = "MySecurePass123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_wrong_password(self):
        """错误密码验证失败"""
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_verify_empty_password(self):
        """空密码验证失败"""
        hashed = hash_password("something")
        assert verify_password("", hashed) is False

    def test_verify_against_different_hash(self):
        """用 A 的密码去验证 B 的哈希"""
        hash_a = hash_password("password_a")
        assert verify_password("password_b", hash_a) is False


class TestCreateAccessToken:
    """JWT Token 生成函数测试"""

    def test_token_contains_original_data(self):
        """Token 包含原始数据"""
        data = {"sub": "42", "role": "MANUFACTURER"}
        token = create_access_token(data)
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "42"
        assert payload["role"] == "MANUFACTURER"

    def test_token_has_expiry(self):
        """Token 包含过期时间"""
        token = create_access_token({"sub": "1"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_default_expiry_is_24h(self):
        """默认过期时间为 24 小时"""
        before = datetime.utcnow()
        token = create_access_token({"sub": "1"})
        after = datetime.utcnow()

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"])

        expected_before = before + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES - 1)
        expected_after = after + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES + 1)
        assert expected_before < exp < expected_after

    def test_custom_expiry(self):
        """自定义过期时间"""
        token = create_access_token({"sub": "1"}, expires=timedelta(minutes=5))
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        exp = datetime.fromtimestamp(payload["exp"])
        expected = datetime.utcnow() + timedelta(minutes=5)
        assert abs((exp - expected).total_seconds()) < 5

    def test_token_is_invalid_with_wrong_secret(self):
        """用错误的密钥无法解码"""
        token = create_access_token({"sub": "1"})
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, "wrong-secret", algorithms=[ALGORITHM])

    def test_expired_token_raises_error(self):
        """过期 Token 解码会报错"""
        token = create_access_token({"sub": "1"}, expires=timedelta(seconds=-1))
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
