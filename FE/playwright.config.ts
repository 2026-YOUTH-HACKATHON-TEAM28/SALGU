import { defineConfig, devices } from '@playwright/test';

/* 화면 동작 시험. 빌드한 운영 서버(mock 통화 60배속)를 띄워 PC와 모바일 크기로 흐름을 확인해요.
 * 동네 추천·중개사무소는 대화 에이전트에서만 받으므로 시험용 가짜 에이전트(tests/fixtures)를 함께 띄워요.
 * 브라우저는 설치된 Chrome 을 써요(없으면 PW_CHANNEL=msedge). */
const PORT = Number(process.env.E2E_PORT || 8799);
const channel = process.env.PW_CHANNEL || 'chrome';
const AGENT_PORT = Number(process.env.FAKE_AGENT_PORT || 8796);

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
  webServer: [
    {
      command: 'node node_modules/tsx/dist/cli.mjs tests/fixtures/fakeChatAgentServer.ts',
      url: `http://127.0.0.1:${AGENT_PORT}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
      env: { FAKE_AGENT_PORT: String(AGENT_PORT) },
    },
    {
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
        CHAT_AGENT_URL: `http://127.0.0.1:${AGENT_PORT}`,
        OPENAI_API_KEY: '',
        PHONE_AGENT_URL: '',
        BE_URL: '',
        KAKAO_REST_API_KEY: '',
      },
    },
  ],
});
