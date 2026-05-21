"""
阶段2: 准备与质押（与Fund.sol对齐）
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    User, AuditTask, UserRole, TaskStatus, get_db,
    BASE_DEPOSIT, AUDIT_FEE, INSURANCE_FEE,
    PREPARE_TIMEOUT_SECONDS,
)
from schemas import TaskResponse, ManufacturerPreparePayload, SupplierPreparePayload
from core.deps import get_current_user
from core.chain_utils import insert_chain_event

router = APIRouter(prefix="/api/tasks", tags=["准备与质押"])


def _compute_stake_ratio(user: User) -> float:
    """
    计算用户动态质押比例 - 与 Identity.getStakeRatio 对齐
    返回: 倍数（1.0 = 100%，1.5 = 150%，2.0 = 200%）
    """
    if user.is_blacklisted:
        return 2.0

    if user.reputation_score == 0 and user.success_count == 0 and not user.is_builtin:
        return 2.0

    if user.role in [UserRole.ADMIN.value, UserRole.AUDITOR.value]:
        return 1.0

    base_ratio = 1.5
    from models import BASE_REPUTATION
    rep_diff = user.reputation_score - BASE_REPUTATION

    if rep_diff > 0:
        reduction = (rep_diff // 10) * 0.03
        reduction = min(reduction, 0.5)
        base_ratio -= reduction
    elif rep_diff < 0:
        increase = (abs(rep_diff) // 10) * 0.03
        increase = min(increase, 0.5)
        base_ratio += increase

    return max(1.0, min(2.0, base_ratio))


@router.post("/{task_id}/manufacturer-prepare", response_model=TaskResponse)
def manufacturer_prepare(
    task_id: int,
    payload: ManufacturerPreparePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    制造商准备：质押 + 上传测试集信息
    """
    if current_user.role != UserRole.MANUFACTURER.value:
        raise HTTPException(403, "仅制造商可操作")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task or task.manufacturer_id != current_user.id:
        raise HTTPException(404, "项目不存在或无权限")
    if task.status != TaskStatus.UPLOADING.value:
        raise HTTPException(400, "当前状态不允许准备")
    if task.mfr_prepared:
        raise HTTPException(400, "制造商已准备")

    stake_ratio = _compute_stake_ratio(current_user)
    deposit_amount = round(BASE_DEPOSIT * stake_ratio)

    required = deposit_amount + AUDIT_FEE
    if payload.purchase_insurance:
        required += INSURANCE_FEE
        task.insurance_purchased = True

    if current_user.balance < required:
        raise HTTPException(400, f"余额不足，需要 {required}，当前余额：{current_user.balance}")

    current_user.balance -= required
    current_user.locked_balance += deposit_amount
    current_user.total_staked += required

    task.mfr_total_paid = required
    task.mfr_locked = deposit_amount
    task.mfr_prepared = True

    if payload.test_set_hash:
        task.dataset_ipfs_hash = payload.test_set_hash
    if payload.control_set_hash:
        task.control_set_ipfs_hash = payload.control_set_hash
    if payload.metadata_hash:
        task.metadata_ipfs_hash = payload.metadata_hash

    if not task.first_prepared_at:
        task.first_prepared_at = datetime.utcnow()

    if task.sup_prepared:
        task.status = TaskStatus.PREPARED.value
        task.prepared_at = datetime.utcnow()
    else:
        task.state_deadline = datetime.utcnow() + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)

    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type="ManufacturerPrepared",
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={
            "role": "manufacturer",
            "amount": float(required),
            "insurance": payload.purchase_insurance,
            "locked": float(deposit_amount),
            "stake_ratio": stake_ratio,
            "reputation_score": current_user.reputation_score
        }
    )

    return task


@router.post("/{task_id}/supplier-prepare", response_model=TaskResponse)
def supplier_prepare(
    task_id: int,
    payload: SupplierPreparePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    供应商准备：质押资金、模型推理包
    """
    if current_user.role != UserRole.SUPPLIER.value:
        raise HTTPException(403, "仅供应商可操作")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task or task.supplier_id != current_user.id:
        raise HTTPException(404, "项目不存在或无权限")
    if task.status != TaskStatus.UPLOADING.value:
        raise HTTPException(400, "当前状态不允许准备")
    if task.sup_prepared:
        raise HTTPException(400, "供应商已准备")

    stake_ratio = _compute_stake_ratio(current_user)
    deposit_amount = round(BASE_DEPOSIT * stake_ratio)

    required = deposit_amount + AUDIT_FEE
    if current_user.balance < required:
        raise HTTPException(400, f"余额不足，需要 {required}，当前余额：{current_user.balance}")

    current_user.balance -= required
    current_user.locked_balance += deposit_amount
    current_user.total_staked += required

    task.sup_total_paid = required
    task.sup_locked = deposit_amount
    task.sup_prepared = True

    if not task.model_hash_history:
        task.model_hash_history = []
    task.model_hash_history.append({
        "hash": payload.model_hash,
        "desc_hash": payload.model_desc_hash,
        "uploaded_at": datetime.utcnow().isoformat()
    })
    task.model_hash = payload.model_hash

    if not task.first_prepared_at:
        task.first_prepared_at = datetime.utcnow()

    if task.mfr_prepared:
        task.status = TaskStatus.PREPARED.value
        task.prepared_at = datetime.utcnow()
    else:
        task.state_deadline = datetime.utcnow() + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)

    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type="SupplierPrepared",
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={
            "role": "supplier",
            "amount": float(required),
            "locked": float(deposit_amount),
            "stake_ratio": stake_ratio,
            "reputation_score": current_user.reputation_score,
            "model_hash": payload.model_hash
        }
    )

    return task


@router.post("/{task_id}/withdraw-if-timeout", response_model=TaskResponse)
def withdraw_if_timeout(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    UPLOADING阶段3天超时后，任一方可调用退款
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.UPLOADING.value:
        raise HTTPException(400, "当前状态不允许退款")
    if not task.first_prepared_at:
        raise HTTPException(400, "尚未有人准备")

    deadline = task.first_prepared_at + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)
    if datetime.utcnow() <= deadline:
        raise HTTPException(400, f"超时未到达，将在 {deadline.isoformat()} 后可用")

    if task.mfr_prepared and not task.sup_prepared:
        if current_user.id != task.manufacturer_id:
            raise HTTPException(403, "仅制造商可退款")
        manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
        if manufacturer:
            manufacturer.balance += task.mfr_total_paid
            manufacturer.locked_balance -= task.mfr_locked
            manufacturer.total_staked -= task.mfr_total_paid
        task.mfr_locked = 0
        task.mfr_total_paid = 0

    elif task.sup_prepared and not task.mfr_prepared:
        if current_user.id != task.supplier_id:
            raise HTTPException(403, "仅供应商可退款")
        supplier = db.query(User).filter(User.id == task.supplier_id).first()
        if supplier:
            supplier.balance += task.sup_total_paid
            supplier.locked_balance -= task.sup_locked
            supplier.total_staked -= task.sup_total_paid
        task.sup_locked = 0
        task.sup_total_paid = 0

    else:
        raise HTTPException(400, "无效的准备状态")

    task.status = TaskStatus.CANCELED.value
    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type="Timeout",
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"reason": "prepare_timeout", "refund_to": current_user.role}
    )

    return task
