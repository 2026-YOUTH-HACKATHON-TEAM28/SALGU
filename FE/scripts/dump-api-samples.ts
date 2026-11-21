/* BE 전달용 JSON 예시 뽑기: mock 서버로 조건부터 일정까지 한 번 돌려 실제 응답을 파일로 남겨요.
 * 실행: node node_modules/tsx/dist/cli.mjs scripts/dump-api-samples.ts docs/api-samples */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { buildApp } from '../src/server/app.js';
import { config } from '../src/server/config.js';
import { Store } from '../src/server/store.js';
import type { ChatState } from '../src/shared/types.js';

const out = process.argv[2] ?? 'docs/api-samples';
mkdirSync(out, { recursive: true });
const app = await buildApp(
  { ...config, timeScale: 3000, clientDir: '__none__', openaiKey: '', kakaoMapKey: '' },
  new Store(null),
);
const json = { 'content-type': 'application/json' };
const login = await app.inject({ method: 'POST', url: '/api/auth/mock-login', headers: json, payload: {} });
const cookie = String(login.headers['set-cookie']).split(';')[0] ?? '';
const save = (name: string, body: unknown) =>
  writeFileSync(join(out, `${name}.json`), `${JSON.stringify(body, null, 2)}\n`, 'utf8');

async function call<T>(method: 'GET' | 'POST', url: string, payload?: object): Promise<T> {
  const res = await app.inject({
    method,
    url,
    headers: method === 'POST' ? { ...json, cookie } : { cookie },
    payload: method === 'POST' ? (payload ?? {}) : undefined,
  });
  return res.json() as T;
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function waitLive(id: string): Promise<ChatState> {
  let c = await call<ChatState>('GET', `/api/chats/${id}`);
  for (let i = 0; i < 100 && c.live; i++) {
    await sleep(50);
    c = await call<ChatState>('GET', `/api/chats/${id}`);
  }
  return c;
}

save('session', await call('GET', '/api/session'));
save('meta', await call('GET', '/api/meta'));
let chat = await call<ChatState>('POST', '/api/chats');
chat = await call<ChatState>('POST', `/api/chats/${chat.id}/messages`, {
  text: '여의도역으로 출근해요. 월세 60만 원 이하, 보증금 1000만 원이면 좋겠어요',
});
save('chat-1-conditions', chat);
chat = await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, { type: 'search' });
save('chat-2-dongs', chat);
chat = await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, {
  type: 'prepCalls',
  dongIds: chat.selectedDongIds,
});
chat = await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, {
  type: 'updatePrep',
  patch: { moveIn: '12월 초', term: '2년', visitSlot: 'sat-pm' },
});
chat = await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, {
  type: 'testCall',
  phone: '01012345678',
});
chat = await waitLive(chat.id);
save('chat-3-prep-testcall', chat);
chat = await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, { type: 'startCalls' });
save('chat-4-calls-started', chat);
chat = await waitLive(chat.id);
save('chat-5-rooms', chat);
chat = await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, {
  type: 'planVisits',
  listingIds: chat.selectedListingIds.slice(0, 3),
});
chat = await waitLive(chat.id);
save('chat-6-visits', chat);
save('schedule', await call('GET', '/api/schedule'));
save('chats', await call('GET', '/api/chats'));
await app.close();
console.warn(`저장: ${out}`);
