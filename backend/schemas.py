from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

# schemas.py是FastAPI中的数据模型与契约层
# 与智能合约完全对齐

# 枚举定义

class UserRole(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    SUPPLIER = "SUPPLIER"
    AUDITOR = "AUDITOR"
    ADMIN = "ADMIN"


class TaskStatus(str, Enum):
    """与Fund.sol合约状态完全对齐"""
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    PREPARED = "PREPARED"
    AUDITING = "AUDITING"
    PASS = "PASS"
    REJECT = "REJECT"
    SLASH = "SLASH"
    DISPUTED_AUDIT = "DISPUTED_AUDIT"
    ACCEPTANCE = "ACCEPTANCE"
    RECTIFICATION = "RECTIFICATION"
    DISPUTED_FIELD = "DISPUTED_FIELD"
    ARBITRATING = "ARBITRATING"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class GuaranteeMode(str, Enum):
    HIGH = "HIGH"
    INSURANCE = "INSURANCE"


class AppealType(str, Enum):
    """与Dispute.sol对齐"""
    AUDIT_REJECT = "AUDIT_REJECT"       # 对REJECT结果不服
    AUDIT_SLASH = "AUDIT_SLASH"         # 对SLASH结果不服
    FIELD_DOWNGRADE = "FIELD_DOWNGRADE"  # 现场履约降级争议
    FIELD_MALICE = "FIELD_MALICE"        # 现场恶意违约争议


class AppealStatus(str, Enum):
    PENDING = "PENDING"
    ARBITRATING = "ARBITRATING"
    RESOLVED = "RESOLVED"


class LiableParty(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    SUPPLIER = "SUPPLIER"
    AUDITOR = "AUDITOR"


class AuditDecision(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    SLASH = "SLASH"


class OnsiteLocalStatus(str, Enum):
    """Settlement.sol 本地状态"""
    NONE = "NONE"
    ONGOING = "ONGOING"
    CONFIRMED = "CONFIRMED"
    RECTIFYING = "RECTIFYING"
    TIMEOUT = "TIMEOUT"


# 常量（与合约对齐）
BASE_DEPOSIT = 1000
AUDIT_FEE = 50
INSURANCE_FEE = 50
EXTENSION_FEE = 200


# 数据表1-Users相关Schema

class UserBase(BaseModel):
    account: str = Field(..., min_length=5, max_length=50, description="登录账号")
    display_name: str = Field(..., min_length=3, max_length=100, description="企业名称")
    role: UserRole = Field(..., description="用户角色")
    wallet_address: Optional[str] = Field(None, description="区块链钱包地址")


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, description="登录密码")

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: UserRole):
        if v == UserRole.ADMIN:
            raise ValueError("ADMIN 角色不允许注册，仅支持内置账号登录")
        return v


class UserLogin(BaseModel):
    account: str = Field(..., description="登录账号")
    password: str = Field(..., description="登录密码")
    role: str = Field(..., description="前端选择的角色")


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reputation_score: int = Field(70, description="信誉积分")
    success_count: int = Field(0, description="顺利完结项目数")
    slash_count: int = Field(0, description="被判定作弊次数")
    claim_count: int = Field(0, description="出险次数（制造商）")
    balance: float = Field(0.0, description="资金余额")
    locked_balance: float = Field(0.0, description="锁定资金")
    total_staked: float = Field(0.0, description="总质押金额")
    is_builtin: bool = Field(False, description="是否为内置账号")
    is_blacklisted: bool = Field(False, description="是否在黑名单")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    version: int = Field(0, description="乐观锁版本号")


# 数据表2-AuditTasks相关Schema

class TaskCreate(BaseModel):
    task_name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    description: Optional[str] = Field(None, description="项目描述")

    target_fnr: float = Field(..., ge=0, le=1, description="漏杀率容忍度")
    target_fpr: float = Field(..., ge=0, le=1, description="误杀率容忍度")

    target_map: Optional[float] = Field(None, ge=0, le=1, description="mAP参考指标")
    target_f1: Optional[float] = Field(None, ge=0, le=1, description="F1参考指标")
    target_latency: Optional[int] = Field(None, ge=0, description="延迟参考指标(ms)")

    conf_threshold: float = Field(..., ge=0, le=1, description="工作置信度阈值")
    iou_threshold: float = Field(..., ge=0, le=1, description="IoU评估阈值")


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_hash: str = Field(..., description="项目链上哈希（唯一标识）")
    task_name: str
    description: Optional[str] = None
    manufacturer_id: int
    supplier_id: Optional[int] = None

    target_fnr: float
    target_fpr: float
    target_map: Optional[float] = None
    target_f1: Optional[float] = None
    target_latency: Optional[int] = None

    conf_threshold: float
    iou_threshold: float

    dataset_ipfs_hash: Optional[str] = None
    control_set_ipfs_hash: Optional[str] = None
    metadata_ipfs_hash: Optional[str] = None
    model_hash_history: Optional[List[dict]] = None
    model_hash: Optional[str] = Field(None, description="当前模型Hash")

    status: TaskStatus
    status_before_appeal: Optional[TaskStatus] = None
    guarantee_mode: Optional[GuaranteeMode] = None
    insurance_purchased: bool = False

    # 准备状态
    mfr_prepared: bool = False
    sup_prepared: bool = False
    first_prepared_at: Optional[datetime] = None
    prepared_at: Optional[datetime] = None

    # 资金体系
    mfr_total_paid: float = 0.0
    sup_total_paid: float = 0.0
    mfr_locked: float = 0.0
    sup_locked: float = 0.0
    extension_deposit: float = 0.0

    # 审计相关
    auditor_id: Optional[int] = None
    audit_started_at: Optional[datetime] = None
    audit_completed_at: Optional[datetime] = None

    # 时间戳
    appeal_deadline: Optional[datetime] = None
    onsite_deadline: Optional[datetime] = None
    rectification_deadline: Optional[datetime] = None

    # 现场验收确认状态
    mfr_confirmed: bool = False
    sup_confirmed: bool = False
    mfr_satisfied: bool = False
    sup_satisfied: bool = False
    supplier_submitted: bool = False

    # 整改
    rectification_count: int = 0

    # 现场实测指标
    field_actual_fnr: Optional[float] = None
    field_actual_fpr: Optional[float] = None
    field_actual_latency: Optional[int] = None
    field_actual_map: Optional[float] = None
    field_actual_f1: Optional[float] = None
    field_environment_notes: Optional[str] = None
    field_evidence_hash: Optional[str] = None

    # 旧字段兼容
    audit_supplier_confirmed: bool = False
    audit_manufacturer_confirmed: bool = False
    manufacturer_margin: float = 0.0
    supplier_margin: float = 0.0
    extra_supplier_margin: float = 0.0
    extension_count: int = 0
    state_deadline: Optional[datetime] = None
    field_supplier_signed: bool = False
    field_manufacturer_signed: bool = False

    gpu_node: Optional[str] = None

    # 最终审计指标
    final_fnr: Optional[float] = None
    final_fpr: Optional[float] = None
    final_map: Optional[float] = None
    final_f1: Optional[float] = None
    final_cr: Optional[float] = None
    completed_at: Optional[datetime] = None

    # 申诉关联
    dispute_type: Optional[str] = None
    dispute_reason: Optional[str] = None
    dispute_at: Optional[datetime] = None

    # 双方信誉积分（UPLOADING 阶段可见，用于协商是否继续）
    manufacturer_reputation: Optional[int] = Field(None, description="制造商信誉积分")
    supplier_reputation: Optional[int] = Field(None, description="供应商信誉积分")
    manufacturer_name: Optional[str] = Field(None, description="制造商企业名称")
    supplier_name: Optional[str] = Field(None, description="供应商企业名称")

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    version: int = 0


class TaskStatusUpdate(BaseModel):
    status: TaskStatus = Field(..., description="目标状态")
    state_deadline: Optional[datetime] = Field(None, description="新状态的超时截止时间")
    note: Optional[str] = Field(None, description="状态变更备注")


class TaskFundStake(BaseModel):
    """双方质押入参 - 与 Fund.sol 对齐"""
    purchase_insurance: bool = Field(False, description="是否购买保险")


class ManufacturerPreparePayload(BaseModel):
    """制造商准备入参"""
    purchase_insurance: bool = Field(False, description="是否购买保险")
    test_set_hash: Optional[str] = Field(None, description="测试集Hash")
    control_set_hash: Optional[str] = Field(None, description="对照集Hash")
    metadata_hash: Optional[str] = Field(None, description="元数据Hash")


class SupplierPreparePayload(BaseModel):
    """供应商准备入参"""
    model_hash: str = Field(..., description="模型Hash")
    model_desc_hash: Optional[str] = Field(None, description="模型描述Hash")


# 数据表3-TaskReports相关Schema

class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    report_hash: Optional[str] = Field(None, description="报告摘要Hash(上链用)")
    pdf_ipfs_hash: Optional[str] = Field(None, description="PDF报告IPFS地址")

    # 核心审计指标
    miss_rate: Optional[float] = Field(None, description="漏杀率")
    false_kill_rate: Optional[float] = Field(None, description="误杀率")
    concentration_ratio: Optional[float] = Field(None, ge=0, le=1, description="注意力密度比")
    avg_fp: Optional[float] = Field(None, description="单图平均误检数")
    arrogance: Optional[float] = Field(None, ge=0, le=1, description="自信度偏差")

    # 协商指标
    map: Optional[float] = Field(None, description="实际mAP")
    f1: Optional[float] = Field(None, description="实际F1")
    latency: Optional[int] = Field(None, description="实际延迟(ms)")

    # 阈值
    miss_threshold: Optional[float] = Field(None, description="漏杀率阈值")
    false_kill_threshold: Optional[float] = Field(None, description="误杀率阈值")

    decision: Optional[AuditDecision] = Field(None, description="审计判定")
    verdict: Optional[str] = Field(None, description="审计判定(同decision)")
    summary_hash: Optional[str] = Field(None, description="报告摘要Hash")
    auditor_node_id: Optional[int] = Field(None, description="审计节点ID")

    created_at: Optional[datetime] = None


class AuditSubmitPayload(BaseModel):
    """审计节点提交审计结果入参 - 与 Audit.sol 对齐"""
    miss_rate: float = Field(..., ge=0, le=1, description="漏杀率")
    false_kill_rate: float = Field(..., ge=0, le=1, description="误杀率")
    concentration_ratio: float = Field(..., ge=0, le=1, description="注意力密度比")
    avg_fp: float = Field(..., ge=0, description="平均误检数")
    arrogance: float = Field(..., ge=0, le=1, description="自信度偏差")
    map: Optional[float] = Field(None, ge=0, le=1, description="mAP")
    f1: Optional[float] = Field(None, ge=0, le=1, description="F1")
    report_hash: Optional[str] = Field(None, description="报告Hash")


# 数据表4-OnsiteRecords相关Schema

class OnsiteRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    mfr_measured_map: Optional[float] = None
    sup_measured_map: Optional[float] = None
    mfr_evidence_hash: Optional[str] = None
    sup_evidence_hash: Optional[str] = None
    mfr_satisfied: bool = False
    sup_satisfied: bool = False
    local_status: OnsiteLocalStatus = OnsiteLocalStatus.NONE
    confirm_time: Optional[datetime] = None
    created_at: Optional[datetime] = None


class FieldSignPayload(BaseModel):
    """现场验收签名入参（制造商和供应商共用）"""
    satisfied: bool = Field(..., description="是否满意")
    measured_map: Optional[float] = Field(None, ge=0, le=1, description="现场实测mAP")
    evidence_hash: Optional[str] = Field(None, description="现场测试证据Hash")
    field_actual_fnr: Optional[float] = Field(None, ge=0, le=100, description="实测漏杀率(%)")
    field_actual_fpr: Optional[float] = Field(None, ge=0, le=100, description="实测误杀率(%)")
    field_actual_latency: Optional[int] = Field(None, ge=0, description="边缘端延迟(ms)")
    field_environment_notes: Optional[str] = Field(None, description="现场环境说明")


# 数据表5-Appeals相关Schema

class AppealCreate(BaseModel):
    task_id: int = Field(..., description="关联项目ID")
    appeal_type: AppealType = Field(..., description="申诉类型")
    reason: str = Field(..., min_length=1, max_length=2000, description="申诉理由")
    evidence_hash: Optional[str] = Field(None, description="申诉证据IPFS Hash")


class AppealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    appeal_type: AppealType
    status: AppealStatus
    reason: str
    evidence_hash: Optional[str] = None
    arbitrator_id: Optional[int] = Field(None, description="仲裁员ID")
    liable_party: Optional[LiableParty] = Field(None, description="仲裁定责方")
    resolution: Optional[str] = Field(None, description="仲裁决议")
    refund_amount: Optional[float] = Field(None, description="清算金额")
    verdict: Optional[int] = Field(None, description="判决结果编码")
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class AppealResolve(BaseModel):
    """协会仲裁裁决入参 - 与 Dispute.sol 对齐"""
    result: int = Field(..., ge=1, le=3, description="裁决结果: 1=维持/降级, 2=PASS/恶意违约, 3=SLASH反转")
    resolution: str = Field(..., min_length=1, max_length=2000, description="仲裁决议说明")


class AssignArbitratorPayload(BaseModel):
    """指派仲裁员入参"""
    arbitrator_id: int = Field(..., description="仲裁员用户ID")


class PendingAppealResponse(BaseModel):
    """待仲裁申诉（含项目信息，方便ADMIN处理）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    appeal_type: AppealType
    status: AppealStatus
    reason: str
    evidence_hash: Optional[str] = None
    arbitrator_id: Optional[int] = None
    liable_party: Optional[LiableParty] = None
    resolution: Optional[str] = None
    refund_amount: Optional[float] = None
    verdict: Optional[int] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    # 关联项目信息
    task_name: Optional[str] = Field(None, description="项目名称")
    task_hash: Optional[str] = Field(None, description="项目链上哈希")
    manufacturer_name: Optional[str] = Field(None, description="制造商名称")
    supplier_name: Optional[str] = Field(None, description="供应商名称")
    manufacturer_margin: Optional[float] = Field(None, description="制造商质押金额")
    supplier_margin: Optional[float] = Field(None, description="供应商质押金额")
    task_status: Optional[str] = Field(None, description="项目当前状态")


# 数据表6-ChainEvents相关Schema

class ChainEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tx_hash: str = Field(..., description="交易哈希")
    block_height: Optional[int] = Field(None, description="区块高度")
    event_type: str = Field(..., description="事件类型")
    task_id: Optional[int] = Field(None, description="关联项目ID")
    sender_address: Optional[str] = Field(None, description="发送方地址")
    data_json: Optional[dict] = Field(None, description="交易数据(JSON)")
    status: str = Field("CONFIRMED", description="交易状态")
    created_at: Optional[datetime] = None


class ChainStatsResponse(BaseModel):
    block_height: Optional[int] = Field(None, description="当前区块高度")
    total_transactions: Optional[int] = Field(None, description="总交易笔数")
    active_nodes: Optional[int] = Field(None, description="活跃节点数")
    total_onchain_records: int = Field(0, description="本平台链上记录数")
    connected: bool = Field(False, description="是否已连接区块链")
    error: Optional[str] = Field(None, description="连接错误信息")


# 数据表7-AuditLogs相关Schema

class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    log_type: str = Field(..., description="日志类型: SYS/DONE/INFO/WARN/ERROR")
    message: str = Field(..., description="日志内容")
    created_at: Optional[datetime] = None


# 数据表8-AuditImages相关Schema

class AuditImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    image_type: str = Field(..., description="图片类型: attention/confidence/original")
    image_path: str = Field(..., description="图片路径")
    sample_id: Optional[int] = None
    label: Optional[str] = None
    confidence: Optional[float] = None
    cr: Optional[float] = None
    created_at: Optional[datetime] = None


# 整改相关Schema

class RectificationExtensionRequest(BaseModel):
    """整改延期申请"""
    pass  # 无额外参数，从登录态取用户


class RectificationSubmitPayload(BaseModel):
    """提交整改完成"""
    pass  # 无额外参数，从登录态取用户


class EscalateFieldDisputePayload(BaseModel):
    """升级现场申诉"""
    reason: str = Field(..., min_length=1, max_length=2000, description="申诉理由")


class UploadAppealEvidencePayload(BaseModel):
    """上传申诉证据，与Dispute.uploadAppealEvidence对齐"""
    evidence_hash: str = Field(..., min_length=1, max_length=255, description="申诉证据 Hash")
