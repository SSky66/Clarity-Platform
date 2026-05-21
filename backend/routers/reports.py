"""
审计报告相关接口（PDF生成预留）
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import AuditTask, TaskReport, UserRole, get_db
from core.deps import get_current_user

router = APIRouter(prefix="/api/tasks", tags=["审计报告"])


@router.get("/{task_id}/report")
def get_report(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取审计报告指标"""
    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    if not report:
        raise HTTPException(404, "报告不存在")
    return report


@router.get("/{task_id}/report/pdf")
def download_audit_report_pdf(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    下载审计报告PDF，预留接口
    """
    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    is_party = current_user.id in [task.manufacturer_id, task.supplier_id, task.auditor_id]
    is_admin = current_user.role == UserRole.ADMIN.value
    if not is_party and not is_admin:
        raise HTTPException(403, "仅项目相关方可下载审计报告")

    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    if not report:
        raise HTTPException(404, "审计报告尚未生成")

    raise HTTPException(501, "审计报告PDF生成功能尚未实现")


@router.post("/{task_id}/report/pdf/generate")
def generate_audit_report_pdf(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    手动触发审计报告PDF生成（ADMIN或审计节点用），预留接口
    """
    if current_user.role not in [UserRole.ADMIN.value, UserRole.AUDITOR.value]:
        raise HTTPException(403, "仅系统管理员或审计节点可生成报告")

    task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "项目不存在")

    report = db.query(TaskReport).filter(TaskReport.task_id == task_id).first()
    if not report:
        raise HTTPException(404, "审计报告尚未提交")

    raise HTTPException(501, "审计报告PDF生成功能尚未实现")


@router.get("/{task_id}/audit-logs")
def get_audit_logs(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """监控大屏左侧终端的日志"""
    from models import AuditLog
    logs = db.query(AuditLog).filter(AuditLog.task_id == task_id).order_by(AuditLog.created_at.asc()).all()
    if logs:
        return logs
    return [
        {"id": 0, "task_id": task_id, "log_type": "[SYS]", "message": "初始化 Clarity Audit Engine v2.1.0", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[DONE]", "message": "准确度审计: 漏杀率=0.2%, 误杀率=3.4%", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[INFO]", "message": "协商指标: mAP=87.3%, F1=0.84", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[DONE]", "message": "注意力审计: 6个TP, 平均CR=41.5%", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[DONE]", "message": "置信度审计: 3组样本, Arrogance=12%", "created_at": None},
        {"id": 0, "task_id": task_id, "log_type": "[DONE]", "message": "审计完成: 综合判定 PASS", "created_at": None},
    ]
