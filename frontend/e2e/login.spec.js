/**
 * E2E测试,,登录链路
 * 覆盖：页面加载、表单校验、登录成功/失败、角色选择
 */
import { test, expect } from '@playwright/test';
import { apiRegister } from './api-helper';

test.describe('登录页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
  });

  test('页面正确加载 - 显示登录表单和3D背景', async ({ page }) => {
    // 验证登录表单元素
    await expect(page.locator('input[type="text"]').first()).toBeVisible();
    await expect(page.locator('input[type="password"]').first()).toBeVisible();
    await expect(page.locator('button[type="submit"]').first()).toBeVisible();

    // 验证3D画布存在
    await expect(page.locator('canvas')).toBeVisible();
  });

  test('登录失败 - 错误密码显示提示', async ({ page }) => {
    await page.fill('input[type="text"]', 'zhizaotest1');
    await page.fill('input[type="password"]', 'wrongpassword');
    await page.selectOption('select', 'manufacturer');
    await page.click('button[type="submit"]');

    // 等待错误提示（Toast或alert）
    await expect(page.locator('body')).toContainText('错误', { timeout: 5000 });
  });

  test('登录失败 - 不存在的账号', async ({ page }) => {
    await page.fill('input[type="text"]', 'notexist999');
    await page.fill('input[type="password"]', 'anypassword');
    await page.selectOption('select', 'manufacturer');
    await page.click('button[type="submit"]');

    await expect(page.locator('body')).toContainText('错误', { timeout: 5000 });
  });

  test('表单校验 - 空账号不能提交', async ({ page }) => {
    // 尝试提交空表单
    await page.click('button[type="submit"]');

    // 页面应停留在登录页
    await expect(page).toHaveURL(/.*login.*/);
  });

  test('角色切换 - 供应商角色登录', async ({ page, request }) => {
    // 先注册一个供应商账号（通过API）
    const account = `e2e_supplier_${Date.now()}`;
    await apiRegister(request, account, 'TestPass123', 'E2E供应商', 'SUPPLIER');

    // 登录
    await page.fill('input[type="text"]', account);
    await page.fill('input[type="password"]', 'TestPass123');
    await page.selectOption('select', 'supplier');
    await page.click('button[type="submit"]');

    // 应跳转至供应商仪表盘
    await page.waitForURL('**/supplier', { timeout: 15000 });
    await expect(page.locator('body')).toContainText('供应商');
  });
});
