"""
定时任务模块，处理所有超时场景
与Fund.sol中的超时机制对齐：
  1.UPLOADING阶段3天超时自动取消
  2.REJECT/SLASH申诉期3天超时自动完成
  3.ACCEPTANCE现场验收72h超时自动通过
  4.RECTIFICATION整改期7天超时自动升级现场申诉

生产环境：使用APScheduler或Celery Beat
开发环境：提供手动触发接口与简单的后台线程
"""

import threading
import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from models import (
    AuditTask, User, TaskStatus, UserRole, ChainEvent, ChainEventType,
    OnsiteRecord, OnsiteLocalStatus,
    PREPARE_TIMEOUT_SECONDS, APPEAL_WINDOW_SECONDS, ONSITE_TIMEOUT_SECONDS,
    RECTIFICATION_PERIOD_SECONDS, SLASH_COMPENSATION_RATIO,
    BASE_REPUTATION, COMPLETION_BONUS, SLASH_PENALTY,
    INSURANCE_FEE, get_db, SessionLocal,
)


# 信誉结算工具（与main.py _finalize_task对齐）

def _settle_reputation(db: Session, task: AuditTask, is_success: bool, supplier_slash: bool, manufacturer_slash: bool):
    """
    项目终态信誉结算，与Identity.settleProjectReputation对齐
    规则：
    1.is_success=True: 双方各+1
    2.supplier_slash=True: 供应商-10
    3.manufacturer_slash=True: 制造-10
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
        # 注意：claim_count只在SLASH反转（制造商担责）时通过updateClaimCount单独更新
        # 不在_settle_reputation中统一处理，避免重复累加


def _finalize_task(db: Session, task: AuditTask, is_success: bool, supplier_slash: bool, manufacturer_slash: bool):
    """
    项目终态收口，与Fund._finalize对齐
    1.信誉结算
    2.保险费释放（如果购买了）
    3.清空锁定资金
    4.记录ReputationFinalized事件
    """
    # 信誉结算
    _settle_reputation(db, task, is_success, supplier_slash, manufacturer_slash)

    # 保险费释放给协会（平台/admin账户）
    if task.insurance_purchased:
        admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if admin:
            admin.balance += INSURANCE_FEE

    # 清空锁定资金标记
    task.mfr_locked = 0
    task.sup_locked = 0

    # 记录链上事件
    event = ChainEvent(
        tx_hash=_generate_tx_hash(),
        event_type=ChainEventType.REPUTATION_FINALIZED.value,
        task_id=task.id,
        data_json={
            "is_success": is_success,
            "supplier_slash": supplier_slash,
            "manufacturer_slash": manufacturer_slash,
            "insurance_released": task.insurance_purchased,
            "auto_processed": True
        }
    )
    db.add(event)


# 超时处理核心逻辑

def process_all_timeouts(db: Session) -> list:
    """
    处理所有超时任务
    返回处理记录列表
    """
    now = datetime.utcnow()
    processed = []

    # 1.UPLOADING阶段超时（3天）
    _process_uploading_timeouts(db, now, processed)

    # 2.REJECT申诉期超时（3天）
    _process_reject_timeouts(db, now, processed)

    # 3.SLASH申诉期超时（3天）
    _process_slash_timeouts(db, now, processed)

    # 4.ACCEPTANCE现场验收超时（72h）
    _process_onsite_timeouts(db, now, processed)

    # 5.RECTIFICATION整改期超时（7天）
    _process_rectification_timeouts(db, now, processed)

    db.commit()
    return processed


def _process_uploading_timeouts(db: Session, now: datetime, processed: list):
    """UPLOADING阶段：一方准备，另一方3天内未响应 → 退款并取消"""
    from models import ChainEvent, ChainEventType

    tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.UPLOADING.value,
        AuditTask.first_prepared_at.isnot(None),
    ).all()

    for task in tasks:
        # 只有一方准备才需要处理超时
        if task.mfr_prepared and task.sup_prepared:
            continue
        if not task.mfr_prepared and not task.sup_prepared:
            continue

        deadline = task.first_prepared_at + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)
        if now <= deadline:
            continue

        # 超时：退款给已准备的一方
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

        # 记录链上事件
        event = ChainEvent(
            tx_hash=_generate_tx_hash(),
            event_type=ChainEventType.TIMEOUT.value,
            task_id=task.id,
            data_json={"reason": "prepare_timeout", "auto_processed": True}
        )
        db.add(event)

        processed.append({
            "task_id": task.id,
            "task_hash": task.task_hash,
            "action": "uploading_timeout_canceled",
            "deadline": deadline.isoformat()
        })


def _process_reject_timeouts(db: Session, now: datetime, processed: list):
    """REJECT 申诉期超时：双方退还锁定资金，项目完成"""
    tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.REJECT.value,
        AuditTask.appeal_deadline.isnot(None)
    ).all()

    for task in tasks:
        if now <= task.appeal_deadline:
            continue

        mfr = db.query(User).filter(User.id == task.manufacturer_id).first()
        sup = db.query(User).filter(User.id == task.supplier_id).first()

        if mfr and task.mfr_locked:
            mfr.balance += task.mfr_locked
            mfr.locked_balance -= task.mfr_locked
        if sup and task.sup_locked:
            sup.balance += task.sup_locked
            sup.locked_balance -= task.sup_locked

        # 使用_finalize_task统一收口（REJECT不算成功也不算作弊）
        _finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=False)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = now

        event = ChainEvent(
            tx_hash=_generate_tx_hash(),
            event_type=ChainEventType.TIMEOUT.value,
            task_id=task.id,
            data_json={"reason": "reject_appeal_timeout", "auto_processed": True}
        )
        db.add(event)

        processed.append({
            "task_id": task.id,
            "task_hash": task.task_hash,
            "action": "reject_appeal_timeout_completed"
        })


def _process_slash_timeouts(db: Session, now: datetime, processed: list):
    """SLASH申诉期超时：制造商拿回全部+10%补偿，供应商-10信誉"""
    tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.SLASH.value,
        AuditTask.appeal_deadline.isnot(None)
    ).all()

    for task in tasks:
        if now <= task.appeal_deadline:
            continue

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

        # 使用_finalize_task统一收口（supplier_slash=True）
        _finalize_task(db, task, is_success=False, supplier_slash=True, manufacturer_slash=False)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = now

        event = ChainEvent(
            tx_hash=_generate_tx_hash(),
            event_type=ChainEventType.TIMEOUT.value,
            task_id=task.id,
            data_json={"reason": "slash_appeal_timeout", "auto_processed": True, "supplier_slash": True}
        )
        db.add(event)

        processed.append({
            "task_id": task.id,
            "task_hash": task.task_hash,
            "action": "slash_appeal_timeout_completed"
        })


def _process_onsite_timeouts(db: Session, now: datetime, processed: list):
    """ACCEPTANCE现场验收超时：制造商72h未响应 → 自动通过"""
    tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.ACCEPTANCE.value,
        AuditTask.supplier_submitted == True,
        AuditTask.onsite_deadline.isnot(None)
    ).all()

    for task in tasks:
        # 制造商已拒绝则不可触发自动通过
        if task.mfr_confirmed and not task.mfr_satisfied:
            continue

        if now <= task.onsite_deadline:
            continue

        mfr = db.query(User).filter(User.id == task.manufacturer_id).first()
        sup = db.query(User).filter(User.id == task.supplier_id).first()

        # 释放双方剩余锁定资金
        if mfr and task.mfr_locked:
            mfr.balance += task.mfr_locked
            mfr.locked_balance -= task.mfr_locked
        if sup and task.sup_locked:
            sup.balance += task.sup_locked
            sup.locked_balance -= task.sup_locked

        # 退还延期费
        if task.extension_deposit > 0 and sup:
            sup.balance += task.extension_deposit

        # 更新onsite_record
        onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task.id).first()
        if onsite:
            onsite.local_status = OnsiteLocalStatus.TIMEOUT.value
            onsite.confirm_time = now

        # 使用_finalize_task统一收口（is_success=True）
        _finalize_task(db, task, is_success=True, supplier_slash=False, manufacturer_slash=False)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = now

        event = ChainEvent(
            tx_hash=_generate_tx_hash(),
            event_type=ChainEventType.TIMEOUT.value,
            task_id=task.id,
            data_json={"reason": "onsite_timeout_auto_pass", "auto_processed": True}
        )
        db.add(event)

        processed.append({
            "task_id": task.id,
            "task_hash": task.task_hash,
            "action": "onsite_timeout_auto_pass"
        })


def _process_rectification_timeouts(db: Session, now: datetime, processed: list):
    """
    RECTIFICATION整改期超时：自动升级至DISPUTED_FIELD
    与Fund.escalateToFieldDispute对齐
    升级后等待任一方调用initiate-field-appeal发起现场申诉，再由仲裁员裁决
    """
    tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.RECTIFICATION.value,
        AuditTask.rectification_deadline.isnot(None)
    ).all()

    for task in tasks:
        if now <= task.rectification_deadline:
            continue

        task.status = TaskStatus.DISPUTED_FIELD.value

        event = ChainEvent(
            tx_hash=_generate_tx_hash(),
            event_type=ChainEventType.FIELD_DISPUTE_ESCALATED.value,
            task_id=task.id,
            data_json={"reason": "rectification_timeout_escalated", "auto_processed": True}
        )
        db.add(event)

        processed.append({
            "task_id": task.id,
            "task_hash": task.task_hash,
            "action": "rectification_timeout_escalated"
        })


# 工具函数

def _generate_tx_hash() -> str:
    import secrets
    return "0x" + secrets.token_hex(32)


# 后台定时线程（开发环境用）

_scheduler_thread = None
_scheduler_running = False


def _scheduler_loop(interval_seconds: int = 60):
    """后台定时线程：每interval_seconds秒检查一次超时"""
    global _scheduler_running
    _scheduler_running = True

    while _scheduler_running:
        try:
            db = SessionLocal()
            try:
                processed = process_all_timeouts(db)
                if processed:
                    print(f"[SCHEDULER] 处理 {len(processed)} 个超时任务:")
                    for p in processed:
                        print(f"  - Task {p['task_id']}: {p['action']}")
            finally:
                db.close()
        except Exception as e:
            print(f"[SCHEDULER] 错误: {e}")

        # 分段睡眠，支持快速停止
        for _ in range(interval_seconds):
            if not _scheduler_running:
                break
            time.sleep(1)


def start_scheduler(interval_seconds: int = 60):
    """启动后台定时任务线程"""
    global _scheduler_thread, _scheduler_running

    if _scheduler_thread and _scheduler_thread.is_alive():
        print("[SCHEDULER] 定时任务已在运行")
        return

    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        args=(interval_seconds,),
        daemon=True,
        name="ClarityTimeoutScheduler"
    )
    _scheduler_thread.start()
    print(f"[SCHEDULER] 超时处理定时任务已启动，检查间隔: {interval_seconds}秒")


def stop_scheduler():
    """停止后台定时任务线程"""
    global _scheduler_running
    _scheduler_running = False
    print("[SCHEDULER] 定时任务已停止")


# FastAPI集成

def init_scheduler(app):
    """在FastAPI应用上注册定时任务启动/停止事件"""

    @app.on_event("startup")
    def _start():
        # 启动后台定时任务（每60秒检查一次）
        start_scheduler(interval_seconds=60)

    @app.on_event("shutdown")
    def _stop():
        stop_scheduler()
