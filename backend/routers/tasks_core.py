"""
项目核心操作：创建、查询、接单、文件上传
"""
import os
import shutil
import uuid
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from models import (
    User, AuditTask, UserRole, TaskStatus, ChainEventType, get_db,
)
from schemas import TaskCreate, TaskResponse
from core.deps import get_current_user
from core.chain_utils import insert_chain_event

router = APIRouter(prefix="/api/tasks", tags=["项目核心"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _attach_task_reputation(db: Session, task: AuditTask):
    """为任务附加双方信誉积分和企业名称"""
    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()
    task.manufacturer_reputation = manufacturer.reputation_score if manufacturer else None
    task.supplier_reputation = supplier.reputation_score if supplier else None
    task.manufacturer_name = manufacturer.display_name if manufacturer else None
    task.supplier_name = supplier.display_name if supplier else None


@router.post("", response_model=TaskResponse)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """制造商创建验收需求"""
    if current_user.role != UserRole.MANUFACTURER.value:
        raise HTTPException(status_code=403, detail="仅制造商可创建项目")

    pseudo_hash = '0x' + secrets.token_hex(32)

    task = AuditTask(
        task_hash=pseudo_hash,
        task_name=payload.task_name,
        description=payload.description,
        manufacturer_id=current_user.id,
        target_fnr=payload.target_fnr,
        target_fpr=payload.target_fpr,
        target_map=payload.target_map,
        target_f1=payload.target_f1,
        target_latency=payload.target_latency,
        conf_threshold=payload.conf_threshold,
        iou_threshold=payload.iou_threshold,
        status=TaskStatus.PENDING.value,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.PROJECT_CREATED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"task_hash": pseudo_hash}
    )

    return task


@router.get("/stats")
def task_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """首页统计数字"""
    query = db.query(AuditTask)
    if current_user.role == UserRole.MANUFACTURER.value:
        query = query.filter(AuditTask.manufacturer_id == current_user.id)
    elif current_user.role == UserRole.SUPPLIER.value:
        query = query.filter(AuditTask.supplier_id == current_user.id)

    return {
        "total": query.count(),
        "pending": query.filter(AuditTask.status == TaskStatus.PENDING.value).count(),
        "uploading": query.filter(AuditTask.status == TaskStatus.UPLOADING.value).count(),
        "prepared": query.filter(AuditTask.status == TaskStatus.PREPARED.value).count(),
        "auditing": query.filter(AuditTask.status == TaskStatus.AUDITING.value).count(),
        "pass": query.filter(AuditTask.status == TaskStatus.PASS.value).count(),
        "reject": query.filter(AuditTask.status == TaskStatus.REJECT.value).count(),
        "slash": query.filter(AuditTask.status == TaskStatus.SLASH.value).count(),
        "acceptance": query.filter(AuditTask.status == TaskStatus.ACCEPTANCE.value).count(),
        "rectification": query.filter(AuditTask.status == TaskStatus.RECTIFICATION.value).count(),
        "disputed_audit": query.filter(AuditTask.status == TaskStatus.DISPUTED_AUDIT.value).count(),
        "disputed_field": query.filter(AuditTask.status == TaskStatus.DISPUTED_FIELD.value).count(),
        "arbitrating": query.filter(AuditTask.status == TaskStatus.ARBITRATING.value).count(),
        "completed": query.filter(AuditTask.status == TaskStatus.COMPLETED.value).count(),
        "canceled": query.filter(AuditTask.status == TaskStatus.CANCELED.value).count(),
    }


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    查询项目列表（按角色自动过滤）
    制造商：只看自己发布的
    供应商：只看自己接入的
    审计节点：看全部（可传status过滤）
    """
    query = db.query(AuditTask)

    if current_user.role == UserRole.MANUFACTURER.value:
        query = query.filter(AuditTask.manufacturer_id == current_user.id)
    elif current_user.role == UserRole.SUPPLIER.value:
        query = query.filter(AuditTask.supplier_id == current_user.id)

    if status:
        query = query.filter(AuditTask.status == status)

    tasks = query.order_by(AuditTask.created_at.desc()).all()

    for task in tasks:
        _attach_task_reputation(db, task)

    return tasks


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询单个项目详情"""
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    _attach_task_reputation(db, task)
    return task


# 供应商接单

@router.put("/{task_id}/accept", response_model=TaskResponse)
def accept_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """供应商接单：PENDING → UPLOADING"""
    if current_user.role != UserRole.SUPPLIER.value:
        raise HTTPException(403, "仅供应商可接单")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.PENDING.value:
        raise HTTPException(400, "项目状态不允许接单")
    if task.supplier_id is not None:
        raise HTTPException(400, "项目已被其他供应商接单")

    task.supplier_id = current_user.id
    task.status = TaskStatus.UPLOADING.value
    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.PROJECT_ACCEPTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"supplier_id": current_user.id}
    )

    return task


@router.put("/accept-by-hash", response_model=TaskResponse)
def accept_task_by_hash(
    task_hash: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """供应商通过 task_hash 接单"""
    if current_user.role != UserRole.SUPPLIER.value:
        raise HTTPException(403, "仅供应商可接单")

    task = db.query(AuditTask).filter(AuditTask.task_hash == task_hash).first()
    if not task:
        raise HTTPException(404, "项目不存在，请核对项目哈希")
    if task.status != TaskStatus.PENDING.value:
        raise HTTPException(400, "项目状态不允许接单")
    if task.supplier_id is not None:
        raise HTTPException(400, "项目已被其他供应商接单")

    task.supplier_id = current_user.id
    task.status = TaskStatus.UPLOADING.value
    db.commit()
    db.refresh(task)

    insert_chain_event(
        db,
        event_type=ChainEventType.PROJECT_ACCEPTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"supplier_id": current_user.id}
    )

    return task


# 文件上传（Mock IPFS）

@router.post("/{task_id}/upload-dataset")
def upload_dataset(
    task_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """制造商上传测试集：存本地，生成伪IPFS Hash"""
    if current_user.role != UserRole.MANUFACTURER.value:
        raise HTTPException(403, "仅制造商可上传数据集")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task or task.manufacturer_id != current_user.id:
        raise HTTPException(404, "项目不存在或无权限")
    if task.status != TaskStatus.UPLOADING.value:
        raise HTTPException(400, "当前状态不允许上传")

    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    filename = f"dataset_{task_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_hash = f"sha256://{__import__('hashlib').sha256(filename.encode()).hexdigest()[:16]}"
    task.dataset_ipfs_hash = file_hash
    db.commit()

    insert_chain_event(
        db,
        event_type=ChainEventType.DATA_UPLOADED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"type": "dataset", "hash": fake_hash}
    )

    return {"ipfs_hash": fake_hash, "filename": file.filename, "type": "dataset"}


@router.post("/{task_id}/upload-model")
def upload_model(
    task_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """供应商上传TorchScript模型"""
    if current_user.role != UserRole.SUPPLIER.value:
        raise HTTPException(403, "仅供应商可上传模型")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task or task.supplier_id != current_user.id:
        raise HTTPException(404, "项目不存在或无权限")
    if task.status != TaskStatus.UPLOADING.value:
        raise HTTPException(400, "当前状态不允许上传")

    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    filename = f"model_{task_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_hash = f"sha256://{__import__('hashlib').sha256(filename.encode()).hexdigest()[:16]}"
    history = task.model_hash_history or []
    from datetime import datetime
    history.append({
        "hash": file_hash,
        "uploaded_at": datetime.utcnow().isoformat(),
        "filename": file.filename
    })
    task.model_hash_history = history
    db.commit()

    insert_chain_event(
        db,
        event_type=ChainEventType.MODEL_UPLOADED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"type": "model", "hash": fake_hash}
    )

    return {"ipfs_hash": fake_hash, "filename": file.filename, "type": "model"}
