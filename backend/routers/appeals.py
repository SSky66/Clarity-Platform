"""
申诉接口，与Dispute.sol对齐
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    AuditTask, Appeal, User, UserRole, TaskStatus, get_db,
    AppealType, AppealStatus, ChainEventType,
)
from schemas import AppealCreate, AppealResponse, TaskResponse, EscalateFieldDisputePayload
from core.deps import get_current_user
from core.chain_utils import insert_chain_event

router = APIRouter(prefix="/api", tags=["申诉"])


@router.post("/tasks/{task_id}/start-appeal", response_model=TaskResponse)
def start_appeal(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    供应商发起线上审计申诉，与Dispute.initiateAuditAppeal/Fund.startAppeal对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if current_user.id != task.supplier_id:
        raise HTTPException(403, "仅供应商可发起线上申诉")
    if task.status not in [TaskStatus.REJECT.value, TaskStatus.SLASH.value]:
        raise HTTPException(400, "当前状态不允许发起申诉")
    if not task.appeal_deadline or datetime.utcnow() > task.appeal_deadline:
        raise HTTPException(400, "申诉期已结束")

    task.status_before_appeal = task.status
    task.status = TaskStatus.DISPUTED_AUDIT.value
    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.APPEAL_STARTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"deadline": task.appeal_deadline.isoformat() if task.appeal_deadline else None}
    )

    return task


@router.post("/tasks/{task_id}/initiate-field-appeal", response_model=TaskResponse)
def initiate_field_appeal(
    task_id: int,
    payload: EscalateFieldDisputePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    发起现场履约申诉，与Dispute.initiateFieldAppeal对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if current_user.id not in [task.manufacturer_id, task.supplier_id]:
        raise HTTPException(403, "仅项目相关方可发起现场申诉")
    if task.status not in [TaskStatus.RECTIFICATION.value, TaskStatus.DISPUTED_FIELD.value]:
        raise HTTPException(400, "当前状态不允许现场申诉")
    if task.status == TaskStatus.RECTIFICATION.value:
        if not task.rectification_deadline or datetime.utcnow() <= task.rectification_deadline:
            raise HTTPException(400, "整改期尚未结束")
        task.status = TaskStatus.DISPUTED_FIELD.value

    task.dispute_reason = payload.reason
    task.dispute_at = datetime.utcnow()
    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.FIELD_APPEAL_INITIATED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"reason": payload.reason}
    )

    return task


@router.post("/appeals", response_model=AppealResponse)
def create_appeal(
    payload: AppealCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    创建申诉记录，与Dispute.initiateAuditAppeal/initiateFieldAppeal对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == payload.task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if current_user.id not in [task.manufacturer_id, task.supplier_id]:
        raise HTTPException(403, "仅项目相关方可申诉")

    if payload.appeal_type.value in [AppealType.AUDIT_REJECT.value, AppealType.AUDIT_SLASH.value]:
        if task.status != TaskStatus.DISPUTED_AUDIT.value:
            raise HTTPException(400, "当前状态不允许线上申诉，请先调用 /start-appeal")
        if current_user.id != task.supplier_id:
            raise HTTPException(403, "仅供应商可对审计结果申诉")
    else:
        if task.status not in [TaskStatus.RECTIFICATION.value, TaskStatus.DISPUTED_FIELD.value]:
            raise HTTPException(400, "当前状态不允许现场申诉")
        if task.status == TaskStatus.RECTIFICATION.value:
            if not task.rectification_deadline or datetime.utcnow() <= task.rectification_deadline:
                raise HTTPException(400, "整改期尚未结束")
            task.status = TaskStatus.DISPUTED_FIELD.value

    appeal = Appeal(
        task_id=payload.task_id,
        appeal_type=payload.appeal_type.value,
        reason=payload.reason,
        evidence_hash=payload.evidence_hash,
        status=AppealStatus.PENDING.value
    )
    db.add(appeal)

    task.dispute_type = payload.appeal_type.value
    task.dispute_reason = payload.reason
    task.dispute_at = datetime.utcnow()

    db.commit()
    db.refresh(appeal)
    return appeal


@router.get("/appeals", response_model=list[AppealResponse])
def list_appeals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询申诉记录"""
    from sqlalchemy import or_
    user_tasks = db.query(AuditTask.id).filter(
        or_(AuditTask.manufacturer_id == current_user.id, AuditTask.supplier_id == current_user.id)
    ).subquery()
    return db.query(Appeal).filter(Appeal.task_id.in_(user_tasks)).order_by(Appeal.created_at.desc()).all()
