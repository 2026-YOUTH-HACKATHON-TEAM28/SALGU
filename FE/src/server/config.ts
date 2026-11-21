import { resolve } from 'node:path';

function num(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n)) throw new Error(`${name} 값이 숫자가 아니에요: ${raw}`);
  return n;
}

/** 서버 설정. 값은 환경 변수에서만 읽고, 키는 코드나 Git에 두지 않아요. */
export const config = {
  port: num('PORT', 8787),
  host: process.env.HOST || '127.0.0.1',
  dataDir: resolve(process.env.DATA_DIR || '.data'),
  /** 앞단 프록시(Caddy)를 믿을지: '1' 이면 모두, '127.0.0.1,172.16.0.0/12' 처럼 주소를 적으면 그 주소만 */
  trustProxy: (process.env.TRUST_PROXY === '1' ? true : process.env.TRUST_PROXY || false) as boolean | string,
  kakaoMapKey: process.env.KAKAO_MAP_KEY || '',
  timeScale: num('MOCK_TIME_SCALE', 1),
  clientDir: resolve(process.env.CLIENT_DIR || 'dist/client'),
  isProd: process.env.NODE_ENV === 'production',
} as const;

export type Config = typeof config;
