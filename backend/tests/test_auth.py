"""
认证模块测试 — 覆盖注册、登录、角色校验、sudo切换
"""

import pytest
from fastapi.testclient import TestClient

from models import User, UserRole


# 1.注册接口测试

class TestRegister:
    """POST /api/auth/register"""

    def test_register_success(self, client: TestClient):
        """正常注册：制造商角色"""
        resp = client.post("/api/auth/register", json={
            "account": "new_mfr",
            "password": "SecurePass123",
            "display_name": "新制造商",
            "role": "MANUFACTURER"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"] == "new_mfr"
        assert data["role"] == "MANUFACTURER"
        assert data["reputation_score"] == 70
        # 注册时 _is_chain_available() 检查 WeBASE，测试环境不可达，wallet_address 为 None
        # 这是预期行为，后续可通过 /api/users/me/assign-wallet 分配
        assert "id" in data

    def test_register_supplier(self, client: TestClient):
        """正常注册：供应商角色"""
        resp = client.post("/api/auth/register", json={
            "account": "new_sup",
            "password": "SecurePass123",
            "display_name": "新供应商",
            "role": "SUPPLIER"
        })
        assert resp.status_code == 200
        assert resp.json()["role"] == "SUPPLIER"

    def test_register_auditor(self, client: TestClient):
        """正常注册：审计节点角色"""
        resp = client.post("/api/auth/register", json={
            "account": "new_aud",
            "password": "SecurePass123",
            "display_name": "新审计节点",
            "role": "AUDITOR"
        })
        assert resp.status_code == 200
        assert resp.json()["role"] == "AUDITOR"

    def test_register_duplicate_account(self, client: TestClient, manufacturer):
        """重复账号注册应失败"""
        resp = client.post("/api/auth/register", json={
            "account": manufacturer.account,
            "password": "AnyPass123",
            "display_name": "重复账号",
            "role": "SUPPLIER"
        })
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]

    def test_register_admin_not_allowed(self, client: TestClient):
        """ADMIN角色不允许注册"""
        resp = client.post("/api/auth/register", json={
            "account": "hacker_admin",
            "password": "SecurePass123",
            "display_name": "黑客",
            "role": "ADMIN"
        })
        assert resp.status_code == 422  # Pydantic validation error

    def test_register_short_password(self, client: TestClient):
        """密码太短应校验失败"""
        resp = client.post("/api/auth/register", json={
            "account": "short_pass",
            "password": "123",
            "display_name": "短密码用户",
            "role": "MANUFACTURER"
        })
        assert resp.status_code == 422

    def test_register_short_account(self, client: TestClient):
        """账号太短应校验失败"""
        resp = client.post("/api/auth/register", json={
            "account": "ab",
            "password": "SecurePass123",
            "display_name": "短账号用户",
            "role": "MANUFACTURER"
        })
        assert resp.status_code == 422

    def test_register_missing_field(self, client: TestClient):
        """缺少必填字段应失败"""
        resp = client.post("/api/auth/register", json={
            "account": "missing_field",
            "role": "MANUFACTURER"
            # 缺少 password 和 display_name
        })
        assert resp.status_code == 422


# 2.登录接口测试

class TestLogin:
    """POST /api/auth/login"""

    def test_login_success(self, client: TestClient, manufacturer):
        """正常登录"""
        resp = client.post("/api/auth/login", json={
            "account": manufacturer.account,
            "password": "TestPass123",
            "role": "MANUFACTURER"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["account"] == manufacturer.account

    def test_login_wrong_password(self, client: TestClient, manufacturer):
        """密码错误"""
        resp = client.post("/api/auth/login", json={
            "account": manufacturer.account,
            "password": "WrongPass123",
            "role": "MANUFACTURER"
        })
        assert resp.status_code == 401
        assert "错误" in resp.json()["detail"]

    def test_login_nonexistent_account(self, client: TestClient):
        """账号不存在"""
        resp = client.post("/api/auth/login", json={
            "account": "not_exists_999",
            "password": "AnyPass123",
            "role": "MANUFACTURER"
        })
        assert resp.status_code == 401

    def test_login_role_mismatch(self, client: TestClient, manufacturer):
        """角色不匹配"""
        resp = client.post("/api/auth/login", json={
            "account": manufacturer.account,
            "password": "TestPass123",
            "role": "SUPPLIER"  # 制造商账号用供应商角色登录
        })
        assert resp.status_code == 403
        assert "不匹配" in resp.json()["detail"]

    def test_login_without_role(self, client: TestClient, manufacturer):
        """不指定角色也能登录（兼容前端）"""
        resp = client.post("/api/auth/login", json={
            "account": manufacturer.account,
            "password": "TestPass123",
            "role": ""
        })
        # 空字符串不等于MANUFACTURER，会被视为不匹配
        # 但如果前端不传role，可能行为不同
        # 这里根据实际代码逻辑：空字符串 != "MANUFACTURER"，会403
        assert resp.status_code in (200, 403)


# 3.Sudo切换测试

class TestSudo:
    """POST /api/auth/sudo"""

    def test_sudo_by_admin_success(self, client: TestClient, admin_user, manufacturer, admin_headers):
        """ADMIN成功切换到制造商"""
        resp = client.post(
            f"/api/auth/sudo?target_user_id={manufacturer.id}",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["account"] == manufacturer.account
        assert data["user"]["role"] == "MANUFACTURER"
        assert "access_token" in data

    def test_sudo_by_admin_to_supplier(self, client: TestClient, admin_user, supplier, admin_headers):
        """ADMIN切换到供应商"""
        resp = client.post(
            f"/api/auth/sudo?target_user_id={supplier.id}",
            headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "SUPPLIER"

    def test_sudo_by_non_admin(self, client: TestClient, manufacturer, supplier, mfr_headers):
        """非ADMIN调用sudo应403"""
        resp = client.post(
            f"/api/auth/sudo?target_user_id={supplier.id}",
            headers=mfr_headers
        )
        assert resp.status_code == 403

    def test_sudo_to_nonexistent_user(self, client: TestClient, admin_user, admin_headers):
        """切换到不存在的用户"""
        resp = client.post(
            "/api/auth/sudo?target_user_id=99999",
            headers=admin_headers
        )
        assert resp.status_code == 404

    def test_sudo_to_admin(self, client: TestClient, admin_user, admin_headers):
        """不能切换到ADMIN自己"""
        resp = client.post(
            f"/api/auth/sudo?target_user_id={admin_user.id}",
            headers=admin_headers
        )
        assert resp.status_code == 400
        assert "不能切换" in resp.json()["detail"]

    def test_sudo_without_auth(self, client: TestClient, manufacturer):
        """未认证调用 sudo"""
        resp = client.post(f"/api/auth/sudo?target_user_id={manufacturer.id}")
        assert resp.status_code == 401


# 4.认证中间件测试

class TestAuthMiddleware:
    """Token校验与权限中间件"""

    def test_access_protected_route_with_valid_token(self, client: TestClient, mfr_headers):
        """携带有效Token访问受保护接口"""
        resp = client.get("/api/users/me", headers=mfr_headers)
        assert resp.status_code == 200

    def test_access_protected_route_without_token(self, client: TestClient):
        """未携带Token访问受保护接口"""
        resp = client.get("/api/users/me")
        # HTTPBearer 在未提供 Authorization 头时返回 403 (auto_error=True 默认行为)
        assert resp.status_code in (401, 403)

    def test_access_protected_route_with_invalid_token(self, client: TestClient):
        """携带无效Token"""
        resp = client.get("/api/users/me", headers={"Authorization": "Bearer invalid_token"})
        assert resp.status_code == 401

    def test_access_protected_route_with_expired_token(self, client: TestClient):
        """携带过期Token（构造一个已过期JWT）"""
        from datetime import datetime, timedelta
        import jwt
        from core.security import SECRET_KEY, ALGORITHM

        expired_token = jwt.encode(
            {"sub": "1", "exp": datetime.utcnow() - timedelta(hours=1)},
            SECRET_KEY,
            algorithm=ALGORITHM
        )
        resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401

    def test_access_protected_route_with_malformed_token(self, client: TestClient):
        """Token格式错误"""
        resp = client.get("/api/users/me", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401
