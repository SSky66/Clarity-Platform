/**
 * 认证状态保存
 * 通过API直接登录获取Token，绕过UI操作
 */
import { test as setup, expect } from '@playwright/test';
import { apiLogin } from './api-helper';

const authFile = 'e2e/.auth/manufacturer.json';

setup('制造商登录并保存状态', async ({ page, request }) => {
  // 通过API登录获取 oken
  const token = await apiLogin(request, 'zhizaotest1', '12345678', 'MANUFACTURER');

  // 访问前端页面并注入token
  await page.goto('/login');
  await page.waitForLoadState('networkidle');

  // 通过localStorage注入认证状态（与Pinia auth store兼容）
  await page.evaluate((t) => {
    localStorage.setItem('clarity_token', t);
    localStorage.setItem('clarity_user', JSON.stringify({
      id: 2,
      account: 'zhizaotest1',
      role: 'MANUFACTURER',
      display_name: '测试制造商',
    }));
  }, token);

  // 刷新页面让Pinia读取localStorage
  await page.goto('/manufacturer');
  await page.waitForLoadState('networkidle');

  // 验证登录成功
  await expect(page.locator('body')).toContainText('制造商', { timeout: 10000 });

  // 保存完整的浏览器状态（含localStorage + cookies）
  await page.context().storageState({ path: authFile });
});
