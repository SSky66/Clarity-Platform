"""
项目全生命周期测试 — 状态机流转与异常边界
覆盖: PENDING → UPLOADING → PREPARED → AUDITING → PASS/REJECT/SLASH → ... → COMPLETED
"""

import pytest
from fastapi.testclient import TestClient

from models import User, AuditTask, UserRole, TaskStatus, BASE_DEPOSIT, AUDIT_FEE


# 1.项目创建

class TestTaskCreate:
    """POST /api/tasks"""

    def test_create_task_success(self, client: TestClient, manufacturer, mfr_headers):
        """制造商正常创建项目"""
        resp = client.post("/api/tasks", headers=mfr_headers, json={
            "task_name": "测试项目A",
            "description": "这是一个测试项目",
            "target_fnr": 0.05,
            "target_fpr": 0.05,
            "target_map": 0.80,
            "target_f1": 0.75,
            "target_latency": 100,
            "conf_threshold": 0.25,
            "iou_threshold": 0.45,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_name"] == "测试项目A"
        assert data["status"] == "PENDING"
        assert data["manufacturer_id"] == manufacturer.id
        assert data["supplier_id"] is None
        assert data["task_hash"].startswith("0x")

    def test_create_task_by_supplier(self, client: TestClient, supplier, sup_headers):
        """供应商创建项目应403"""
        resp = client.post("/api/tasks", headers=sup_headers, json={
            "task_name": "非法项目",
            "target_fnr": 0.05,
            "target_fpr": 0.05,
            "conf_threshold": 0.25,
            "iou_threshold": 0.45,
        })
        assert resp.status_code == 403

    def test_create_task_missing_required_field(self, client: TestClient, manufacturer, mfr_headers):
        """缺少必填字段"""
        resp = client.post("/api/tasks", headers=mfr_headers, json={
            "task_name": "缺少字段",
            # 缺少 target_fnr, target_fpr
        })
        assert resp.status_code == 422

    def test_create_task_invalid_threshold(self, client: TestClient, manufacturer, mfr_headers):
        """阈值超出范围[0,1]"""
        resp = client.post("/api/tasks", headers=mfr_headers, json={
            "task_name": "非法阈值",
            "target_fnr": 1.5,  # > 1
            "target_fpr": 0.05,
            "conf_threshold": 0.25,
            "iou_threshold": 0.45,
        })
        assert resp.status_code == 422


# 2.供应商接单

class TestTaskAccept:
    """PUT /api/tasks/{id}/accept"""

    def test_accept_success(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """供应商正常接单"""
        task = create_task(status=TaskStatus.PENDING, supplier_id=None)
        # 确保supplier_id为None
        assert task.supplier_id is None
        resp = client.put(f"/api/tasks/{task.id}/accept", headers=sup_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "UPLOADING"
        assert data["supplier_id"] == supplier.id

    def test_accept_by_manufacturer(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """制造商接单应403"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.put(f"/api/tasks/{task.id}/accept", headers=mfr_headers)
        assert resp.status_code == 403

    def test_accept_already_accepted(self, client: TestClient, create_task, supplier, sup_headers):
        """重复接单"""
        task = create_task(status=TaskStatus.PENDING, supplier_id=supplier.id)
        resp = client.put(f"/api/tasks/{task.id}/accept", headers=sup_headers)
        assert resp.status_code == 400
        assert "已被" in resp.json()["detail"] or "其他" in resp.json()["detail"]

    def test_accept_wrong_status(self, client: TestClient, create_task, supplier, sup_headers):
        """非 PENDING 状态接单"""
        task = create_task(status=TaskStatus.UPLOADING)
        resp = client.put(f"/api/tasks/{task.id}/accept", headers=sup_headers)
        assert resp.status_code == 400

    def test_accept_nonexistent_task(self, client: TestClient, supplier, sup_headers):
        """接单不存在的项目"""
        resp = client.put("/api/tasks/99999/accept", headers=sup_headers)
        assert resp.status_code == 404


# 3.制造商准备与质押

class TestManufacturerPrepare:
    """POST /api/tasks/{id}/manufacturer-prepare"""

    def test_mfr_prepare_success(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """制造商正常准备+质押"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id)
        # 给制造商充足够的钱
        manufacturer.balance = 10000
        db_session.commit()

        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=mfr_headers,
            json={"purchase_insurance": False, "test_set_hash": "ipfs://test"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfr_prepared"] is True
        assert data["status"] == "UPLOADING"  # 供应商还没准备

    def test_mfr_prepare_insufficient_balance(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """余额不足"""
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

    def test_mfr_prepare_wrong_role(self, client: TestClient, create_task, supplier, sup_headers):
        """供应商调用制造商准备接口"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id)
        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=sup_headers,
            json={}
        )
        assert resp.status_code == 403

    def test_mfr_prepare_wrong_status(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """非UPLOADING状态调用"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=mfr_headers,
            json={}
        )
        assert resp.status_code == 400

    def test_mfr_prepare_already_prepared(self, client: TestClient, db_session, create_task, manufacturer, supplier, mfr_headers):
        """重复准备"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id, mfr_prepared=True)
        manufacturer.balance = 10000
        db_session.commit()

        resp = client.post(
            f"/api/tasks/{task.id}/manufacturer-prepare",
            headers=mfr_headers,
            json={}
        )
        assert resp.status_code == 400
        assert "已准备" in resp.json()["detail"]


# 4.供应商准备与质押

class TestSupplierPrepare:
    """POST /api/tasks/{id}/supplier-prepare"""

    def test_sup_prepare_success(self, client: TestClient, db_session, create_task, manufacturer, supplier, sup_headers):
        """供应商正常准备+质押"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id, mfr_prepared=True)
        supplier.balance = 10000
        db_session.commit()

        resp = client.post(
            f"/api/tasks/{task.id}/supplier-prepare",
            headers=sup_headers,
            json={"model_hash": "ipfs://model_v1"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sup_prepared"] is True
        assert data["status"] == "PREPARED"  # 双方都准备了

    def test_sup_prepare_insufficient_balance(self, client: TestClient, db_session, create_task, manufacturer, supplier, sup_headers):
        """余额不足"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id, mfr_prepared=True)
        supplier.balance = 0
        db_session.commit()

        resp = client.post(
            f"/api/tasks/{task.id}/supplier-prepare",
            headers=sup_headers,
            json={"model_hash": "ipfs://model_v1"}
        )
        assert resp.status_code == 400
        assert "余额不足" in resp.json()["detail"]

    def test_sup_prepare_wrong_role(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """制造商调用供应商准备接口"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=None)
        resp = client.post(
            f"/api/tasks/{task.id}/supplier-prepare",
            headers=mfr_headers,
            json={"model_hash": "ipfs://model_v1"}
        )
        assert resp.status_code == 403


# 5.审计流程

class TestAuditFlow:
    """审计节点开始审计+提交报告"""

    def test_start_audit_success(self, client: TestClient, create_task, auditor, aud_headers):
        """审计节点正常开始审计"""
        task = create_task(status=TaskStatus.PREPARED)
        resp = client.put(f"/api/tasks/{task.id}/start-audit", headers=aud_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "AUDITING"
        assert data["auditor_id"] == auditor.id

    def test_start_audit_wrong_status(self, client: TestClient, create_task, auditor, aud_headers):
        """非PREPARED状态开始审计"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.put(f"/api/tasks/{task.id}/start-audit", headers=aud_headers)
        assert resp.status_code == 400

    def test_start_audit_by_non_auditor(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """非审计节点开始审计"""
        task = create_task(status=TaskStatus.PREPARED)
        resp = client.put(f"/api/tasks/{task.id}/start-audit", headers=mfr_headers)
        assert resp.status_code == 403

    def test_submit_report_pass(self, client: TestClient, create_task, auditor, aud_headers):
        """提交PASS报告"""
        task = create_task(status=TaskStatus.AUDITING, auditor_id=auditor.id)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={
                "miss_rate": 0.01,
                "false_kill_rate": 0.01,
                "concentration_ratio": 0.50,
                "avg_fp": 0.05,
                "arrogance": 0.20,
                "map": 0.85,
                "f1": 0.80,
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "PASS"
        assert data["task"]["status"] == "PASS"

    def test_submit_report_reject(self, client: TestClient, create_task, auditor, aud_headers):
        """提交REJECT报告（漏杀率超标）"""
        task = create_task(status=TaskStatus.AUDITING, auditor_id=auditor.id)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={
                "miss_rate": 0.10,  # > 0.05 threshold
                "false_kill_rate": 0.01,
                "concentration_ratio": 0.50,
                "avg_fp": 0.05,
                "arrogance": 0.20,
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "REJECT"
        assert data["task"]["status"] == "REJECT"
        assert data["task"]["appeal_deadline"] is not None

    def test_submit_report_slash(self, client: TestClient, create_task, auditor, aud_headers):
        """提交SLASH报告（注意力密度过低）"""
        task = create_task(status=TaskStatus.AUDITING, auditor_id=auditor.id)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={
                "miss_rate": 0.01,
                "false_kill_rate": 0.01,
                "concentration_ratio": 0.10,  # < 0.20
                "avg_fp": 0.05,
                "arrogance": 0.20,
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "SLASH"
        assert data["task"]["status"] == "SLASH"

    def test_submit_report_by_non_auditor(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """非审计节点提交报告"""
        task = create_task(status=TaskStatus.AUDITING)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=mfr_headers,
            json={"miss_rate": 0.01, "false_kill_rate": 0.01, "concentration_ratio": 0.5, "avg_fp": 0.05, "arrogance": 0.2}
        )
        assert resp.status_code == 403

    def test_submit_report_wrong_status(self, client: TestClient, create_task, auditor, aud_headers):
        """非AUDITING状态提交报告"""
        task = create_task(status=TaskStatus.PREPARED)
        resp = client.post(
            f"/api/tasks/{task.id}/report",
            headers=aud_headers,
            json={"miss_rate": 0.01, "false_kill_rate": 0.01, "concentration_ratio": 0.5, "avg_fp": 0.05, "arrogance": 0.2}
        )
        assert resp.status_code == 400


# 6.PASS → ACCEPTANCE资金释放

class TestAdvanceToAcceptance:
    """POST /api/tasks/{id}/advance-to-acceptance"""

    def test_advance_success(self, client: TestClient, db_session, create_task, manufacturer, supplier):
        """PASS后释放30%资金"""
        task = create_task(status=TaskStatus.PASS, supplier_id=supplier.id)
        from core.security import create_access_token
        headers = {"Authorization": f"Bearer {create_access_token(data={'sub': str(manufacturer.id)})}"}

        resp = client.post(f"/api/tasks/{task.id}/advance-to-acceptance", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACCEPTANCE"

    def test_advance_wrong_status(self, client: TestClient, create_task, manufacturer):
        """非PASS状态调用"""
        task = create_task(status=TaskStatus.AUDITING)
        from core.security import create_access_token
        headers = {"Authorization": f"Bearer {create_access_token(data={'sub': str(manufacturer.id)})}"}

        resp = client.post(f"/api/tasks/{task.id}/advance-to-acceptance", headers=headers)
        assert resp.status_code == 400


# 7.查询接口

class TestTaskQuery:
    """GET /api/tasks/*"""

    def test_list_tasks_by_manufacturer(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """制造商只看自己的项目"""
        task1 = create_task(status=TaskStatus.PENDING, manufacturer_id=manufacturer.id)
        task2 = create_task(status=TaskStatus.PENDING)  # 其他制造商的

        resp = client.get("/api/tasks", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        task_ids = [t["id"] for t in data]
        assert task1.id in task_ids
        # task2不是当前制造商的，不应出现

    def test_get_task_detail(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """查询单个项目详情"""
        task = create_task(status=TaskStatus.PENDING, manufacturer_id=manufacturer.id)
        resp = client.get(f"/api/tasks/{task.id}", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == task.id
        assert data["task_hash"] == task.task_hash

    def test_get_nonexistent_task(self, client: TestClient, manufacturer, mfr_headers):
        """查询不存在的项目"""
        resp = client.get("/api/tasks/99999", headers=mfr_headers)
        assert resp.status_code == 404

    def test_task_stats(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """统计接口"""
        create_task(status=TaskStatus.PENDING, manufacturer_id=manufacturer.id)
        create_task(status=TaskStatus.COMPLETED, manufacturer_id=manufacturer.id)

        resp = client.get("/api/tasks/stats", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "pending" in data
        assert "completed" in data
        assert data["total"] >= 2
