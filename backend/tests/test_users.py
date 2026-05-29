"""
用户管理模块测试
覆盖: /api/users/* 接口
"""

import pytest
from fastapi.testclient import TestClient

from models import User, UserRole


class TestGetMe:
    """GET /api/users/me"""

    def test_get_me(self, client: TestClient, mfr_headers, manufacturer):
        """获取当前用户信息"""
        resp = client.get("/api/users/me", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"] == manufacturer.account
        assert data["role"] == "MANUFACTURER"


class TestListUsers:
    """GET /api/users"""

    def test_list_users_by_admin(self, client: TestClient, admin_headers):
        """ADMIN获取用户列表"""
        resp = client.get("/api/users", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # 不应包含ADMIN自身
        assert all(u["role"] != "ADMIN" for u in data)

    def test_list_users_by_non_admin(self, client: TestClient, mfr_headers):
        """非ADMIN获取用户列表"""
        resp = client.get("/api/users", headers=mfr_headers)
        assert resp.status_code == 403


class TestStakeRatio:
    """GET /api/users/{id}/stake-ratio"""

    def test_stake_ratio_blacklist(self, client: TestClient, db_session, make_user, auth_headers):
        """黑名单用户"""
        user = make_user(role=UserRole.MANUFACTURER, reputation_score=90)
        user.is_blacklisted = True
        db_session.commit()

        headers = auth_headers(user)
        resp = client.get(f"/api/users/{user.id}/stake-ratio", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["stake_ratio"] == 2.0

    def test_stake_ratio_builtin(self, client: TestClient, admin_user, admin_headers):
        """内置 ADMIN 用户"""
        resp = client.get(f"/api/users/{admin_user.id}/stake-ratio", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["stake_ratio"] == 1.0

    def test_stake_ratio_not_found(self, client: TestClient, mfr_headers):
        """用户不存在"""
        resp = client.get("/api/users/99999/stake-ratio", headers=mfr_headers)
        assert resp.status_code == 404


class TestRecharge:
    """POST /api/users/recharge"""

    def test_recharge_success(self, client: TestClient, db_session, manufacturer, mfr_headers):
        """正常充值"""
        old_balance = float(manufacturer.balance)
        resp = client.post("/api/users/recharge?amount=1000", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["new_balance"]) == old_balance + 1000

    def test_recharge_negative(self, client: TestClient, mfr_headers):
        """充值负数"""
        resp = client.post("/api/users/recharge?amount=-100", headers=mfr_headers)
        assert resp.status_code == 400

    def test_recharge_zero(self, client: TestClient, mfr_headers):
        """充值0"""
        resp = client.post("/api/users/recharge?amount=0", headers=mfr_headers)
        assert resp.status_code == 400


class TestAssignWallet:
    """POST /api/users/me/assign-wallet"""

    def test_assign_wallet_already_has(self, client: TestClient, manufacturer, mfr_headers):
        """已有钱包地址，幂等返回"""
        resp = client.post("/api/users/me/assign-wallet", headers=mfr_headers)
        assert resp.status_code == 200
        # 已有wallet_address，直接返回

    def test_assign_wallet_new(self, client: TestClient, db_session, make_user, auth_headers):
        """新用户分配钱包"""
        user = make_user(role=UserRole.SUPPLIER)
        user.wallet_address = None
        db_session.commit()

        headers = auth_headers(user)
        resp = client.post("/api/users/me/assign-wallet", headers=headers)
        # Mock环境下会成功分配
        assert resp.status_code in (200, 503)


class TestChangePassword:
    """POST /api/users/me/change-password"""

    def test_change_password_success(self, client: TestClient, manufacturer, mfr_headers):
        """正常修改密码"""
        resp = client.post(
            "/api/users/me/change-password",
            headers=mfr_headers,
            params={"old_password": "TestPass123", "new_password": "NewPass456"}
        )
        assert resp.status_code == 200
        assert "成功" in resp.json()["message"]

    def test_change_password_wrong_old(self, client: TestClient, mfr_headers):
        """旧密码错误"""
        resp = client.post(
            "/api/users/me/change-password",
            headers=mfr_headers,
            params={"old_password": "wrong", "new_password": "NewPass456"}
        )
        assert resp.status_code == 400
        assert "旧密码错误" in resp.json()["detail"]

    def test_change_password_too_short(self, client: TestClient, manufacturer, mfr_headers):
        """新密码太短"""
        resp = client.post(
            "/api/users/me/change-password",
            headers=mfr_headers,
            params={"old_password": "TestPass123", "new_password": "123"}
        )
        assert resp.status_code == 400
        assert "至少8位" in resp.json()["detail"]


class TestChangeAccount:
    """PUT /api/users/me/change-account"""

    def test_change_account_success(self, client: TestClient, manufacturer, mfr_headers):
        """正常修改账号"""
        new_account = "new_account_" + str(manufacturer.id)
        resp = client.put(
            "/api/users/me/change-account",
            headers=mfr_headers,
            params={"new_account": new_account}
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["account"] == new_account

    def test_change_account_same(self, client: TestClient, manufacturer, mfr_headers):
        """新账号与旧账号相同"""
        resp = client.put(
            "/api/users/me/change-account",
            headers=mfr_headers,
            params={"new_account": manufacturer.account}
        )
        assert resp.status_code == 400
        assert "不能与旧账号相同" in resp.json()["detail"]

    def test_change_account_duplicate(self, client: TestClient, supplier, manufacturer, mfr_headers):
        """账号已被使用"""
        resp = client.put(
            "/api/users/me/change-account",
            headers=mfr_headers,
            params={"new_account": supplier.account}
        )
        assert resp.status_code == 400
        assert "已被使用" in resp.json()["detail"]

    def test_change_account_too_short(self, client: TestClient, mfr_headers):
        """账号太短"""
        resp = client.put(
            "/api/users/me/change-account",
            headers=mfr_headers,
            params={"new_account": "ab"}
        )
        assert resp.status_code == 400
        assert "最少5位" in resp.json()["detail"]
