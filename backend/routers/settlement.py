"""
阶段4: 线上申诉后处理（终态结算）
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    User, AuditTask, UserRole, TaskStatus, get_db,
    SLASH_COMPENSATION_RATIO,
)
from schemas import TaskResponse
from core.deps import get_current_user
from core.chain_utils import insert_chain_event
from core.settlement import finalize_task

router = APIRouter(prefix="/api/tasks", tags=["终态结算"])


@router.post("/{task_id}/complete-reject", response_model=TaskResponse)
def complete_reject(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    REJECT申诉期结束后，任何人可调用完成
    与Fund.completeReject对齐：双方退还锁定资金
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.REJECT.value:
        raise HTTPException(400, "项目状态非REJECT")
    if not task.appeal_deadline or datetime.utcnow() <= task.appeal_deadline:
        raise HTTPException(400, "申诉期尚未结束")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()
    if manufacturer and task.mfr_locked:
        manufacturer.balance += task.mfr_locked
        manufacturer.locked_balance -= task.mfr_locked
    if supplier and task.sup_locked:
        supplier.balance += task.sup_locked
        supplier.locked_balance -= task.sup_locked

    finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=False)
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/complete-slash", response_model=TaskResponse)
def complete_slash(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    SLASH申诉期结束后，任何人可调用完成
    与Fund.completeSlash对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.SLASH.value:
        raise HTTPException(400, "项目状态非SLASH")
    if not task.appeal_deadline or datetime.utcnow() <= task.appeal_deadline:
        raise HTTPException(400, "申诉期尚未结束")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

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

    db.commit()
    db.refresh(task)
    return task
