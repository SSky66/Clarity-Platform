"""
申诉与仲裁模块测试
覆盖: start-appeal, initiate-field-appeal, create-appeal, list-appeals, pending, assign-arbitrator, resolve
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

from models import User, AuditTask, Appeal, UserRole, TaskStatus, AppealType, AppealStatus


# 1.发起线上申诉

class TestStartAppeal:
    """POST /api/tasks/{id}/start-appeal"""

    def test_start_appeal_from_reject(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """REJECT状态发起申诉"""
        task = create_task(
            status=TaskStatus.REJECT,
            supplier_id=supplier.id,
            appeal_deadline=datetime.utcnow() + timedelta(days=3)
        )
        resp = client.post(f"/api/tasks/{task.id}/start-appeal", headers=sup_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "DISPUTED_AUDIT"
        assert data["status_before_appeal"] == "REJECT"

    def test_start_appeal_from_slash(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """SLASH状态发起申诉"""
        task = create_task(
            status=TaskStatus.SLASH,
            supplier_id=supplier.id,
            appeal_deadline=datetime.utcnow() + timedelta(days=3)
        )
        resp = client.post(f"/api/tasks/{task.id}/start-appeal", headers=sup_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "DISPUTED_AUDIT"

    def test_start_appeal_deadline_passed(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """申诉期已结束"""
        task = create_task(
            status=TaskStatus.REJECT,
            supplier_id=supplier.id,
            appeal_deadline=datetime.utcnow() - timedelta(hours=1)
        )
        resp = client.post(f"/api/tasks/{task.id}/start-appeal", headers=sup_headers)
        assert resp.status_code == 400
        assert "已结束" in resp.json()["detail"]

    def test_start_appeal_wrong_status(self, client: TestClient, create_task, supplier, sup_headers):
        """非REJECT/SLASH状态"""
        task = create_task(status=TaskStatus.PENDING, supplier_id=supplier.id)
        resp = client.post(f"/api/tasks/{task.id}/start-appeal", headers=sup_headers)
        assert resp.status_code == 400

    def test_start_appeal_by_manufacturer(self, client: TestClient, create_task, manufacturer, supplier, mfr_headers):
        """制造商发起申诉应403"""
        task = create_task(
            status=TaskStatus.REJECT,
            manufacturer_id=manufacturer.id,
            supplier_id=supplier.id,
            appeal_deadline=datetime.utcnow() + timedelta(days=3)
        )
        resp = client.post(f"/api/tasks/{task.id}/start-appeal", headers=mfr_headers)
        assert resp.status_code == 403


# 2. 发起现场申诉

class TestInitiateFieldAppeal:
    """POST /api/tasks/{id}/initiate-field-appeal"""

    def test_field_appeal_from_rectification(self, client: TestClient, db_session, create_task, manufacturer, mfr_headers):
        """RECTIFICATION整改期结束后发起现场申诉"""
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            manufacturer_id=manufacturer.id,
            rectification_deadline=datetime.utcnow() - timedelta(hours=1)
        )
        resp = client.post(
            f"/api/tasks/{task.id}/initiate-field-appeal",
            headers=mfr_headers,
            json={"reason": "整改不达标"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "DISPUTED_FIELD"

    def test_field_appeal_from_disputed_field(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """DISPUTED_FIELD状态发起申诉"""
        task = create_task(status=TaskStatus.DISPUTED_FIELD, manufacturer_id=manufacturer.id)
        resp = client.post(
            f"/api/tasks/{task.id}/initiate-field-appeal",
            headers=mfr_headers,
            json={"reason": "继续申诉"}
        )
        assert resp.status_code == 200

    def test_field_appeal_before_deadline(self, client: TestClient, db_session, create_task, manufacturer, mfr_headers):
        """整改期未结束就发起"""
        task = create_task(
            status=TaskStatus.RECTIFICATION,
            manufacturer_id=manufacturer.id,
            rectification_deadline=datetime.utcnow() + timedelta(days=7)
        )
        resp = client.post(
            f"/api/tasks/{task.id}/initiate-field-appeal",
            headers=mfr_headers,
            json={"reason": "提前申诉"}
        )
        assert resp.status_code == 400
        assert "尚未结束" in resp.json()["detail"]

    def test_field_appeal_by_non_party(self, client: TestClient, create_task, auditor, aud_headers):
        """非相关方发起应 403"""
        task = create_task(status=TaskStatus.DISPUTED_FIELD)
        resp = client.post(
            f"/api/tasks/{task.id}/initiate-field-appeal",
            headers=aud_headers,
            json={"reason": "无权申诉"}
        )
        assert resp.status_code == 403


# 3.创建申诉记录

class TestCreateAppeal:
    """POST /api/appeals"""

    def test_create_audit_appeal(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """创建线上审计申诉记录"""
        task = create_task(
            status=TaskStatus.DISPUTED_AUDIT,
            supplier_id=supplier.id
        )
        resp = client.post("/api/appeals", headers=sup_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "对审计结果有异议",
            "evidence_hash": "ipfs://appeal_evidence_1"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["appeal_type"] == "AUDIT_REJECT"
        assert data["status"] == "PENDING"

    def test_create_field_appeal(self, client: TestClient, db_session, create_task, manufacturer, mfr_headers):
        """创建现场申诉记录"""
        task = create_task(
            status=TaskStatus.DISPUTED_FIELD,
            manufacturer_id=manufacturer.id
        )
        resp = client.post("/api/appeals", headers=mfr_headers, json={
            "task_id": task.id,
            "appeal_type": "FIELD_DOWNGRADE",
            "reason": "现场履约争议",
            "evidence_hash": "ipfs://field_evidence_1"
        })
        assert resp.status_code == 200
        assert resp.json()["appeal_type"] == "FIELD_DOWNGRADE"

    def test_create_appeal_wrong_status(self, client: TestClient, create_task, supplier, sup_headers):
        """状态不允许申诉"""
        task = create_task(status=TaskStatus.PENDING, supplier_id=supplier.id)
        resp = client.post("/api/appeals", headers=sup_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "错误状态申诉"
        })
        assert resp.status_code == 400

    def test_create_appeal_by_non_party(self, client: TestClient, create_task, auditor, aud_headers):
        """非相关方创建申诉"""
        task = create_task(status=TaskStatus.DISPUTED_AUDIT)
        resp = client.post("/api/appeals", headers=aud_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "无权申诉"
        })
        assert resp.status_code == 403


# 4.查询申诉列表

class TestListAppeals:
    """GET /api/appeals"""

    def test_list_appeals(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """查询自己的申诉记录"""
        task = create_task(status=TaskStatus.DISPUTED_AUDIT, supplier_id=supplier.id)
        # 先创建一个申诉
        client.post("/api/appeals", headers=sup_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "测试申诉"
        })

        resp = client.get("/api/appeals", headers=sup_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_appeals_empty(self, client: TestClient, sup_headers):
        """无申诉记录"""
        resp = client.get("/api/appeals", headers=sup_headers)
        assert resp.status_code == 200
        assert resp.json() == []


# 5.仲裁管理（ADMIN）

class TestArbitration:
    """仲裁接口测试"""

    def test_pending_appeals_list(self, client: TestClient, db_session, create_task, supplier, admin_user, admin_headers):
        """ADMIN查询待仲裁列表"""
        task = create_task(status=TaskStatus.DISPUTED_AUDIT, supplier_id=supplier.id)
        # 创建申诉
        client.post("/api/appeals", headers=admin_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "待仲裁申诉"
        })

        resp = client.get("/api/appeals/pending", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_pending_appeals_by_non_admin(self, client: TestClient, mfr_headers):
        """非ADMIN查询待仲裁"""
        resp = client.get("/api/appeals/pending", headers=mfr_headers)
        assert resp.status_code == 403

    def test_assign_arbitrator(self, client: TestClient, db_session, create_task, supplier, auditor, admin_user, admin_headers, sup_headers):
        """指派仲裁员"""
        task = create_task(status=TaskStatus.DISPUTED_AUDIT, supplier_id=supplier.id)
        # supplier创建申诉
        appeal_resp = client.post("/api/appeals", headers=sup_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "指派仲裁员测试"
        })
        assert appeal_resp.status_code == 200
        appeal_id = appeal_resp.json()["id"]

        # admin指派仲裁员
        resp = client.post(
            f"/api/appeals/{appeal_id}/assign-arbitrator",
            headers=admin_headers,
            json={"arbitrator_id": auditor.id}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["arbitrator_id"] == auditor.id
        assert data["status"] == "ARBITRATING"

    def test_assign_arbitrator_non_admin(self, client: TestClient, create_task, supplier, auditor, sup_headers):
        """非 ADMIN 指派仲裁员"""
        task = create_task(status=TaskStatus.DISPUTED_AUDIT, supplier_id=supplier.id)
        resp = client.post(
            f"/api/appeals/999/assign-arbitrator",
            headers=sup_headers,
            json={"arbitrator_id": auditor.id}
        )
        assert resp.status_code == 403

    def test_resolve_audit_appeal_result1(self, client: TestClient, db_session, create_task, supplier, auditor, admin_user, admin_headers, sup_headers):
        """仲裁裁决 result=1（维持原判）"""
        task = create_task(status=TaskStatus.DISPUTED_AUDIT, supplier_id=supplier.id)
        # supplier 创建申诉
        appeal_resp = client.post("/api/appeals", headers=sup_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "裁决测试"
        })
        appeal_id = appeal_resp.json()["id"]

        # admin指派仲裁员
        client.post(f"/api/appeals/{appeal_id}/assign-arbitrator", headers=admin_headers, json={"arbitrator_id": auditor.id})

        # admin裁决
        resp = client.post(
            f"/api/appeals/{appeal_id}/resolve",
            headers=admin_headers,
            json={"result": 1, "resolution": "维持原判，供应商能力不足"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RESOLVED"
        assert data["verdict"] == 1

    def test_resolve_audit_appeal_result2(self, client: TestClient, db_session, create_task, supplier, auditor, admin_user, admin_headers, sup_headers):
        """仲裁裁决result=2（改判PASS）"""
        task = create_task(status=TaskStatus.DISPUTED_AUDIT, supplier_id=supplier.id)
        appeal_resp = client.post("/api/appeals", headers=sup_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "改判测试"
        })
        appeal_id = appeal_resp.json()["id"]
        client.post(f"/api/appeals/{appeal_id}/assign-arbitrator", headers=admin_headers, json={"arbitrator_id": auditor.id})

        resp = client.post(
            f"/api/appeals/{appeal_id}/resolve",
            headers=admin_headers,
            json={"result": 2, "resolution": "改判为PASS"}
        )
        assert resp.status_code == 200
        assert resp.json()["verdict"] == 2

    def test_resolve_before_assign(self, client: TestClient, db_session, create_task, supplier, admin_user, admin_headers, sup_headers):
        """未指派仲裁员就裁决"""
        task = create_task(status=TaskStatus.DISPUTED_AUDIT, supplier_id=supplier.id)
        appeal_resp = client.post("/api/appeals", headers=sup_headers, json={
            "task_id": task.id,
            "appeal_type": "AUDIT_REJECT",
            "reason": "提前裁决测试"
        })
        appeal_id = appeal_resp.json()["id"]

        resp = client.post(
            f"/api/appeals/{appeal_id}/resolve",
            headers=admin_headers,
            json={"result": 1, "resolution": "提前裁决"}
        )
        assert resp.status_code == 400
        assert "尚未进入仲裁" in resp.json()["detail"]

    def test_resolve_non_admin(self, client: TestClient, create_task, supplier, sup_headers):
        """非ADMIN裁决"""
        resp = client.post("/api/appeals/999/resolve", headers=sup_headers, json={"result": 1, "resolution": "无权"})
        assert resp.status_code == 403
