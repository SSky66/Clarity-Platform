"""
现场验收与整改模块测试
覆盖: submit-completion, confirm-onsite, timeout-auto-pass, request-extension, submit-rectification, escalate-field-dispute
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

from models import User, AuditTask, OnsiteRecord, UserRole, TaskStatus, OnsiteLocalStatus


# 1.供应商提交完成

class TestSubmitCompletion:
    """POST /api/tasks/{id}/submit-completion"""

    def test_submit_completion_success(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """供应商正常提交完成"""
        task = create_task(status=TaskStatus.ACCEPTANCE, supplier_id=supplier.id)
        resp = client.post(f"/api/tasks/{task.id}/submit-completion", headers=sup_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["supplier_submitted"] is True
        assert data["status"] == "ACCEPTANCE"
        assert data["onsite_deadline"] is not None

    def test_submit_completion_wrong_status(self, client: TestClient, create_task, supplier, sup_headers):
        """非ACCEPTANCE状态提交"""
        task = create_task(status=TaskStatus.PENDING, supplier_id=supplier.id)
        resp = client.post(f"/api/tasks/{task.id}/submit-completion", headers=sup_headers)
        assert resp.status_code == 400

    def test_submit_completion_by_manufacturer(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """制造商提交完成应403"""
        task = create_task(status=TaskStatus.ACCEPTANCE, manufacturer_id=manufacturer.id)
        resp = client.post(f"/api/tasks/{task.id}/submit-completion", headers=mfr_headers)
        assert resp.status_code == 403

    def test_submit_completion_duplicate(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """重复提交"""
        task = create_task(status=TaskStatus.ACCEPTANCE, supplier_id=supplier.id, supplier_submitted=True)
        resp = client.post(f"/api/tasks/{task.id}/submit-completion", headers=sup_headers)
        assert resp.status_code == 400
        assert "已提交" in resp.json()["detail"]


# 2.现场确认

class TestConfirmOnsite:
    """POST /api/tasks/{id}/confirm-onsite"""

    def test_manufacturer_confirm_satisfied(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers, sup_headers):
        """制造商确认满意 → 等待供应商确认"""
        task = create_task(status=TaskStatus.ACCEPTANCE, supplier_id=supplier.id, supplier_submitted=True)
        resp = client.post(
            f"/api/tasks/{task.id}/confirm-onsite",
            headers=mfr_headers,
            json={"satisfied": True, "measured_map": 0.85}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfr_confirmed"] is True
        assert data["mfr_satisfied"] is True
        assert data["status"] == "ACCEPTANCE"  # 供应商还没确认

    def test_manufacturer_confirm_not_satisfied(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """制造商确认不满意 → 记录拒绝但不改变状态（等待供应商响应）"""
        task = create_task(status=TaskStatus.ACCEPTANCE, supplier_id=supplier.id, supplier_submitted=True)
        resp = client.post(
            f"/api/tasks/{task.id}/confirm-onsite",
            headers=mfr_headers,
            json={"satisfied": False, "measured_map": 0.60}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfr_satisfied"] is False
        # 制造商拒绝后状态仍是 ACCEPTANCE，等待供应商确认是否接受整改
        assert data["status"] == "ACCEPTANCE"

    def test_both_confirm_satisfied(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers, sup_headers):
        """双方都满意 → COMPLETED"""
        task = create_task(status=TaskStatus.ACCEPTANCE, supplier_id=supplier.id, supplier_submitted=True)

        # 制造商先确认
        client.post(f"/api/tasks/{task.id}/confirm-onsite", headers=mfr_headers, json={"satisfied": True})

        # 供应商确认
        resp = client.post(
            f"/api/tasks/{task.id}/confirm-onsite",
            headers=sup_headers,
            json={"satisfied": True, "measured_map": 0.85}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "COMPLETED"

    def test_confirm_without_submission(self, client: TestClient, create_task, manufacturer, supplier, mfr_headers):
        """供应商未提交就确认"""
        task = create_task(status=TaskStatus.ACCEPTANCE, supplier_id=supplier.id, supplier_submitted=False)
        resp = client.post(
            f"/api/tasks/{task.id}/confirm-onsite",
            headers=mfr_headers,
            json={"satisfied": True}
        )
        assert resp.status_code == 400
        assert "尚未提交" in resp.json()["detail"]

    def test_confirm_by_auditor(self, client: TestClient, create_task, supplier, aud_headers):
        """审计节点确认应 403"""
        task = create_task(status=TaskStatus.ACCEPTANCE, supplier_id=supplier.id, supplier_submitted=True)
        resp = client.post(f"/api/tasks/{task.id}/confirm-onsite", headers=aud_headers, json={"satisfied": True})
        assert resp.status_code == 403

    def test_duplicate_confirm(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """制造商重复确认"""
        task = create_task(status=TaskStatus.ACCEPTANCE, supplier_id=supplier.id, supplier_submitted=True, mfr_confirmed=True)
        resp = client.post(
            f"/api/tasks/{task.id}/confirm-onsite",
            headers=mfr_headers,
            json={"satisfied": True}
        )
        assert resp.status_code == 400
        assert "已确认" in resp.json()["detail"]


# 3.超时自动通过

class TestTimeoutAutoPass:
    """POST /api/tasks/{id}/timeout-auto-pass"""

    def test_timeout_auto_pass_success(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """超时后自动通过"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.ACCEPTANCE,
            supplier_id=supplier.id,
            supplier_submitted=True,
            onsite_deadline=datetime.utcnow() - timedelta(hours=1)  # 已超时
        )
        resp = client.post(f"/api/tasks/{task.id}/timeout-auto-pass", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "COMPLETED"

    def test_timeout_not_reached(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """超时未到达"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.ACCEPTANCE,
            supplier_id=supplier.id,
            supplier_submitted=True,
            onsite_deadline=datetime.utcnow() + timedelta(hours=1)  # 未超时
        )
        resp = client.post(f"/api/tasks/{task.id}/timeout-auto-pass", headers=mfr_headers)
        assert resp.status_code == 400
        assert "超时未到达" in resp.json()["detail"]

    def test_timeout_auto_pass_wrong_status(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """非ACCEPTANCE状态"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.post(f"/api/tasks/{task.id}/timeout-auto-pass", headers=mfr_headers)
        assert resp.status_code == 400


# 4.整改延期

class TestRequestExtension:
    """POST /api/tasks/{id}/request-extension"""

    def test_extension_success(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """供应商正常申请延期"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            supplier_id=supplier.id,
            rectification_deadline=datetime.utcnow() + timedelta(days=7),
            rectification_count=0
        )
        supplier.balance = 1000
        db_session.commit()

        resp = client.post(f"/api/tasks/{task.id}/request-extension", headers=sup_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["rectification_count"] == 1

    def test_extension_max_reached(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """延期次数已达上限"""
        from datetime import datetime, timedelta
        from models import MAX_EXTENSIONS
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            supplier_id=supplier.id,
            rectification_deadline=datetime.utcnow() + timedelta(days=7),
            rectification_count=MAX_EXTENSIONS
        )
        supplier.balance = 1000
        db_session.commit()

        resp = client.post(f"/api/tasks/{task.id}/request-extension", headers=sup_headers)
        assert resp.status_code == 400
        assert "最多延期" in resp.json()["detail"]

    def test_extension_insufficient_balance(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """余额不足"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            supplier_id=supplier.id,
            rectification_deadline=datetime.utcnow() + timedelta(days=7),
            rectification_count=0
        )
        supplier.balance = 0
        db_session.commit()

        resp = client.post(f"/api/tasks/{task.id}/request-extension", headers=sup_headers)
        assert resp.status_code == 400
        assert "余额不足" in resp.json()["detail"]

    def test_extension_by_manufacturer(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """制造商申请延期应403"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            manufacturer_id=manufacturer.id,
            rectification_deadline=datetime.utcnow() + timedelta(days=7)
        )
        resp = client.post(f"/api/tasks/{task.id}/request-extension", headers=mfr_headers)
        assert resp.status_code == 403

    def test_extension_deadline_passed(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """整改期已结束"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            supplier_id=supplier.id,
            rectification_deadline=datetime.utcnow() - timedelta(hours=1)  # 已过期
        )
        supplier.balance = 1000
        db_session.commit()

        resp = client.post(f"/api/tasks/{task.id}/request-extension", headers=sup_headers)
        assert resp.status_code == 400
        assert "已结束" in resp.json()["detail"]


# 5.提交整改

class TestSubmitRectification:
    """POST /api/tasks/{id}/submit-rectification"""

    def test_submit_rectification_success(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """供应商提交整改完成"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            supplier_id=supplier.id,
            rectification_deadline=datetime.utcnow() + timedelta(days=7)
        )
        resp = client.post(f"/api/tasks/{task.id}/submit-rectification", headers=sup_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACCEPTANCE"
        assert data["supplier_submitted"] is True

    def test_submit_rectification_wrong_status(self, client: TestClient, create_task, supplier, sup_headers):
        """非RECTIFICATION状态"""
        task = create_task(status=TaskStatus.PENDING, supplier_id=supplier.id)
        resp = client.post(f"/api/tasks/{task.id}/submit-rectification", headers=sup_headers)
        assert resp.status_code == 400

    def test_submit_rectification_by_manufacturer(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """制造商提交整改应403"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            manufacturer_id=manufacturer.id,
            rectification_deadline=datetime.utcnow() + timedelta(days=7)
        )
        resp = client.post(f"/api/tasks/{task.id}/submit-rectification", headers=mfr_headers)
        assert resp.status_code == 403

    def test_submit_rectification_deadline_passed(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """整改期已结束"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            supplier_id=supplier.id,
            rectification_deadline=datetime.utcnow() - timedelta(hours=1)
        )
        resp = client.post(f"/api/tasks/{task.id}/submit-rectification", headers=sup_headers)
        assert resp.status_code == 400
        assert "已结束" in resp.json()["detail"]


# 6.升级现场争议

class TestEscalateFieldDispute:
    """POST /api/tasks/{id}/escalate-field-dispute"""

    def test_escalate_success(self, client: TestClient, db_session, create_task, manufacturer, mfr_headers):
        """整改期结束后升级争议"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            manufacturer_id=manufacturer.id,
            rectification_deadline=datetime.utcnow() - timedelta(hours=1)  # 已过期
        )
        resp = client.post(
            f"/api/tasks/{task.id}/escalate-field-dispute",
            headers=mfr_headers,
            json={"reason": "供应商整改不达标"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "DISPUTED_FIELD"

    def test_escalate_before_deadline(self, client: TestClient, db_session, create_task, manufacturer, mfr_headers):
        """整改期未结束就升级"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            manufacturer_id=manufacturer.id,
            rectification_deadline=datetime.utcnow() + timedelta(days=7)
        )
        resp = client.post(
            f"/api/tasks/{task.id}/escalate-field-dispute",
            headers=mfr_headers,
            json={"reason": "提前升级"}
        )
        assert resp.status_code == 400
        assert "尚未结束" in resp.json()["detail"]

    def test_escalate_by_non_party(self, client: TestClient, create_task, auditor, aud_headers):
        """非相关方升级应403"""
        from datetime import datetime, timedelta
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            rectification_deadline=datetime.utcnow() - timedelta(hours=1)
        )
        resp = client.post(
            f"/api/tasks/{task.id}/escalate-field-dispute",
            headers=aud_headers,
            json={"reason": "无权升级"}
        )
        assert resp.status_code == 403
