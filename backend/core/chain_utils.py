import secrets
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from models import ChainEvent, ContractConfig


def generate_tx_hash() -> str:
    """生成模拟的0x+64位十六进制交易哈希"""
    return "0x" + secrets.token_hex(32)


def insert_chain_event(
    db: Session,
    event_type: str,
    task_id: Optional[int] = None,
    sender_address: Optional[str] = None,
    data_json: Optional[dict] = None
) -> ChainEvent:
    """插入链上事件记录（Mock阶段用，后续接入真实交易时替换）"""
    event = ChainEvent(
        tx_hash=generate_tx_hash(),
        block_height=None,
        event_type=event_type,
        task_id=task_id,
        sender_address=sender_address,
        data_json=data_json,
        status="CONFIRMED"
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_contract_addresses(db: Session) -> dict:
    """从数据库获取已配置的合约地址"""
    configs = db.query(ContractConfig).all()
    result = {}
    for c in configs:
        result[c.config_key] = c.config_value
    return result


def get_admin_sign_info(db: Session) -> tuple:
    """
    获取admin的链上签名信息
    返回: (admin_user, sign_user_id) 或 (None, None)
    """
    from models import User, UserRole
    admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
    if not admin or not admin.wallet_address:
        return None, None
    sign_user_id = f"clarity_admin_{admin.account}"
    return admin, sign_user_id
