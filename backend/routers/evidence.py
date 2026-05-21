"""
存证查询与上传接口，与Evidence.sol对齐
"""
from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from datetime import datetime

from models import (
    AuditTask, TaskReport, OnsiteRecord, Appeal, UserRole, get_db,
    OnsiteLocalStatus, ChainEventType, AppealType, AppealStatus,
)
from core.deps import get_current_user
from core.chain_utils import insert_chain_event

router = APIRouter(prefix="/api/tasks", tags=["存证"])


@router.get("/{task_id}/evidence/data")
def get_evidence_data(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询测试集存证，对应Evidence.getDataHashes"""
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    return {
        "test_set_hash": task.dataset_ipfs_hash,
        "control_set_hash": task.control_set_ipfs_hash,
        "metadata_hash": task.metadata_ipfs_hash,
    }


@router.get("/{task_id}/evidence/model")
def get_evidence_model(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询模型存证 - 对应 Evidence.getModelHashes"""
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    latest = task.model_hash_history[-1] if task.model_hash_history else None
    return {
        "model_hash": latest.get("hash") if latest else None,
        "model_desc_hash": latest.get("desc_hash") if latest else None,
        "history": task.model_hash_history or []
    }


@router.get("/{task_id}/evidence/audit")
def get_evidence_audit(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询审计报告存证，对应Evidence.getAuditMetrics与getAuditResult"""
    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    if not report:
        raise HTTPException(404, "审计报告不存在")
    return {
        "report_hash": report.report_hash,
        "miss_rate": report.miss_rate,
        "false_kill_rate": report.false_kill_rate,
        "concentration_ratio": report.concentration_ratio,
        "avg_fp": report.avg_fp,
        "arrogance": report.arrogance,
        "map": report.map,
        "f1": report.f1,
        "verdict": report.verdict,
        "miss_threshold": report.miss_threshold,
        "false_kill_threshold": report.false_kill_threshold,
    }


@router.get("/{task_id}/evidence/onsite")
def get_evidence_onsite(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询现场验收存证，对应Evidence.getOnsiteConfirmation"""
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    return {
        "mfr_satisfied": task.mfr_satisfied,
        "sup_satisfied": task.sup_satisfied,
        "mfr_measured_map": onsite.mfr_measured_map if onsite else None,
        "sup_measured_map": onsite.sup_measured_map if onsite else None,
        "mfr_evidence_hash": onsite.mfr_evidence_hash if onsite else None,
        "sup_evidence_hash": onsite.sup_evidence_hash if onsite else None,
        "local_status": onsite.local_status if onsite else None,
        "confirm_time": onsite.confirm_time.isoformat() if onsite and onsite.confirm_time else None,
    }


@router.get("/{task_id}/evidence/appeal")
def get_evidence_appeal(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询申诉证据存证，对应Evidence.getAppealEvidence"""
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    appeal = db.query(Appeal).filter(Appeal.task_id == task_id).order_by(Appeal.created_at.desc()).first()
    return {
        "evidence_hash": appeal.evidence_hash if appeal else None,
        "appeal_type": appeal.appeal_type if appeal else None,
        "reason": appeal.reason if appeal else None,
        "created_at": appeal.created_at.isoformat() if appeal and appeal.created_at else None,
    }


@router.get("/{task_id}/evidence/complete")
def is_evidence_complete(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询证据是否完整 - 对应 Evidence.isEvidenceComplete"""
    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    return {"complete": report is not None}


# 存证上传接口

@router.post("/{task_id}/evidence/onsite")
def upload_onsite_evidence(
    task_id: int,
    confirm_hash: str = Form(...),
    mfr_satisfied: bool = Form(...),
    sup_satisfied: bool = Form(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    上传现场验收确认存证，与Evidence.uploadOnsiteConfirmation对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    is_party = current_user.id in [task.manufacturer_id, task.supplier_id]
    is_admin = current_user.role == UserRole.ADMIN.value
    if not is_party and not is_admin:
        raise HTTPException(403, "无权上传现场验收存证")

    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    if not onsite:
        onsite = OnsiteRecord(task_id=task_id)
        db.add(onsite)

    onsite.confirm_hash = confirm_hash
    onsite.mfr_satisfied = mfr_satisfied
    onsite.sup_satisfied = sup_satisfied
    onsite.local_status = OnsiteLocalStatus.CONFIRMED.value
    onsite.confirm_time = datetime.utcnow()

    task.mfr_satisfied = mfr_satisfied
    task.sup_satisfied = sup_satisfied

    db.commit()

    insert_chain_event(
        db,
        event_type=ChainEventType.ONSITE_CONFIRMED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"confirm_hash": confirm_hash, "mfr_satisfied": mfr_satisfied, "sup_satisfied": sup_satisfied}
    )

    return {"message": "现场验收存证已上传", "confirm_hash": confirm_hash}


@router.post("/{task_id}/evidence/appeal")
def upload_appeal_evidence(
    task_id: int,
    evidence_hash: str = Form(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    上传申诉证据存证，与Evidence.uploadAppealEvidence/Dispute.uploadAppealEvidence对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    appeal = db.query(Appeal).filter(Appeal.task_id == task_id).order_by(Appeal.created_at.desc()).first()

    is_initiator = current_user.id in [task.manufacturer_id, task.supplier_id]
    is_arbitrator = appeal and appeal.arbitrator_id == current_user.id
    is_admin = current_user.role == UserRole.ADMIN.value

    if not (is_initiator or is_arbitrator or is_admin):
        raise HTTPException(403, "无权上传申诉证据")

    if appeal:
        appeal.evidence_hash = evidence_hash
    else:
        appeal = Appeal(
            task_id=task_id,
            appeal_type=AppealType.FIELD_DOWNGRADE.value,
            reason="现场争议证据上传（自动创建）",
            evidence_hash=evidence_hash,
            status=AppealStatus.PENDING.value
        )
        db.add(appeal)

    db.commit()

    insert_chain_event(
        db,
        event_type=ChainEventType.APPEAL_EVIDENCE_UPLOADED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"evidence_hash": evidence_hash, "appeal_id": appeal.id if appeal else None}
    )

    return {"message": "申诉证据已上传", "evidence_hash": evidence_hash}
