"""
Locust压力测试脚本
模拟多审计节点并发提交任务，对模型推理与结果回传接口进行压力测试

运行方式:
    locust -f locustfile.py --host=http://localhost:8000
Headless 模式:
    locust -f locustfile.py --host=http://localhost:8000 -u 100 -r 10 -t 60s --headless --csv=locust_result
"""

import random
from locust import HttpUser, task, between, events


# 全局变量，记录峰值并发用户数

_peak_user_count = 0

@events.spawning_complete.add_listener
def on_spawning_complete(user_count, **kwargs):
    """记录实际启动的并发用户数"""
    global _peak_user_count
    _peak_user_count = user_count


# 测试停止时输出报告

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束时基于Locust原生统计输出报告"""
    stats = environment.runner.stats
    total = stats.total

    if total.num_requests == 0:
        print("\n[Locust] 无请求数据")
        return

    # 使用Locust原生统计指标
    total_requests = total.num_requests
    success_requests = total.num_requests - total.num_failures
    failed_requests = total.num_failures
    success_rate = (success_requests / total_requests * 100) if total_requests > 0 else 0
    avg_time = total.avg_response_time
    min_time = total.min_response_time or 0
    max_time = total.max_response_time or 0

    # 计算P95
    p95 = stats.total.get_response_time_percentile(0.95) or 0

    # Locust原生RPS（滑动窗口计算）
    rps = total.total_rps

    # 测试持续时间（秒）
    duration = stats.last_request_timestamp - stats.start_time

    report = f"""
{'-' * 60}
Locust 压力测试报告
{'-' * 60}
测试目标: Clarity API
并发用户数: {_peak_user_count}
测试持续时间: {duration:.2f}s

请求统计:
  总请求数: {total_requests}
  成功请求: {success_requests}
  失败请求: {failed_requests}
  成功率: {success_rate:.2f}%
  RPS: {rps:.2f}

响应时间:
  平均: {avg_time:.2f}ms
  最小: {min_time:.2f}ms
  最大: {max_time:.2f}ms
  P95: {p95:.2f}ms

接口分布:
"""
    # 按请求数排序取top5
    sorted_entries = sorted(
        stats.entries.values(),
        key=lambda x: x.num_requests,
        reverse=True
    )[:5]

    for entry in sorted_entries:
        name = entry.name
        num = entry.num_requests
        avg = entry.avg_response_time
        fail_rate = (entry.num_failures / entry.num_requests * 100) if entry.num_requests > 0 else 0
        report += f"  - {name}: {num} 次, 平均 {avg:.2f}ms, 失败率 {fail_rate:.2f}%\n"

    report += f"""
{'-' * 60}
"""
    print(report)

    # 输出到文件
    with open("locust_report.txt", "w", encoding="utf-8") as f:
        f.write(report)


# 用户行为定义

class AuditUser(HttpUser):
    """
    模拟审计节点用户行为
    权重分配:
    1.查询任务列表: 60% (高频读取)
    2.查询项目详情: 30% (中频读取)
    3.查询统计: 20% (中频读取)
    4.提交审计报告: 20% (写入操作)
    5.创建项目: 10% (低频)
    6.查询链上事件: 10% (低频)
    """
    wait_time = between(1, 3)

    def on_start(self):
        """用户启动时登录获取 Token"""
        roles = ["MANUFACTURER", "SUPPLIER", "AUDITOR"]
        accounts = {
            "MANUFACTURER": ("zhizaotest1", "12345678"),
            "SUPPLIER": ("e2e_supplier", "TestPass123"),
            "AUDITOR": ("e2e_auditor", "TestPass123"),
        }

        self.role = random.choice(roles)
        account, password = accounts.get(self.role, ("zhizaotest1", "12345678"))

        resp = self.client.post("/api/auth/login", json={
            "account": account,
            "password": password,
            "role": self.role
        })

        if resp.status_code == 200:
            self.token = resp.json().get("access_token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    @task(6)
    def query_task_list(self):
        """高频：查询项目列表"""
        self.client.get("/api/tasks", headers=self.headers)

    @task(3)
    def query_task_detail(self):
        """中频：查询项目详情"""
        task_id = random.randint(1, 10)
        self.client.get(f"/api/tasks/{task_id}", headers=self.headers)

    @task(2)
    def query_stats(self):
        """中频：查询统计数据"""
        self.client.get("/api/tasks/stats", headers=self.headers)

    @task(2)
    def submit_audit_report(self):
        """中频：提交审计报告（模拟推理回传）"""
        task_id = random.randint(1, 10)
        payload = {
            "miss_rate": round(random.uniform(0.01, 0.10), 4),
            "false_kill_rate": round(random.uniform(0.01, 0.10), 4),
            "concentration_ratio": round(random.uniform(0.10, 0.80), 4),
            "avg_fp": round(random.uniform(0.01, 0.20), 4),
            "arrogance": round(random.uniform(0.10, 0.80), 4),
            "map": round(random.uniform(0.70, 0.95), 4),
            "f1": round(random.uniform(0.65, 0.90), 4),
        }
        self.client.post(f"/api/tasks/{task_id}/report", headers=self.headers, json=payload)

    @task(1)
    def create_task(self):
        """低频：创建项目（仅制造商）"""
        if self.role == "MANUFACTURER":
            payload = {
                "task_name": f"压测项目-{random.randint(1000, 9999)}",
                "target_fnr": 0.05,
                "target_fpr": 0.05,
                "conf_threshold": 0.25,
                "iou_threshold": 0.45,
            }
            self.client.post("/api/tasks", headers=self.headers, json=payload)

    @task(1)
    def query_chain_events(self):
        """低频：查询链上事件"""
        self.client.get("/api/chain-events?page=1&limit=20", headers=self.headers)


class HeavyLoadUser(HttpUser):
    """
    重负载用户，专门压测推理接口
    模拟多审计节点同时提交报告的场景
    """
    wait_time = between(0.5, 1.5)
    weight = 2

    def on_start(self):
        """以审计节点身份登录"""
        resp = self.client.post("/api/auth/login", json={
            "account": "e2e_auditor",
            "password": "TestPass123",
            "role": "AUDITOR"
        })
        if resp.status_code == 200:
            self.token = resp.json().get("access_token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    @task(10)
    def heavy_audit_submit(self):
        """高频提交审计报告，模拟推理回传瓶颈"""
        task_id = random.randint(1, 20)
        payload = {
            "miss_rate": 0.02,
            "false_kill_rate": 0.03,
            "concentration_ratio": 0.45,
            "avg_fp": 0.05,
            "arrogance": 0.30,
            "map": 0.82,
            "f1": 0.78,
        }
        with self.client.post(
            f"/api/tasks/{task_id}/report",
            headers=self.headers,
            json=payload,
            catch_response=True
        ) as resp:
            if resp.status_code in (200, 400):
                resp.success()
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    @task(3)
    def heavy_start_audit(self):
        """高频开始审计，状态变更竞争"""
        task_id = random.randint(1, 20)
        with self.client.put(
            f"/api/tasks/{task_id}/start-audit",
            headers=self.headers,
            catch_response=True
        ) as resp:
            if resp.status_code in (200, 400):
                resp.success()
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")
