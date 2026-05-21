from sqlalchemy import (
    create_engine, ForeignKey, String, Integer, Float, Boolean,
    DateTime, Text, JSON, Numeric, Index,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship, sessionmaker
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, List
from enum import Enum as PyEnum

# 数据库配置
SQLALCHEMY_DATABASE_URL = "sqlite:///./clarity_dev.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    pass


# 枚举映射
# 与智能合约完全对齐的角色体系
# 合约: ROLE_NONE=0, SUPPLIER=1, MANUFACTURER=2, AUDITOR=3, ARBITRATOR=4, SUPER_ADMIN=5, ASSOCIATION=6
# 为了方便演示，ADMIN同时承担SUPER_ADMIN、ARBITRATOR、ASSOCIATION

class UserRole(PyEnum):
    MANUFACTURER = "MANUFACTURER"    # 制造商
    SUPPLIER = "SUPPLIER"            # 供应商
    AUDITOR = "AUDITOR"              # 审计节点
    ADMIN = "ADMIN"                  # 系统管理员(同时是仲裁员+协会)


class TaskStatus(PyEnum):
    """
    审计任务状态机，与Fund.sol合约完全对齐
    合约状态码:
      NONE=0, PENDING=1, UPLOADING=2, PREPARED=3, AUDITING=4,
      PASS=5, REJECT=6, SLASH=7, DISPUTED_AUDIT=8, ACCEPTANCE=9,
      RECTIFICATION=10, DISPUTED_FIELD=11, COMPLETED=12, CANCELED=13, ARBITRATING=14
    """
    PENDING = "PENDING"                    # 1: 制造商刚创建项目
    UPLOADING = "UPLOADING"                # 2: 供应商已接单，双方上传文件并质押
    PREPARED = "PREPARED"                  # 3: 双方均完成质押，待审计
    AUDITING = "AUDITING"                  # 4: 审计节点正在审计
    PASS = "PASS"                          # 5: 审计通过，已释放30%资金，进入现场验收
    REJECT = "REJECT"                      # 6: 能力不足，进入72h申诉期
    SLASH = "SLASH"                        # 7: 恶意作弊，进入72h申诉期
    DISPUTED_AUDIT = "DISPUTED_AUDIT"      # 8: 供应商对审计结果发起申诉
    ACCEPTANCE = "ACCEPTANCE"              # 9: 线上通过，进入现场验收
    RECTIFICATION = "RECTIFICATION"        # 10: 制造商拒绝现场验收，进入整改期
    DISPUTED_FIELD = "DISPUTED_FIELD"      # 11: 整改期结束或供应商不认同，升级现场申诉
    ARBITRATING = "ARBITRATING"            # 14: 协会仲裁员已介入
    COMPLETED = "COMPLETED"                # 12: 终态，资金已清算，信誉已结算
    CANCELED = "CANCELED"                  # 13: 终态，项目已作废（超时未准备）


class GuaranteeMode(PyEnum):
    HIGH = "HIGH"            # 三倍基础质押金
    INSURANCE = "INSURANCE"  # 协会保险


class AppealType(PyEnum):
    AUDIT_REJECT = "AUDIT_REJECT"      # 对REJECT结果不服
    AUDIT_SLASH = "AUDIT_SLASH"        # 对SLASH结果不服
    FIELD_DOWNGRADE = "FIELD_DOWNGRADE"  # 现场履约降级争议
    FIELD_MALICE = "FIELD_MALICE"        # 现场恶意违约争议


class AppealStatus(PyEnum):
    PENDING = "PENDING"          # 0: 已发起，待仲裁员接手
    ARBITRATING = "ARBITRATING"  # 2: 仲裁员已介入
    RESOLVED = "RESOLVED"        # 3: 已判决


class OnsiteLocalStatus(PyEnum):
    """Settlement.sol 本地状态"""
    NONE = "NONE"
    ONGOING = "ONGOING"
    CONFIRMED = "CONFIRMED"
    RECTIFYING = "RECTIFYING"
    TIMEOUT = "TIMEOUT"


class LiableParty(PyEnum):
    MANUFACTURER = "MANUFACTURER"
    SUPPLIER = "SUPPLIER"
    AUDITOR = "AUDITOR"


class AuditDecision(PyEnum):
    PASS = "PASS"
    REJECT = "REJECT"
    SLASH = "SLASH"


class ChainEventType(PyEnum):
    """链上事件类型，与智能合约事件名对齐"""
    # Fund.sol事件
    PROJECT_CREATED = "ProjectCreated"           # 项目创建
    PROJECT_ACCEPTED = "ProjectAccepted"         # 供应商接单
    MANUFACTURER_PREPARED = "ManufacturerPrepared"  # 制造商准备完成
    SUPPLIER_PREPARED = "SupplierPrepared"       # 供应商准备完成
    STATUS_CHANGED = "StatusChanged"             # 状态变更
    AUDIT_STARTED = "AuditStarted"               # 审计开始
    AUDIT_COMPLETED = "AuditCompleted"           # 审计完成
    FUNDS_RELEASED = "FundsReleased"             # 资金释放
    APPEAL_STARTED = "AppealStarted"             # 申诉开始
    APPEAL_SETTLED = "AppealSettled"             # 申诉结算
    SUPPLIER_SUBMITTED_COMPLETION = "SupplierSubmittedCompletion"  # 供应商提交完成
    ONSITE_CONFIRMED = "OnsiteConfirmed"         # 现场确认
    MANUFACTURER_REJECTED = "ManufacturerRejected"  # 制造商拒绝
    SUPPLIER_ACCEPTED_RECTIFICATION = "SupplierAcceptedRectification"  # 接受整改
    EXTENSION_REQUESTED = "ExtensionRequested"   # 延期申请
    RECTIFICATION_SUBMITTED = "RectificationSubmitted"  # 整改提交
    FIELD_DISPUTE_ESCALATED = "FieldDisputeEscalated"  # 现场申诉升级
    ARBITRATION_STARTED = "ArbitrationStarted"   # 仲裁开始
    REPUTATION_FINALIZED = "ReputationFinalized" # 信誉结算
    # Audit.sol 事件
    AUDIT_SUBMITTED = "AuditSubmitted"           # 审计提交
    # Dispute.sol 事件
    AUDIT_APPEAL_INITIATED = "AuditAppealInitiated"    # 线上申诉发起
    FIELD_APPEAL_INITIATED = "FieldAppealInitiated"    # 现场申诉发起
    ARBITRATOR_ASSIGNED = "ArbitratorAssigned"   # 仲裁员指派
    ARBITRATION_ENTERED = "ArbitrationEntered"   # 进入仲裁
    AUDIT_ARBITRATION_COMPLETED = "AuditArbitrationCompleted"   # 线上仲裁完成
    FIELD_ARBITRATION_COMPLETED = "FieldArbitrationCompleted"   # 现场仲裁完成
    # Evidence.sol 事件
    DATA_UPLOADED = "DataUploaded"               # 测试集上传
    MODEL_UPLOADED = "ModelUploaded"             # 模型上传
    AUDIT_REPORTED = "AuditReported"             # 审计报告上传
    APPEAL_EVIDENCE_UPLOADED = "AppealEvidenceUploaded"  # 申诉证据上传
    # 通用
    TIMEOUT = "Timeout"                          # 超时自动处理


# 常量（与合约对齐）
# Fund.sol常量
BASE_DEPOSIT = 1000          # 基础质押金
AUDIT_FEE = 50               # 审计费（双方各付）
INSURANCE_FEE = 50           # 保险费（可选）
PASS_RELEASE_RATIO = 0.30    # PASS时释放30%
SLASH_COMPENSATION_RATIO = 0.10  # SLASH时10%补偿制造商

# 时间常量（秒）
PREPARE_TIMEOUT_SECONDS = 3 * 24 * 3600    # 3天
APPEAL_WINDOW_SECONDS = 3 * 24 * 3600      # 3天
ONSITE_TIMEOUT_SECONDS = 3 * 24 * 3600     # 3天
RECTIFICATION_PERIOD_SECONDS = 7 * 24 * 3600  # 7天
MAX_EXTENSIONS = 2           # 最大延期次数
EXTENSION_FEE = 200          # 延期费

# Identity.sol常量
BASE_REPUTATION = 70         # 初始信誉分
COMPLETION_BONUS = 1         # 顺利完结 +1
SLASH_PENALTY = 10           # 作弊 -10


# 表1：Users

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    wallet_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 信誉体系（与Identity.sol对齐）
    reputation_score: Mapped[int] = mapped_column(Integer, default=BASE_REPUTATION, server_default=str(BASE_REPUTATION))
    success_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    slash_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    claim_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 制造商出险次数

    # 资金体系（与Fund.sol对齐）
    balance: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    locked_balance: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    total_staked: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")

    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    manufactured_tasks: Mapped[List["AuditTask"]] = relationship(
        "AuditTask", foreign_keys="AuditTask.manufacturer_id", back_populates="manufacturer"
    )
    supplied_tasks: Mapped[List["AuditTask"]] = relationship(
        "AuditTask", foreign_keys="AuditTask.supplier_id", back_populates="supplier"
    )


# 表2：AuditTasks

class AuditTask(Base):
    __tablename__ = "audit_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_hash: Mapped[str] = mapped_column(String(66), unique=True, nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    manufacturer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 制造商指定的验收标准（阈值）
    target_fnr: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)  # 漏杀率容忍度
    target_fpr: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)  # 误杀率容忍度
    target_map: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    target_f1: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    target_latency: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    conf_threshold: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    iou_threshold: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)

    # 文件存证
    dataset_ipfs_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    control_set_ipfs_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_ipfs_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    model_hash_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    model_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 当前模型Hash（与Fund.Trade.modelHash对齐）

    # 状态
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING", index=True)
    status_before_appeal: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 申诉前的状态

    # 担保方式
    guarantee_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    insurance_purchased: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # 准备状态（双方是否已质押+上传）
    mfr_prepared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sup_prepared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    first_prepared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    prepared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 资金体系（与Fund.sol对齐）
    mfr_total_paid: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    sup_total_paid: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    mfr_locked: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    sup_locked: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    extension_deposit: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")

    # 审计相关
    auditor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    audit_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    audit_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 申诉相关时间戳
    appeal_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    onsite_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rectification_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 现场验收确认状态（与Fund.sol mfrConfirmed/supConfirmed对齐）
    mfr_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sup_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    mfr_satisfied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sup_satisfied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    supplier_submitted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # 整改相关
    rectification_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # 现场实测指标
    field_actual_fnr: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    field_actual_fpr: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    field_actual_latency: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    field_actual_map: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    field_actual_f1: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    field_environment_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    field_evidence_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 旧字段兼容（保留但逐渐废弃）
    audit_supplier_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    audit_manufacturer_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    manufacturer_margin: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    supplier_margin: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    extra_supplier_margin: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0, server_default="0.0")
    extension_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    state_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    field_supplier_signed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    field_manufacturer_signed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    gpu_node: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # 最终审计指标
    final_fnr: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    final_fpr: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    final_map: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    final_f1: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    final_cr: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 申诉关联
    dispute_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dispute_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dispute_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    manufacturer: Mapped["User"] = relationship(
        "User", foreign_keys=[manufacturer_id], back_populates="manufactured_tasks"
    )
    supplier: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[supplier_id], back_populates="supplied_tasks"
    )
    auditor: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[auditor_id]
    )
    report: Mapped[Optional["TaskReport"]] = relationship(
        "TaskReport", back_populates="task", uselist=False
    )
    appeals: Mapped[List["Appeal"]] = relationship("Appeal", back_populates="task")
    chain_events: Mapped[List["ChainEvent"]] = relationship("ChainEvent", back_populates="task")
    onsite_records: Mapped[List["OnsiteRecord"]] = relationship("OnsiteRecord", back_populates="task")


# 表3：TaskReports

class TaskReport(Base):
    __tablename__ = "task_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("audit_tasks.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    report_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pdf_ipfs_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 核心审计指标（与Audit.sol/Evidence.sol 对齐，×10000定点数）
    # 后端存储时保持为float（如5%存为0.05），对外接口做转换
    miss_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)           # 漏杀率
    false_kill_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)     # 误杀率
    concentration_ratio: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)  # 注意力密度比
    avg_fp: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)             # 平均误检数
    arrogance: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)           # 自信度偏差

    # 协商指标
    map: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    f1: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    latency: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 实际使用的阈值（制造商指定）
    miss_threshold: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    false_kill_threshold: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)

    decision: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    summary_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 审计节点信息
    auditor_node_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped["AuditTask"] = relationship("AuditTask", back_populates="report")


# 表4：OnsiteRecords（现场验收记录）
# 与Settlement.sol对齐

class OnsiteRecord(Base):
    __tablename__ = "onsite_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("audit_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 双方现场实测 mAP（×10000定点数，存储为float）
    mfr_measured_map: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    sup_measured_map: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)

    # 双方测试证据文件 Hash
    mfr_evidence_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sup_evidence_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 满意度缓存
    mfr_satisfied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sup_satisfied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # 本地流程状态
    # LOCAL_NONE=0, ONGOING=1, CONFIRMED=2, RECTIFYING=3, TIMEOUT=4
    local_status: Mapped[str] = mapped_column(String(20), default="NONE", server_default="NONE")
    confirm_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 现场验收确认Hash（与 Settlement._uploadOnsiteEvidence 对齐）
    confirm_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped["AuditTask"] = relationship("AuditTask", back_populates="onsite_records")


# 表5：Appeals

class Appeal(Base):
    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("audit_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 申诉类型（与Dispute.sol对齐）
    # AUDIT_REJECT, AUDIT_SLASH, FIELD_DOWNGRADE, FIELD_MALICE
    appeal_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # 申诉状态
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 仲裁员信息
    arbitrator_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # 裁决结果
    # 线上申诉: 1=维持原判, 2=REJECT→PASS, 3=SLASH反转（制造商投毒）
    # 现场申诉: 1=履约降级, 2=恶意违约（等同SLASH）
    verdict: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refund_amount: Mapped[Optional[float]] = mapped_column(Numeric(20, 8), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    task: Mapped["AuditTask"] = relationship("AuditTask", back_populates="appeals")
    arbitrator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[arbitrator_id])


# 表6：ChainEvents

class ChainEvent(Base):
    __tablename__ = "chain_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tx_hash: Mapped[str] = mapped_column(String(66), unique=True, nullable=False, index=True)
    block_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("audit_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sender_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    data_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="CONFIRMED")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped[Optional["AuditTask"]] = relationship("AuditTask", back_populates="chain_events")


# 表7：AuditLogs

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("audit_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    log_type: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# 表8：AuditImages

class AuditImage(Base):
    __tablename__ = "audit_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("audit_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_type: Mapped[str] = mapped_column(String(20), nullable=False)
    image_path: Mapped[str] = mapped_column(String(255), nullable=False)
    sample_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    cr: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# 表9：ContractConfig（合约地址配置）
# 与Fund.sol/Identity.sol等合约的地址管理对齐，持久化到数据库

class ContractConfig(Base):
    __tablename__ = "contract_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    config_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# 初始化

def init_db():
    Base.metadata.create_all(bind=engine)


def ensure_builtin_admin():
    from passlib.context import CryptContext
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.account == "admin").first()
        if not admin:
            # 尝试创建链上钱包
            wallet_address = None
            try:
                from chain import create_wallet
                sign_user_id = "clarity_admin_admin"
                wallet = create_wallet(sign_user_id)
                if wallet and wallet.get("address"):
                    wallet_address = wallet["address"]
                    print(f"[INIT] Admin 链上钱包已创建: {wallet_address}, signUserId={sign_user_id}")
                else:
                    print("[INIT] 警告: 链上钱包创建失败，将使用占位地址")
            except Exception as e:
                print(f"[INIT] 警告: 链上钱包创建异常: {e}")

            admin = User(
                account="admin",
                password_hash=pwd.hash("clarity123"),
                display_name="系统管理员",
                role="ADMIN",
                wallet_address=wallet_address or "0x0000000000000000000000000000000000000000",
                is_builtin=True
            )
            db.add(admin)
            db.commit()
            print("[INIT] 内置 ADMIN 账号已创建: admin / clarity123")
        else:
            print("[INIT] 内置 ADMIN 账号已存在")
            # 检查是否需要补创建链上钱包
            if not admin.wallet_address or admin.wallet_address == "0x0000000000000000000000000000000000000000":
                try:
                    from chain import create_wallet
                    sign_user_id = f"clarity_admin_{admin.account}"
                    wallet = create_wallet(sign_user_id)
                    if wallet and wallet.get("address"):
                        admin.wallet_address = wallet["address"]
                        db.commit()
                        print(f"[INIT] 已为 Admin 补创建链上钱包: {wallet['address']}")
                    else:
                        print("[INIT] 警告: 补创建链上钱包失败")
                except Exception as e:
                    print(f"[INIT] 警告: 补创建链上钱包异常: {e}")
    except Exception as e:
        print(f"[INIT] 创建 ADMIN 账号失败: {e}")
    finally:
        db.close()
