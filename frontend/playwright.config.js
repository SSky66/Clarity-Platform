import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright 配置
 * 覆盖：登录、任务创建、模型上传、结果查询 4个关键链路
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // UI测试串行执行，避免状态干扰
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // 单worker，避免登录态冲突
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['list'],
  ],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // 自动等待配置
    actionTimeout: 10000,
    navigationTimeout: 15000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // 测试前启动前端开发服务器
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
