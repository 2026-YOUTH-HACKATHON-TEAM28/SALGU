import { defineConfig } from 'vitest/config';

// 개발: vite(5173)가 화면을, mock API 서버(8787)가 /api 를 맡아요.
// 운영: 빌드한 화면(dist/client)과 /api 를 Node 서버 하나(8080)가 함께 내보내요.
export default defineConfig({
  root: '.',
  publicDir: 'public',
  build: {
    outDir: 'dist/client',
    emptyOutDir: true,
    sourcemap: true,
    target: 'es2022',
  },
  server: {
    port: 5173,
    proxy: {
      // Host 를 그대로 넘겨야 서버의 출처 확인(같은 호스트)이 통과해요.
      '/api': { target: 'http://127.0.0.1:8787', changeOrigin: false },
    },
  },
  test: {
    include: ['tests/unit/**/*.test.ts'],
    environment: 'node',
  },
});
