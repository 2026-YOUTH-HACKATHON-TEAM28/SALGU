import { defineConfig, devices } from '@playwright/test';

/* 화면 동작 시험. 빌드한 운영 서버(mock 통화 60배속)를 띄워 PC와 모바일 크기로 흐름을 확인해요.
 * 브라우저는 설치된 Chrome 을 써요(없으면 PW_CHANNEL=msedge). */
const PORT = Number(process.env.E2E_PORT || 8799);
const channel = process.env.PW_CHANNEL || 'chrome';

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
  },
  projects: [
    { name: 'pc', use: { ...devices['Desktop Chrome'], channel, viewport: { width: 1280, height: 860 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'], channel, viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: 'node dist/server/server/index.js',
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 30_000,
    env: {
      PORT: String(PORT),
      HOST: '127.0.0.1',
      DATA_DIR: '.data-e2e',
      MOCK_TIME_SCALE: '60',
      NODE_ENV: 'production',
      LOG_LEVEL: 'warn',
    },
  },
});
