"""
阶段6: 整改与最终清算
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    AuditTask, User, UserRole, TaskStatus, get_db,
    ChainEventType, OnsiteLocalStatus,
    RECTIFICATION_PERIOD_SECONDS, MAX_EXTENSIONS, EXTENSION_FEE, ONSITE_TIMEOUT_SECONDS,
)
from schemas import TaskResponse, EscalateFieldDisputePayload
from core.deps import get_current_user
from core.chain_utils import insert_chain_event

router = APIRouter(prefix="/api/tasks", tags=["整改"])


@router.post("/{task_id}/request-extension", response_model=TaskResponse)
def request_extension(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    整改延期申请，与Fund.requestExtension对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.RECTIFICATION.value:
        raise HTTPException(400, "项目状态非整改中")
    if current_user.id != task.supplier_id:
        raise HTTPException(403, "仅供应商可申请延期")
    if task.rectification_count >= MAX_EXTENSIONS:
        raise HTTPException(400, f"最多延期 {MAX_EXTENSIONS} 次")
    if not task.rectification_deadline or datetime.utcnow() > task.rectification_deadline:
        raise HTTPException(400, "整改期已结束")

    if current_user.balance < EXTENSION_FEE:
        raise HTTPException(400, f"余额不足，需要 {EXTENSION_FEE}")

    current_user.balance -= EXTENSION_FEE
    task.extension_deposit += EXTENSION_FEE
    task.rectification_count += 1
    task.rectification_deadline = task.rectification_deadline + timedelta(seconds=RECTIFICATION_PERIOD_SECONDS)

    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.EXTENSION_REQUESTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"extension_count": task.rectification_count, "fee": EXTENSION_FEE}
    )

    return task


@router.post("/{task_id}/submit-rectification", response_model=TaskResponse)
def submit_rectification(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    提交整改完成，与Fund.submitRectification对齐
    回到ACCEPTANCE，重置验收流程
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.RECTIFICATION.value:
        raise HTTPException(400, "项目状态非整改中")
    if current_user.id != task.supplier_id:
        raise HTTPException(403, "仅供应商可提交整改")
    if not task.rectification_deadline or datetime.utcnow() > task.rectification_deadline:
        raise HTTPException(400, "整改期已结束")

    task.status = TaskStatus.ACCEPTANCE.value
    task.onsite_deadline = datetime.utcnow() + timedelta(seconds=ONSITE_TIMEOUT_SECONDS)
    task.supplier_submitted = True
    task.mfr_confirmed = False
    task.sup_confirmed = False
    task.mfr_satisfied = False
    task.sup_satisfied = False

    onsite = db.query(__import__('models').OnsiteRecord).filter(__import__('models').OnsiteRecord.task_id == task_id).first()
    if onsite:
        onsite.local_status = OnsiteLocalStatus.ONGOING.value

    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.RECTIFICATION_SUBMITTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"action": "submitted"}
    )

    return task


@router.post("/{task_id}/escalate-field-dispute", response_model=TaskResponse)
def escalate_field_dispute(
    task_id: int,
    payload: EscalateFieldDisputePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    整改期结束后升级现场争议状态，与Fund.escalateToFieldDispute对齐
    建议前端统一使用 /initiate-field-appeal
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.RECTIFICATION.value:
        raise HTTPException(400, "项目状态非整改中")
    if current_user.id not in [task.manufacturer_id, task.supplier_id]:
        raise HTTPException(403, "仅项目相关方可操作")
    if not task.rectification_deadline or datetime.utcnow() <= task.rectification_deadline:
        raise HTTPException(400, "整改期尚未结束")

    task.status = TaskStatus.DISPUTED_FIELD.value
    task.dispute_reason = payload.reason
    task.dispute_at = datetime.utcnow()

    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.FIELD_DISPUTE_ESCALATED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"reason": payload.reason, "note": "兼容接口，建议改用 /initiate-field-appeal"}
    )

    return task
