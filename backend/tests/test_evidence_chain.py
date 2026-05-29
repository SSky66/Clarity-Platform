"""
存证查询与链上事件模块测试
覆盖: evidence/*, chain-events, chain/stats, chain/health
"""

import pytest
from fastapi.testclient import TestClient

from models import User, AuditTask, TaskReport, UserRole, TaskStatus


# 1.存证查询

class TestEvidenceQuery:
    """GET /api/tasks/{id}/evidence/*"""

    def test_evidence_data(self, client: TestClient, create_task, mfr_headers):
        """查询测试集存证"""
        task = create_task(status=TaskStatus.PREPARED, dataset_ipfs_hash="ipfs://dataset_1")
        resp = client.get(f"/api/tasks/{task.id}/evidence/data", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["test_set_hash"] == "ipfs://dataset_1"

    def test_evidence_model(self, client: TestClient, create_task, mfr_headers):
        """查询模型存证"""
        task = create_task(status=TaskStatus.PREPARED, model_hash_history=[{"hash": "ipfs://model_v1"}])
        resp = client.get(f"/api/tasks/{task.id}/evidence/model", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_hash"] == "ipfs://model_v1"
        assert len(data["history"]) == 1

    def test_evidence_model_empty(self, client: TestClient, create_task, mfr_headers):
        """无模型历史"""
        task = create_task(status=TaskStatus.PREPARED)
        resp = client.get(f"/api/tasks/{task.id}/evidence/model", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_hash"] is None
        assert data["history"] == []

    def test_evidence_audit(self, client: TestClient, db_session, create_task, mfr_headers):
        """查询审计报告存证"""
        task = create_task(status=TaskStatus.PASS)
        report = TaskReport(
            task_id=task.id,
            miss_rate=0.01,
            false_kill_rate=0.01,
            concentration_ratio=0.50,
            avg_fp=0.05,
            arrogance=0.20,
            map=0.85,
            f1=0.80,
            verdict="PASS",
            decision="PASS",
        )
        db_session.add(report)
        db_session.commit()

        resp = client.get(f"/api/tasks/{task.id}/evidence/audit", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["verdict"] == "PASS"
        assert data["miss_rate"] == 0.01

    def test_evidence_audit_not_found(self, client: TestClient, create_task, mfr_headers):
        """审计报告不存在"""
        task = create_task(status=TaskStatus.PREPARED)
        resp = client.get(f"/api/tasks/{task.id}/evidence/audit", headers=mfr_headers)
        assert resp.status_code == 404

    def test_evidence_onsite(self, client: TestClient, create_task, mfr_headers):
        """查询现场验收存证"""
        task = create_task(status=TaskStatus.COMPLETED, mfr_satisfied=True, sup_satisfied=True)
        resp = client.get(f"/api/tasks/{task.id}/evidence/onsite", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfr_satisfied"] is True

    def test_evidence_appeal(self, client: TestClient, db_session, create_task, supplier, sup_headers):
        """查询申诉证据存证"""
        from models import Appeal, AppealType, AppealStatus
        task = create_task(status=TaskStatus.DISPUTED_AUDIT, supplier_id=supplier.id)
        appeal = Appeal(
            task_id=task.id,
            appeal_type=AppealType.AUDIT_REJECT.value,
            reason="测试申诉",
            evidence_hash="ipfs://appeal_evidence",
            status=AppealStatus.PENDING.value
        )
        db_session.add(appeal)
        db_session.commit()

        resp = client.get(f"/api/tasks/{task.id}/evidence/appeal", headers=sup_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["evidence_hash"] == "ipfs://appeal_evidence"

    def test_evidence_complete(self, client: TestClient, db_session, create_task, mfr_headers):
        """查询证据完整性"""
        task = create_task(status=TaskStatus.PASS)
        # 无报告
        resp = client.get(f"/api/tasks/{task.id}/evidence/complete", headers=mfr_headers)
        assert resp.status_code == 200
        assert resp.json()["complete"] is False

        # 有报告
        report = TaskReport(task_id=task.id, verdict="PASS", decision="PASS")
        db_session.add(report)
        db_session.commit()

        resp = client.get(f"/api/tasks/{task.id}/evidence/complete", headers=mfr_headers)
        assert resp.status_code == 200
        assert resp.json()["complete"] is True

    def test_evidence_nonexistent_task(self, client: TestClient, mfr_headers):
        """查询不存在的项目存证"""
        resp = client.get("/api/tasks/99999/evidence/data", headers=mfr_headers)
        assert resp.status_code == 404


# 2.链上事件查询

class TestChainEvents:
    """链上事件相关接口"""

    def test_list_chain_events(self, client: TestClient, create_task, mfr_headers):
        """查询链上事件列表"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.get("/api/chain-events", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_chain_events_with_filter(self, client: TestClient, create_task, mfr_headers):
        """按条件筛选链上事件"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.get(f"/api/chain-events?task_id={task.id}&event_type=ProjectCreated", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_chain_health(self, client: TestClient):
        """链健康检查"""
        resp = client.get("/api/chain/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "connected" in data

    def test_chain_stats(self, client: TestClient, mfr_headers):
        """链上统计"""
        resp = client.get("/api/chain/stats", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_onchain_records" in data
        assert "connected" in data

    def test_chain_event_detail(self, client: TestClient, db_session, create_task, mfr_headers):
        """查询单条链上事件"""
        from models import ChainEvent
        event = ChainEvent(
            tx_hash="0xabc123",
            event_type="TestEvent",
            data_json={"test": True}
        )
        db_session.add(event)
        db_session.commit()

        resp = client.get("/api/chain/events/0xabc123", headers=mfr_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tx_hash"] == "0xabc123"

    def test_chain_event_detail_not_found(self, client: TestClient, mfr_headers):
        """查询不存在的交易"""
        resp = client.get("/api/chain/events/0xnonexistent", headers=mfr_headers)
        assert resp.status_code == 404


# 3.ADMIN管理接口

class TestAdmin:
    """ADMIN管理接口测试"""

    def test_process_timeouts_by_admin(self, client: TestClient, admin_headers):
        """ADMIN手动触发超时处理"""
        resp = client.post("/api/tasks/process-timeouts", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "processed" in data
        assert "count" in data

    def test_process_timeouts_by_non_admin(self, client: TestClient, mfr_headers):
        """非ADMIN触发超时处理"""
        resp = client.post("/api/tasks/process-timeouts", headers=mfr_headers)
        assert resp.status_code == 403

    def test_emergency_stop(self, client: TestClient, create_task, admin_headers):
        """ADMIN紧急停止项目"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.post(f"/api/tasks/{task.id}/emergency-stop?reason=测试紧急停止", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task.id
        assert "紧急停止" in data["message"]

    def test_emergency_stop_completed_task(self, client: TestClient, create_task, admin_headers):
        """紧急停止已终态项目"""
        task = create_task(status=TaskStatus.COMPLETED)
        resp = client.post(f"/api/tasks/{task.id}/emergency-stop?reason=测试", headers=admin_headers)
        assert resp.status_code == 400
        assert "已终态" in resp.json()["detail"]

    def test_emergency_stop_by_non_admin(self, client: TestClient, create_task, mfr_headers):
        """非ADMIN紧急停止"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.post(f"/api/tasks/{task.id}/emergency-stop?reason=测试", headers=mfr_headers)
        assert resp.status_code == 403

    def test_emergency_withdraw(self, client: TestClient, db_session, create_task, manufacturer, supplier, admin_headers):
        """ADMIN紧急撤回资金"""
        task = create_task(status=TaskStatus.PENDING)
        # 设置锁定资金
        manufacturer.locked_balance = 1000
        supplier.locked_balance = 1000
        task.mfr_locked = 1000
        task.sup_locked = 1000
        db_session.commit()

        resp = client.post(f"/api/tasks/{task.id}/emergency-withdraw", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "紧急撤回" in data["message"]

    def test_emergency_withdraw_by_non_admin(self, client: TestClient, create_task, mfr_headers):
        """非ADMIN紧急撤回"""
        task = create_task(status=TaskStatus.PENDING)
        resp = client.post(f"/api/tasks/{task.id}/emergency-withdraw", headers=mfr_headers)
        assert resp.status_code == 403

    def test_setup_contract_links_by_non_admin(self, client: TestClient, mfr_headers):
        """非ADMIN配置合约关联"""
        resp = client.post("/api/admin/setup-contract-links", headers=mfr_headers)
        assert resp.status_code == 403
