"""
阶段3: 线上审计
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    User, AuditTask, TaskReport, UserRole, TaskStatus, get_db,
    ChainEventType, AuditDecision,
    AUDIT_FEE, APPEAL_WINDOW_SECONDS,
    PASS_RELEASE_RATIO, BASE_DEPOSIT,
)
from schemas import TaskResponse, AuditSubmitPayload
from core.deps import get_current_user
from core.chain_utils import insert_chain_event
from core.settlement_calc import finalize_task

router = APIRouter(prefix="/api/tasks", tags=["审计"])


@router.put("/{task_id}/start-audit", response_model=TaskResponse)
def start_audit(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """审计节点将PREPARED项目改为AUDITING"""
    if current_user.role != UserRole.AUDITOR.value:
        raise HTTPException(403, "仅审计节点可操作")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.PREPARED.value:
        raise HTTPException(400, "项目未准备好，无法开始审计")

    task.status = TaskStatus.AUDITING.value
    task.auditor_id = current_user.id
    task.audit_started_at = datetime.utcnow()
    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.AUDIT_STARTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"auditor_id": current_user.id}
    )

    return task


@router.post("/{task_id}/report")
def submit_report(
    task_id: int,
    payload: AuditSubmitPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    审计节点提交审计结果，与Audit.sol对齐
    三阶段判定：准确度 → 注意力 → 置信度
    """
    if current_user.role != UserRole.AUDITOR.value:
        raise HTTPException(403, "仅审计节点可提交报告")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task or task.status != TaskStatus.AUDITING.value:
        raise HTTPException(400, "项目不存在或状态非AUDITING")

    miss_th = task.target_fnr if task.target_fnr else 0.05
    false_kill_th = task.target_fpr if task.target_fpr else 0.05

    decision = _evaluate_verdict(
        payload.miss_rate,
        payload.false_kill_rate,
        payload.concentration_ratio,
        payload.avg_fp,
        payload.arrogance,
        miss_th,
        false_kill_th
    )

    report = TaskReport(
        task_id=task.id,
        miss_rate=payload.miss_rate,
        false_kill_rate=payload.false_kill_rate,
        concentration_ratio=payload.concentration_ratio,
        avg_fp=payload.avg_fp,
        arrogance=payload.arrogance,
        map=payload.map,
        f1=payload.f1,
        miss_threshold=miss_th,
        false_kill_threshold=false_kill_th,
        decision=decision.value,
        verdict=decision.value,
        report_hash=payload.report_hash or f"report_hash_{__import__('uuid').uuid4().hex[:16]}",
        auditor_node_id=current_user.id,
    )
    db.add(report)

    total_audit_fee = AUDIT_FEE * 2
    if task.auditor_id:
        auditor = db.query(User).filter(User.id == task.auditor_id).first()
        if auditor:
            auditor.balance += total_audit_fee
    else:
        admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if admin:
            admin.balance += total_audit_fee

    task.audit_completed_at = datetime.utcnow()
    task.final_fnr = payload.miss_rate
    task.final_fpr = payload.false_kill_rate
    task.final_cr = payload.concentration_ratio

    if decision == AuditDecision.PASS:
        task.status = TaskStatus.PASS.value
    elif decision == AuditDecision.REJECT:
        task.status = TaskStatus.REJECT.value
        task.appeal_deadline = datetime.utcnow() + timedelta(seconds=APPEAL_WINDOW_SECONDS)
    elif decision == AuditDecision.SLASH:
        task.status = TaskStatus.SLASH.value
        task.appeal_deadline = datetime.utcnow() + timedelta(seconds=APPEAL_WINDOW_SECONDS)

    insert_chain_event(
        db,
        event_type=ChainEventType.AUDIT_COMPLETED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={
            "decision": decision.value,
            "miss_rate": payload.miss_rate,
            "false_kill_rate": payload.false_kill_rate,
            "concentration_ratio": payload.concentration_ratio,
            "avg_fp": payload.avg_fp,
            "arrogance": payload.arrogance,
            "audit_fee": total_audit_fee
        }
    )

    db.commit()
    db.refresh(task)
    return {"task": task, "decision": decision.value}


def _evaluate_verdict(
    miss_rate: float,
    false_kill_rate: float,
    concentration_ratio: float,
    avg_fp: float,
    arrogance: float,
    miss_th: float,
    false_kill_th: float
) -> AuditDecision:
    """
    三阶段判定逻辑，与Audit._evaluateVerdict对齐
    """
    if miss_rate > miss_th or false_kill_rate > false_kill_th:
        return AuditDecision.REJECT

    if concentration_ratio < 0.20:
        return AuditDecision.SLASH

    if avg_fp >= 0.1:
        if arrogance >= 0.5:
            return AuditDecision.SLASH
        return AuditDecision.REJECT

    return AuditDecision.PASS


@router.post("/{task_id}/advance-to-acceptance", response_model=TaskResponse)
def advance_to_acceptance(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    PASS后释放30%锁定资金，进入ACCEPTANCE现场验收阶段
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.PASS.value:
        raise HTTPException(400, "项目状态非PASS")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    from decimal import Decimal
    release = Decimal(str(BASE_DEPOSIT)) * Decimal(str(PASS_RELEASE_RATIO))
    if manufacturer:
        manufacturer.balance += release
        manufacturer.locked_balance -= release
        task.mfr_locked -= release
    if supplier:
        supplier.balance += release
        supplier.locked_balance -= release
        task.sup_locked -= release

    task.status = TaskStatus.ACCEPTANCE.value
    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.FUNDS_RELEASED.value,
        task_id=task.id,
        data_json={
            "to_manufacturer": float(release) if manufacturer else 0,
            "to_supplier": float(release) if supplier else 0,
            "reason": "pass_advance_to_acceptance"
        }
    )

    return task
