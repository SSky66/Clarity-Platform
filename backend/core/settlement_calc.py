"""
信誉结算与项目终态收口工具
与 Identity.settleProjectReputation / Fund._finalize 对齐
"""
import os
from sqlalchemy.orm import Session

from models import (
    User, AuditTask, UserRole, ChainEvent, ChainEventType,
    BASE_REPUTATION, COMPLETION_BONUS, SLASH_PENALTY,
    INSURANCE_FEE,
)
from core.chain_utils import insert_chain_event, get_contract_addresses, get_admin_sign_info

CHAIN_SYNC_ENABLED = os.getenv("CHAIN_SYNC_ENABLED", "false").lower() == "true"


def _settle_reputation(
    db: Session,
    task: AuditTask,
    is_success: bool,
    supplier_slash: bool,
    manufacturer_slash: bool
):
    """
    规则：
      is_success=True: 双方各+1
      supplier_slash=True: 供应商-10
      manufacturer_slash=True: 制造商-10
    """
    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    if is_success:
        if manufacturer:
            manufacturer.success_count += 1
            manufacturer.reputation_score = min(100, manufacturer.reputation_score + COMPLETION_BONUS)
        if supplier:
            supplier.success_count += 1
            supplier.reputation_score = min(100, supplier.reputation_score + COMPLETION_BONUS)

    if supplier_slash and supplier:
        supplier.slash_count += 1
        supplier.reputation_score = max(0, supplier.reputation_score - SLASH_PENALTY)

    if manufacturer_slash and manufacturer:
        manufacturer.slash_count += 1
        manufacturer.reputation_score = max(0, manufacturer.reputation_score - SLASH_PENALTY)

    db.commit()

    # 合约同步钩子：链上信誉结算
    if CHAIN_SYNC_ENABLED and supplier and manufacturer:
        try:
            from blockchain_client import settle_reputation_onchain
            contracts = get_contract_addresses(db)
            identity_contract = contracts.get("identity_contract")
            if identity_contract:
                admin, sign_user_id = get_admin_sign_info(db)
                if admin and sign_user_id:
                    result = settle_reputation_onchain(
                        identity_contract=identity_contract,
                        supplier_address=supplier.wallet_address,
                        manufacturer_address=manufacturer.wallet_address,
                        is_success=is_success,
                        supplier_slash=supplier_slash,
                        manufacturer_slash=manufacturer_slash,
                        caller_address=admin.wallet_address,
                        caller_sign_user_id=sign_user_id
                    )
                    if result.get("success"):
                        print(f"[CHAIN] 链上信誉结算成功: task={task.id}, tx={result.get('tx_hash')}")
                    else:
                        print(f"[CHAIN] 链上信誉结算失败: task={task.id}, error={result.get('error')}")
        except Exception as e:
            print(f"[CHAIN] 链上信誉结算异常: task={task.id}, error={e}")


def _update_claim_count_onchain(db: Session, manufacturer: User):
    """
    合约同步：更新制造商出险计数，对应Identity.updateClaimCount
    在SLASH反转（制造商担责）时调用
    """
    if not CHAIN_SYNC_ENABLED or not manufacturer or not manufacturer.wallet_address:
        return

    try:
        from blockchain_client import update_claim_count_onchain
        contracts = get_contract_addresses(db)
        identity_contract = contracts.get("identity_contract")
        if identity_contract:
            admin, sign_user_id = get_admin_sign_info(db)
            if admin and sign_user_id:
                result = update_claim_count_onchain(
                    identity_contract=identity_contract,
                    manufacturer_address=manufacturer.wallet_address,
                    caller_address=admin.wallet_address,
                    caller_sign_user_id=sign_user_id
                )
                if result.get("success"):
                    print(f"[CHAIN] 链上出险计数更新成功: user={manufacturer.id}, tx={result.get('tx_hash')}")
                else:
                    print(f"[CHAIN] 链上出险计数更新失败: user={manufacturer.id}, error={result.get('error')}")
    except Exception as e:
        print(f"[CHAIN] 链上出险计数更新异常: user={manufacturer.id}, error={e}")


def finalize_task(
    db: Session,
    task: AuditTask,
    is_success: bool,
    supplier_slash: bool,
    manufacturer_slash: bool
):
    """
    项目资金收口
    1. 信誉结算（含链上同步）
    2. 保险费释放（如果购买了）
    3. 清空锁定资金
    4. 制造商出险计数（链上同步，如适用）
    """
    # 信誉结算（内部已包含链上同步钩子）
    _settle_reputation(db, task, is_success, supplier_slash, manufacturer_slash)

    # 制造商出险计数（SLASH反转情况）
    if manufacturer_slash:
        manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
        if manufacturer:
            manufacturer.claim_count += 1
            db.commit()
            _update_claim_count_onchain(db, manufacturer)

    # 保险费释放给协会（平台）
    if task.insurance_purchased:
        admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if admin:
            admin.balance += INSURANCE_FEE

    # 清空锁定资金标记
    task.mfr_locked = 0
    task.sup_locked = 0

    insert_chain_event(
        db,
        event_type=ChainEventType.REPUTATION_FINALIZED.value,
        task_id=task.id,
        data_json={
            "is_success": is_success,
            "supplier_slash": supplier_slash,
            "manufacturer_slash": manufacturer_slash,
            "insurance_released": task.insurance_purchased,
            "chain_sync_enabled": CHAIN_SYNC_ENABLED
        }
    )

    db.commit()
