from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional, List, Any
from pydantic import BaseModel, Field
import shutil
import uuid
import secrets
import jwt
import os

from models import (
    init_db, get_db, ensure_builtin_admin,
    User, AuditTask, TaskReport, ChainEvent, Appeal, AuditLog, AuditImage, OnsiteRecord, ContractConfig,
    UserRole, TaskStatus, AppealType, AppealStatus, LiableParty, AuditDecision,
    ChainEventType, OnsiteLocalStatus,
    BASE_DEPOSIT, AUDIT_FEE, INSURANCE_FEE, EXTENSION_FEE,
    PASS_RELEASE_RATIO, SLASH_COMPENSATION_RATIO,
    PREPARE_TIMEOUT_SECONDS, APPEAL_WINDOW_SECONDS, ONSITE_TIMEOUT_SECONDS,
    RECTIFICATION_PERIOD_SECONDS, MAX_EXTENSIONS,
    BASE_REPUTATION, COMPLETION_BONUS, SLASH_PENALTY,
)
from schemas import (
    UserCreate, UserResponse, UserLogin,
    TaskCreate, TaskResponse,
    AppealCreate, AppealResponse, AppealResolve, PendingAppealResponse,
    AssignArbitratorPayload,
    ReportResponse, ChainEventResponse, ChainStatsResponse,
    AuditLogResponse, AuditImageResponse,
    GuaranteeMode, TaskFundStake,
    ManufacturerPreparePayload, SupplierPreparePayload,
    AuditSubmitPayload,
    FieldSignPayload,
    RectificationExtensionRequest, RectificationSubmitPayload, EscalateFieldDisputePayload,
    UploadAppealEvidencePayload,
)
from chain import get_chain_stats, create_wallet
from scheduler import init_scheduler

# 基础配置
SECRET_KEY = "clarity-dev-key-change-before-deploy"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

app = FastAPI(title="Clarity API")

# 允许前端Vue跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动时自动建表，启动定时任务
@app.on_event("startup")
def on_startup():
    init_db()
    ensure_builtin_admin()
    init_scheduler(app)


# 各类工具函数
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    exc = HTTPException(status_code=401, detail="无效的认证凭据", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception:
        raise exc
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise exc
    return user


# 链上事件工具
def _generate_tx_hash() -> str:
    """生成模拟的0x+64位十六进制交易哈希"""
    return "0x" + secrets.token_hex(32)


def _insert_chain_event(
    db: Session,
    event_type: str,
    task_id: Optional[int] = None,
    sender_address: Optional[str] = None,
    data_json: Optional[dict] = None
) -> ChainEvent:
    """插入链上事件记录（Mock阶段用，后续接入真实交易时替换）"""
    event = ChainEvent(
        tx_hash=_generate_tx_hash(),
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


# 合约交互开关与工具
# 部署合约后，将此处设为True，系统会自动同步链上操作
CHAIN_SYNC_ENABLED = os.getenv("CHAIN_SYNC_ENABLED", "false").lower() == "true"


def _get_admin_sign_info(db: Session) -> tuple:
    """
    获取admin的链上签名信息
    返回: (admin_user, sign_user_id) 或 (None, None)
    """
    admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
    if not admin or not admin.wallet_address:
        return None, None
    sign_user_id = f"clarity_admin_{admin.account}"
    return admin, sign_user_id


def _get_contract_addresses(db: Session) -> dict:
    """从数据库获取已配置的合约地址"""
    configs = db.query(ContractConfig).all()
    result = {}
    for c in configs:
        result[c.config_key] = c.config_value
    return result


# 信誉结算工具
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
    
    合约同步：部署后自动调用Identity.settleProjectReputation
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
        # 注意：claim_count只在SLASH反转（制造商出现问题）时通过updateClaimCount单独更新
        # 不在_settle_reputation中统一处理，避免重复累加

    db.commit()

    # 合约同步钩子：链上信誉结算
    if CHAIN_SYNC_ENABLED and supplier and manufacturer:
        try:
            contracts = _get_contract_addresses(db)
            identity_contract = contracts.get("identity_contract")
            if identity_contract:
                admin, sign_user_id = _get_admin_sign_info(db)
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
            # 链上失败不影响本地数据库事务


def _update_claim_count_onchain(db: Session, manufacturer: User):
    """
    合约同步：更新制造商出险计数，对应Identity.updateClaimCount
    在SLASH反转（制造商担责）时调用
    """
    if not CHAIN_SYNC_ENABLED or not manufacturer or not manufacturer.wallet_address:
        return
    
    try:
        contracts = _get_contract_addresses(db)
        identity_contract = contracts.get("identity_contract")
        if identity_contract:
            admin, sign_user_id = _get_admin_sign_info(db)
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


def _finalize_task(
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
        # Mock: 保险费进入平台（admin账户）
        admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if admin:
            admin.balance += INSURANCE_FEE

    # 清空锁定资金标记
    task.mfr_locked = 0
    task.sup_locked = 0

    _insert_chain_event(
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


# 认证接口

@app.post("/api/auth/register", response_model=UserResponse)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    """注册：查重 → 哈希密码 → 入库 → 创建链上钱包"""
    if db.query(User).filter(User.account == payload.account).first():
        raise HTTPException(status_code=400, detail="账号已存在")

    # 通过WeBASE-Front创建链上钱包地址
    sign_user_id = f"clarity_{payload.account}_{uuid.uuid4().hex[:8]}"
    wallet = create_wallet(sign_user_id)
    if not wallet:
        raise HTTPException(status_code=500, detail="链上钱包创建失败，请稍后重试")

    user = User(
        account=payload.account,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role.value,
        wallet_address=wallet["address"],
        reputation_score=BASE_REPUTATION,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/auth/login")
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """登录：验密码 → 校验角色 → 发 JWT Token"""
    user = db.query(User).filter(User.account == payload.account).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")

    # 校验前端选择的角色必须与账号实际角色匹配
    if payload.role and payload.role.upper() != user.role:
        raise HTTPException(status_code=403, detail=f"角色不匹配：该账号为 {user.role}，请选择正确角色登录")

    token = create_access_token(
        data={"sub": str(user.id)},
        expires=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": token, "token_type": "bearer", "user": UserResponse.model_validate(user)}


@app.post("/api/auth/sudo")
def sudo_login(
    target_user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """ADMIN切换到指定用户身份，模拟登录"""
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可使用切换功能")

    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(404, "目标用户不存在")
    if target.role == UserRole.ADMIN.value:
        raise HTTPException(400, "不能切换到 ADMIN 账号")

    token = create_access_token(
        data={"sub": str(target.id)},
        expires=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": token, "token_type": "bearer", "user": UserResponse.model_validate(target)}


# 用户接口

@app.get("/api/users/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return current_user


@app.get("/api/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """ADMIN 获取所有用户列表（不含 ADMIN 自身）"""
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可查看用户列表")
    return db.query(User).filter(User.role != UserRole.ADMIN.value).all()


@app.get("/api/users/{user_id}/stake-ratio")
def get_stake_ratio(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    查询用户动态质押比例
    信誉越高，质押比例越低
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    # 黑名单: 200%
    if user.is_blacklisted:
        return {"user_id": user_id, "stake_ratio": 2.0, "basis_points": 20000}

    # 未注册: 200%
    if user.reputation_score == 0 and user.success_count == 0 and not user.is_builtin:
        return {"user_id": user_id, "stake_ratio": 2.0, "basis_points": 20000}

    # 管理员/审计节点: 100%（无需额外质押）
    if user.role in [UserRole.ADMIN.value, UserRole.AUDITOR.value]:
        return {"user_id": user_id, "stake_ratio": 1.0, "basis_points": 10000}

    # 动态计算: 基础 150%，信誉每高 10 分减 3%，最多减 50%；信誉低则反加
    base_ratio = 1.5  # 150%
    rep_diff = user.reputation_score - BASE_REPUTATION  # 与 70 分基准的差值

    if rep_diff > 0:
        reduction = (rep_diff // 10) * 0.03
        reduction = min(reduction, 0.5)
        base_ratio -= reduction
    elif rep_diff < 0:
        increase = (abs(rep_diff) // 10) * 0.03
        increase = min(increase, 0.5)
        base_ratio += increase

    # 限制范围: 100% ~ 200%
    base_ratio = max(1.0, min(2.0, base_ratio))

    return {
        "user_id": user_id,
        "stake_ratio": round(base_ratio, 2),
        "basis_points": int(base_ratio * 10000),
        "reputation_score": user.reputation_score
    }


@app.post("/api/users/recharge")
def recharge(
    amount: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mock充值：直接加余额（生产环境应走链上转账）"""
    if amount <= 0:
        raise HTTPException(400, "充值金额必须大于0")
    current_user.balance += amount
    db.commit()
    return {"new_balance": current_user.balance}


# 项目接口

@app.post("/api/tasks", response_model=TaskResponse)
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

    _insert_chain_event(
        db,
        event_type=ChainEventType.PROJECT_CREATED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"task_hash": pseudo_hash}
    )

    return task


@app.get("/api/tasks/stats")
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


@app.get("/api/tasks", response_model=list[TaskResponse])
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
    # AUDITOR/ADMIN看全部

    if status:
        query = query.filter(AuditTask.status == status)

    tasks = query.order_by(AuditTask.created_at.desc()).all()

    # 为每个任务附加双方信誉积分和企业名称
    for task in tasks:
        manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
        supplier = db.query(User).filter(User.id == task.supplier_id).first()
        task.manufacturer_reputation = manufacturer.reputation_score if manufacturer else None
        task.supplier_reputation = supplier.reputation_score if supplier else None
        task.manufacturer_name = manufacturer.display_name if manufacturer else None
        task.supplier_name = supplier.display_name if supplier else None

    return tasks


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询单个项目详情"""
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()
    task.manufacturer_reputation = manufacturer.reputation_score if manufacturer else None
    task.supplier_reputation = supplier.reputation_score if supplier else None
    task.manufacturer_name = manufacturer.display_name if manufacturer else None
    task.supplier_name = supplier.display_name if supplier else None

    return task


# 供应商接单

@app.put("/api/tasks/{task_id}/accept", response_model=TaskResponse)
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

    _insert_chain_event(
        db,
        event_type=ChainEventType.PROJECT_ACCEPTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"supplier_id": current_user.id}
    )

    return task


@app.put("/api/tasks/accept-by-hash", response_model=TaskResponse)
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

    _insert_chain_event(
        db,
        event_type=ChainEventType.PROJECT_ACCEPTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"supplier_id": current_user.id}
    )

    return task


# 文件上传（Mock IPFS）

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.post("/api/tasks/{task_id}/upload-dataset")
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

    fake_hash = f"ipfs://mock/{filename}"
    task.dataset_ipfs_hash = fake_hash
    db.commit()

    _insert_chain_event(
        db,
        event_type=ChainEventType.DATA_UPLOADED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"type": "dataset", "hash": fake_hash}
    )

    return {"ipfs_hash": fake_hash, "filename": file.filename, "type": "dataset"}


@app.post("/api/tasks/{task_id}/upload-model")
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

    fake_hash = f"ipfs://mock/{filename}"
    history = task.model_hash_history or []
    history.append({
        "hash": fake_hash,
        "uploaded_at": datetime.utcnow().isoformat(),
        "filename": file.filename
    })
    task.model_hash_history = history
    db.commit()

    _insert_chain_event(
        db,
        event_type=ChainEventType.MODEL_UPLOADED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"type": "model", "hash": fake_hash}
    )

    return {"ipfs_hash": fake_hash, "filename": file.filename, "type": "model"}


# 阶段2: 准备与质押（与Fund.sol对齐）

def _compute_stake_ratio(user: User) -> float:
    """
    计算用户动态质押比例 - 与 Identity.getStakeRatio 对齐
    返回: 倍数（1.0 = 100%，1.5 = 150%，2.0 = 200%）
    """
    # 黑名单: 200%
    if user.is_blacklisted:
        return 2.0

    # 未注册: 200%
    if user.reputation_score == 0 and user.success_count == 0 and not user.is_builtin:
        return 2.0

    # 管理员/审计节点: 100%（无需额外质押）
    if user.role in [UserRole.ADMIN.value, UserRole.AUDITOR.value]:
        return 1.0

    # 动态计算: 基础 150%，信誉每高 10 分减 3%，最多减 50%；信誉低则反加
    base_ratio = 1.5  # 150%
    rep_diff = user.reputation_score - BASE_REPUTATION  # 与 70 分基准的差值

    if rep_diff > 0:
        reduction = (rep_diff // 10) * 0.03
        reduction = min(reduction, 0.5)
        base_ratio -= reduction
    elif rep_diff < 0:
        increase = (abs(rep_diff) // 10) * 0.03
        increase = min(increase, 0.5)
        base_ratio += increase

    # 限制范围: 100% ~ 200%
    return max(1.0, min(2.0, base_ratio))


@app.post("/api/tasks/{task_id}/manufacturer-prepare", response_model=TaskResponse)
def manufacturer_prepare(
    task_id: int,
    payload: ManufacturerPreparePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    制造商准备：质押 + 上传测试集信息
    动态质押金额 = BASE_DEPOSIT * stake_ratio + AUDIT_FEE + optional INSURANCE_FEE
    与 Identity.getStakeRatio / Fund.manufacturerPrepare 对齐
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

    # 动态计算质押比例和金额
    stake_ratio = _compute_stake_ratio(current_user)
    deposit_amount = round(BASE_DEPOSIT * stake_ratio)  # 动态质押金

    # 计算所需总金额
    required = deposit_amount + AUDIT_FEE
    if payload.purchase_insurance:
        required += INSURANCE_FEE
        task.insurance_purchased = True

    if current_user.balance < required:
        raise HTTPException(400, f"余额不足，需要 {required}，当前余额：{current_user.balance}")

    # 扣款
    current_user.balance -= required
    current_user.locked_balance += deposit_amount
    current_user.total_staked += required

    # 更新任务
    task.mfr_total_paid = required
    task.mfr_locked = deposit_amount
    task.mfr_prepared = True

    # 记录Hash
    if payload.test_set_hash:
        task.dataset_ipfs_hash = payload.test_set_hash
    if payload.control_set_hash:
        task.control_set_ipfs_hash = payload.control_set_hash
    if payload.metadata_hash:
        task.metadata_ipfs_hash = payload.metadata_hash

    # 设置首次准备时间（用于超时检测）
    if not task.first_prepared_at:
        task.first_prepared_at = datetime.utcnow()

    # 检查双方是否都完成
    if task.sup_prepared:
        task.status = TaskStatus.PREPARED.value
        task.prepared_at = datetime.utcnow()
    else:
        task.state_deadline = datetime.utcnow() + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)

    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.MANUFACTURER_PREPARED.value,
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


@app.post("/api/tasks/{task_id}/supplier-prepare", response_model=TaskResponse)
def supplier_prepare(
    task_id: int,
    payload: SupplierPreparePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    供应商准备：质押资金、模型推理包
    动态质押金额 = BASE_DEPOSIT * stake_ratio + AUDIT_FEE
    与Identity.getStakeRatio/Fund.supplierPrepare对齐
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

    # 动态计算质押比例和金额
    stake_ratio = _compute_stake_ratio(current_user)
    deposit_amount = round(BASE_DEPOSIT * stake_ratio)  # 动态质押金

    required = deposit_amount + AUDIT_FEE
    if current_user.balance < required:
        raise HTTPException(400, f"余额不足，需要 {required}，当前余额：{current_user.balance}")

    # 扣款
    current_user.balance -= required
    current_user.locked_balance += deposit_amount
    current_user.total_staked += required

    # 更新任务
    task.sup_total_paid = required
    task.sup_locked = deposit_amount
    task.sup_prepared = True

    # 记录模型Hash（历史+当前）
    if not task.model_hash_history:
        task.model_hash_history = []
    task.model_hash_history.append({
        "hash": payload.model_hash,
        "desc_hash": payload.model_desc_hash,
        "uploaded_at": datetime.utcnow().isoformat()
    })
    task.model_hash = payload.model_hash

    # 设置首次准备时间
    if not task.first_prepared_at:
        task.first_prepared_at = datetime.utcnow()

    # 检查双方是否都完成
    if task.mfr_prepared:
        task.status = TaskStatus.PREPARED.value
        task.prepared_at = datetime.utcnow()
    else:
        task.state_deadline = datetime.utcnow() + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)

    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.SUPPLIER_PREPARED.value,
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


@app.post("/api/tasks/{task_id}/withdraw-if-timeout", response_model=TaskResponse)
def withdraw_if_timeout(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    UPLOADING阶段3天超时后，任一方可调用退款
    与Fund.withdrawIfTimeout对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.UPLOADING.value:
        raise HTTPException(400, "当前状态不允许退款")
    if not task.first_prepared_at:
        raise HTTPException(400, "尚未有人准备")

    # 检查是否超时
    deadline = task.first_prepared_at + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)
    if datetime.utcnow() <= deadline:
        raise HTTPException(400, f"超时未到达，将在 {deadline.isoformat()} 后可用")

    # 只有已准备的一方可退款
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

    _insert_chain_event(
        db,
        event_type=ChainEventType.TIMEOUT.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"reason": "prepare_timeout", "refund_to": current_user.role}
    )

    return task


# 阶段3: 线上审计

@app.put("/api/tasks/{task_id}/start-audit", response_model=TaskResponse)
def start_audit(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """审计节点将PREPARED项目改为AUDITING"""
    if current_user.role != UserRole.AUDITOR.value:
        raise HTTPException(403, "仅审计节点可操作")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.PREPARED.value:
        raise HTTPException(400, "项目未准备好，无法开始审计")

    task.status = TaskStatus.AUDITING.value
    task.auditor_id = current_user.id
    task.audit_started_at = datetime.utcnow()
    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.AUDIT_STARTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"auditor_id": current_user.id}
    )

    return task


@app.post("/api/tasks/{task_id}/report")
def submit_report(
    task_id: int,
    payload: AuditSubmitPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    审计节点提交审计结果，与Audit.sol对齐
    三阶段判定：准确度 → 注意力 → 置信度
    返回：{ task: TaskResponse, decision: str }，前端根据decision决定是否调用advanceToAcceptance
    """
    if current_user.role != UserRole.AUDITOR.value:
        raise HTTPException(403, "仅审计节点可提交报告")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task or task.status != TaskStatus.AUDITING.value:
        raise HTTPException(400, "项目不存在或状态非AUDITING")

    # 获取制造商指定的阈值
    miss_th = task.target_fnr if task.target_fnr else 0.05
    false_kill_th = task.target_fpr if task.target_fpr else 0.05

    # 三阶段判定逻辑（与Audit._evaluateVerdict对齐）
    decision = _evaluate_verdict(
        payload.miss_rate,
        payload.false_kill_rate,
        payload.concentration_ratio,
        payload.avg_fp,
        payload.arrogance,
        miss_th,
        false_kill_th
    )

    # 生成报告
    report = TaskReport(
        task_id=task.id,
        miss_rate=payload.miss_rate,
        false_kill_rate=payload.false_kill_rate,
        concentration_ratio=payload.concentration_ratio,
        avg_fp=payload.avg_fp,
        arrogance=payload.arrogance,
        map=payload.map,
        f1=payload.f1,
        miss_threshold=miss_th,
        false_kill_threshold=false_kill_th,
        decision=decision.value,
        verdict=decision.value,
        report_hash=payload.report_hash or f"mock_report_hash_{uuid.uuid4().hex[:16]}",
        auditor_node_id=current_user.id,
    )
    db.add(report)

    # 审计费结算：与Fund.settleAudit对齐
    # 双方各出AUDIT_FEE，共2*AUDIT_FEE
    # 如果auditor_id存在则给审计节点，否则给平台(admin)
    total_audit_fee = AUDIT_FEE * 2
    if task.auditor_id:
        # 给执行审计的节点
        auditor = db.query(User).filter(User.id == task.auditor_id).first()
        if auditor:
            auditor.balance += total_audit_fee
    else:
        # 没有指定审计节点，给平台(admin)
        admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if admin:
            admin.balance += total_audit_fee

    # 状态变更与资金处理
    task.audit_completed_at = datetime.utcnow()
    task.final_fnr = payload.miss_rate
    task.final_fpr = payload.false_kill_rate
    task.final_cr = payload.concentration_ratio

    if decision == AuditDecision.PASS:
        task.status = TaskStatus.PASS.value
    elif decision == AuditDecision.REJECT:
        task.status = TaskStatus.REJECT.value
        task.appeal_deadline = datetime.utcnow() + timedelta(seconds=APPEAL_WINDOW_SECONDS)
    elif decision == AuditDecision.SLASH:
        task.status = TaskStatus.SLASH.value
        task.appeal_deadline = datetime.utcnow() + timedelta(seconds=APPEAL_WINDOW_SECONDS)

    _insert_chain_event(
        db,
        event_type=ChainEventType.AUDIT_COMPLETED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={
            "decision": decision.value,
            "miss_rate": payload.miss_rate,
            "false_kill_rate": payload.false_kill_rate,
            "concentration_ratio": payload.concentration_ratio,
            "avg_fp": payload.avg_fp,
            "arrogance": payload.arrogance,
            "audit_fee": total_audit_fee
        }
    )

    db.commit()
    db.refresh(task)
    return {"task": task, "decision": decision.value}


def _evaluate_verdict(
    miss_rate: float,
    false_kill_rate: float,
    concentration_ratio: float,
    avg_fp: float,
    arrogance: float,
    miss_th: float,
    false_kill_th: float
) -> AuditDecision:
    """
    三阶段判定逻辑，与Audit._evaluateVerdict对齐
    阶段一：准确度审计
    阶段二：注意力审计
    阶段三：置信度审计
    """
    # 阶段一：误杀率或漏杀率超过制造商容忍度 → REJECT
    if miss_rate > miss_th or false_kill_rate > false_kill_th:
        return AuditDecision.REJECT

    # 阶段二：注意力密度比 < 20% → SLASH（涉嫌利用背景作弊）
    if concentration_ratio < 0.20:
        return AuditDecision.SLASH

    # 阶段三：置信度审计
    # Avg >= 0.1 说明误检数量超标
    if avg_fp >= 0.1:
        # 高置信度误检占比 >= 50% → SLASH（确信性犯错）
        if arrogance >= 0.5:
            return AuditDecision.SLASH
        # 低置信度误检 → REJECT（纯粹泛化能力不足）
        return AuditDecision.REJECT

    # 全部通过
    return AuditDecision.PASS


# 阶段3.5: PASS后进入现场验收

@app.post("/api/tasks/{task_id}/advance-to-acceptance", response_model=TaskResponse)
def advance_to_acceptance(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    PASS后释放30%锁定资金，进入ACCEPTANCE现场验收阶段
    与Fund.advanceToAcceptance对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.PASS.value:
        raise HTTPException(400, "项目状态非PASS")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    release = BASE_DEPOSIT * PASS_RELEASE_RATIO
    if manufacturer:
        manufacturer.balance += release
        manufacturer.locked_balance -= release
        task.mfr_locked -= release
    if supplier:
        supplier.balance += release
        supplier.locked_balance -= release
        task.sup_locked -= release

    task.status = TaskStatus.ACCEPTANCE.value
    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.FUNDS_RELEASED.value,
        task_id=task.id,
        data_json={
            "to_manufacturer": float(release) if manufacturer else 0,
            "to_supplier": float(release) if supplier else 0,
            "reason": "pass_advance_to_acceptance"
        }
    )

    return task


# 阶段4: 线上申诉后处理

@app.post("/api/tasks/{task_id}/complete-reject", response_model=TaskResponse)
def complete_reject(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    REJECT申诉期结束后，任何人可调用完成
    与Fund.completeReject对齐：双方退还锁定资金
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.REJECT.value:
        raise HTTPException(400, "项目状态非REJECT")
    if not task.appeal_deadline or datetime.utcnow() <= task.appeal_deadline:
        raise HTTPException(400, "申诉期尚未结束")

    # 退还双方锁定资金
    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()
    if manufacturer and task.mfr_locked:
        manufacturer.balance += task.mfr_locked
        manufacturer.locked_balance -= task.mfr_locked
    if supplier and task.sup_locked:
        supplier.balance += task.sup_locked
        supplier.locked_balance -= task.sup_locked

    _finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=False)
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return task


@app.post("/api/tasks/{task_id}/complete-slash", response_model=TaskResponse)
def complete_slash(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    SLASH申诉期结束后，任何人可调用完成
    与Fund.completeSlash对齐：
    1.制造商拿回全部锁定资金+10%供应商补偿
    2.剩余90%供应商资金入系统池
    3.供应商信誉积分-10
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.SLASH.value:
        raise HTTPException(400, "项目状态非SLASH")
    if not task.appeal_deadline or datetime.utcnow() <= task.appeal_deadline:
        raise HTTPException(400, "申诉期尚未结束")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    # 计算补偿
    compensation = task.sup_locked * SLASH_COMPENSATION_RATIO
    system_pool = task.sup_locked - compensation

    # 制造商拿回全部+补偿
    if manufacturer:
        manufacturer.balance += task.mfr_locked + compensation
        manufacturer.locked_balance -= task.mfr_locked

    # 系统池（给平台/admin）
    admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
    if admin:
        admin.balance += system_pool

    # 供应商清空锁定
    if supplier:
        supplier.locked_balance -= task.sup_locked

    _finalize_task(db, task, is_success=False, supplier_slash=True, manufacturer_slash=False)
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return task


# 阶段5: 现场验收（与Settlement.sol对齐）

@app.post("/api/tasks/{task_id}/submit-completion", response_model=TaskResponse)
def submit_completion(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    供应商提交"部署完成"，与Fund.submitCompletion/Settlement.submitSupplierCompletion对齐
    触发72h现场验收等待期
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.ACCEPTANCE.value:
        raise HTTPException(400, "项目状态非ACCEPTANCE")
    if current_user.id != task.supplier_id:
        raise HTTPException(403, "仅供应商可提交")
    if task.supplier_submitted:
        raise HTTPException(400, "已提交过")

    task.supplier_submitted = True
    task.onsite_deadline = datetime.utcnow() + timedelta(seconds=ONSITE_TIMEOUT_SECONDS)

    # 重置确认状态（支持整改后重新验收）
    task.mfr_confirmed = False
    task.sup_confirmed = False
    task.mfr_satisfied = False
    task.sup_satisfied = False

    # 初始化onsite_record
    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    if not onsite:
        onsite = OnsiteRecord(task_id=task_id, local_status=OnsiteLocalStatus.ONGOING.value)
        db.add(onsite)
    else:
        onsite.local_status = OnsiteLocalStatus.ONGOING.value

    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.SUPPLIER_SUBMITTED_COMPLETION.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"onsite_deadline": task.onsite_deadline.isoformat()}
    )

    return task


@app.post("/api/tasks/{task_id}/confirm-onsite", response_model=TaskResponse)
def confirm_onsite(
    task_id: int,
    payload: FieldSignPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    现场验收确认，与Fund.confirmOnsite/Settlement对齐
    制造商和供应商分别调用
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status not in [TaskStatus.ACCEPTANCE.value, TaskStatus.RECTIFICATION.value]:
        raise HTTPException(400, "当前状态不允许现场确认")
    if not task.supplier_submitted:
        raise HTTPException(400, "供应商尚未提交完成")

    is_manufacturer = current_user.id == task.manufacturer_id
    is_supplier = current_user.id == task.supplier_id
    if not is_manufacturer and not is_supplier:
        raise HTTPException(403, "仅项目相关方可操作")

    # 回填现场实测指标
    if payload.field_actual_fnr is not None:
        task.field_actual_fnr = payload.field_actual_fnr
    if payload.field_actual_fpr is not None:
        task.field_actual_fpr = payload.field_actual_fpr
    if payload.field_actual_latency is not None:
        task.field_actual_latency = payload.field_actual_latency
    if payload.field_actual_map is not None:
        task.field_actual_map = payload.field_actual_map
    if payload.field_actual_f1 is not None:
        task.field_actual_f1 = payload.field_actual_f1
    if payload.field_environment_notes:
        task.field_environment_notes = payload.field_environment_notes
    if payload.evidence_hash:
        task.field_evidence_hash = payload.evidence_hash

    # 获取或创建onsite_record
    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    if not onsite:
        onsite = OnsiteRecord(task_id=task_id)
        db.add(onsite)

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    if is_manufacturer:
        # 制造商确认
        if task.mfr_confirmed:
            raise HTTPException(400, "制造商已确认")
        task.mfr_confirmed = True
        task.mfr_satisfied = payload.satisfied
        onsite.mfr_satisfied = payload.satisfied
        onsite.mfr_measured_map = payload.measured_map
        onsite.mfr_evidence_hash = payload.evidence_hash

        if not payload.satisfied:
            # 制造商拒绝，等待供应商回应（不立即改状态）
            _insert_chain_event(
                db,
                event_type=ChainEventType.MANUFACTURER_REJECTED.value,
                task_id=task.id,
                sender_address=current_user.wallet_address,
                data_json={"onsite_deadline": task.onsite_deadline.isoformat() if task.onsite_deadline else None}
            )
            db.commit()
            return task

    else:
        # 供应商确认
        if task.sup_confirmed:
            raise HTTPException(400, "供应商已确认")

        # 如果制造商已拒绝，供应商的satisfied语义重载
        if task.mfr_confirmed and not task.mfr_satisfied:
            task.sup_confirmed = True
            onsite.sup_satisfied = payload.satisfied
            onsite.sup_measured_map = payload.measured_map
            onsite.sup_evidence_hash = payload.evidence_hash

            if payload.satisfied:
                # 供应商接受整改 → 进入整改期
                _enter_rectification(db, task, onsite)
            else:
                # 供应商不认同 → 提起现场申诉
                task.status = TaskStatus.DISPUTED_FIELD.value
                task.sup_satisfied = False

            db.commit()
            db.refresh(task)
            return task

        # 正常流程：制造商已满意或尚未确认
        task.sup_confirmed = True
        task.sup_satisfied = payload.satisfied
        onsite.sup_satisfied = payload.satisfied
        onsite.sup_measured_map = payload.measured_map
        onsite.sup_evidence_hash = payload.evidence_hash

    # 双方都确认且都满意 → 完成
    if task.mfr_confirmed and task.sup_confirmed and task.mfr_satisfied and task.sup_satisfied:
        # 释放双方剩余锁定资金
        if manufacturer and task.mfr_locked:
            manufacturer.balance += task.mfr_locked
            manufacturer.locked_balance -= task.mfr_locked
        if supplier and task.sup_locked:
            supplier.balance += task.sup_locked
            supplier.locked_balance -= task.sup_locked

        # 退还延期费
        if task.extension_deposit > 0 and supplier:
            supplier.balance += task.extension_deposit

        onsite.local_status = OnsiteLocalStatus.CONFIRMED.value
        onsite.confirm_time = datetime.utcnow()

        # 生成确认Hash（与Settlement._uploadOnsiteEvidence 对齐）
        # 包含双方实测mAP值，与合约keccak256(abi.encodePacked(...)) 逻辑对应
        import hashlib
        confirm_data = (
            f"{task.manufacturer_id}:"
            f"{task.supplier_id}:"
            f"{onsite.mfr_satisfied}:"
            f"{onsite.sup_satisfied}:"
            f"{onsite.mfr_measured_map or 0}:"
            f"{onsite.sup_measured_map or 0}:"
            f"{datetime.utcnow().isoformat()}"
        )
        onsite.confirm_hash = "0x" + hashlib.sha256(confirm_data.encode()).hexdigest()[:64]

        _finalize_task(db, task, is_success=True, supplier_slash=False, manufacturer_slash=False)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return task


def _enter_rectification(db: Session, task: AuditTask, onsite: OnsiteRecord):
    """进入整改期，与Fund._enterRectification对齐
    
    合约行为：
      t.status = STATUS_RECTIFICATION
      t.rectificationDeadline = now + RECTIFICATION_PERIOD
      t.rectificationCount = 0
      // 重置确认状态，整改完重新验收
      t.mfrConfirmed = false
      t.supConfirmed = false
      t.mfrSatisfied = false
      t.supSatisfied = false
      t.supplierSubmitted = false
    """
    task.status = TaskStatus.RECTIFICATION.value
    task.rectification_deadline = datetime.utcnow() + timedelta(seconds=RECTIFICATION_PERIOD_SECONDS)
    task.rectification_count = 0

    # 重置确认状态，整改完重新验收
    task.mfr_confirmed = False
    task.sup_confirmed = False
    task.mfr_satisfied = False
    task.sup_satisfied = False
    task.supplier_submitted = False  # 与合约对齐，整改后需要供应商重新提交完成

    # 重置onsite记录
    onsite.local_status = OnsiteLocalStatus.RECTIFYING.value
    # 清除旧的现场实测数据（保留历史记录也行，后面再说）
    onsite.mfr_measured_map = None
    onsite.sup_measured_map = None
    onsite.mfr_evidence_hash = None
    onsite.sup_evidence_hash = None
    onsite.mfr_satisfied = False
    onsite.sup_satisfied = False
    onsite.confirm_hash = None
    onsite.confirm_time = None

    _insert_chain_event(
        db,
        event_type=ChainEventType.SUPPLIER_ACCEPTED_RECTIFICATION.value,
        task_id=task.id,
        data_json={"rectification_deadline": task.rectification_deadline.isoformat()}
    )


@app.post("/api/tasks/{task_id}/timeout-auto-pass", response_model=TaskResponse)
def timeout_auto_pass(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    制造商72h无响应，自动通过，与Fund.timeoutAutoPass对齐
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.ACCEPTANCE.value:
        raise HTTPException(400, "项目状态非ACCEPTANCE")
    if not task.supplier_submitted:
        raise HTTPException(400, "供应商尚未提交")
    if not task.onsite_deadline or datetime.utcnow() <= task.onsite_deadline:
        raise HTTPException(400, "超时未到达")
    if task.mfr_confirmed and not task.mfr_satisfied:
        raise HTTPException(400, "制造商已拒绝，不可自动通过")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    # 释放双方剩余锁定资金
    if manufacturer and task.mfr_locked:
        manufacturer.balance += task.mfr_locked
        manufacturer.locked_balance -= task.mfr_locked
    if supplier and task.sup_locked:
        supplier.balance += task.sup_locked
        supplier.locked_balance -= task.sup_locked

    # 退还延期费
    if task.extension_deposit > 0 and supplier:
        supplier.balance += task.extension_deposit

    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    if onsite:
        onsite.local_status = OnsiteLocalStatus.TIMEOUT.value
        onsite.confirm_time = datetime.utcnow()

        # 生成超时自动通过的确认Hash（与Settlement._uploadOnsiteEvidence对齐）
        # 包含双方实测mAP值
        import hashlib
        confirm_data = (
            f"TIMEOUT_AUTO_PASS:"
            f"{task.manufacturer_id}:"
            f"{task.supplier_id}:"
            f"{onsite.mfr_satisfied}:"
            f"{onsite.sup_satisfied}:"
            f"{onsite.mfr_measured_map or 0}:"
            f"{onsite.sup_measured_map or 0}:"
            f"{datetime.utcnow().isoformat()}"
        )
        onsite.confirm_hash = "0x" + hashlib.sha256(confirm_data.encode()).hexdigest()[:64]

    _finalize_task(db, task, is_success=True, supplier_slash=False, manufacturer_slash=False)
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return task


# 阶段6: 整改与最终清算

@app.post("/api/tasks/{task_id}/request-extension", response_model=TaskResponse)
def request_extension(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    整改延期申请，与Fund.requestExtension对齐
    整改期内，供应商最多申请2次延期，每次补交质押金
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.RECTIFICATION.value:
        raise HTTPException(400, "项目状态非整改中")
    if current_user.id != task.supplier_id:
        raise HTTPException(403, "仅供应商可申请延期")
    if task.rectification_count >= MAX_EXTENSIONS:
        raise HTTPException(400, f"最多延期 {MAX_EXTENSIONS} 次")
    if not task.rectification_deadline or datetime.utcnow() > task.rectification_deadline:
        raise HTTPException(400, "整改期已结束")

    if current_user.balance < EXTENSION_FEE:
        raise HTTPException(400, f"余额不足，需要 {EXTENSION_FEE}")

    # 扣延期费
    current_user.balance -= EXTENSION_FEE
    task.extension_deposit += EXTENSION_FEE
    task.rectification_count += 1
    task.rectification_deadline = task.rectification_deadline + timedelta(seconds=RECTIFICATION_PERIOD_SECONDS)

    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.EXTENSION_REQUESTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"extension_count": task.rectification_count, "fee": EXTENSION_FEE}
    )

    return task


@app.post("/api/tasks/{task_id}/submit-rectification", response_model=TaskResponse)
def submit_rectification(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    提交整改完成，与Fund.submitRectification 齐
    回到ACCEPTANCE，重置验收流程
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.RECTIFICATION.value:
        raise HTTPException(400, "项目状态非整改中")
    if current_user.id != task.supplier_id:
        raise HTTPException(403, "仅供应商可提交整改")
    if not task.rectification_deadline or datetime.utcnow() > task.rectification_deadline:
        raise HTTPException(400, "整改期已结束")

    task.status = TaskStatus.ACCEPTANCE.value
    task.onsite_deadline = datetime.utcnow() + timedelta(seconds=ONSITE_TIMEOUT_SECONDS)
    task.supplier_submitted = True
    task.mfr_confirmed = False
    task.sup_confirmed = False
    task.mfr_satisfied = False
    task.sup_satisfied = False

    onsite = db.query(OnsiteRecord).filter(OnsiteRecord.task_id == task_id).first()
    if onsite:
        onsite.local_status = OnsiteLocalStatus.ONGOING.value

    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.RECTIFICATION_SUBMITTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"action": "submitted"}
    )

    return task


# 已合并到/initiate-field-appeal
# escalate-field-dispute的功能已合并到initiate-field-appeal中
# 整改期结束后，任一方调用/initiate-field-appeal即可自动升级状态并创建申诉记录
# 保留此接口作为向后兼容的快捷方式（直接调用initiate-field-appeal的逻辑）
@app.post("/api/tasks/{task_id}/escalate-field-dispute", response_model=TaskResponse)
def escalate_field_dispute(
    task_id: int,
    payload: EscalateFieldDisputePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    整改期结束后升级现场争议状态，与Fund.escalateToFieldDispute对齐
    实际逻辑已合并到/initiate-field-appeal，本接口仅做状态升级，不创建Appeal记录
    建议前端统一使用/initiate-field-appeal
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status != TaskStatus.RECTIFICATION.value:
        raise HTTPException(400, "项目状态非整改中")
    if current_user.id not in [task.manufacturer_id, task.supplier_id]:
        raise HTTPException(403, "仅项目相关方可操作")
    if not task.rectification_deadline or datetime.utcnow() <= task.rectification_deadline:
        raise HTTPException(400, "整改期尚未结束")

    task.status = TaskStatus.DISPUTED_FIELD.value
    task.dispute_reason = payload.reason
    task.dispute_at = datetime.utcnow()

    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.FIELD_DISPUTE_ESCALATED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"reason": payload.reason, "note": "兼容接口，建议改用 /initiate-field-appeal"}
    )

    return task


# 申诉接口，与Dispute.sol对齐

@app.post("/api/tasks/{task_id}/start-appeal", response_model=TaskResponse)
def start_appeal(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    供应商发起线上审计申诉，与Dispute.initiateAuditAppeal/Fund.startAppeal对齐
    将REJECT/SLASH状态变更为DISPUTED_AUDIT
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if current_user.id != task.supplier_id:
        raise HTTPException(403, "仅供应商可发起线上申诉")
    if task.status not in [TaskStatus.REJECT.value, TaskStatus.SLASH.value]:
        raise HTTPException(400, "当前状态不允许发起申诉")
    if not task.appeal_deadline or datetime.utcnow() > task.appeal_deadline:
        raise HTTPException(400, "申诉期已结束")

    task.status_before_appeal = task.status
    task.status = TaskStatus.DISPUTED_AUDIT.value
    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.APPEAL_STARTED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"deadline": task.appeal_deadline.isoformat() if task.appeal_deadline else None}
    )

    return task


@app.post("/api/tasks/{task_id}/initiate-field-appeal", response_model=TaskResponse)
def initiate_field_appeal(
    task_id: int,
    payload: EscalateFieldDisputePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    发起现场履约申诉，与Dispute.initiateFieldAppeal对齐
    整改期结束后，任一方可将争议升级至DISPUTED_FIELD
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if current_user.id not in [task.manufacturer_id, task.supplier_id]:
        raise HTTPException(403, "仅项目相关方可发起现场申诉")
    if task.status not in [TaskStatus.RECTIFICATION.value, TaskStatus.DISPUTED_FIELD.value]:
        raise HTTPException(400, "当前状态不允许现场申诉")
    if task.status == TaskStatus.RECTIFICATION.value:
        if not task.rectification_deadline or datetime.utcnow() <= task.rectification_deadline:
            raise HTTPException(400, "整改期尚未结束")
        task.status = TaskStatus.DISPUTED_FIELD.value

    task.dispute_reason = payload.reason
    task.dispute_at = datetime.utcnow()
    db.commit()
    db.refresh(task)

    _insert_chain_event(
        db,
        event_type=ChainEventType.FIELD_APPEAL_INITIATED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"reason": payload.reason}
    )

    return task


@app.post("/api/appeals", response_model=AppealResponse)
def create_appeal(
    payload: AppealCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    创建申诉记录，与Dispute.initiateAuditAppeal/initiateFieldAppeal对齐
    线上申诉需先调用/start-appeal，再调用本接口创建申诉记录
    """
    task = db.query(AuditTask).filter(AuditTask.id == payload.task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if current_user.id not in [task.manufacturer_id, task.supplier_id]:
        raise HTTPException(403, "仅项目相关方可申诉")

    # 校验申诉类型与当前状态匹配
    if payload.appeal_type in [AppealType.AUDIT_REJECT, AppealType.AUDIT_SLASH]:
        # 线上申诉：仅供应商可在 DISPUTED_AUDIT 状态下发起
        if task.status != TaskStatus.DISPUTED_AUDIT.value:
            raise HTTPException(400, "当前状态不允许线上申诉，请先调用 /start-appeal")
        if current_user.id != task.supplier_id:
            raise HTTPException(403, "仅供应商可对审计结果申诉")
    else:
        # 现场申诉：任一方可在RECTIFICATION（整改期结束后）或DISPUTED_FIELD状态下发起
        if task.status not in [TaskStatus.RECTIFICATION.value, TaskStatus.DISPUTED_FIELD.value]:
            raise HTTPException(400, "当前状态不允许现场申诉")
        if task.status == TaskStatus.RECTIFICATION.value:
            if not task.rectification_deadline or datetime.utcnow() <= task.rectification_deadline:
                raise HTTPException(400, "整改期尚未结束")
            task.status = TaskStatus.DISPUTED_FIELD.value

    appeal = Appeal(
        task_id=payload.task_id,
        appeal_type=payload.appeal_type.value,
        reason=payload.reason,
        evidence_hash=payload.evidence_hash,
        status=AppealStatus.PENDING.value
    )
    db.add(appeal)

    task.dispute_type = payload.appeal_type.value
    task.dispute_reason = payload.reason
    task.dispute_at = datetime.utcnow()

    db.commit()
    db.refresh(appeal)
    return appeal


@app.get("/api/appeals", response_model=list[AppealResponse])
def list_appeals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询申诉记录"""
    user_tasks = db.query(AuditTask.id).filter(
        (AuditTask.manufacturer_id == current_user.id) | (AuditTask.supplier_id == current_user.id)
    ).subquery()
    return db.query(Appeal).filter(Appeal.task_id.in_(user_tasks)).order_by(Appeal.created_at.desc()).all()


@app.get("/api/appeals/pending", response_model=list[PendingAppealResponse])
def list_pending_appeals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """ADMIN查询所有待仲裁申诉"""
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可查看待仲裁列表")

    appeals = db.query(Appeal).filter(
        Appeal.status.in_([AppealStatus.PENDING.value, AppealStatus.ARBITRATING.value])
    ).order_by(Appeal.created_at.desc()).all()

    result = []
    for appeal in appeals:
        task = db.query(AuditTask).filter(AuditTask.id == appeal.task_id).first()
        manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first() if task else None
        supplier = db.query(User).filter(User.id == task.supplier_id).first() if task else None
        arbitrator = db.query(User).filter(User.id == appeal.arbitrator_id).first() if appeal.arbitrator_id else None

        result.append(PendingAppealResponse(
            id=appeal.id,
            task_id=appeal.task_id,
            appeal_type=appeal.appeal_type,
            status=appeal.status,
            reason=appeal.reason,
            evidence_hash=appeal.evidence_hash,
            arbitrator_id=appeal.arbitrator_id,
            liable_party=appeal.liable_party,
            resolution=appeal.resolution,
            refund_amount=float(appeal.refund_amount) if appeal.refund_amount else None,
            verdict=appeal.verdict,
            created_at=appeal.created_at,
            resolved_at=appeal.resolved_at,
            task_name=task.task_name if task else None,
            task_hash=task.task_hash if task else None,
            manufacturer_name=manufacturer.display_name if manufacturer else None,
            supplier_name=supplier.display_name if supplier else None,
            manufacturer_margin=float(task.mfr_locked) if task else None,
            supplier_margin=float(task.sup_locked) if task else None,
            task_status=task.status if task else None,
        ))
    return result


@app.post("/api/appeals/{appeal_id}/assign-arbitrator", response_model=AppealResponse)
def assign_arbitrator(
    appeal_id: int,
    payload: AssignArbitratorPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    指派仲裁员，与Dispute.assignArbitrator对齐
    同时触发Fund.enterArbitration
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可指派仲裁员")

    appeal = db.query(Appeal).filter(Appeal.id == appeal_id).first()
    if not appeal:
        raise HTTPException(404, "申诉不存在")
    if appeal.status != AppealStatus.PENDING.value:
        raise HTTPException(400, "该申诉不可指派仲裁员")

    arbitrator = db.query(User).filter(User.id == payload.arbitrator_id).first()
    if not arbitrator:
        raise HTTPException(404, "仲裁员不存在")

    appeal.arbitrator_id = payload.arbitrator_id
    appeal.status = AppealStatus.ARBITRATING.value

    task = db.query(AuditTask).filter(AuditTask.id == appeal.task_id).first()
    if task:
        task.status = TaskStatus.ARBITRATING.value

    db.commit()
    db.refresh(appeal)
    return appeal


@app.post("/api/appeals/{appeal_id}/resolve", response_model=AppealResponse)
def resolve_appeal(
    appeal_id: int,
    payload: AppealResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    协会仲裁裁决，与Dispute.submitAuditArbitration/submitFieldArbitration对齐
    严格按合约规则执行资金结算
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅协会管理员可执行仲裁")

    appeal = db.query(Appeal).filter(Appeal.id == appeal_id).first()
    if not appeal:
        raise HTTPException(404, "申诉不存在")
    if appeal.status != AppealStatus.ARBITRATING.value:
        raise HTTPException(400, "该申诉尚未进入仲裁状态")

    task = db.query(AuditTask).filter(AuditTask.id == appeal.task_id).first()
    if not task:
        raise HTTPException(404, "关联项目不存在")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    appeal.verdict = payload.result
    appeal.resolution = payload.resolution
    appeal.status = AppealStatus.RESOLVED.value
    appeal.resolved_at = datetime.utcnow()

    # 根据申诉类型和结果执行不同结算
    if appeal.appeal_type in [AppealType.AUDIT_REJECT.value, AppealType.AUDIT_SLASH.value]:
        # 线上申诉结算，与Fund.settleAppeal对齐
        _resolve_audit_appeal(db, task, appeal, payload.result, manufacturer, supplier)
    else:
        # 现场申诉结算，与Fund.settleFieldDispute对齐
        _resolve_field_appeal(db, task, appeal, payload.result, manufacturer, supplier)

    _insert_chain_event(
        db,
        event_type=ChainEventType.APPEAL_SETTLED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={
            "appeal_id": appeal.id,
            "result": payload.result,
            "resolution": payload.resolution,
            "appeal_type": appeal.appeal_type
        }
    )

    db.commit()
    db.refresh(appeal)
    return appeal


@app.post("/api/appeals/{appeal_id}/evidence")
def upload_appeal_evidence(
    appeal_id: int,
    payload: UploadAppealEvidencePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    上传申诉证据，与Dispute.uploadAppealEvidence对齐
    仅申诉发起人、被指派的仲裁员或管理员可上传
    """
    appeal = db.query(Appeal).filter(Appeal.id == appeal_id).first()
    if not appeal:
        raise HTTPException(404, "申诉不存在")

    task = db.query(AuditTask).filter(AuditTask.id == appeal.task_id).first()
    if not task:
        raise HTTPException(404, "关联项目不存在")

    # 权限校验：发起人、仲裁员、管理员
    is_initiator = current_user.id in [task.manufacturer_id, task.supplier_id]
    is_arbitrator = appeal.arbitrator_id == current_user.id
    is_admin = current_user.role == UserRole.ADMIN.value

    if not (is_initiator or is_arbitrator or is_admin):
        raise HTTPException(403, "无权上传申诉证据")

    appeal.evidence_hash = payload.evidence_hash
    db.commit()
    db.refresh(appeal)

    _insert_chain_event(
        db,
        event_type=ChainEventType.APPEAL_EVIDENCE_UPLOADED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"appeal_id": appeal.id, "evidence_hash": payload.evidence_hash}
    )

    return appeal


def _resolve_audit_appeal(db, task, appeal, result, manufacturer, supplier):
    """线上申诉结算，对应Fund.settleAppeal"""
    if result == 1:
        # 维持原判
        if appeal.appeal_type == AppealType.AUDIT_REJECT.value:
            # REJECT维持：双方退还
            if manufacturer and task.mfr_locked:
                manufacturer.balance += task.mfr_locked
                manufacturer.locked_balance -= task.mfr_locked
            if supplier and task.sup_locked:
                supplier.balance += task.sup_locked
                supplier.locked_balance -= task.sup_locked
            _finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=False)
        else:
            # SLASH维持：供应商罚没
            compensation = task.sup_locked * SLASH_COMPENSATION_RATIO
            system_pool = task.sup_locked - compensation
            if manufacturer:
                manufacturer.balance += task.mfr_locked + compensation
                manufacturer.locked_balance -= task.mfr_locked
            admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
            if admin:
                admin.balance += system_pool
            if supplier:
                supplier.locked_balance -= task.sup_locked
            _finalize_task(db, task, is_success=False, supplier_slash=True, manufacturer_slash=False)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.utcnow()

    elif result == 2:
        # REJECT → PASS 反转：与Fund.settleAppeal对齐
        # 合约行为：status = PASS，由前端后续调用advance-to-acceptance释放资金
        task.status = TaskStatus.PASS.value

    elif result == 3:
        # SLASH反转（制造商投毒）
        if supplier and task.sup_locked:
            supplier.balance += task.sup_locked + task.mfr_locked
            supplier.locked_balance -= task.sup_locked
        if manufacturer and task.mfr_locked:
            manufacturer.locked_balance -= task.mfr_locked
        # 制造商出险计数
        if manufacturer:
            manufacturer.claim_count += 1
        _finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=True)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.utcnow()


def _resolve_field_appeal(db, task, appeal, result, manufacturer, supplier):
    """现场申诉结算，对应Fund.settleFieldDispute
    
    与动态质押对齐：
    1.履约降级：扣供应商锁定金额的30%（而非固定300）
    2.恶意违约：扣供应商锁定金额的10% 给制造商，90%入系统池
    """
    if result == 1:
        # 履约降级：扣供应商锁定金额的30%补偿制造商
        # 比如锁定1000 → 扣300；锁定1500 → 扣450；锁定2000 → 扣600
        compensation = task.sup_locked * 0.30
        if manufacturer:
            manufacturer.balance += task.mfr_locked
            manufacturer.locked_balance -= task.mfr_locked
            if task.sup_locked >= compensation:
                manufacturer.balance += compensation
        if supplier and task.sup_locked:
            supplier.balance += max(0, task.sup_locked - compensation)
            supplier.locked_balance -= task.sup_locked

        # 延期费没收
        if task.extension_deposit > 0:
            admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
            if admin:
                admin.balance += task.extension_deposit

        _finalize_task(db, task, is_success=False, supplier_slash=False, manufacturer_slash=False)

    elif result == 2:
        # 恶意违约：供应商现场锁定全部罚没，10%给制造商，90%入系统池
        if manufacturer:
            manufacturer.balance += task.mfr_locked
            manufacturer.locked_balance -= task.mfr_locked
            compensation = task.sup_locked * SLASH_COMPENSATION_RATIO
            manufacturer.balance += compensation
        admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if admin and task.sup_locked:
            system_pool = task.sup_locked - (task.sup_locked * SLASH_COMPENSATION_RATIO)
            admin.balance += system_pool
        if supplier and task.sup_locked:
            supplier.locked_balance -= task.sup_locked

        # 延期费没收
        if task.extension_deposit > 0:
            if admin:
                admin.balance += task.extension_deposit

        _finalize_task(db, task, is_success=False, supplier_slash=True, manufacturer_slash=False)

    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()


# 审计报告PDF生成（预留接口，还没做hhh）
# 功能划分:
#   1.audit.py: 只负责审计计算，输出JSON指标数据
#   2.后端: 整合项目信息，调用audit.py，拿到数据后传给report.py并生成PDF
#   3.前端: 下载/预览PDF
#
# 生成流程:
#   1.审计节点提交报告时，后端保存指标到task_reports表
#   2.用户请求下载PDF时，后端从数据库读取指标+项目信息
#   3.后端调用report.py生成PDF报告（含企业名、链上哈希、时间戳等）
#   4.返回PDF文件流给前端下载
#
# 文件位置:
#   1.PDF生成逻辑: backend/report_generator.py（新增文件）
#   2.PDF模板: 没想好
#   3.生成的PDF缓存: backend/reports/（避免重复生成）


@app.get("/api/tasks/{task_id}/report/pdf")
def download_audit_report_pdf(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    下载审计报告PDF，预留接口
    权限: 项目相关方（制造商、供应商、审计节点）或ADMIN
    返回: PDF文件流 (Content-Type: application/pdf)
    
    实现步骤:
      1.校验权限（项目相关方可下载）
      2.从task_reports表读取审计指标
      3.从audit_tasks与users表读取项目信息和企业名称
      4.调用report_generator.generate_pdf(task_id)生成PDF
      5.返回StreamingResponse(pdf_bytes, media_type="application/pdf")
    """
    # 权限校验=
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    
    is_party = current_user.id in [task.manufacturer_id, task.supplier_id, task.auditor_id]
    is_admin = current_user.role == UserRole.ADMIN.value
    if not is_party and not is_admin:
        raise HTTPException(403, "仅项目相关方可下载审计报告")
    
    # 检查报告是否存在
    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    if not report:
        raise HTTPException(404, "审计报告尚未生成")
    
    # TODO:生成 PDF
    # from report_generator import AuditReportGenerator
    # generator = AuditReportGenerator(task_id, db)
    # pdf_bytes = generator.generate_pdf()
    # 
    # return StreamingResponse(
    #     io.BytesIO(pdf_bytes),
    #     media_type="application/pdf",
    #     headers={"Content-Disposition": f"attachment; filename=audit_report_{task_id}.pdf"}
    # )
    
    raise HTTPException(501, "审计报告PDF生成功能尚未实现")


@app.post("/api/tasks/{task_id}/report/pdf/generate")
def generate_audit_report_pdf(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    手动触发审计报告PDF生成（ADMIN或审计节点用），预留接口
    场景:
      1.审计节点提交报告后，自动触发PDF生成
      2.或ADMIN手动重新生成PDF
    
    实现步骤:
      1. 校验权限（ADMIN或审计节点）
      2. 调用report_generator.generate_pdf(task_id)
      3. 保存PDF到本地缓存（backend/reports/）
      4. 返回生成结果
    """
    if current_user.role not in [UserRole.ADMIN.value, UserRole.AUDITOR.value]:
        raise HTTPException(403, "仅系统管理员或审计节点可生成报告")
    
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    
    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    if not report:
        raise HTTPException(404, "审计报告尚未提交")
    
    # TODO: 生成并保存PDF
    # from report_generator import AuditReportGenerator
    # generator = AuditReportGenerator(task_id, db)
    # pdf_bytes = generator.generate_pdf()
    # 
    # # 保存到本地
    # import os
    # os.makedirs("reports", exist_ok=True)
    # filepath = f"reports/audit_report_{task_id}.pdf"
    # with open(filepath, "wb") as f:
    #     f.write(pdf_bytes)
    # 
    # return {"message": "PDF生成成功", "filepath": filepath, "size": len(pdf_bytes)}
    
    raise HTTPException(501, "审计报告PDF生成功能尚未实现")


# 链上事件查询

@app.get("/api/chain-events", response_model=list[ChainEventResponse])
def list_chain_events(
    task_id: Optional[int] = None,
    event_type: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """链上查询页面：查询链上事件列表"""
    query = db.query(ChainEvent)
    if task_id:
        query = query.filter(ChainEvent.task_id == task_id)
    if event_type:
        query = query.filter(ChainEvent.event_type == event_type)

    return query.order_by(ChainEvent.created_at.desc()).offset((page-1)*limit).limit(limit).all()


# 审计报告与日志

@app.get("/api/tasks/{task_id}/report", response_model=ReportResponse)
def get_report(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取审计报告指标"""
    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    if not report:
        raise HTTPException(404, "报告不存在")
    return report


@app.get("/api/tasks/{task_id}/audit-logs", response_model=list[AuditLogResponse])
def get_audit_logs(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """监控大屏左侧终端的日志"""
    logs = db.query(AuditLog).filter(AuditLog.task_id == task_id).order_by(AuditLog.created_at.asc()).all()
    if logs:
        return logs
    # Mock 返回固定日志流
    return [
        {"id": 0, "task_id": task_id, "log_type": "[SYS]", "message": "初始化 Clarity Audit Engine v2.1.0", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[DONE]", "message": "准确度审计: 漏杀率=0.2%, 误杀率=3.4%", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[INFO]", "message": "协商指标: mAP=87.3%, F1=0.84", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[DONE]", "message": "注意力审计: 6个TP, 平均CR=41.5%", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[DONE]", "message": "置信度审计: 3组样本, Arrogance=12%", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[DONE]", "message": "审计完成: 综合判定 PASS", "created_at": None},
    ]


# 区块链接口

@app.get("/api/chain/health")
def chain_health():
    """检查 WeBASE-Front 连通性"""
    stats = get_chain_stats()
    return {"connected": stats.get("connected", False), "error": stats.get("error")}


@app.get("/api/chain/stats", response_model=ChainStatsResponse)
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


@app.get("/api/chain/events", response_model=list[ChainEventResponse])
def list_chain_events_v2(
    task_id: Optional[int] = None,
    event_type: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询链上事件列表（支持分页和筛选）"""
    query = db.query(ChainEvent)
    if task_id:
        query = query.filter(ChainEvent.task_id == task_id)
    if event_type:
        query = query.filter(ChainEvent.event_type == event_type)

    return query.order_by(ChainEvent.created_at.desc()).offset((page - 1) * limit).limit(limit).all()


@app.get("/api/chain/events/{tx_hash}", response_model=ChainEventResponse)
def get_chain_event_detail(
    tx_hash: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根据交易哈希查询单条链上事件详情"""
    event = db.query(ChainEvent).filter(ChainEvent.tx_hash == tx_hash).first()
    if not event:
        raise HTTPException(404, "交易不存在")
    return event


# 定时任务接口（手动触发，用于测试）

@app.post("/api/tasks/process-timeouts")
def process_timeouts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    手动触发超时处理（生产环境应由定时任务自动执行）
    处理以下超时场景：
    1.UPLOADING阶段3天超时 → CANCELED
    2.REJECT/SLASH申诉期3天超时 → COMPLETED
    3.ACCEPTANCE现场验收72h超时 → COMPLETED
    4.RECTIFICATION整改期7天超时 → DISPUTED_FIELD
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行")

    now = datetime.utcnow()
    processed = []

    # 1.UPLOADING超时
    uploading_tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.UPLOADING.value,
        AuditTask.first_prepared_at.isnot(None),
        AuditTask.mfr_prepared != AuditTask.sup_prepared  # 只有一方准备
    ).all()

    for task in uploading_tasks:
        deadline = task.first_prepared_at + timedelta(seconds=PREPARE_TIMEOUT_SECONDS)
        if now > deadline:
            # 自动退款给已准备的一方
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

            _finalize_task(db, task, False, False, False)
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

            _finalize_task(db, task, False, True, False)
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = now
            processed.append({"task_id": task.id, "action": "slash_appeal_timeout_completed"})

    # 4.ACCEPTANCE现场验收超时（制造商未响应）
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

            _finalize_task(db, task, True, False, False)
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = now
            processed.append({"task_id": task.id, "action": "onsite_timeout_auto_pass"})

    # 5.RECTIFICATION整改期超时 → DISPUTED_FIELD
    rect_tasks = db.query(AuditTask).filter(
        AuditTask.status == TaskStatus.RECTIFICATION.value,
        AuditTask.rectification_deadline.isnot(None)
    ).all()

    for task in rect_tasks:
        if now > task.rectification_deadline:
            task.status = TaskStatus.DISPUTED_FIELD.value

            _insert_chain_event(
                db,
                event_type=ChainEventType.FIELD_DISPUTE_ESCALATED.value,
                task_id=task.id,
                data_json={"reason": "rectification_timeout_escalated", "auto_processed": True}
            )

            processed.append({"task_id": task.id, "action": "rectification_timeout_escalated"})

    db.commit()
    return {"processed": processed, "count": len(processed)}


# 存证查询接口，与Evidence.sol对齐

@app.get("/api/tasks/{task_id}/evidence/data")
def get_evidence_data(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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


@app.get("/api/tasks/{task_id}/evidence/model")
def get_evidence_model(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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


@app.get("/api/tasks/{task_id}/evidence/audit")
def get_evidence_audit(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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


@app.get("/api/tasks/{task_id}/evidence/onsite")
def get_evidence_onsite(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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


@app.get("/api/tasks/{task_id}/evidence/appeal")
def get_evidence_appeal(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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


@app.get("/api/tasks/{task_id}/evidence/complete")
def is_evidence_complete(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询证据是否完整 - 对应 Evidence.isEvidenceComplete"""
    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    return {"complete": report is not None}


# 存证上传接口，与Evidence.sol对齐

@app.post("/api/tasks/{task_id}/evidence/onsite")
def upload_onsite_evidence(
    task_id: int,
    confirm_hash: str = Form(...),
    mfr_satisfied: bool = Form(...),
    sup_satisfied: bool = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    上传现场验收确认存证，与Evidence.uploadOnsiteConfirmation对齐
    由Settlement流程在双方确认完成后自动调用，或ADMIN手动补录
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    # 权限：项目相关方或ADMIN
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

    # 同步更新task状态
    task.mfr_satisfied = mfr_satisfied
    task.sup_satisfied = sup_satisfied

    db.commit()

    _insert_chain_event(
        db,
        event_type=ChainEventType.ONSITE_CONFIRMED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"confirm_hash": confirm_hash, "mfr_satisfied": mfr_satisfied, "sup_satisfied": sup_satisfied}
    )

    return {"message": "现场验收存证已上传", "confirm_hash": confirm_hash}


@app.post("/api/tasks/{task_id}/evidence/appeal")
def upload_appeal_evidence(
    task_id: int,
    evidence_hash: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    上传申诉证据存证，与Evidence.uploadAppealEvidence/Dispute.uploadAppealEvidence对齐
    申诉发起人、被指派的仲裁员或管理员可上传
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    appeal = db.query(Appeal).filter(Appeal.task_id == task_id).order_by(Appeal.created_at.desc()).first()

    # 权限校验：发起人、仲裁员、管理员
    is_initiator = current_user.id in [task.manufacturer_id, task.supplier_id]
    is_arbitrator = appeal and appeal.arbitrator_id == current_user.id
    is_admin = current_user.role == UserRole.ADMIN.value

    if not (is_initiator or is_arbitrator or is_admin):
        raise HTTPException(403, "无权上传申诉证据")

    if appeal:
        appeal.evidence_hash = evidence_hash
    else:
        # 如果没有Appeal记录，创建一个（用于整改超时后自动升级的场景）
        appeal = Appeal(
            task_id=task_id,
            appeal_type=AppealType.FIELD_DOWNGRADE.value,
            reason="现场争议证据上传（自动创建）",
            evidence_hash=evidence_hash,
            status=AppealStatus.PENDING.value
        )
        db.add(appeal)

    db.commit()

    _insert_chain_event(
        db,
        event_type=ChainEventType.APPEAL_EVIDENCE_UPLOADED.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"evidence_hash": evidence_hash, "appeal_id": appeal.id if appeal else None}
    )

    return {"message": "申诉证据已上传", "evidence_hash": evidence_hash}


# 紧急管理接口，与Fund.sol对齐

@app.post("/api/tasks/{task_id}/emergency-stop")
def emergency_stop(
    task_id: int,
    reason: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    紧急停止项目，与Fund.emergencyStop对齐
    仅ADMIN可操作，项目进入NONE状态（可后续用emergency-withdraw退款）
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行紧急停止")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    if task.status in [TaskStatus.COMPLETED.value, TaskStatus.CANCELED.value]:
        raise HTTPException(400, "项目已终态，不可停止")

    task.status = TaskStatus.CANCELED.value

    _insert_chain_event(
        db,
        event_type=ChainEventType.EMERGENCY_STOP.value,
        task_id=task.id,
        sender_address=current_user.wallet_address,
        data_json={"reason": reason}
    )

    db.commit()
    return {"message": "项目已紧急停止", "task_id": task_id, "reason": reason}


@app.post("/api/tasks/{task_id}/emergency-withdraw")
def emergency_withdraw(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    紧急撤回锁定资金，与Fund.emergencyWithdraw对齐
    仅ADMIN可操作，将项目所有锁定资金退回给原持有者
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行紧急撤回")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    manufacturer = db.query(User).filter(User.id == task.manufacturer_id).first()
    supplier = db.query(User).filter(User.id == task.supplier_id).first()

    # 退回制造商锁定资金
    if task.mfr_locked > 0 and manufacturer:
        manufacturer.balance += task.mfr_locked
        manufacturer.locked_balance -= task.mfr_locked
        task.mfr_locked = 0

    # 退回供应商锁定资金
    if task.sup_locked > 0 and supplier:
        supplier.balance += task.sup_locked
        supplier.locked_balance -= task.sup_locked
        task.sup_locked = 0

    # 退回延期费
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


# 合约部署管理接口（ADMIN 专用）
# 这些接口用于部署阶段配置合约地址，与Identity.sol/Fund.sol的管理函数对齐

# 导入链上交互工具
from chain import (
    call_contract_method,
    deploy_contract,
    set_trusted_contract,
    set_authorized_auditor,
    set_contract_address,
    query_contract_stake_ratio,
    query_identity_stake_ratio,
    query_trade_status,
    settle_reputation_onchain,
    update_claim_count_onchain,
    poll_transaction_status,
    CONTRACT_ABIS,
)


# 部署阶段1: 部署合约

@app.post("/api/admin/deploy-contract")
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
    
    Args:
        contract_name: 合约名称（identity/fund/audit/dispute/evidence/settlement）
        bytecode: 合约字节码（hex string，0x 开头）
        abi_json: 完整ABI JSON字符串（可选，使用内置ABI）
        constructor_params: 构造函数参数列表（可选）
    
    返回:
        {success, contract_address, tx_hash, error}
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可部署合约")
    
    import json
    
    # 获取ABI
    if abi_json:
        abi = json.loads(abi_json)
    else:
        abi = CONTRACT_ABIS.get(contract_name.lower())
        if not abi:
            raise HTTPException(400, f"未知合约: {contract_name}，请提供 abi_json")
    
    # 默认构造函数参数
    if constructor_params is None:
        constructor_params = []
        # Fund合约需要platformTreasury地址
        if contract_name.lower() == "fund":
            # 使用admin钱包作为platformTreasury（测试阶段）
            constructor_params = [current_user.wallet_address]
    
    # 部署合约
    result = deploy_contract(
        contract_name=contract_name,
        abi=abi,
        bytecode=bytecode,
        constructor_params=constructor_params,
        from_address=current_user.wallet_address,
        sign_user_id=f"clarity_admin_{current_user.account}"
    )
    
    if result["success"] and result["contract_address"]:
        # 自动保存合约地址到数据库
        key_map = {
            "identity": "identity_contract",
            "fund": "fund_contract",
            "audit": "audit_contract",
            "dispute": "appeal_contract",  # Dispute.sol 对应 appeal_contract
            "evidence": "evidence_contract",
            "settlement": "settlement_contract",
        }
        config_key = key_map.get(contract_name.lower())
        if config_key:
            _set_contract_config_in_db(db, config_key, result["contract_address"])
            db.commit()
        
        # 记录链上事件
        _insert_chain_event(
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


# 部署阶段2: 配置合约间关联

@app.post("/api/admin/setup-contract-links")
def admin_setup_contract_links(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    一键配置所有合约间的地址关联
    部署所有合约后调用，自动完成：
      1.Identity.setTrustedContract(Fund, Audit, Dispute, Evidence, Settlement)
      2.Fund.setIdentityContract / setEvidenceContract / setAuditContract / setAppealContract
      3.Audit.setFundContract / setEvidenceContract
      4.Dispute.setFundContract / setIdentityContract / setEvidenceContract
      5.Evidence.setFundContract / setAuditContract / setSettlementContract / setDisputeContract
      6.Settlement.setFundContract / setEvidenceContract
      7.Audit.setAuthorizedAuditor(审计节点)
    
    注意：需要admin的sign_user_id已注册到WeBASE-Front
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可配置")
    
    config = _get_contract_config_from_db(db)
    
    # 检查必要地址
    required = ["identity_contract", "fund_contract", "audit_contract", 
                "appeal_contract", "evidence_contract"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise HTTPException(400, f"缺少合约地址: {missing}，请先部署合约")
    
    admin_sign_user_id = f"clarity_admin_{current_user.account}"
    admin_addr = current_user.wallet_address
    
    results = []
    
    # 1.Identity: 设置可信合约
    for contract_key, name in [
        ("fund_contract", "Fund"),
        ("audit_contract", "Audit"),
        ("appeal_contract", "Dispute"),
        ("evidence_contract", "Evidence"),
    ]:
        addr = config.get(contract_key)
        if addr:
            r = set_trusted_contract(
                identity_contract=config["identity_contract"],
                target_contract=addr,
                status=True,
                admin_address=admin_addr,
                admin_sign_user_id=admin_sign_user_id
            )
            results.append({"step": f"Identity.setTrustedContract({name})", "result": r})
    
    # 2.Fund: 设置关联合约
    for method, contract_key in [
        ("setIdentityContract", "identity_contract"),
        ("setEvidenceContract", "evidence_contract"),
        ("setAuditContract", "audit_contract"),
        ("setAppealContract", "appeal_contract"),
    ]:
        addr = config.get(contract_key)
        if addr:
            r = set_contract_address(
                caller_contract=config["fund_contract"],
                caller_name="fund",
                method_name=method,
                target_address=addr,
                admin_address=admin_addr,
                admin_sign_user_id=admin_sign_user_id
            )
            results.append({"step": f"Fund.{method}", "result": r})
    
    # 3.Audit: 设置关联合约
    for method, contract_key in [
        ("setFundContract", "fund_contract"),
        ("setEvidenceContract", "evidence_contract"),
    ]:
        addr = config.get(contract_key)
        if addr:
            r = set_contract_address(
                caller_contract=config["audit_contract"],
                caller_name="audit",
                method_name=method,
                target_address=addr,
                admin_address=admin_addr,
                admin_sign_user_id=admin_sign_user_id
            )
            results.append({"step": f"Audit.{method}", "result": r})
    
    # 4.Dispute: 设置关联合约
    for method, contract_key in [
        ("setFundContract", "fund_contract"),
        ("setIdentityContract", "identity_contract"),
        ("setEvidenceContract", "evidence_contract"),
    ]:
        addr = config.get(contract_key)
        if addr:
            r = set_contract_address(
                caller_contract=config["appeal_contract"],
                caller_name="dispute",
                method_name=method,
                target_address=addr,
                admin_address=admin_addr,
                admin_sign_user_id=admin_sign_user_id
            )
            results.append({"step": f"Dispute.{method}", "result": r})
    
    # 5.Evidence: 设置关联合约
    for method, contract_key in [
        ("setFundContract", "fund_contract"),
        ("setAuditContract", "audit_contract"),
        ("setSettlementContract", "settlement_contract"),
        ("setDisputeContract", "appeal_contract"),
    ]:
        addr = config.get(contract_key)
        if addr:
            r = set_contract_address(
                caller_contract=config["evidence_contract"],
                caller_name="evidence",
                method_name=method,
                target_address=addr,
                admin_address=admin_addr,
                admin_sign_user_id=admin_sign_user_id
            )
            results.append({"step": f"Evidence.{method}", "result": r})
    
    # 6.Settlement: 设置关联合约
    for method, contract_key in [
        ("setFundContract", "fund_contract"),
        ("setEvidenceContract", "evidence_contract"),
    ]:
        addr = config.get(contract_key)
        if addr:
            r = set_contract_address(
                caller_contract=config.get("settlement_contract", config["fund_contract"]),
                caller_name="settlement",
                method_name=method,
                target_address=addr,
                admin_address=admin_addr,
                admin_sign_user_id=admin_sign_user_id
            )
            results.append({"step": f"Settlement.{method}", "result": r})
    
    # 7.授权审计节点
    auditors = db.query(User).filter(User.role == UserRole.AUDITOR.value).all()
    for auditor in auditors:
        r = set_authorized_auditor(
            audit_contract=config["audit_contract"],
            auditor_address=auditor.wallet_address,
            status=True,
            admin_address=admin_addr,
            admin_sign_user_id=admin_sign_user_id
        )
        results.append({"step": f"Audit.setAuthorizedAuditor({auditor.display_name})", "result": r})
    
    return {
        "message": "合约关联配置完成",
        "results": results,
        "config": config
    }


# 部署阶段0: 一键检查链上环境

@app.get("/api/admin/chain-setup-check")
def admin_chain_setup_check(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    一键检查链上环境配置状态
    返回完整的部署准备情况报告
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可查看")
    
    from chain import get_chain_stats, check_wallet_exists
    
    result = {
        "ready_to_deploy": False,
        "checks": {}
    }
    
    # 1.WeBASE-Front连通性
    stats = get_chain_stats()
    result["checks"]["webase_front_connected"] = stats.get("connected", False)
    result["checks"]["block_height"] = stats.get("block_height")
    result["checks"]["active_nodes"] = stats.get("active_nodes")
    
    if not stats.get("connected"):
        result["message"] = "WeBASE-Front 未连接，请检查服务是否启动"
        return result
    
    # 2.Admin钱包状态
    sign_user_id = f"clarity_admin_{current_user.account}"
    wallet_check = check_wallet_exists(sign_user_id)
    
    # 也检查旧版sign_user_id
    if not wallet_check["exists"]:
        wallet_check = check_wallet_exists("clarity_admin_admin")
    
    # 判断钱包是否可用：WeBASE-Front中存在，同时看数据库中有有效地址
    has_valid_address = (
        current_user.wallet_address is not None and
        current_user.wallet_address.startswith("0x") and
        len(current_user.wallet_address) == 42 and
        current_user.wallet_address != "0x0000000000000000000000000000000000000000"
    )
    
    result["checks"]["admin_wallet_on_chain"] = wallet_check["exists"]
    result["checks"]["admin_wallet_can_sign"] = wallet_check["can_sign"]
    result["checks"]["admin_db_address"] = current_user.wallet_address
    result["checks"]["admin_has_valid_address"] = has_valid_address
    result["checks"]["wallet_check_error"] = wallet_check.get("error")
    
    # 3.合约地址配置状态
    config = _get_contract_config_from_db(db)
    contracts = {
        "identity_contract": "Identity",
        "fund_contract": "Fund",
        "audit_contract": "Audit",
        "appeal_contract": "Dispute",
        "evidence_contract": "Evidence",
        "settlement_contract": "Settlement",
    }
    result["checks"]["contracts_configured"] = {}
    all_contracts_ready = True
    for key, name in contracts.items():
        addr = config.get(key)
        configured = addr is not None and addr.startswith("0x") and len(addr) == 42
        result["checks"]["contracts_configured"][name] = {
            "configured": configured,
            "address": addr
        }
        if not configured:
            all_contracts_ready = False
    
    # 4.审计节点状态
    auditors = db.query(User).filter(User.role == UserRole.AUDITOR.value).all()
    result["checks"]["auditors"] = [
        {
            "id": a.id,
            "name": a.display_name,
            "address": a.wallet_address,
            "has_wallet": a.wallet_address is not None and a.wallet_address.startswith("0x")
        }
        for a in auditors
    ]
    
    # 5.总体评估
    result["ready_to_deploy"] = (
        stats.get("connected") and
        wallet_check["can_sign"] and
        has_valid_address
    )
    
    result["ready_to_run"] = (
        result["ready_to_deploy"] and
        all_contracts_ready
    )
    
    if result["ready_to_run"]:
        result["message"] = "环境完全就绪，可以开始业务运行"
    elif result["ready_to_deploy"]:
        result["message"] = "可以部署合约，但尚未配置合约地址"
    else:
        missing = []
        if not stats.get("connected"):
            missing.append("WeBASE-Front 未连接")
        if not wallet_check["can_sign"]:
            missing.append("Admin 链上钱包未创建或无法签名")
        if not has_valid_address:
            missing.append("Admin 数据库中无有效钱包地址")
        result["message"] = f"环境未就绪: {', '.join(missing)}"
    
    return result


# 部署阶段3: 单个配置接口（精细控制）

@app.post("/api/admin/set-trusted-contract")
def admin_set_trusted_contract(
    target_contract_address: str,
    status: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    设置可信合约 - 对应 Identity.setTrustedContract
    让目标合约获得调用 Identity 合约方法的权限
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可执行")
    
    config = _get_contract_config_from_db(db)
    identity_contract = config.get("identity_contract")
    if not identity_contract:
        raise HTTPException(400, "Identity 合约地址未配置")
    
    result = set_trusted_contract(
        identity_contract=identity_contract,
        target_contract=target_contract_address,
        status=status,
        admin_address=current_user.wallet_address,
        admin_sign_user_id=f"clarity_admin_{current_user.account}"
    )
    
    return result


@app.post("/api/admin/set-authorized-auditor")
def admin_set_authorized_auditor(
    auditor_address: str,
    status: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    授权/取消授权审计节点，对应Audit.setAuthorizedAuditor
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行")
    
    config = _get_contract_config_from_db(db)
    audit_contract = config.get("audit_contract")
    if not audit_contract:
        raise HTTPException(400, "Audit合约地址未配置")
    
    result = set_authorized_auditor(
        audit_contract=audit_contract,
        auditor_address=auditor_address,
        status=status,
        admin_address=current_user.wallet_address,
        admin_sign_user_id=f"clarity_admin_{current_user.account}"
    )
    
    return result


@app.post("/api/admin/set-contract-link")
def admin_set_contract_link(
    caller_contract: str,      # identity/fund/audit/dispute/evidence/settlement
    method_name: str,
    target_address: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    通用：设置合约间地址关联
    例如: Fund.setIdentityContract, Audit.setFundContract等
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可执行")
    
    config = _get_contract_config_from_db(db)
    caller_address = config.get(f"{caller_contract}_contract")
    if not caller_address:
        raise HTTPException(400, f"{caller_contract} 合约地址未配置")
    
    result = set_contract_address(
        caller_contract=caller_address,
        caller_name=caller_contract,
        method_name=method_name,
        target_address=target_address,
        admin_address=current_user.wallet_address,
        admin_sign_user_id=f"clarity_admin_{current_user.account}"
    )
    
    return result


# 链上查询接口（验证用）

@app.get("/api/admin/chain/stake-ratio")
def admin_query_chain_stake_ratio(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    查询链上动态质押比例（与后端计算对比验证）
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可查询")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    
    config = _get_contract_config_from_db(db)
    identity_contract = config.get("identity_contract")
    fund_contract = config.get("fund_contract")
    
    result = {
        "user_id": user_id,
        "wallet_address": user.wallet_address,
        "backend_stake_ratio": None,
        "chain_identity_ratio": None,
        "chain_fund_ratio": None,
    }
    
    # 后端计算值
    from main import _compute_stake_ratio
    result["backend_stake_ratio"] = _compute_stake_ratio(user)
    
    # 链上查询
    if identity_contract and user.wallet_address:
        r = query_identity_stake_ratio(identity_contract, user.wallet_address)
        if r["success"]:
            result["chain_identity_ratio"] = r["data"]
    
    if fund_contract and user.wallet_address:
        r = query_contract_stake_ratio(fund_contract, user.wallet_address)
        if r["success"]:
            result["chain_fund_ratio"] = r["data"]
    
    return result


@app.get("/api/admin/chain/trade-status")
def admin_query_chain_trade_status(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    查询链上项目状态（与数据库对比验证）
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可查询")
    
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")
    
    config = _get_contract_config_from_db(db)
    fund_contract = config.get("fund_contract")
    
    result = {
        "task_id": task_id,
        "task_hash": task.task_hash,
        "db_status": task.status,
        "chain_status": None,
    }
    
    if fund_contract:
        # task_hash是0x+64位hex，直接作为bytes32使用
        r = query_trade_status(fund_contract, task.task_hash, current_user.wallet_address)
        if r["success"]:
            result["chain_status"] = r["data"]
    
    return result


@app.post("/api/admin/mint")
def admin_mint(
    user_id: int,
    amount: float,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    管理员为用户充值余额，与Fund.mint对齐
    用于测试阶段模拟链上转账
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行")
    if amount <= 0:
        raise HTTPException(400, "金额必须大于0")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")

    target.balance += amount
    db.commit()
    db.refresh(target)

    _insert_chain_event(
        db,
        event_type=ChainEventType.BALANCE_MINTED.value if hasattr(ChainEventType, 'BALANCE_MINTED') else "BalanceMinted",
        sender_address=current_user.wallet_address,
        data_json={"to_user_id": user_id, "amount": float(amount), "new_balance": float(target.balance)}
    )

    return {"user_id": user_id, "minted": amount, "new_balance": float(target.balance)}


# 合约地址配置持久化（与数据库ContractConfig表对齐）

def _get_contract_config_from_db(db: Session) -> dict:
    """从数据库读取合约地址配置"""
    configs = db.query(ContractConfig).all()
    result = {
        "identity_contract": None,
        "evidence_contract": None,
        "audit_contract": None,
        "appeal_contract": None,
        "association_address": None,
        "platform_treasury": None,
    }
    for c in configs:
        if c.config_key in result:
            result[c.config_key] = c.config_value
    return result


def _set_contract_config_in_db(db: Session, key: str, value: Optional[str]):
    """将合约地址配置持久化到数据库"""
    config = db.query(ContractConfig).filter(ContractConfig.config_key == key).first()
    if config:
        config.config_value = value
    else:
        config = ContractConfig(config_key=key, config_value=value)
        db.add(config)


@app.get("/api/admin/contract-config")
def get_contract_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前合约地址配置（从数据库持久化读取）"""
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可查看")
    return _get_contract_config_from_db(db)


@app.post("/api/admin/contract-config")
def set_contract_config(
    identity_contract: Optional[str] = None,
    evidence_contract: Optional[str] = None,
    audit_contract: Optional[str] = None,
    appeal_contract: Optional[str] = None,
    association_address: Optional[str] = None,
    platform_treasury: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    设置合约地址配置，与Fund.setIdentityContract/setEvidenceContract等对齐
    部署阶段使用，配置持久化到数据库
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可配置")

    if identity_contract is not None:
        _set_contract_config_in_db(db, "identity_contract", identity_contract)
    if evidence_contract is not None:
        _set_contract_config_in_db(db, "evidence_contract", evidence_contract)
    if audit_contract is not None:
        _set_contract_config_in_db(db, "audit_contract", audit_contract)
    if appeal_contract is not None:
        _set_contract_config_in_db(db, "appeal_contract", appeal_contract)
    if association_address is not None:
        _set_contract_config_in_db(db, "association_address", association_address)
    if platform_treasury is not None:
        _set_contract_config_in_db(db, "platform_treasury", platform_treasury)

    db.commit()
    return {"message": "合约地址配置已更新并持久化", "config": _get_contract_config_from_db(db)}


@app.post("/api/admin/blacklist")
def admin_blacklist(
    user_id: int,
    reason: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    将用户加入黑名单，与Identity.blacklist对齐
    仅ADMIN可操作
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.role == UserRole.ADMIN.value:
        raise HTTPException(400, "不能将系统管理员加入黑名单")

    target.is_blacklisted = True
    db.commit()
    db.refresh(target)

    _insert_chain_event(
        db,
        event_type=ChainEventType.USER_BLACKLISTED.value if hasattr(ChainEventType, 'USER_BLACKLISTED') else "UserBlacklisted",
        sender_address=current_user.wallet_address,
        data_json={"user_id": user_id, "reason": reason}
    )

    return {"user_id": user_id, "is_blacklisted": True, "reason": reason}


@app.post("/api/admin/whitelist")
def admin_whitelist(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    将用户移出黑名单，与Identity.whitelist对齐
    仅ADMIN可操作
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅系统管理员可执行")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")

    target.is_blacklisted = False
    db.commit()
    db.refresh(target)

    return {"user_id": user_id, "is_blacklisted": False}


# 添加ChainEventType中可能缺失的枚举值（向后兼容）
# 如果models.py 中没有定义，使用字符串替代
if not hasattr(ChainEventType, 'BALANCE_MINTED'):
    ChainEventType.BALANCE_MINTED = "BalanceMinted"
if not hasattr(ChainEventType, 'USER_BLACKLISTED'):
    ChainEventType.USER_BLACKLISTED = "UserBlacklisted"
