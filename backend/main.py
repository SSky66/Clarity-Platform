"""
Clarity API - FastAPI 主入口
============================

所有业务路由已按模块拆分至 routers/ 目录。
本文件仅负责：
  1. 创建 FastAPI 应用实例
  2. 注册 CORS 中间件
  3. 注册所有路由
  4. 启动/关闭事件（数据库初始化、定时任务）

业务模块：
  - routers/auth.py          认证（注册、登录、sudo）
  - routers/users.py         用户管理
  - routers/tasks_core.py    项目核心（创建、查询、接单、上传）
  - routers/prepare.py       准备与质押
  - routers/audit.py         线上审计
  - routers/settlement.py    终态结算（complete-reject、complete-slash）
  - routers/onsite.py        现场验收
  - routers/rectification.py 整改与延期
  - routers/appeals.py       申诉
  - routers/arbitration.py   仲裁
  - routers/evidence.py      存证查询与上传
  - routers/reports.py       审计报告（预留）
  - routers/chain_events.py  链上事件查询
  - routers/admin.py         管理接口（ADMIN 专用）
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models import init_db, ensure_builtin_admin
from scheduler import init_scheduler

# 导入所有路由模块
from routers import (
    auth,
    users,
    tasks_core,
    prepare,
    audit,
    settlement,
    onsite,
    rectification,
    appeals,
    arbitration,
    evidence,
    reports,
    chain_events,
    admin,
)

app = FastAPI(title="Clarity API")

# 允许前端Vue跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """启动时自动建表，启动定时任务"""
    init_db()
    ensure_builtin_admin()
    init_scheduler(app)


# 注册所有路由
# 注意：各 router 的 prefix 已在各自文件中定义，此处无需重复

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tasks_core.router)
app.include_router(prepare.router)
app.include_router(audit.router)
app.include_router(settlement.router)
app.include_router(onsite.router)
app.include_router(rectification.router)
app.include_router(appeals.router)
app.include_router(arbitration.router)
app.include_router(evidence.router)
app.include_router(reports.router)
app.include_router(chain_events.router)
app.include_router(admin.router)
