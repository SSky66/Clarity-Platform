"""
阶段5: 现场验收（与Settlement.sol对齐）
"""
import hashlib
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    User, AuditTask, OnsiteRecord, UserRole, TaskStatus, get_db,
    ChainEventType, OnsiteLocalStatus,
    ONSITE_TIMEOUT_SECONDS,
)
from schemas import TaskResponse, FieldSignPayload
from core.deps import get_current_user
from core.chain_utils import insert_chain_event
from core.settlement_calc import finalize_task

router = APIRouter(prefix="/api/tasks", tags=["现场验收"])


@router.post("/{task_id}/submit-completion", response_model=TaskResponse)
def submit_completion(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    供应商提交"部署完成"，与Fund.submitCompletion/Settlement.submitSupplierCompletion对齐
    触发72h现场验收等待期
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.ACCEPTANCE.value:
        raise HTTPException(400, "项目状态非ACCEPTANCE")
    if current_user.id != task.supplier_id:
        raise HTTPException(403, "仅供应商可提交")
    if task.supplier_submitted:
        raise HTTPException(400, "已提交过")

    task.supplier_submitted = True
    task.onsite_deadline = datetime.utcnow() + timedelta(seconds=ONSITE_TIMEOUT_SECONDS)

    task.mfr_confirmed = False
    task.sup_confirmed = False
    task.mfr_satisfied = False
    task.sup_satisfied = False

    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    if not onsite:
        onsite = OnsiteRecord(task_id=task_id, local_status=OnsiteLocalStatus.ONGOING.value)
        db.add(onsite)
    else:
        onsite.local_status = OnsiteLocalStatus.ONGOING.value

    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.SUPPLIER_SUBMITTED_COMPLETION.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"onsite_deadline": task.onsite_deadline.isoformat()}
    )

    return task


@router.post("/{task_id}/confirm-onsite", response_model=TaskResponse)
def confirm_onsite(
    task_id: int,
    payload: FieldSignPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    现场验收确认，与Fund.confirmOnsite/Settlement对齐
    制造商和供应商分别调用
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status not in [TaskStatus.ACCEPTANCE.value, TaskStatus.RECTIFICATION.value]:
        raise HTTPException(400, "当前状态不允许现场确认")
    if not task.supplier_submitted:
        raise HTTPException(400, "供应商尚未提交完成")

    is_manufacturer = current_user.id == task.manufacturer_id
    is_supplier = current_user.id == task.supplier_id
    if not is_manufacturer and not is_supplier:
        raise HTTPException(403, "仅项目相关方可操作")

    # 回填现场实测指标
    if payload.field_actual_fnr is not None:
        task.field_actual_fnr = payload.field_actual_fnr
    if payload.field_actual_fpr is not None:
        task.field_actual_fpr = payload.field_actual_fpr
    if payload.field_actual_latency is not None:
        task.field_actual_latency = payload.field_actual_latency
    # field_actual_map 和 field_actual_f1 不在 FieldSignPayload 中
    # 但可能在 task 模型中有这些字段，通过 measured_map 回填
    if payload.measured_map is not None:
        task.field_actual_map = payload.measured_map
    if payload.field_environment_notes:
        task.field_environment_notes = payload.field_environment_notes
    if payload.evidence_hash:
        task.field_evidence_hash = payload.evidence_hash

    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    if not onsite:
        onsite = OnsiteRecord(task_id=task_id)
        db.add(onsite)

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    if is_manufacturer:
        if task.mfr_confirmed:
            raise HTTPException(400, "制造商已确认")
        task.mfr_confirmed = True
        task.mfr_satisfied = payload.satisfied
        onsite.mfr_satisfied = payload.satisfied
        onsite.mfr_measured_map = payload.measured_map
        onsite.mfr_evidence_hash = payload.evidence_hash

        if not payload.satisfied:
            insert_chain_event(
                db,
                event_type=ChainEventType.MANUFACTURER_REJECTED.value,
                task_id=task.id,
                sender_address=current_user.wallet_address,
                data_json={"onsite_deadline": task.onsite_deadline.isoformat() if task.onsite_deadline else None}
            )
            db.commit()
            return task

    else:
        if task.sup_confirmed:
            raise HTTPException(400, "供应商已确认")

        if task.mfr_confirmed and not task.mfr_satisfied:
            task.sup_confirmed = True
            onsite.sup_satisfied = payload.satisfied
            onsite.sup_measured_map = payload.measured_map
            onsite.sup_evidence_hash = payload.evidence_hash

            if payload.satisfied:
                _enter_rectification(db, task, onsite)
            else:
                task.status = TaskStatus.DISPUTED_FIELD.value
                task.sup_satisfied = False

            db.commit()
            db.refresh(task)
            return task

        task.sup_confirmed = True
        task.sup_satisfied = payload.satisfied
        onsite.sup_satisfied = payload.satisfied
        onsite.sup_measured_map = payload.measured_map
        onsite.sup_evidence_hash = payload.evidence_hash

    # 双方都确认且都满意 → 完成
    if task.mfr_confirmed and task.sup_confirmed and task.mfr_satisfied and task.sup_satisfied:
        if manufacturer and task.mfr_locked:
            manufacturer.balance += task.mfr_locked
            manufacturer.locked_balance -= task.mfr_locked
        if supplier and task.sup_locked:
            supplier.balance += task.sup_locked
            supplier.locked_balance -= task.sup_locked

        if task.extension_deposit > 0 and supplier:
            supplier.balance += task.extension_deposit

        onsite.local_status = OnsiteLocalStatus.CONFIRMED.value
        onsite.confirm_time = datetime.utcnow()

        confirm_data = (
            f"{task.manufacturer_id}:"
            f"{task.supplier_id}:"
            f"{onsite.mfr_satisfied}:"
            f"{onsite.sup_satisfied}:"
            f"{onsite.mfr_measured_map or 0}:"
            f"{onsite.sup_measured_map or 0}:"
            f"{datetime.utcnow().isoformat()}"
        )
        onsite.confirm_hash = "0x" + hashlib.sha256(confirm_data.encode()).hexdigest()[:64]

        finalize_task(db, task, is_success=True, supplier_slash=False, manufacturer_slash=False)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return task


def _enter_rectification(db: Session, task: AuditTask, onsite: OnsiteRecord):
    """进入整改期，与Fund._enterRectification对齐"""
    from models import RECTIFICATION_PERIOD_SECONDS
    task.status = TaskStatus.RECTIFICATION.value
    task.rectification_deadline = datetime.utcnow() + timedelta(seconds=RECTIFICATION_PERIOD_SECONDS)
    task.rectification_count = 0

    task.mfr_confirmed = False
    task.sup_confirmed = False
    task.mfr_satisfied = False
    task.sup_satisfied = False
    task.supplier_submitted = False

    onsite.local_status = OnsiteLocalStatus.RECTIFYING.value
    onsite.mfr_measured_map = None
    onsite.sup_measured_map = None
    onsite.mfr_evidence_hash = None
    onsite.sup_evidence_hash = None
    onsite.mfr_satisfied = False
    onsite.sup_satisfied = False
    onsite.confirm_hash = None
    onsite.confirm_time = None

    insert_chain_event(
        db,
        event_type=ChainEventType.SUPPLIER_ACCEPTED_RECTIFICATION.value,
        task_id=task.id,
        data_json={"rectification_deadline": task.rectification_deadline.isoformat()}
    )


@router.post("/{task_id}/timeout-auto-pass", response_model=TaskResponse)
def timeout_auto_pass(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    制造商72h无响应，自动通过，与Fund.timeoutAutoPass对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.ACCEPTANCE.value:
        raise HTTPException(400, "项目状态非ACCEPTANCE")
    if not task.supplier_submitted:
        raise HTTPException(400, "供应商尚未提交")
    if not task.onsite_deadline or datetime.utcnow() <= task.onsite_deadline:
        raise HTTPException(400, "超时未到达")
    if task.mfr_confirmed and not task.mfr_satisfied:
        raise HTTPException(400, "制造商已拒绝，不可自动通过")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    if manufacturer and task.mfr_locked:
        manufacturer.balance += task.mfr_locked
        manufacturer.locked_balance -= task.mfr_locked
    if supplier and task.sup_locked:
        supplier.balance += task.sup_locked
        supplier.locked_balance -= task.sup_locked

    if task.extension_deposit > 0 and supplier:
        supplier.balance += task.extension_deposit

    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    if onsite:
        onsite.local_status = OnsiteLocalStatus.TIMEOUT.value
        onsite.confirm_time = datetime.utcnow()

        confirm_data = (
            f"TIMEOUT_AUTO_PASS:"
            f"{task.manufacturer_id}:"
            f"{task.supplier_id}:"
            f"{onsite.mfr_satisfied}:"
            f"{onsite.sup_satisfied}:"
            f"{onsite.mfr_measured_map or 0}:"
            f"{onsite.sup_measured_map or 0}:"
            f"{datetime.utcnow().isoformat()}"
        )
        onsite.confirm_hash = "0x" + hashlib.sha256(confirm_data.encode()).hexdigest()[:64]

    finalize_task(db, task, is_success=True, supplier_slash=False, manufacturer_slash=False)
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return task
