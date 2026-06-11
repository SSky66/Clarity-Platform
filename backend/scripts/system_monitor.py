#!/usr/bin/env python3
"""
系统监控脚本
采集服务器状态、检查服务状态、读取最近日志
用法:
    python scripts/system_monitor.py              # 单次检查
    python scripts/system_monitor.py --watch      # 持续监控，每60秒一次
"""

import os
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# 配置区
PROJECT_ROOT = Path(__file__).parent.parent.resolve()  # 项目根目录
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

API_URL = "http://127.0.0.1:8000/api/tasks/stats"  # 要检查的服务地址
API_PORT = 8000


# 采集区
def run_cmd(cmd):
    """执行命令，返回输出文本"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as e:
        return f"出错: {e}"


def get_cpu():
    """获取CPU信息"""
    # 读取系统负载
    load = run_cmd("cat /proc/loadavg").split()
    
    # 读取CPU使用率（top命令采样一次）
    cpu_line = run_cmd("top -bn1 | grep 'Cpu(s)'")
    
    return {
        "cpu核数": os.cpu_count(),
        "负载": f"{load[0]} {load[1]} {load[2]}" if len(load) >= 3 else "未知",
        "使用率": cpu_line[:50] if cpu_line else "未知",  # 只取前50字符
    }


def get_memory():
    """获取内存信息"""
    mem_line = run_cmd("free -m | grep Mem").split()
    
    if len(mem_line) >= 3:
        total = int(mem_line[1])
        used = int(mem_line[2])
        return {
            "总共_MB": total,
            "已用_MB": used,
            "使用率_%": round(used / total * 100, 1),
        }
    return {"错误": "无法读取内存信息"}


def get_disk():
    """获取磁盘信息"""
    df_line = run_cmd("df -h / | tail -1").split()
    
    if len(df_line) >= 5:
        return {
            "总容量": df_line[1],
            "已用": df_line[2],
            "可用": df_line[3],
            "使用率": df_line[4],
        }
    return {"错误": "无法读取磁盘信息"}


def get_process():
    """获取服务器进程信息"""
    # 查找uvicorn进程
    ps_output = run_cmd("ps aux | grep uvicorn | grep -v grep")
    
    # 检查端口是否在监听
    port_check = run_cmd(f"ss -tlnp | grep :{API_PORT}")
    
    return {
        "uvicorn进程": "有" if ps_output else "无",
        "端口监听": "有" if port_check else "无",
        "进程详情": ps_output[:100] if ps_output else "",
    }


def get_logs():
    """读取最近的错误日志"""
    log_file = LOG_DIR / "app.log"
    
    if not log_file.exists():
        return {"app.log": "文件不存在"}
    
    # 取最后30行
    lines = run_cmd(f"tail -n 30 {log_file}")
    return {
        "app.log": lines.split("\n") if lines else ["空日志"],
    }


def check_api():
    """检查API是否活着"""
    import urllib.request
    
    try:
        start = time.time()
        req = urllib.request.Request(API_URL, method="GET")
        req.add_header("Authorization", "Bearer test")
        
        response = urllib.request.urlopen(req, timeout=5)
        
        return {
            "状态": "正常",
            "响应码": response.status,
            "响应时间_ms": round((time.time() - start) * 1000, 2),
        }
    except urllib.error.HTTPError as e:
        # 401/403也算活着，只是没权限或者前端出现了问题
        return {
            "状态": "正常(需登录)" if e.code < 500 else "异常",
            "响应码": e.code,
        }
    except Exception as e:
        return {
            "状态": "无法连接",
            "错误": str(e)[:100],
        }


def check_alerts(cpu, memory, disk, api):
    """检查是否有告警"""
    alerts = []
    
    # 内存超过80%告警
    mem_usage = memory.get("使用率_%", 0)
    if mem_usage > 80:
        alerts.append(f"内存使用率过高: {mem_usage}%")
    
    # 磁盘超过80%告警
    disk_usage = disk.get("使用率", "0%").replace("%", "")
    try:
        if int(disk_usage) > 80:
            alerts.append(f"磁盘使用率过高: {disk_usage}%")
    except ValueError:
        pass
    
    # API不通告警
    if api.get("状态", "").startswith("无法"):
        alerts.append("API服务无法连接")
    
    return alerts


def run_check():
    """执行一次完整检查"""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 开始检查...")
    
    # 采集各项指标
    cpu = get_cpu()
    memory = get_memory()
    disk = get_disk()
    process = get_process()
    logs = get_logs()
    api = check_api()
    
    # 检查告警
    alerts = check_alerts(cpu, memory, disk, api)
    
    # 组装报告
    report = {
        "检查时间": datetime.now().isoformat(),
        "整体状态": "告警" if alerts else "正常",
        "告警项": alerts,
        "CPU": cpu,
        "内存": memory,
        "磁盘": disk,
        "进程": process,
        "API": api,
        "日志": logs,
    }
    
    # 打印到控制台
    print_report(report)
    
    # 保存到文件
    filename = LOG_DIR / f"monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告已保存: {filename}\n")
    
    return report


# 报告区
def print_report(report):
    """打印可读报告"""
    print("=" * 50)
    print(f"状态: {report['整体状态']}")
    
    if report['告警项']:
        print(f"告警: {', '.join(report['告警项'])}")
    
    print(f"CPU: {report['CPU']['cpu核数']}核, 负载 {report['CPU']['负载']}")
    print(f"内存: {report['内存'].get('已用_MB', '?')}MB / {report['内存'].get('总共_MB', '?')}MB ({report['内存'].get('使用率_%', '?')}%)")
    print(f"磁盘: 已用 {report['磁盘'].get('已用', '?')} / {report['磁盘'].get('总容量', '?')}")
    print(f"进程: {report['进程']['uvicorn进程']}, 端口: {report['进程']['端口监听']}")
    print(f"API: {report['API']['状态']}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="系统监控")
    parser.add_argument("--watch", action="store_true", help="持续监控模式")
    parser.add_argument("--interval", type=int, default=60, help="检查间隔(秒)")
    args = parser.parse_args()
    
    if args.watch:
        print(f"持续监控模式，每 {args.interval} 秒检查一次，Ctrl+C 停止")
        try:
            while True:
                run_check()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n已停止")
    else:
        run_check()


if __name__ == "__main__":
    main()