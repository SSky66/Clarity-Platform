"""
链上事件查询接口
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import ChainEvent, get_db
from schemas import ChainEventResponse, ChainStatsResponse
from core.deps import get_current_user
from core.chain_utils import get_contract_addresses, get_admin_sign_info
from chain import get_chain_stats

router = APIRouter(prefix="/api", tags=["链上事件"])


@router.get("/chain-events", response_model=list[ChainEventResponse])
def list_chain_events(
    task_id: Optional[int] = None,
    event_type: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """链上查询页面：查询链上事件列表"""
    query = db.query(ChainEvent)
    if task_id:
        query = query.filter(ChainEvent.task_id == task_id)
    if event_type:
        query = query.filter(ChainEvent.event_type == event_type)

    return query.order_by(ChainEvent.created_at.desc()).offset((page-1)*limit).limit(limit).all()


@router.get("/chain/health")
def chain_health():
    """检查 WeBASE-Front 连通性"""
    stats = get_chain_stats()
    return {"connected": stats.get("connected", False), "error": stats.get("error")}


@router.get("/chain/stats", response_model=ChainStatsResponse)
def chain_stats(db: Session = Depends(get_db)):
    """获取链上统计信息"""
    stats = get_chain_stats()
    total_records = db.query(ChainEvent).count()
    return {
        "block_height": stats.get("block_height"),
        "total_transactions": total_records,
        "active_nodes": stats.get("active_nodes"),
        "total_onchain_records": total_records,
        "connected": stats["connected"],
        "error": stats.get("error")
    }


@router.get("/chain/events", response_model=list[ChainEventResponse])
def list_chain_events_v2(
    task_id: Optional[int] = None,
    event_type: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询链上事件列表（支持分页和筛选）"""
    query = db.query(ChainEvent)
    if task_id:
        query = query.filter(ChainEvent.task_id == task_id)
    if event_type:
        query = query.filter(ChainEvent.event_type == event_type)

    return query.order_by(ChainEvent.created_at.desc()).offset((page - 1) * limit).limit(limit).all()


@router.get("/chain/events/{tx_hash}", response_model=ChainEventResponse)
def get_chain_event_detail(
    tx_hash: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """根据交易哈希查询单条链上事件详情"""
    event = db.query(ChainEvent).filter(ChainEvent.tx_hash == tx_hash).first()
    if not event:
        raise HTTPException(404, "交易不存在")
    return event
