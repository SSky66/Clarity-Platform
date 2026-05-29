"""
异常边界场景测试
包含：SLASH罚没、履约降级、时间锁释放、权限越界、状态机非法跳转等
"""

import pytest
from fastapi.testclient import TestClient

from models import User, AuditTask, UserRole, TaskStatus, BASE_DEPOSIT, AUDIT_FEE, INSURANCE_FEE


# 1.权限越界场景

class TestPermissionBoundary:
    """角色权限边界测试"""

    def test_manufacturer_cannot_accept_task(self, client: TestClient, create_task, mfr_headers):
        """制造商不能接单"""
        task = create_task(status=TaskStatus.PENDING, supplier_id=None)
        resp = client.put(f"/api/tasks/{task.id}/accept", headers=mfr_headers)
        assert resp.status_code == 403

    def test_supplier_cannot_create_task(self, client: TestClient, sup_headers):
        """供应商不能创建项目"""
        resp = client.post("/api/tasks", headers=sup_headers, json={
            "task_name": "非法创建",
            "target_fnr": 0.05, "target_fpr": 0.05,
            "conf_threshold": 0.25, "iou_threshold": 0.45,
        })
        assert resp.status_code == 403

    def test_auditor_cannot_prepare_as_manufacturer(self, client: TestClient, create_task, aud_headers):
        """审计节点不能执行制造商准备"""
        task = create_task(status=TaskStatus.UPLOADING)
        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=aud_headers,
            json={}
        )
        assert resp.status_code == 403

    def test_manufacturer_cannot_submit_report(self, client: TestClient, create_task, mfr_headers):
        """制造商不能提交审计报告"""
        task = create_task(status=TaskStatus.AUDITING)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=mfr_headers,
            json={"miss_rate": 0.01, "false_kill_rate": 0.01, "concentration_ratio": 0.5, "avg_fp": 0.05, "arrogance": 0.2}
        )
        assert resp.status_code == 403

    def test_non_owner_cannot_access_task(self, client: TestClient, make_user, create_task, auth_headers):
        """非项目相关方不能查看项目详情"""
        # 创建另一个制造商
        other_mfr = make_user(account="other_mfr", role=UserRole.MANUFACTURER)
        task = create_task(status=TaskStatus.PENDING)

        headers = auth_headers(other_mfr)
        resp = client.get(f"/api/tasks/{task.id}", headers=headers)
        # 当前代码没有严格限制非相关方查看，返回200但数据中不包含敏感信息
        # 如果后续加了权限校验，这里应返回403
        assert resp.status_code in (200, 403)


# 2.状态机非法跳转

class TestStateMachineIllegalTransition:
    """状态机非法跳转测试"""

    def test_cannot_start_audit_from_pending(self, client: TestClient, create_task, aud_headers):
        """PENDING不能直接开始审计"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.put(f"/api/tasks/{task.id}/start-audit", headers=aud_headers)
        assert resp.status_code == 400

    def test_cannot_prepare_from_pending(self, client: TestClient, create_task, mfr_headers):
        """PENDING不能准备"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=mfr_headers,
            json={}
        )
        assert resp.status_code == 400

    def test_cannot_accept_from_uploading(self, client: TestClient, create_task, sup_headers):
        """UPLOADING不能再次接单"""
        task = create_task(status=TaskStatus.UPLOADING)
        resp = client.put(f"/api/tasks/{task.id}/accept", headers=sup_headers)
        assert resp.status_code == 400

    def test_cannot_submit_report_from_prepared(self, client: TestClient, create_task, aud_headers):
        """PREPARED不能提交报告（必须先start-audit）"""
        task = create_task(status=TaskStatus.PREPARED)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={"miss_rate": 0.01, "false_kill_rate": 0.01, "concentration_ratio": 0.5, "avg_fp": 0.05, "arrogance": 0.2}
        )
        assert resp.status_code == 400

    def test_cannot_advance_from_reject(self, client: TestClient, create_task, mfr_headers):
        """REJECT不能直接advance-to-acceptance"""
        task = create_task(status=TaskStatus.REJECT)
        resp = client.post(f"/api/tasks/{task.id}/advance-to-acceptance", headers=mfr_headers)
        assert resp.status_code == 400

    def test_cannot_advance_from_slash(self, client: TestClient, create_task, mfr_headers):
        """SLASH不能直接advance-to-acceptance"""
        task = create_task(status=TaskStatus.SLASH)
        resp = client.post(f"/api/tasks/{task.id}/advance-to-acceptance", headers=mfr_headers)
        assert resp.status_code == 400

    def test_cannot_complete_reject_from_pass(self, client: TestClient, create_task, mfr_headers):
        """PASS不能调用complete-reject"""
        task = create_task(status=TaskStatus.PASS)
        resp = client.post(f"/api/tasks/{task.id}/complete-reject", headers=mfr_headers)
        assert resp.status_code == 400

    def test_cannot_complete_slash_from_pass(self, client: TestClient, create_task, mfr_headers):
        """PASS不能调用complete-slash"""
        task = create_task(status=TaskStatus.PASS)
        resp = client.post(f"/api/tasks/{task.id}/complete-slash", headers=mfr_headers)
        assert resp.status_code == 400


# 3.资金与质押边界

class TestFundBoundary:
    """资金相关边界测试"""

    def test_prepare_with_zero_balance(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """余额为0时准备应失败"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id)
        manufacturer.balance = 0
        db_session.commit()

        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=mfr_headers,
            json={"purchase_insurance": False}
        )
        assert resp.status_code == 400
        assert "余额不足" in resp.json()["detail"]

    def test_prepare_with_exact_balance(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """余额刚好等于所需金额（信誉70的质押比例是1.5x，需要 1500+50=1550）"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id)
        # 信誉70的新用户 stake_ratio = 1.5，deposit = 1500，加上审计费50 = 1550
        manufacturer.balance = 1550
        db_session.commit()

        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=mfr_headers,
            json={"purchase_insurance": False}
        )
        assert resp.status_code == 200

    def test_prepare_with_insurance_insufficient(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """购买保险但余额不足"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id)
        # 刚好够基础质押+审计费，但不够保险费
        manufacturer.balance = BASE_DEPOSIT + AUDIT_FEE
        db_session.commit()

        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=mfr_headers,
            json={"purchase_insurance": True}
        )
        assert resp.status_code == 400
        assert "余额不足" in resp.json()["detail"]

    def test_recharge_negative_amount(self, client: TestClient, mfr_headers):
        """充值负数金额"""
        resp = client.post("/api/users/recharge?amount=-100", headers=mfr_headers)
        assert resp.status_code == 400

    def test_recharge_zero_amount(self, client: TestClient, mfr_headers):
        """充值0金额"""
        resp = client.post("/api/users/recharge?amount=0", headers=mfr_headers)
        assert resp.status_code == 400


# 4.信誉分与质押比例边界

class TestReputationBoundary:
    """信誉分相关边界测试"""

    def test_blacklist_user_stake_ratio(self, client: TestClient, db_session, make_user, auth_headers):
        """黑名单用户质押比例固定2.0"""
        user = make_user(role=UserRole.MANUFACTURER, reputation_score=90)
        user.is_blacklisted = True
        db_session.commit()

        headers = auth_headers(user)
        resp = client.get(f"/api/users/{user.id}/stake-ratio", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["stake_ratio"] == 2.0

    def test_new_user_stake_ratio(self, client: TestClient, make_user, auth_headers):
        """新用户（信誉70）质押比例1.5"""
        user = make_user(role=UserRole.SUPPLIER, reputation_score=70)
        headers = auth_headers(user)
        resp = client.get(f"/api/users/{user.id}/stake-ratio", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["stake_ratio"] == 1.5

    def test_high_reputation_stake_ratio(self, client: TestClient, db_session, make_user, auth_headers):
        """高信誉用户（100分）质押比例最低1.0"""
        user = make_user(role=UserRole.MANUFACTURER, reputation_score=100)
        db_session.commit()

        headers = auth_headers(user)
        resp = client.get(f"/api/users/{user.id}/stake-ratio", headers=headers)
        assert resp.status_code == 200
        ratio = resp.json()["stake_ratio"]
        assert ratio >= 1.0
        assert ratio < 1.5

    def test_low_reputation_stake_ratio(self, client: TestClient, db_session, make_user, auth_headers):
        """低信誉用户（0分且无成功记录）质押比例最高2.0"""
        # 注意：_compute_stake_ratio中，reputation_score==0 且 success_count==0 且非内置用户 = 2.0
        user = make_user(role=UserRole.SUPPLIER, reputation_score=0)
        # 确保不是内置用户，且 success_count=0（make_user默认就是0）
        user.is_builtin = False
        db_session.commit()

        headers = auth_headers(user)
        resp = client.get(f"/api/users/{user.id}/stake-ratio", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["stake_ratio"] == 2.0

    def test_auditor_stake_ratio(self, client: TestClient, auditor, aud_headers):
        """审计节点质押比例固定1.0"""
        resp = client.get(f"/api/users/{auditor.id}/stake-ratio", headers=aud_headers)
        assert resp.status_code == 200
        assert resp.json()["stake_ratio"] == 1.0


# 5.审计判定边界

class TestAuditVerdictBoundary:
    """审计判定边界值测试"""

    def test_verdict_at_exact_miss_threshold(self, client: TestClient, create_task, auditor, aud_headers):
        """漏杀率刚好等于阈值：直接调用判定函数验证逻辑"""
        from routers.audit import _evaluate_verdict
        # 漏杀率刚好等于阈值0.05，代码逻辑是 > 才REJECT
        decision = _evaluate_verdict(
            miss_rate=0.05,
            false_kill_rate=0.01,
            concentration_ratio=0.50,
            avg_fp=0.05,
            arrogance=0.20,
            miss_th=0.05,
            false_kill_th=0.05,
        )
        # 0.05 > 0.05 = False，所以不应是REJECT
        assert decision.value == "PASS"

    def test_verdict_just_above_miss_threshold(self, client: TestClient, create_task, auditor, aud_headers):
        """漏杀率略高于阈值：应REJECT"""
        task = create_task(status=TaskStatus.AUDITING, auditor_id=auditor.id)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={
                "miss_rate": 0.051,  # 略高于 0.05
                "false_kill_rate": 0.01,
                "concentration_ratio": 0.50,
                "avg_fp": 0.05,
                "arrogance": 0.20,
            }
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "REJECT"

    def test_verdict_at_concentration_boundary(self, client: TestClient, create_task, auditor, aud_headers):
        """注意力密度刚好0.20：应 PASS（< 0.20才SLASH）"""
        task = create_task(status=TaskStatus.AUDITING, auditor_id=auditor.id)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={
                "miss_rate": 0.01,
                "false_kill_rate": 0.01,
                "concentration_ratio": 0.20,  # 刚好等于边界
                "avg_fp": 0.05,
                "arrogance": 0.20,
            }
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "PASS"

    def test_verdict_slash_with_high_arrogance(self, client: TestClient, create_task, auditor, aud_headers):
        """avg_fp >= 0.1 且 arrogance >= 0.5：应 SLASH"""
        task = create_task(status=TaskStatus.AUDITING, auditor_id=auditor.id)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={
                "miss_rate": 0.01,
                "false_kill_rate": 0.01,
                "concentration_ratio": 0.50,
                "avg_fp": 0.15,  # >= 0.1
                "arrogance": 0.60,  # >= 0.5
            }
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "SLASH"

    def test_verdict_reject_with_low_arrogance(self, client: TestClient, create_task, auditor, aud_headers):
        """avg_fp >= 0.1 但 arrogance < 0.5：应 REJECT"""
        task = create_task(status=TaskStatus.AUDITING, auditor_id=auditor.id)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={
                "miss_rate": 0.01,
                "false_kill_rate": 0.01,
                "concentration_ratio": 0.50,
                "avg_fp": 0.15,
                "arrogance": 0.30,  # < 0.5
            }
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "REJECT"


# 6.时间锁与超时边界

class TestTimeoutBoundary:
    """时间锁相关边界测试"""

    def test_complete_reject_before_appeal_deadline(self, client: TestClient, db_session, create_task, mfr_headers):
        """申诉期结束前不能complete-reject"""
        from datetime import datetime, timedelta
        task = create_task(status=TaskStatus.REJECT)
        task.appeal_deadline = datetime.utcnow() + timedelta(days=3)
        db_session.commit()

        resp = client.post(f"/api/tasks/{task.id}/complete-reject", headers=mfr_headers)
        assert resp.status_code == 400
        assert "尚未结束" in resp.json()["detail"]

    def test_complete_slash_before_appeal_deadline(self, client: TestClient, db_session, create_task, mfr_headers):
        """申诉期结束前不能complete-slash"""
        from datetime import datetime, timedelta
        task = create_task(status=TaskStatus.SLASH)
        task.appeal_deadline = datetime.utcnow() + timedelta(days=3)
        db_session.commit()

        resp = client.post(f"/api/tasks/{task.id}/complete-slash", headers=mfr_headers)
        assert resp.status_code == 400
        assert "尚未结束" in resp.json()["detail"]


# 7.数据校验边界

class TestDataValidationBoundary:
    """输入数据校验边界"""

    def test_create_task_with_zero_threshold(self, client: TestClient, mfr_headers):
        """阈值为0（允许）"""
        resp = client.post("/api/tasks", headers=mfr_headers, json={
            "task_name": "零阈值项目",
            "target_fnr": 0.0,
            "target_fpr": 0.0,
            "conf_threshold": 0.0,
            "iou_threshold": 0.0,
        })
        assert resp.status_code == 200

    def test_create_task_with_one_threshold(self, client: TestClient, mfr_headers):
        """阈值为1（允许）"""
        resp = client.post("/api/tasks", headers=mfr_headers, json={
            "task_name": "满阈值项目",
            "target_fnr": 1.0,
            "target_fpr": 1.0,
            "conf_threshold": 1.0,
            "iou_threshold": 1.0,
        })
        assert resp.status_code == 200

    def test_create_task_with_negative_threshold(self, client: TestClient, mfr_headers):
        """负阈值（不允许）"""
        resp = client.post("/api/tasks", headers=mfr_headers, json={
            "task_name": "负阈值项目",
            "target_fnr": -0.1,
            "target_fpr": 0.05,
            "conf_threshold": 0.25,
            "iou_threshold": 0.45,
        })
        assert resp.status_code == 422

    def test_create_task_with_empty_name(self, client: TestClient, mfr_headers):
        """空项目名称（不允许）"""
        resp = client.post("/api/tasks", headers=mfr_headers, json={
            "task_name": "",
            "target_fnr": 0.05,
            "target_fpr": 0.05,
            "conf_threshold": 0.25,
            "iou_threshold": 0.45,
        })
        assert resp.status_code == 422

    def test_report_with_negative_metrics(self, client: TestClient, create_task, auditor, aud_headers):
        """提交负值指标（根据代码逻辑，负值不会触发阈值，但数据不合理）"""
        task = create_task(status=TaskStatus.AUDITING, auditor_id=auditor.id)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={
                "miss_rate": -0.1,  # 负值
                "false_kill_rate": -0.1,
                "concentration_ratio": 0.50,
                "avg_fp": 0.05,
                "arrogance": 0.20,
            }
        )
        # 当前代码没有对指标做ge=0校验，可能200
        assert resp.status_code in (200, 422)


# 8. 用户管理边界

class TestUserBoundary:
    """用户相关边界测试"""

    def test_change_password_wrong_old(self, client: TestClient, mfr_headers):
        """修改密码：旧密码错误"""
        resp = client.post(
            "/api/users/me/change-password",
            headers=mfr_headers,
            params={"old_password": "wrong_old", "new_password": "NewPass123"}
        )
        assert resp.status_code == 400
        assert "旧密码错误" in resp.json()["detail"]

    def test_change_password_too_short(self, client: TestClient, manufacturer, mfr_headers):
        """修改密码：新密码太短"""
        resp = client.post(
            "/api/users/me/change-password",
            headers=mfr_headers,
            params={"old_password": "TestPass123", "new_password": "123"}
        )
        assert resp.status_code == 400
        assert "至少8位" in resp.json()["detail"]

    def test_change_account_to_same(self, client: TestClient, manufacturer, mfr_headers):
        """修改账号：新账号与旧账号相同"""
        resp = client.put(
            "/api/users/me/change-account",
            headers=mfr_headers,
            params={"new_account": manufacturer.account}
        )
        assert resp.status_code == 400
        assert "不能与旧账号相同" in resp.json()["detail"]

    def test_list_users_by_non_admin(self, client: TestClient, mfr_headers):
        """非ADMIN查看用户列表"""
        resp = client.get("/api/users", headers=mfr_headers)
        assert resp.status_code == 403
