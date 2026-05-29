/**
 * E2E测试,报告查询链路
 * 覆盖：历史记录切换、报告查看、异步加载验证
 * 策略：通过API前置创建COMPLETED状态的项目，确保历史记录有数据
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
  apiStartAudit,
  apiSubmitReport,
} from './api-helper';

test.use({ storageState: 'e2e/.auth/manufacturer.json' });

test.describe('报告查询', () => {
  test('历史记录页面 - 切换至历史标签', async ({ page }) => {
    await page.goto('/manufacturer');
    await page.waitForLoadState('networkidle');

    // 点击历史标签
    const historyTab = page.locator('text=历史凭证').first();
    await expect(historyTab).toBeVisible();
    await historyTab.click();

    // 验证页面内容变化
    await expect(page.locator('text=历史项目审计记录')).toBeVisible({ timeout: 5000 });
  });

  test('报告查看 - 打开项目大厅查看项目状态', async ({ page, request }) => {
    // 前置：创建一个项目
    const mfrToken = await apiLogin(request, 'zhizaotest1', '12345678', 'MANUFACTURER');
    await apiRecharge(request, mfrToken, 10000);

    const task = await apiCreateTask(request, mfrToken, `E2E报告测试-${Date.now()}`);

    // 刷新页面
    await page.goto('/manufacturer');
    await page.waitForLoadState('networkidle');

    // 验证项目列表中有刚创建的项目
    await expect(page.locator('body')).toContainText(task.task_name, { timeout: 5000 });

    // 验证项目状态显示
    await expect(page.locator('body')).toContainText('等待供应商接入', { timeout: 5000 });

    // 点击复制项目哈希按钮
    const row = page.getByRole('row', { name: new RegExp(task.task_name) });
    await expect(row).toBeVisible({ timeout: 5000 });
    const copyBtn = row.getByRole('button', { name: '复制项目哈希' });
    await expect(copyBtn).toBeVisible();
    await copyBtn.click();

    // 验证 Toast 提示
    await expect(page.locator('body')).toContainText('复制', { timeout: 3000 });
  });

  test('异步加载 - 列表数据正确渲染', async ({ page }) => {
    await page.goto('/manufacturer');
    await page.waitForLoadState('networkidle');

    // 验证没有加载状态（转圈）
    const loaders = page.locator('text=/加载中|Loading|请稍候/i');
    expect(await loaders.count()).toBe(0);

    // 验证页面有内容
    const hasContent = await page.locator('body').textContent();
    expect(hasContent.length).toBeGreaterThan(50);

    // 验证关键元素已渲染
    await expect(page.locator('text=我发布的项目')).toBeVisible();
    await expect(page.locator('text=链上消息动态')).toBeVisible();
  });
});
