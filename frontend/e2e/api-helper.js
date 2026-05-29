/**
 * E2E测试API工具函数
 * 通过后端API准备测试数据，确保UI测试有确定性前置条件
 */

const BASE_URL = 'http://localhost:8000';

/**
 * 登录获取Token
 */
export async function apiLogin(request, account, password, role) {
  const res = await request.post(`${BASE_URL}/api/auth/login`, {
    data: { account, password, role },
  });
  if (!res.ok()) {
    throw new Error(`登录失败: ${account}`);
  }
  const data = await res.json();
  return data.access_token;
}

/**
 * 注册用户（如果不存在）
 */
export async function apiRegister(request, account, password, displayName, role) {
  const res = await request.post(`${BASE_URL}/api/auth/register`, {
    data: {
      account,
      password,
      display_name: displayName,
      role,
    },
  });
  // 409表示已存在，也算成功
  if (!res.ok() && res.status() !== 409) {
    throw new Error(`注册失败: ${account}, status=${res.status()}`);
  }
  return res.ok() ? await res.json() : null;
}

/**
 * 创建项目（制造商）
 */
export async function apiCreateTask(request, token, taskName) {
  const res = await request.post(`${BASE_URL}/api/tasks`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      task_name: taskName,
      target_fnr: 0.05,
      target_fpr: 0.05,
      target_map: 0.80,
      target_f1: 0.75,
      target_latency: 100,
      conf_threshold: 0.25,
      iou_threshold: 0.45,
    },
  });
  if (!res.ok()) {
    throw new Error(`创建项目失败: ${res.status()}`);
  }
  return await res.json();
}

/**
 * 供应商接单
 */
export async function apiAcceptTask(request, token, taskId) {
  const res = await request.put(`${BASE_URL}/api/tasks/${taskId}/accept`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) {
    throw new Error(`接单失败: ${res.status()}`);
  }
  return await res.json();
}

/**
 * 制造商准备（上传数据集）
 */
export async function apiManufacturerPrepare(request, token, taskId) {
  const res = await request.post(`${BASE_URL}/api/tasks/${taskId}/manufacturer-prepare`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      purchase_insurance: false,
      test_set_hash: 'ipfs://e2e_test_dataset',
    },
  });
  if (!res.ok()) {
    throw new Error(`制造商准备失败: ${res.status()}`);
  }
  return await res.json();
}

/**
 * 供应商准备（上传模型）
 */
export async function apiSupplierPrepare(request, token, taskId) {
  const res = await request.post(`${BASE_URL}/api/tasks/${taskId}/supplier-prepare`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      model_hash: 'ipfs://e2e_test_model',
    },
  });
  if (!res.ok()) {
    throw new Error(`供应商准备失败: ${res.status()}`);
  }
  return await res.json();
}

/**
 * 开始审计
 */
export async function apiStartAudit(request, token, taskId) {
  const res = await request.put(`${BASE_URL}/api/tasks/${taskId}/start-audit`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) {
    throw new Error(`开始审计失败: ${res.status()}`);
  }
  return await res.json();
}

/**
 * 提交审计报告
 */
export async function apiSubmitReport(request, token, taskId, decision = 'PASS') {
  const payloads = {
    PASS: {
      miss_rate: 0.01,
      false_kill_rate: 0.01,
      concentration_ratio: 0.50,
      avg_fp: 0.05,
      arrogance: 0.20,
      map: 0.85,
      f1: 0.80,
    },
    REJECT: {
      miss_rate: 0.10,
      false_kill_rate: 0.01,
      concentration_ratio: 0.50,
      avg_fp: 0.05,
      arrogance: 0.20,
    },
    SLASH: {
      miss_rate: 0.01,
      false_kill_rate: 0.01,
      concentration_ratio: 0.10,
      avg_fp: 0.05,
      arrogance: 0.20,
    },
  };
  const res = await request.post(`${BASE_URL}/api/tasks/${taskId}/report`, {
    headers: { Authorization: `Bearer ${token}` },
    data: payloads[decision] || payloads.PASS,
  });
  if (!res.ok()) {
    throw new Error(`提交报告失败: ${res.status()}`);
  }
  return await res.json();
}

/**
 * 充值余额
 */
export async function apiRecharge(request, token, amount = 10000) {
  const res = await request.post(`${BASE_URL}/api/users/recharge?amount=${amount}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) {
    throw new Error(`充值失败: ${res.status()}`);
  }
  return await res.json();
}
