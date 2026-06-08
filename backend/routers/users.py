from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid

from models import User, UserRole, BASE_REPUTATION, get_db
from schemas import UserResponse
from core.deps import get_current_user
from core.security import verify_password, hash_password
from blockchain_client import create_wallet, check_wallet_exists

router = APIRouter(prefix="/api/users", tags=["用户"])


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return current_user


@router.get("", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """ADMIN 获取所有用户列表（不含 ADMIN 自身）"""
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "仅 ADMIN 可查看用户列表")
    return db.query(User).filter(User.role != UserRole.ADMIN.value).all()


@router.get("/{user_id}/stake-ratio")
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

    if user.is_blacklisted:
        return {"user_id": user_id, "stake_ratio": 2.0, "basis_points": 20000}

    if user.reputation_score == 0 and user.success_count == 0 and not user.is_builtin:
        return {"user_id": user_id, "stake_ratio": 2.0, "basis_points": 20000}

    if user.role in [UserRole.ADMIN.value, UserRole.AUDITOR.value]:
        return {"user_id": user_id, "stake_ratio": 1.0, "basis_points": 10000}

    base_ratio = 1.5
    rep_diff = user.reputation_score - BASE_REPUTATION

    if rep_diff > 0:
        reduction = (rep_diff // 10) * 0.03
        reduction = min(reduction, 0.5)
        base_ratio -= reduction
    elif rep_diff < 0:
        increase = (abs(rep_diff) // 10) * 0.03
        increase = min(increase, 0.5)
        base_ratio += increase

    base_ratio = max(1.0, min(2.0, base_ratio))

    return {
        "user_id": user_id,
        "stake_ratio": round(base_ratio, 2),
        "basis_points": int(base_ratio * 10000),
        "reputation_score": user.reputation_score
    }


@router.post("/recharge")
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


@router.post("/me/assign-wallet", response_model=UserResponse)
def assign_wallet(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    为当前用户分配/刷新链上钱包地址
    - 如果用户已有钱包地址，直接返回（幂等）
    - 如果没有，尝试创建新钱包或复用 WeBASE-Front 中已有的同名钱包
    """
    # 已有有效地址，直接返回
    if current_user.wallet_address:
        return current_user

    sign_user_id = f"clarity_{current_user.account}_{uuid.uuid4().hex[:8]}"

    try:
        # 先检查 WeBASE-Front 是否已有同名钱包可复用
        exists_info = check_wallet_exists(sign_user_id)
        if exists_info.get("address"):
            current_user.wallet_address = exists_info["address"]
            db.commit()
            db.refresh(current_user)
            return current_user

        # 没有则创建新钱包
        wallet = create_wallet(sign_user_id)
        if wallet and wallet.get("address"):
            current_user.wallet_address = wallet["address"]
            db.commit()
            db.refresh(current_user)
            return current_user
        else:
            raise HTTPException(status_code=503, detail="链上钱包创建失败，WeBASE-Front 可能未连接")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"链上服务异常: {str(e)}")


@router.post("/me/change-password")
def change_password(
    old_password: str,
    new_password: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """修改密码：验证旧密码，更新为新密码"""
    if not verify_password(old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少8位")
    current_user.password_hash = hash_password(new_password)
    db.commit()
    return {"message": "密码修改成功"}


@router.put("/me/change-account")
def change_account(
    new_account: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """修改登录账号：查重后更新"""
    if not new_account or len(new_account) < 5:
        raise HTTPException(status_code=400, detail="账号最少5位")
    if new_account == current_user.account:
        raise HTTPException(status_code=400, detail="新账号不能与旧账号相同")
    existing = db.query(User).filter(User.account == new_account).first()
    if existing:
        raise HTTPException(status_code=400, detail="该账号已被使用")
    current_user.account = new_account
    db.commit()
    db.refresh(current_user)
    return {"message": "账号修改成功", "user": UserResponse.model_validate(current_user)}
