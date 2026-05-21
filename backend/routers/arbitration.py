"""
仲裁接口
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    AuditTask, Appeal, User, UserRole, TaskStatus, get_db,
    AppealStatus, AppealType, ChainEventType,
    SLASH_COMPENSATION_RATIO,
)
from schemas import (
    AppealResponse, AppealResolve, AssignArbitratorPayload,
    PendingAppealResponse, UploadAppealEvidencePayload,
)
from core.deps import get_current_user
from core.chain_utils import insert_chain_event
from core.settlement import finalize_task

router = APIRouter(prefix="/api/appeals", tags=["仲裁"])


@router.get("/pending", response_model=list[PendingAppealResponse])
def list_pending_appeals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """ADMIN查询所有待仲裁申诉"""
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可查看待仲裁列表")

    appeals = db.query(Appeal).filter(
        Appeal.status.in_([AppealStatus.PENDING.value, AppealStatus.ARBITRATING.value])
    ).order_by(Appeal.created_at.desc()).all()

    result = []
    for appeal in appeals:
        task = db.query(AuditTask).filter(AuditTask.id == appeal.task_id).first()
        manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first() if task else None
        supplier = db.query(User).filter(User.id == task.supplier_id).first() if task else None

        result.append(PendingAppealResponse(
            id=appeal.id,
            task_id=appeal.task_id,
            appeal_type=appeal.appeal_type,
            status=appeal.status,
            reason=appeal.reason,
            evidence_hash=appeal.evidence_hash,
            arbitrator_id=appeal.arbitrator_id,
            liable_party=appeal.liable_party,
            resolution=appeal.resolution,
            refund_amount=float(appeal.refund_amount) if appeal.refund_amount else None,
            verdict=appeal.verdict,
            created_at=appeal.created_at,
            resolved_at=appeal.resolved_at,
            task_name=task.task_name if task else None,
            task_hash=task.task_hash if task else None,
            manufacturer_name=manufacturer.display_name if manufacturer else None,
            supplier_name=supplier.display_name if supplier else None,
            manufacturer_margin=float(task.mfr_locked) if task else None,
            supplier_margin=float(task.sup_locked) if task else None,
            task_status=task.status if task else None,
        ))
    return result


@router.post("/{appeal_id}/assign-arbitrator", response_model=AppealResponse)
def assign_arbitrator(
    appeal_id: int,
    payload: AssignArbitratorPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    指派仲裁员，与Dispute.assignArbitrator对齐
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可指派仲裁员")

    appeal = db.query(Appeal).filter(Appeal.id == appeal_id).first()
    if not appeal:
        raise HTTPException(404, "申诉不存在")
    if appeal.status != AppealStatus.PENDING.value:
        raise HTTPException(400, "该申诉不可指派仲裁员")

    arbitrator = db.query(User).filter(User.id == payload.arbitrator_id).first()
    if not arbitrator:
        raise HTTPException(404, "仲裁员不存在")

    appeal.arbitrator_id = payload.arbitrator_id
    appeal.status = AppealStatus.ARBITRATING.value

    task = db.query(AuditTask).filter(AuditTask.id == appeal.task_id).first()
    if task:
        task.status = TaskStatus.ARBITRATING.value

    db.commit()
    db.refresh(appeal)
    return appeal


@router.post("/{appeal_id}/resolve", response_model=AppealResponse)
def resolve_appeal(
    appeal_id: int,
    payload: AppealResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    协会仲裁裁决，与Dispute.submitAuditArbitration/submitFieldArbitration对齐
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅协会管理员可执行仲裁")

    appeal = db.query(Appeal).filter(Appeal.id == appeal_id).first()
    if not appeal:
        raise HTTPException(404, "申诉不存在")
    if appeal.status != AppealStatus.ARBITRATING.value:
        raise HTTPException(400, "该申诉尚未进入仲裁状态")

    task = db.query(AuditTask).filter(AuditTask.id == appeal.task_id).first()
    if not task:
        raise HTTPException(404, "关联项目不存在")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    appeal.verdict = payload.result
    appeal.resolution = payload.resolution
    appeal.status = AppealStatus.RESOLVED.value
    appeal.resolved_at = datetime.utcnow()

    if appeal.appeal_type in [AppealType.AUDIT_REJECT.value, AppealType.AUDIT_SLASH.value]:
        _resolve_audit_appeal(db, task, appeal, payload.result, manufacturer, supplier)
    else:
        _resolve_field_appeal(db, task, appeal, payload.result, manufacturer, supplier)

    insert_chain_event(
        db,
        event_type=ChainEventType.APPEAL_SETTLED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={
            "appeal_id": appeal.id,
            "result": payload.result,
            "resolution": payload.resolution,
            "appeal_type": appeal.appeal_type
        }
    )

    db.commit()
    db.refresh(appeal)
    return appeal


def _resolve_audit_appeal(db, task, appeal, result, manufacturer, supplier):
    """线上申诉结算，对应Fund.settleAppeal"""
    if result == 1:
        if appeal.appeal_type == AppealType.AUDIT_REJECT.value:
            if manufacturer and task.mfr_locked:
                manufacturer.balance += task.mfr_locked
                manufacturer.locked_balance -= task.mfr_locked
            if supplier and task.sup_locked:
                supplier.balance += task.sup_locked
                supplier.locked_balance -= task.sup_locked
            finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=False)
        else:
            compensation = task.sup_locked * SLASH_COMPENSATION_RATIO
            system_pool = task.sup_locked - compensation
            if manufacturer:
                manufacturer.balance += task.mfr_locked + compensation
                manufacturer.locked_balance -= task.mfr_locked
            admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
            if admin:
                admin.balance += system_pool
            if supplier:
                supplier.locked_balance -= task.sup_locked
            finalize_task(db, task, is_success=False, supplier_slash=True, manufacturer_slash=False)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.utcnow()

    elif result == 2:
        task.status = TaskStatus.PASS.value

    elif result == 3:
        if supplier and task.sup_locked:
            supplier.balance += task.sup_locked + task.mfr_locked
            supplier.locked_balance -= task.sup_locked
        if manufacturer and task.mfr_locked:
            manufacturer.locked_balance -= task.mfr_locked
        if manufacturer:
            manufacturer.claim_count += 1
        finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=True)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.utcnow()


def _resolve_field_appeal(db, task, appeal, result, manufacturer, supplier):
    """现场申诉结算，对应Fund.settleFieldDispute"""
    if result == 1:
        compensation = task.sup_locked * 0.30
        if manufacturer:
            manufacturer.balance += task.mfr_locked
            manufacturer.locked_balance -= task.mfr_locked
            if task.sup_locked >= compensation:
                manufacturer.balance += compensation
        if supplier and task.sup_locked:
            supplier.balance += max(0, task.sup_locked - compensation)
            supplier.locked_balance -= task.sup_locked

        if task.extension_deposit > 0:
            admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
            if admin:
                admin.balance += task.extension_deposit

        finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=False)

    elif result == 2:
        if manufacturer:
            manufacturer.balance += task.mfr_locked
            manufacturer.locked_balance -= task.mfr_locked
            compensation = task.sup_locked * SLASH_COMPENSATION_RATIO
            manufacturer.balance += compensation
        admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if admin and task.sup_locked:
            system_pool = task.sup_locked - (task.sup_locked * SLASH_COMPENSATION_RATIO)
            admin.balance += system_pool
        if supplier and task.sup_locked:
            supplier.locked_balance -= task.sup_locked

        if task.extension_deposit > 0:
            if admin:
                admin.balance += task.extension_deposit

        finalize_task(db, task, is_success=False, supplier_slash=True, manufacturer_slash=False)

    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()


@router.post("/{appeal_id}/evidence")
def upload_appeal_evidence(
    appeal_id: int,
    payload: __import__('schemas').UploadAppealEvidencePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    上传申诉证据，与Dispute.uploadAppealEvidence对齐
    """
    appeal = db.query(Appeal).filter(Appeal.id == appeal_id).first()
    if not appeal:
        raise HTTPException(404, "申诉不存在")

    task = db.query(AuditTask).filter(AuditTask.id == appeal.task_id).first()
    if not task:
        raise HTTPException(404, "关联项目不存在")

    is_initiator = current_user.id in [task.manufacturer_id, task.supplier_id]
    is_arbitrator = appeal.arbitrator_id == current_user.id
    is_admin = current_user.role == UserRole.ADMIN.value

    if not (is_initiator or is_arbitrator or is_admin):
        raise HTTPException(403, "无权上传申诉证据")

    appeal.evidence_hash = payload.evidence_hash
    db.commit()
    db.refresh(appeal)

    insert_chain_event(
        db,
        event_type=ChainEventType.APPEAL_EVIDENCE_UPLOADED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"appeal_id": appeal.id, "evidence_hash": payload.evidence_hash}
    )

    return appeal
