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
  /** OpenAI(대화 보조). 키가 없으면 규칙으로만 답해요 */
  openaiKey: process.env.OPENAI_API_KEY || '',
  openaiModel: process.env.OPENAI_MODEL || 'gpt-5.4-mini',
  aiDailyCap: num('AI_DAILY_CAP', 400),
  /** AI 폴더 대화 에이전트(AI/chat_agent) 주소. 비우면 이 서버 규칙(+OpenAI)으로만 답해요 */
  chatAgentUrl: process.env.CHAT_AGENT_URL || '',
  /** AI 폴더 전화 에이전트(AI/phone_agent) 주소. 비우면 통화는 이 서버 시뮬레이션 */
  phoneAgentUrl: process.env.PHONE_AGENT_URL || '',
  /** BE(Spring Boot) 주소. 있으면 카카오 로그인을 BE 로 넘겨요(예: http://127.0.0.1:8081) */
  beUrl: process.env.BE_URL || '',
  /** 카카오 로컬 REST 키: 동네·회사(학교) 이름을 좌표로 바꿔요. 비우면 자치구 중심 근처에 표시 */
  kakaoRestKey: process.env.KAKAO_REST_API_KEY || '',
  /** 카카오톡 알림(나에게 보내기) 전용 앱의 REST API 키. 비우면 알림 연결을 못 해요.
   *  시크릿은 그 앱에서 클라이언트 시크릿을 켰을 때만(KAKAO_CLIENT_SECRET_NOTIFY) */
  kakaoClientId: process.env.KAKAO_REST_API_KEY_NOTIFY || '',
  kakaoClientSecret: process.env.KAKAO_CLIENT_SECRET_NOTIFY || '',
  /** (로컬 시험용) 전화 에이전트 mock 모드에 보낼 결과 시나리오. 예: listing,two_rooms */
  phoneMockScenario: process.env.PHONE_AGENT_MOCK_SCENARIO || '',
  /** 실제 전화일 때 동네마다 걸 사무소 수(본인 번호로 가니 기본 1곳) */
  phoneBrokersPerDong: num('PHONE_BROKERS_PER_DONG', 1),
  /** 시연에서 같은 사무소 하루 1번 규칙에 막히지 않게 등록번호에 시각을 붙일지 */
  phoneUniqueReg: process.env.PHONE_UNIQUE_REG !== '0',
  timeScale: num('MOCK_TIME_SCALE', 1),
  clientDir: resolve(process.env.CLIENT_DIR || 'dist/client'),
  isProd: process.env.NODE_ENV === 'production',
} as const;

export type Config = typeof config;
