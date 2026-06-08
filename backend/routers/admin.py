"""
管理接口（ADMIN专用）
"""
from datetime import datetime, timedelta
from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    AuditTask, User, TaskStatus, UserRole, ChainEvent, ChainEventType,
    OnsiteRecord, OnsiteLocalStatus, Appeal, AppealStatus,
    PREPARE_TIMEOUT_SECONDS, APPEAL_WINDOW_SECONDS, ONSITE_TIMEOUT_SECONDS,
    RECTIFICATION_PERIOD_SECONDS, SLASH_COMPENSATION_RATIO,
    BASE_REPUTATION, COMPLETION_BONUS, SLASH_PENALTY,
    INSURANCE_FEE, get_db,
)
from schemas import TaskResponse
from core.deps import get_current_user
from core.chain_utils import insert_chain_event
from core.settlement_calc import finalize_task

router = APIRouter(prefix="/api", tags=["管理"])


@router.post("/tasks/process-timeouts")
def process_timeouts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    手动触发超时处理（生产环境应由定时任务自动执行）
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行")

    now = datetime.utcnow()
    processed = []

    # 1.UPLOADING超时
    uploading_tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.UPLOADING.value,
        AuditTask.first_prepared_at.isnot(None),
        AuditTask.mfr_prepared != AuditTask.sup_prepared
    ).all()

    for task in uploading_tasks:
        deadline = task.first_prepared_at + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)
        if now > deadline:
            if task.mfr_prepared and not task.sup_prepared:
                mfr = db.query(User).filter(User.id == task.manufacturer_id).first()
                if mfr:
                    mfr.balance += task.mfr_total_paid
                    mfr.locked_balance -= task.mfr_locked
                    mfr.total_staked -= task.mfr_total_paid
                task.mfr_locked = 0
                task.mfr_total_paid = 0
            elif task.sup_prepared and not task.mfr_prepared:
                sup = db.query(User).filter(User.id == task.supplier_id).first()
                if sup:
                    sup.balance += task.sup_total_paid
                    sup.locked_balance -= task.sup_locked
                    sup.total_staked -= task.sup_total_paid
                task.sup_locked = 0
                task.sup_total_paid = 0

            task.status = TaskStatus.CANCELED.value
            processed.append({"task_id": task.id, "action": "uploading_timeout_canceled"})

    # 2.REJECT申诉期超时
    reject_tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.REJECT.value,
        AuditTask.appeal_deadline.isnot(None)
    ).all()

    for task in reject_tasks:
        if now > task.appeal_deadline:
            mfr = db.query(User).filter(User.id == task.manufacturer_id).first()
            sup = db.query(User).filter(User.id == task.supplier_id).first()
            if mfr and task.mfr_locked:
                mfr.balance += task.mfr_locked
                mfr.locked_balance -= task.mfr_locked
            if sup and task.sup_locked:
                sup.balance += task.sup_locked
                sup.locked_balance -= task.sup_locked

            finalize_task(db, task, False, False, False)
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = now
            processed.append({"task_id": task.id, "action": "reject_appeal_timeout_completed"})

    # 3.SLASH申诉期超时
    slash_tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.SLASH.value,
        AuditTask.appeal_deadline.isnot(None)
    ).all()

    for task in slash_tasks:
        if now > task.appeal_deadline:
            mfr = db.query(User).filter(User.id == task.manufacturer_id).first()
            sup = db.query(User).filter(User.id == task.supplier_id).first()

            compensation = task.sup_locked * SLASH_COMPENSATION_RATIO
            system_pool = task.sup_locked - compensation

            if mfr:
                mfr.balance += task.mfr_locked + compensation
                mfr.locked_balance -= task.mfr_locked
            admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
            if admin:
                admin.balance += system_pool
            if sup:
                sup.locked_balance -= task.sup_locked

            finalize_task(db, task, False, True, False)
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = now
            processed.append({"task_id": task.id, "action": "slash_appeal_timeout_completed"})

    # 4.ACCEPTANCE现场验收超时
    acceptance_tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.ACCEPTANCE.value,
        AuditTask.supplier_submitted == True,
        AuditTask.onsite_deadline.isnot(None)
    ).all()

    for task in acceptance_tasks:
        if now > task.onsite_deadline and (not task.mfr_confirmed or task.mfr_satisfied):
            mfr = db.query(User).filter(User.id == task.manufacturer_id).first()
            sup = db.query(User).filter(User.id == task.supplier_id).first()

            if mfr and task.mfr_locked:
                mfr.balance += task.mfr_locked
                mfr.locked_balance -= task.mfr_locked
            if sup and task.sup_locked:
                sup.balance += task.sup_locked
                sup.locked_balance -= task.sup_locked
            if task.extension_deposit > 0 and sup:
                sup.balance += task.extension_deposit

            finalize_task(db, task, True, False, False)
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = now
            processed.append({"task_id": task.id, "action": "onsite_timeout_auto_pass"})

    # 5.RECTIFICATION整改期超时
    rect_tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.RECTIFICATION.value,
        AuditTask.rectification_deadline.isnot(None)
    ).all()

    for task in rect_tasks:
        if now > task.rectification_deadline:
            task.status = TaskStatus.DISPUTED_FIELD.value

            insert_chain_event(
                db,
                event_type=ChainEventType.FIELD_DISPUTE_ESCALATED.value,
                task_id=task.id,
                data_json={"reason": "rectification_timeout_escalated", "auto_processed": True}
            )

            processed.append({"task_id": task.id, "action": "rectification_timeout_escalated"})

    db.commit()
    return {"processed": processed, "count": len(processed)}


@router.post("/tasks/{task_id}/emergency-stop")
def emergency_stop(
    task_id: int,
    reason: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    紧急停止项目，与Fund.emergencyStop对齐
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行紧急停止")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status in [TaskStatus.COMPLETED.value, TaskStatus.CANCELED.value]:
        raise HTTPException(400, "项目已终态，不可停止")

    task.status = TaskStatus.CANCELED.value

    insert_chain_event(
        db,
        event_type="EmergencyStop",
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"reason": reason}
    )

    db.commit()
    return {"message": "项目已紧急停止", "task_id": task_id, "reason": reason}


@router.post("/tasks/{task_id}/emergency-withdraw")
def emergency_withdraw(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    紧急撤回锁定资金，与Fund.emergencyWithdraw对齐
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行紧急撤回")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    if task.mfr_locked > 0 and manufacturer:
        manufacturer.balance += task.mfr_locked
        manufacturer.locked_balance -= task.mfr_locked
        task.mfr_locked = 0

    if task.sup_locked > 0 and supplier:
        supplier.balance += task.sup_locked
        supplier.locked_balance -= task.sup_locked
        task.sup_locked = 0

    if task.extension_deposit > 0 and supplier:
        supplier.balance += task.extension_deposit
        task.extension_deposit = 0

    db.commit()
    return {
        "message": "紧急撤回完成",
        "task_id": task_id,
        "mfr_refunded": float(task.mfr_locked) if manufacturer else 0,
        "sup_refunded": float(task.sup_locked) if supplier else 0
    }


# 合约部署管理接口

@router.post("/admin/deploy-contract")
def admin_deploy_contract(
    contract_name: str,
    bytecode: str,
    abi_json: Optional[str] = None,
    constructor_params: Optional[List[Any]] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    通过WeBASE-Front部署智能合约上链
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可部署合约")

    import json
    from blockchain_client import deploy_contract, CONTRACT_ABIS

    if abi_json:
        abi = json.loads(abi_json)
    else:
        abi = CONTRACT_ABIS.get(contract_name.lower())
        if not abi:
            raise HTTPException(400, f"未知合约: {contract_name}，请提供 abi_json")

    if constructor_params is None:
        constructor_params = []
        if contract_name.lower() == "fund":
            constructor_params = [current_user.wallet_address]

    result = deploy_contract(
        contract_name=contract_name,
        abi=abi,
        bytecode=bytecode,
        constructor_params=constructor_params,
        from_address=current_user.wallet_address,
        sign_user_id=f"clarity_admin_{current_user.account}"
    )

    if result["success"] and result["contract_address"]:
        key_map = {
            "identity": "identity_contract",
            "fund": "fund_contract",
            "audit": "audit_contract",
            "dispute": "appeal_contract",
            "evidence": "evidence_contract",
            "settlement": "settlement_contract",
        }
        config_key = key_map.get(contract_name.lower())
        if config_key:
            from models import ContractConfig
            config = db.query(ContractConfig).filter(ContractConfig.config_key == config_key).first()
            if config:
                config.config_value = result["contract_address"]
            else:
                config = ContractConfig(config_key=config_key, config_value=result["contract_address"])
                db.add(config)
            db.commit()

        insert_chain_event(
            db,
            event_type="ContractDeployed",
            sender_address=current_user.wallet_address,
            data_json={
                "contract_name": contract_name,
                "contract_address": result["contract_address"],
                "tx_hash": result["tx_hash"]
            }
        )

    return result


@router.post("/admin/setup-contract-links")
def admin_setup_contract_links(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    一键配置所有合约间的地址关联
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可配置")

    from models import ContractConfig
    configs = db.query(ContractConfig).all()
    config = {}
    for c in configs:
        config[c.config_key] = c.config_value

    required = ["identity_contract", "fund_contract", "audit_contract",
                "appeal_contract", "evidence_contract"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise HTTPException(400, f"缺少合约地址: {missing}")

    # 返回配置计划，实际链上调用需要前端或后续实现
    return {
        "message": "合约关联配置计划已生成",
        "contracts": config,
        "note": "请通过 chain.py 中的工具函数执行实际链上调用"
    }
