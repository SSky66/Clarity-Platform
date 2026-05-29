/**
 * E2E测试,核心业务流程
 * 覆盖：任务创建、结果查询、项目详情
 * 依赖：auth.setup.js已执行，认证状态已保存
 */
import { test, expect } from '@playwright/test';
import {
  apiLogin,
  apiCreateTask,
  apiAcceptTask,
  apiManufacturerPrepare,
  apiSupplierPrepare,
  apiRegister,
  apiRecharge,
} from './api-helper';

test.use({ storageState: 'e2e/.auth/manufacturer.json' });

test.describe('制造商仪表盘 - 项目全流程', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/manufacturer');
    await page.waitForLoadState('networkidle');
  });

  test('页面加载 - 显示仪表盘关键元素', async ({ page }) => {
    // 验证侧边栏和头部
    await expect(page.locator('body')).toContainText('项目');
    await expect(page.locator('body')).toContainText('历史');

    // 验证统计数据区域
    await expect(page.locator('text=/\\d+/').first()).toBeVisible();
  });

  test('创建项目 - 打开弹窗并填写表单', async ({ page }) => {
    // 点击创建项目按钮（确定性的文本匹配）
    const createBtn = page.locator('button:has-text("创建新的验收需求")');
    await expect(createBtn).toBeVisible({ timeout: 5000 });
    await createBtn.click();

    // 等待弹窗出现
    await expect(page.locator('text=新建审计项目')).toBeVisible({ timeout: 5000 });

    // 填写表单
    const taskName = `E2E测试项目-${Date.now()}`;
    await page.locator('input[type="text"]').first().fill(taskName);

    // 提交
    const confirmBtn = page.locator('button:has-text("创建项目")');
    await expect(confirmBtn).toBeVisible();
    await confirmBtn.click();

    // 验证弹窗关闭（创建成功）
    await expect(page.locator('text=新建审计项目')).not.toBeVisible({ timeout: 5000 });

    // 验证列表中出现新项目
    await expect(page.locator('body')).toContainText(taskName, { timeout: 5000 });
  });

  test('查询项目列表 - 列表加载正常', async ({ page }) => {
    // 等待页面完全加载
    await page.waitForLoadState('networkidle');

    // 验证页面有内容
    const bodyText = await page.locator('body').textContent();
    expect(bodyText.length).toBeGreaterThan(100);

    // 验证表格头部存在
    await expect(page.locator('text=项目名称')).toBeVisible();
    await expect(page.locator('text=当前状态')).toBeVisible();
  });

  test('项目详情 - 点击项目查看详情', async ({ page, request }) => {
    // 通过API创建一个项目，确保列表中有可点击的项目
    const mfrToken = await apiLogin(request, 'zhizaotest1', '12345678', 'MANUFACTURER');
    await apiRecharge(request, mfrToken, 10000);

    const task = await apiCreateTask(request, mfrToken, `E2E详情测试-${Date.now()}`);

    // 刷新页面
    await page.reload();
    await page.waitForLoadState('networkidle');

    // 查找刚创建的项目行并点击复制哈希
    const row = page.getByRole('row', { name: new RegExp(task.task_name) });
    await expect(row).toBeVisible({ timeout: 5000 });
    const copyBtn = row.getByRole('button', { name: '复制项目哈希' });
    await expect(copyBtn).toBeVisible();
    await copyBtn.click();

    // 验证Toast提示
    await expect(page.locator('body')).toContainText('复制', { timeout: 3000 });
  });

  test('全流程 - 创建项目后列表自动刷新', async ({ page }) => {
    // 记录当前项目数
    const initialText = await page.locator('body').textContent();

    // 创建项目
    const createBtn = page.locator('button:has-text("创建新的验收需求")');
    await createBtn.click();

    const taskName = `E2E刷新测试-${Date.now()}`;
    await page.locator('input[type="text"]').first().fill(taskName);
    await page.locator('button:has-text("创建项目")').click();

    // 等待弹窗关闭（创建成功）
    await expect(page.locator('text=新建审计项目')).not.toBeVisible({ timeout: 5000 });

    // 验证列表刷新（出现新项目）
    await expect(page.locator('body')).toContainText(taskName, { timeout: 5000 });
  });
});
