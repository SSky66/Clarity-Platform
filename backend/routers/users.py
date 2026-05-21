from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import User, UserRole, BASE_REPUTATION, get_db
from schemas import UserResponse
from core.deps import get_current_user

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
