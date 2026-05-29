"""
Pytest全局配置与共享Fixtures
设计原则：
  1.测试数据库完全隔离（内存SQLite），不污染开发数据库
  2.每个测试函数独立事务，自动回滚
  3.提供常用角色用户的快速创建fixture
  4.链上交互统一Mock，避免依赖WeBASE-Front）
"""

import os
import sys

# 必须在导入models/main之前设置，确保全局engine使用内存SQLite
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

# 确保能导入backend根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Base, User, AuditTask, UserRole, TaskStatus, get_db
from core.security import hash_password, create_access_token
from main import app


# 1.测试数据库引擎（内存SQLite，每个测试进程一个实例）

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

# 让SQLite支持外键约束（生产环境行为一致）
@event.listens_for(test_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


# 2.全局：每个测试session创建/销毁表结构

@pytest.fixture(scope="session", autouse=True)
def setup_test_database() -> Generator[None, None, None]:
    """测试会话开始时建表，结束时删表"""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# 3.每个测试函数：独立事务与自动回滚

@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """
    为每个测试函数提供独立的数据库会话
    测试结束后自动回滚，确保测试互不干扰
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def override_get_db(db_session: Session):
    """覆盖FastAPI的get_db依赖，使其使用测试会话"""
    def _get_db():
        yield db_session
    return _get_db


@pytest.fixture(scope="function")
def client(override_get_db):
    """
    提供配置了测试数据库的TestClient
    所有通过client发起的请求都会使用测试数据库会话
    """
    from fastapi.testclient import TestClient
    app.dependency_overrides[get_db] = override_get_db
    # 同时mock掉chain.py中的WeBASE调用，避免网络请求
    _mock_chain_calls()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _mock_chain_calls():
    """
    Mock链上交互，避免测试时连接 WeBASE-Front。
    通过monkeypatch 替换chain.py中的关键函数。
    """
    import chain as chain_module
    # 保存原始函数（可选，用于恢复）
    if not hasattr(chain_module, "_original_create_wallet"):
        chain_module._original_create_wallet = getattr(chain_module, "create_wallet", None)
        chain_module._original_check_wallet_exists = getattr(chain_module, "check_wallet_exists", None)

    def _mock_create_wallet(sign_user_id: str):
        return {"address": f"0xmock_{sign_user_id[:20]}"}

    def _mock_check_wallet_exists(sign_user_id: str):
        return {}

    chain_module.create_wallet = _mock_create_wallet
    chain_module.check_wallet_exists = _mock_check_wallet_exists


# 4.快速创建用户Fixture

DEFAULT_PASSWORD = "TestPass123"

def _make_user(
    db: Session,
    account: str,
    role: UserRole,
    display_name: str = None,
    balance: float = 10000.0,
    reputation_score: int = 70,
    password: str = DEFAULT_PASSWORD,
) -> User:
    """内部辅助：创建用户并返回"""
    user = User(
        account=account,
        password_hash=hash_password(password),
        display_name=display_name or account,
        role=role.value,
        wallet_address=f"0xwallet_{account}",
        reputation_score=reputation_score,
        balance=balance,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def make_user(db_session: Session):
    """返回一个工厂函数，用于在测试中快速创建用户"""
    def factory(
        account: str = None,
        role: UserRole = UserRole.MANUFACTURER,
        display_name: str = None,
        balance: float = 10000.0,
        reputation_score: int = 70,
        password: str = DEFAULT_PASSWORD,
    ) -> User:
        import uuid
        account = account or f"user_{uuid.uuid4().hex[:8]}"
        return _make_user(
            db_session, account, role, display_name, balance, reputation_score, password
        )
    return factory


@pytest.fixture
def manufacturer(make_user) -> User:
    """预创建一个制造商用户"""
    return make_user(account="mfr_test", role=UserRole.MANUFACTURER)


@pytest.fixture
def supplier(make_user) -> User:
    """预创建一个供应商用户"""
    return make_user(account="sup_test", role=UserRole.SUPPLIER)


@pytest.fixture
def auditor(make_user) -> User:
    """预创建一个审计节点用户"""
    return make_user(account="aud_test", role=UserRole.AUDITOR)


@pytest.fixture
def admin_user(make_user) -> User:
    """预创建一个ADMIN用户"""
    return make_user(account="admin_test", role=UserRole.ADMIN)


# 5.认证辅助

@pytest.fixture
def auth_headers():
    """返回一个工厂函数，生成Bearer Token请求头"""
    def factory(user: User) -> dict:
        token = create_access_token(data={"sub": str(user.id)})
        return {"Authorization": f"Bearer {token}"}
    return factory


@pytest.fixture
def mfr_headers(auth_headers, manufacturer) -> dict:
    """制造商认证头"""
    return auth_headers(manufacturer)


@pytest.fixture
def sup_headers(auth_headers, supplier) -> dict:
    """供应商认证头"""
    return auth_headers(supplier)


@pytest.fixture
def aud_headers(auth_headers, auditor) -> dict:
    """审计节点认证头"""
    return auth_headers(auditor)


@pytest.fixture
def admin_headers(auth_headers, admin_user) -> dict:
    """ADMIN认证头"""
    return auth_headers(admin_user)


# 6.任务辅助

# Sentinel值，用于区分未传入参数和传入None
_UNSET = object()


@pytest.fixture
def create_task(db_session: Session, manufacturer: User, supplier: User):
    """返回工厂函数，快速创建任务并推进到指定状态"""
    def factory(
        status: TaskStatus = TaskStatus.PENDING,
        task_name: str = "测试项目",
        manufacturer_id: int = _UNSET,
        supplier_id: int = _UNSET,
        **kwargs
    ) -> AuditTask:
        import secrets
        from datetime import datetime
        from core.chain_utils import insert_chain_event

        mfr_id = manufacturer_id if manufacturer_id is not _UNSET else manufacturer.id
        sup_id = supplier_id if supplier_id is not _UNSET else (supplier.id if supplier else None)

        # 从kwargs中提取可能覆盖的字段
        task_kwargs = {
            "task_hash": "0x" + secrets.token_hex(32),
            "task_name": task_name,
            "description": "测试描述",
            "manufacturer_id": mfr_id,
            "supplier_id": sup_id,
            "status": status.value,
            "target_fnr": 0.05,
            "target_fpr": 0.05,
            "target_map": 0.80,
            "target_f1": 0.75,
            "target_latency": 100,
            "conf_threshold": 0.25,
            "iou_threshold": 0.45,
        }
        task_kwargs.update(kwargs)

        task = AuditTask(**task_kwargs)
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        insert_chain_event(
            db_session,
            event_type="ProjectCreated",
            task_id=task.id,
            sender_address="0xmock",
            data_json={"task_hash": task.task_hash}
        )
        return task
    return factory
