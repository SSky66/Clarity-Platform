from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import timedelta
import uuid

from models import (
    init_db, get_db, ensure_builtin_admin,
    User, UserRole,
)
from schemas import UserCreate, UserResponse, UserLogin
from core.security import hash_password, verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from core.deps import get_current_user
from blockchain_client import create_wallet, check_wallet_exists

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _is_chain_available() -> bool:
    """检查 WeBASE-Front 是否可连接"""
    try:
        import requests
        from blockchain_client import WEBASE_FRONT_URL, GROUP_ID
        resp = requests.get(f"{WEBASE_FRONT_URL}/WeBASE-Front/{GROUP_ID}/web3/clientVersion", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


@router.post("/register", response_model=UserResponse)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    """
    注册：查重 → 哈希密码 → 入库 → 尝试创建链上钱包
    WeBASE 不可用时，wallet_address 为 null，前端可后续刷新分配
    """
    if db.query(User).filter(User.account == payload.account).first():
        raise HTTPException(status_code=400, detail="账号已存在")

    wallet_address = None
    sign_user_id = f"clarity_{payload.account}_{uuid.uuid4().hex[:8]}"

    if _is_chain_available():
        try:
            # 先检查是否已有同名钱包可复用（理论上不应该有，但防御性编程）
            exists_info = check_wallet_exists(sign_user_id)
            if exists_info.get("address"):
                wallet_address = exists_info["address"]
            else:
                wallet = create_wallet(sign_user_id)
                if wallet and wallet.get("address"):
                    wallet_address = wallet["address"]
        except Exception:
            pass  # 创建失败，wallet_address 保持 None

    user = User(
        account=payload.account,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role.value,
        wallet_address=wallet_address,
        reputation_score=70,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login")
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """登录：验密码 → 校验角色 → 发 JWT Token"""
    user = db.query(User).filter(User.account == payload.account).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")

    if payload.role and payload.role.upper() != user.role:
        raise HTTPException(status_code=403, detail=f"角色不匹配：该账号为 {user.role}，请选择正确角色登录")

    token = create_access_token(
        data={"sub": str(user.id)},
        expires=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": token, "token_type": "bearer", "user": UserResponse.model_validate(user)}


@router.post("/sudo")
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
