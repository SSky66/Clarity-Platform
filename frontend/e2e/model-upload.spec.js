/**
 * E2E测试,文件上传链路
 * 覆盖：数据集上传弹窗、模型上传
 * 策略：通过API前置创建UPLOADING状态的项目，确保上传按钮可见
 */
import { test, expect } from '@playwright/test';
import {
  apiLogin,
  apiRegister,
  apiRecharge,
  apiCreateTask,
  apiAcceptTask,
  apiManufacturerPrepare,
  apiSupplierPrepare,
} from './api-helper';

test.use({ storageState: 'e2e/.auth/manufacturer.json' });

test.describe('文件上传流程', () => {
  test('数据集上传弹窗 - 打开并验证', async ({ page, request }) => {
    // 前置：创建PENDING项目并接单，使其进入UPLOADING状态
    const mfrToken = await apiLogin(request, 'zhizaotest1', '12345678', 'MANUFACTURER');
    await apiRecharge(request, mfrToken, 10000);

    // 注册并充值供应商
    const supAccount = `e2e_sup_upload_${Date.now()}`;
    await apiRegister(request, supAccount, 'TestPass123', 'E2E上传供应商', 'SUPPLIER');
    const supToken = await apiLogin(request, supAccount, 'TestPass123', 'SUPPLIER');
    await apiRecharge(request, supToken, 10000);

    // 创建项目并接单
    const task = await apiCreateTask(request, mfrToken, `E2E上传测试-${Date.now()}`);
    await apiAcceptTask(request, supToken, task.id);

    // 刷新页面
    await page.goto('/manufacturer');
    await page.waitForLoadState('networkidle');

    // 验证上传按钮可见
    const uploadBtn = page.locator('button:has-text("点击上传数据")').first();
    await expect(uploadBtn).toBeVisible({ timeout: 5000 });

    // 点击上传按钮
    await uploadBtn.click();

    // 验证上传弹窗
    await expect(page.locator('text=上传测试数据集')).toBeVisible({ timeout: 5000 });

    // 验证文件输入框存在（hidden input，通过label触发）
    const fileInput = page.locator('input[type="file"]');
    await expect(fileInput).toHaveCount(1);
  });

  test('模型上传 - 供应商上传模型文件', async ({ page, request }) => {
    // 前置：创建项目 → 接单 → 制造商准备，使供应商需要上传模型
    const mfrToken = await apiLogin(request, 'zhizaotest1', '12345678', 'MANUFACTURER');
    await apiRecharge(request, mfrToken, 10000);

    const supAccount = `e2e_model_${Date.now()}`;
    await apiRegister(request, supAccount, 'TestPass123', 'E2E模型供应商', 'SUPPLIER');
    const supToken = await apiLogin(request, supAccount, 'TestPass123', 'SUPPLIER');
    await apiRecharge(request, supToken, 10000);

    // 创建项目并接单
    const task = await apiCreateTask(request, mfrToken, `E2E模型测试-${Date.now()}`);
    await apiAcceptTask(request, supToken, task.id);

    // 制造商准备（上传数据集）
    await apiManufacturerPrepare(request, mfrToken, task.id);

    // 切换到供应商登录态
    await page.goto('/login');
    await page.waitForLoadState('networkidle');

    // 供应商登录
    await page.fill('input[type="text"]', supAccount);
    await page.fill('input[type="password"]', 'TestPass123');
    await page.selectOption('select', 'supplier');
    await page.click('button[type="submit"]');

    // 等待跳转到供应商仪表盘
    await page.waitForURL('**/supplier', { timeout: 15000 });
    await page.waitForLoadState('networkidle');

    // 查找上传模型按钮
    const uploadModelBtn = page.locator('button:has-text("上传模型")').first();
    await expect(uploadModelBtn).toBeVisible({ timeout: 5000 });
    await uploadModelBtn.click();

    // 选择文件
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'test-model.pt',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('mock model content for e2e test'),
    });

    // 提交
    const confirmBtn = page.locator('button:has-text("签署并上传")');
    await expect(confirmBtn).toBeVisible({ timeout: 5000 });
    await confirmBtn.click();

    // 验证上传成功（Toast提示）
    await expect(page.locator('body')).toContainText('模型上传并质押成功', { timeout: 10000 });
  });
});
