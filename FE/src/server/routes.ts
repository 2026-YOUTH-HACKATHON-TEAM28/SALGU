import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Action, ChatState, ChatSummary, ScheduleItem, SessionInfo, User } from '../shared/types.js';
import { APP_VERSION } from '../shared/version.js';
import type { Config } from './config.js';
import { Store, type UserRecord } from './store.js';
import {
  DialogError,
  PHONE_OFF,
  advance,
  aiContext,
  applyAgentTurn,
  deferSearch,
  searchUnavailable,
  showSearch,
  takeDeferredSearch,
  applyAiAnswer,
  userSays,
  handleAction,
  handleText,
  newChat,
  type Ctx,
} from './mock/dialog.js';
import { intentOf } from './mock/nlu.js';
import { maskPersonal } from '../shared/format.js';
import { Ai } from './ai.js';
import { ChatAgent, mapAgentCard, mapRecs } from './chatAgent.js';
import { PhoneAgent, acceptRealProposal, planRealVisits, startRealCalls, syncReal } from './phoneAgent.js';
import type { ChatRecord } from './store.js';
import { BeAuth } from './beAuth.js';
import {
  agentSearch,
  brokersFromAction,
  brokersFromRealtors,
  condQuestion,
  locateDongs,
  restoreAgentDongs,
} from './dongAgent.js';
import { KakaoLocal } from './kakaoLocal.js';
import { KakaoTalk } from './kakaoTalk.js';
import { randomBytes } from 'node:crypto';
import { dateTime } from '../shared/format.js';
import { DONGS, STATIONS, WORKPLACES, dongById } from './mock/data.js';
import { VISIT_SLOTS } from './mock/sim.js';

const COOKIE = 'sg_sid';

declare module 'fastify' {
  interface FastifyRequest {
    user: UserRecord | null;
  }
}

function publicUser(u: UserRecord): User {
  return { id: u.id, name: u.name, kind: u.kind, photo: u.photo };
}

function summary(c: ChatState): ChatSummary {
  return { id: c.id, title: c.title, updatedAt: c.updatedAt, stage: c.stage };
}

const idParam = {
  type: 'object',
  required: ['id'],
  properties: { id: { type: 'string', minLength: 3, maxLength: 64, pattern: '^[A-Za-z0-9_-]+$' } },
} as const;

export async function registerRoutes(app: FastifyInstance, config: Config, store: Store): Promise<void> {
  const ai = new Ai({
    apiKey: config.openaiKey,
    model: config.openaiModel,
    timeoutMs: 20000,
    dailyCap: config.aiDailyCap,
  });
  const agent = new ChatAgent(config.chatAgentUrl);
  const be = new BeAuth(config.beUrl);
  const kakao = new KakaoLocal(config.kakaoRestKey);
  const talk = new KakaoTalk(config.kakaoClientId, config.kakaoClientSecret);

  /* 카카오톡 알림 보내기(연결한 사용자만). 토큰이 끊겼으면 연결을 풀어요 */
  const notify = async (userId: string, text: string): Promise<boolean> => {
    const u = store.user(userId);
    if (!u?.kakaoTalk || !u.kakaoToken || !talk.enabled) return false;
    const r = await talk.send(u.kakaoToken, text, u.kakaoToken.origin);
    if (r.newToken) u.kakaoToken = { ...r.newToken, origin: u.kakaoToken.origin };
    if (r.revoked) {
      u.kakaoTalk = false;
      u.kakaoToken = null;
    }
    store.markDirty();
    return r.ok;
  };

  /* 통화가 끝나거나 방문이 확정되면 알려요 */
  const announce = async (rec: ChatRecord, before: { done: boolean; confirmed: Set<string> }) => {
    const c = rec.state;
    if (!before.done && c.batch?.doneAt) {
      const calls = c.batch.calls;
      const dongs = [...new Set(calls.map((x) => dongById(x.dongId)?.name).filter(Boolean))].join(', ');
      const has = calls.filter((x) => x.outcome === 'listing').length;
      const none = calls.filter((x) => x.outcome === 'no_listing').length;
      await notify(
        rec.userId,
        `[살구] ${dongs || '고른 동네'} 중개사무소 ${calls.length}곳 문의가 끝났어요. 방 있음 ${has}곳 · 없음 ${none}곳 · 확인 못 함 ${calls.length - has - none}곳. 살구에서 방을 골라 주세요.`,
      );
    }
    for (const v of c.visits) {
      if (v.status !== 'confirmed' || before.confirmed.has(v.id)) continue;
      const l = c.listings.find((x) => x.id === v.listingId);
      const b = c.brokers.find((x) => x.id === l?.brokerId);
      await notify(
        rec.userId,
        `[살구] 방문 확정 ${dateTime(v.at)} · ${dongById(l?.dongId ?? '')?.name ?? ''} ${l?.building ?? ''} ${l?.floor ? `${l.floor}층` : ''} · ${b?.name ?? '중개사무소'}`.replace(
          /\s+/g,
          ' ',
        ),
      );
    }
  };

  /* 방문 알림: 전날 저녁 8시 이후 한 번, 1시간 전 한 번(서버가 5분마다 확인) */
  const kstNow = () => new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 19);
  const remind = async () => {
    const now = kstNow();
    for (const u of store.kakaoUsers()) {
      for (const rec of store.chatsOf(u.id)) {
        for (const v of rec.state.visits) {
          if (v.status !== 'confirmed' || v.at <= now) continue;
          const sent = (rec.internal.reminded ??= {})[v.id] ?? [];
          const at = new Date(`${v.at}Z`);
          const dayBefore = new Date(at.getTime() - 24 * 3600000).toISOString().slice(0, 10) + 'T20:00:00';
          const hourBefore = new Date(at.getTime() - 3600000).toISOString().slice(0, 19);
          const l = rec.state.listings.find((x) => x.id === v.listingId);
          const where = `${dongById(l?.dongId ?? '')?.name ?? ''} ${l?.building ?? ''}`.trim();
          let kind: string | null = null;
          if (now >= hourBefore && !sent.includes('hour')) kind = 'hour';
          else if (now >= dayBefore && now < hourBefore && !sent.includes('day')) kind = 'day';
          if (!kind) continue;
          const ok = await notify(
            u.id,
            kind === 'hour'
              ? `[살구] 1시간 뒤 방문이에요. ${dateTime(v.at)} · ${where}`
              : `[살구] 내일 방문이 있어요. ${dateTime(v.at)} · ${where}`,
          );
          if (ok) {
            rec.internal.reminded![v.id] = [...sent, kind];
            store.markDirty();
          }
        }
      }
    }
  };
  if (talk.enabled) {
    const timer = setInterval(() => void remind().catch(() => undefined), 5 * 60000);
    timer.unref();
    app.addHook('onClose', async () => clearInterval(timer));
  }
  const talkStates = new Map<string, { userId: string; at: number }>();
  be.register(app);
  const phone = new PhoneAgent(config.phoneAgentUrl, {
    mockScenario: config.phoneMockScenario,
    brokersPerDong: config.phoneBrokersPerDong,
    uniqueReg: config.phoneUniqueReg,
  });
  let phoneCheckedAt = 0;
  const phoneMode = async () => {
    if (!phone.enabled) return null;
    if (Date.now() - phoneCheckedAt > 30000) {
      phoneCheckedAt = Date.now();
      await phone.health();
    }
    return phone.lastMode;
  };
  // 실제 통화 결과는 대화를 읽을 때 전화 에이전트에서 가져와요(같은 대화는 1초에 한 번까지).
  const lastSync = new Map<string, number>();
  /* 동네 찾기는 대화 에이전트(실거래 추천 엔진)에 물어봐요. 못 받으면 예시 데이터로 */
  const finishSearch = async (rec: ChatRecord) => {
    const p = takeDeferredSearch(rec.state);
    if (!p) return;
    const turn = await agent.turn(rec.state.id, condQuestion(rec.state, WORKPLACES));
    const result = agentSearch(turn?.backend, p.exclude);
    if (!result) {
      if (turn?.backend?.error) console.error(`[agent] 추천 엔진 오류: ${turn.backend.error.slice(0, 160)}`);
      searchUnavailable(rec.state, new Date());
      return;
    }
    await locateDongs(result, kakao);
    showSearch(rec.state, result, new Date(), p.lead, {
      source: turn?.backend?.source ?? '추천 엔진(실거래 DB)',
      notes: turn?.backend?.notes ?? [],
    });
  };
  /* 회사(학교) 좌표: 회사 목록에 있으면 그 좌표, 없으면 카카오 장소 검색 */
  const locateWorkplace = async (rec: ChatRecord) => {
    const value = rec.state.conditions.workplace?.value;
    if (!value) {
      rec.state.workplacePoint = null;
      return;
    }
    if (rec.state.workplacePoint?.value === value) return;
    const known = WORKPLACES.find((w) => w.id === value);
    const p = known ? { name: known.name, lat: known.lat, lng: known.lng } : await kakao.place(value);
    rec.state.workplacePoint = p ? { value, ...p } : null;
  };
  /* 전화할 동네의 중개사무소: 에이전트에 대표 후보를 '문의'해서 전화 요청 초안의 사무소 목록을 받아요.
   * 에이전트의 마지막 검색이 바뀌었으면(후보 주소가 다르면) 조건으로 다시 찾고 한 번 더 물어요. */
  const fillBrokers = async (rec: ChatRecord, dongIds: string[]) => {
    for (const d of rec.state.search?.dongs ?? []) {
      if (!dongIds.includes(d.id) || d.source !== 'agent' || d.brokersReal || !d.agentPick) continue;
      // 1) 추천 엔진 중개사무소 검색(대표 후보 주소 기준 거리순, 중개업소 DB 와 대조해 영업 중인 곳만)
      const offices = d.agentPick.address ? await agent.realtors(d.agentPick.address, 3) : null;
      const near = offices ? brokersFromRealtors(offices, d.id) : [];
      if (near.length) {
        d.brokers = near;
        d.brokersReal = true;
        continue;
      }
      // 2) 못 받으면 대화 에이전트 전화 요청 초안(같은 동 중개업소 DB)
      const ask = () => agent.turn(rec.state.id, `${d.agentPick!.index}번 집 문의해 줘`);
      let turn = await ask();
      if (turn?.action?.listing?.address !== d.agentPick.address) {
        await agent.turn(rec.state.id, condQuestion(rec.state, WORKPLACES));
        turn = await ask();
        if (turn?.action?.listing?.address !== d.agentPick.address) continue;
      }
      const brokers = brokersFromAction(turn?.action, d);
      if (brokers.length) {
        d.brokers = brokers;
        d.brokersReal = true;
      }
    }
  };
  /* 본인 번호 확인: 휴대폰 번호 형식, 전화 서버 연결(mock 모드는 쓰지 않음).
   * 전화 에이전트(PHONE_AGENT_DIAL_REQUESTED=1)가 이 번호로 걸고, 휴대폰이 아니면 거절해요 */
  const callablePhone = async (raw: unknown): Promise<string> => {
    const digits = String(raw ?? '').replace(/\D/g, '');
    if (!/^01[016789]\d{7,8}$/.test(digits))
      throw new DialogError('invalid_phone', '본인 휴대폰 번호를 010-1234-5678처럼 적어 주세요.');
    if (!phone.enabled) throw new DialogError('phone_off', PHONE_OFF);
    const mode = await phoneMode();
    if (mode !== 'demo' && mode !== 'live') throw new DialogError('phone_off', PHONE_OFF);
    return digits;
  };
  const sync = async (rec: ChatRecord) => {
    restoreAgentDongs(rec.state.search);
    if (!rec.internal.real || !phone.enabled) return;
    const t = Date.now();
    if (t - (lastSync.get(rec.state.id) ?? 0) < 1000) return;
    lastSync.set(rec.state.id, t);
    const before = {
      done: Boolean(rec.state.batch?.doneAt),
      confirmed: new Set(rec.state.visits.filter((v) => v.status === 'confirmed').map((v) => v.id)),
    };
    if (await syncReal(rec.state, rec.internal, phone, new Date())) {
      store.markDirty();
      await announce(rec, before);
    }
  };
  // 에이전트가 맡는 말: 규칙이 흐름 명령으로 알아듣지 못한 자유로운 말
  const AGENT_INTENTS = new Set(['other', 'question', 'greeting', 'oneByOne']);
  app.decorateRequest('user', null);

  app.addHook('preHandler', async (req) => {
    const sid = req.cookies[COOKIE];
    const s = store.session(sid);
    req.user = s ? (store.user(s.userId) ?? null) : null;
  });

  const needUser = async (req: FastifyRequest, reply: FastifyReply) => {
    if (!req.user)
      return reply
        .code(401)
        .send({ error: 'login_required', message: '먼저 로그인하거나 둘러보기를 눌러 주세요.' });
  };

  const setSession = (reply: FastifyReply, req: FastifyRequest, userId: string) => {
    const old = req.cookies[COOKIE];
    if (old) store.deleteSession(old);
    const sid = store.createSession(userId);
    reply.setCookie(COOKIE, sid, {
      path: '/',
      httpOnly: true,
      sameSite: 'lax',
      secure: req.protocol === 'https',
      maxAge: 30 * 86400,
    });
  };

  const ctxFor = (user: UserRecord): Ctx => ({
    now: new Date(),
    scale: config.timeScale,
    useCalls: (n) => store.useCalls(user.id, n, new Date().toISOString().slice(0, 10)),
  });

  const sendDialogError = (reply: FastifyReply, err: unknown) => {
    if (err instanceof DialogError) return reply.code(409).send({ error: err.code, message: err.message });
    throw err;
  };

  /* 세션 · 로그인 */

  app.get('/api/ai', async () => ({
    enabled: ai.enabled,
    model: ai.enabled ? ai.model : null,
    chatAgent: agent.enabled,
    phone: phone.enabled ? (phone.lastMode ?? 'unreachable') : null,
  }));

  app.get('/api/session', async (req, reply): Promise<SessionInfo> => {
    // BE 카카오 로그인을 마치고 돌아오면(JSESSIONID) 그 사용자를 화면 계정과 이어요.
    if (be.enabled && BeAuth.beCookie(req) && req.user?.kind !== 'kakao') {
      const u = await be.me(req);
      if (u) {
        const user = store.userByBe(u.id, u.nickname ?? '');
        setSession(reply, req, user.id);
        req.user = user;
      }
    }
    return {
      user: req.user ? publicUser(req.user) : null,
      version: APP_VERSION,
      kakaoMapKey: config.kakaoMapKey,
      kakaoTalk: req.user?.kakaoTalk ?? false,
      kakaoTalkReady: talk.enabled,
      phoneMode: await phoneMode(),
      brokersPerDong: config.phoneBrokersPerDong,
      kakaoLogin: be.enabled,
    };
  });

  // 카카오 로그인은 서버에 카카오 키가 생기면 /oauth2/authorization/kakao 로 바꿔요. 지금은 예시 계정.
  app.post('/api/auth/mock-login', async (req, reply) => {
    const user = store.createUser('mock', '예시 사용자');
    setSession(reply, req, user.id);
    return { user: publicUser(user) };
  });

  app.post('/api/auth/guest', async (req, reply) => {
    const user = store.createUser('guest', '둘러보는 중');
    setSession(reply, req, user.id);
    return { user: publicUser(user) };
  });

  app.post('/api/auth/logout', async (req, reply) => {
    const sid = req.cookies[COOKIE];
    if (sid) store.deleteSession(sid);
    reply.clearCookie(COOKIE, { path: '/' });
    if (be.enabled) {
      await be.logout(req);
      reply.clearCookie('JSESSIONID', { path: '/' });
    }
    return { ok: true };
  });

  /* 화면에 필요한 기준 데이터 */

  app.get('/api/meta', async (_req, reply) => {
    reply.header('Cache-Control', 'public, max-age=300');
    return {
      workplaces: WORKPLACES.map(({ id, name, lat, lng }) => ({ id, name, lat, lng })),
      visitSlots: VISIT_SLOTS.map(({ id, label }) => ({ id, label })),
      dongs: DONGS.map(({ id, name, gu, lat, lng }) => ({ id, name, gu, lat, lng })),
      stations: STATIONS,
    };
  });

  /* 대화 */

  app.get('/api/chats', { preHandler: needUser }, async (req) => {
    return { chats: store.chatsOf(req.user!.id).map((c) => summary(c.state)) };
  });

  app.post('/api/chats', { preHandler: needUser }, async (req, reply) => {
    const { state, internal } = newChat(new Date());
    store.putChat({ userId: req.user!.id, state, internal });
    return reply.code(201).send(state);
  });

  app.get<{ Params: { id: string }; Querystring: { rev?: string } }>(
    '/api/chats/:id',
    { preHandler: needUser, schema: { params: idParam } },
    async (req, reply) => {
      const rec = store.chat(req.params.id, req.user!.id);
      if (!rec) return reply.code(404).send({ error: 'not_found', message: '대화를 찾지 못했어요.' });
      await sync(rec);
      if (advance(rec.state, rec.internal, new Date())) store.markDirty();
      if (req.query.rev && Number(req.query.rev) === rec.state.rev) return reply.code(204).send();
      return rec.state;
    },
  );

  app.delete<{ Params: { id: string } }>(
    '/api/chats/:id',
    { preHandler: needUser, schema: { params: idParam } },
    async (req, reply) => {
      if (!store.deleteChat(req.params.id, req.user!.id)) return reply.code(404).send({ error: 'not_found' });
      return { ok: true };
    },
  );

  app.post<{ Params: { id: string }; Body: { text: string } }>(
    '/api/chats/:id/messages',
    {
      preHandler: needUser,
      config: { rateLimit: { max: 30, timeWindow: '1 minute' } },
      schema: {
        params: idParam,
        body: {
          type: 'object',
          required: ['text'],
          additionalProperties: false,
          properties: { text: { type: 'string', minLength: 1, maxLength: 500 } },
        },
      },
    },
    async (req, reply) => {
      const rec = store.chat(req.params.id, req.user!.id);
      if (!rec) return reply.code(404).send({ error: 'not_found', message: '대화를 찾지 못했어요.' });
      await sync(rec);
      advance(rec.state, rec.internal, new Date());
      const text = maskPersonal(req.body.text.trim());
      // 1) AI 폴더의 대화 에이전트가 있으면 자유로운 말은 에이전트가 이해해요.
      const intent = intentOf(text).kind;
      // 실제 통화 중인 대화에서 "미팅 잡아줘"는 전화 에이전트로 확정 통화를 걸어요.
      if (intent === 'plan' && rec.internal.real && phone.enabled) {
        try {
          userSays(rec.state, text, new Date());
          await planRealVisits(rec.state, rec.internal, phone, null, new Date());
        } catch (err) {
          rec.state.messages.pop();
          return sendDialogError(reply, err);
        }
        store.putChat(rec);
        return rec.state;
      }
      if (agent.enabled && AGENT_INTENTS.has(intent)) {
        const turn = await agent.turn(rec.state.id, text);
        const askingMore = turn?.intent === 'control' && /다른|더\s*보여|자세히|번째/.test(text);
        const generic = turn?.intent === 'question' && turn.via.startsWith('rules');
        if (turn && !askingMore && !(generic && ai.enabled)) {
          // 에이전트의 자체 검색 말풍선(예시 응답)은 빼고 첫 답(reply)만 써요. 동네 찾기는 이 서버가 해요.
          const reply = turn.messages?.find((m) => m.kind === 'reply')?.text ?? turn.reply;
          const items = mapRecs(turn.backend);
          applyAgentTurn(
            rec.state,
            text,
            { ...turn, reply },
            mapAgentCard(turn.card, WORKPLACES),
            new Date(),
            items.length
              ? {
                  items,
                  notes: turn.backend?.notes ?? [],
                  source: turn.backend?.source ?? '추천 엔진(실거래 DB)',
                }
              : null,
          );
          await locateWorkplace(rec);
          store.putChat(rec);
          return rec.state;
        }
      }
      // 2) 규칙이 의도를 모르는 말이면 AI가 먼저 조건을 뽑아 봐요.
      const aiValues =
        ai.enabled && intentOf(text).kind === 'other' ? await ai.extract(text, WORKPLACES) : {};
      let result;
      if (agent.enabled) deferSearch(rec.state);
      // '다 전화해줘', '2번만 전화해줘': 전화 준비 전에 중개사무소를 에이전트에서 받아 둬요.
      if (agent.enabled && (intent === 'callAll' || intent === 'callOnly'))
        await fillBrokers(rec, rec.state.search?.dongs.map((d) => d.id) ?? []);
      try {
        result = handleText(rec.state, rec.internal, text, { ...ctxFor(req.user!), aiValues });
      } catch (err) {
        takeDeferredSearch(rec.state);
        return sendDialogError(reply, err);
      }
      await finishSearch(rec);
      await locateWorkplace(rec);
      // 규칙으로 못 답한 질문은 AI가 답해요(실패하면 규칙 안내 그대로).
      if (result.askAi && ai.enabled) {
        const answer = await ai.answer(result.askAi.question, aiContext(rec.state));
        if (answer) applyAiAnswer(rec.state, result.askAi.messageId, answer, ai.model);
      }
      store.putChat(rec);
      return rec.state;
    },
  );

  app.post<{ Params: { id: string }; Body: Action }>(
    '/api/chats/:id/actions',
    {
      preHandler: needUser,
      config: { rateLimit: { max: 60, timeWindow: '1 minute' } },
      schema: {
        params: idParam,
        body: { type: 'object', required: ['type'], properties: { type: { type: 'string', maxLength: 32 } } },
      },
    },
    async (req, reply) => {
      const rec = store.chat(req.params.id, req.user!.id);
      if (!rec) return reply.code(404).send({ error: 'not_found', message: '대화를 찾지 못했어요.' });
      await sync(rec);
      advance(rec.state, rec.internal, new Date());
      const a = req.body;
      try {
        // 전화 에이전트가 있으면 문의·확정 통화는 실제 에이전트로(없으면 시뮬레이션)
        if (a.type === 'startCalls') {
          // 이 프로젝트는 아직 실제 중개사무소에 연락하지 않아요. 사용자가 적은 본인 번호로만 걸어요.
          const digits = await callablePhone(a.phone);
          userSays(rec.state, '이대로 전화하기', new Date());
          try {
            await startRealCalls(rec.state, rec.internal, phone, {
              now: new Date(),
              useCalls: ctxFor(req.user!).useCalls,
              userPhone: digits,
            });
          } catch (err) {
            rec.state.messages.pop();
            throw err;
          }
        } else if (phone.enabled && rec.internal.real && a.type === 'planVisits') {
          userSays(rec.state, '고른 방으로 미팅 잡아줘', new Date());
          try {
            await planRealVisits(rec.state, rec.internal, phone, a.listingIds ?? null, new Date());
          } catch (err) {
            rec.state.messages.pop();
            throw err;
          }
        } else if (
          phone.enabled &&
          rec.internal.real?.visitRefs[(a as { visitId?: string }).visitId ?? ''] &&
          a.type === 'acceptProposal'
        ) {
          await acceptRealProposal(rec.state, rec.internal, phone, a.visitId, new Date());
        } else {
          if (agent.enabled) deferSearch(rec.state);
          if (agent.enabled && a.type === 'prepCalls') await fillBrokers(rec, a.dongIds);
          handleAction(rec.state, rec.internal, a, ctxFor(req.user!));
          await finishSearch(rec);
          await locateWorkplace(rec);
        }
      } catch (err) {
        takeDeferredSearch(rec.state);
        return sendDialogError(reply, err);
      }
      store.putChat(rec);
      return rec.state;
    },
  );

  /* 일정 */

  app.get('/api/schedule', { preHandler: needUser }, async (req) => {
    const items: ScheduleItem[] = [];
    for (const rec of store.chatsOf(req.user!.id)) {
      await sync(rec);
      if (advance(rec.state, rec.internal, new Date())) store.markDirty();
      const c = rec.state;
      for (const v of c.visits) {
        if (v.status !== 'confirmed') continue;
        const listing = c.listings.find((l) => l.id === v.listingId);
        if (!listing) continue;
        const dong = dongById(listing.dongId);
        items.push({
          chatId: c.id,
          visit: v,
          listing,
          broker: c.brokers.find((b) => b.id === listing.brokerId) ?? null,
          dongName: dong?.name ?? '',
          station: dong?.station ?? '',
        });
      }
    }
    items.sort((a, b) => a.visit.at.localeCompare(b.visit.at));
    return { items };
  });

  /* 카카오톡 알림(시험 연결) */

  app.post<{ Body: { on: boolean } }>(
    '/api/notify/kakao',
    {
      preHandler: needUser,
      schema: { body: { type: 'object', required: ['on'], properties: { on: { type: 'boolean' } } } },
    },
    async (req, reply) => {
      if (req.user!.kind === 'guest') {
        return reply
          .code(403)
          .send({ error: 'login_required', message: '카카오톡 알림은 로그인한 뒤에 연결할 수 있어요.' });
      }
      // 켜기는 카카오 동의 화면(/api/notify/kakao/connect)으로만 해요. 여기서는 끄기만
      if (req.body.on)
        return reply
          .code(409)
          .send({ error: 'consent_required', message: '카카오 화면에서 메시지 전송에 동의해 주세요.' });
      req.user!.kakaoTalk = false;
      req.user!.kakaoToken = null;
      store.markDirty();
      return { kakaoTalk: false };
    },
  );

  app.post(
    '/api/notify/test',
    { preHandler: needUser, config: { rateLimit: { max: 3, timeWindow: '1 minute' } } },
    async (req, reply) => {
      if (!req.user!.kakaoTalk)
        return reply.code(409).send({ error: 'not_connected', message: '카카오톡이 연결되어 있지 않아요.' });
      const ok = await notify(
        req.user!.id,
        '[살구] 카카오톡 알림이 연결됐어요. 통화 결과와 방문 일정을 여기로 알려 드릴게요.',
      );
      if (!ok)
        return reply
          .code(502)
          .send({ error: 'send_failed', message: '카카오톡으로 보내지 못했어요. 연결을 다시 해 주세요.' });
      return { ok: true };
    },
  );

  /* 카카오톡 알림 동의: 카카오 화면으로 보냈다가 돌아와요 */
  const callbackUrl = (req: FastifyRequest) => `${req.protocol}://${req.host}/api/notify/kakao/callback`;
  app.get('/api/notify/kakao/connect', async (req, reply) => {
    if (!req.user || req.user.kind === 'guest') return reply.redirect('/?kakao=login');
    if (!talk.enabled) return reply.redirect('/?kakao=unavailable');
    for (const [k, v] of talkStates) if (Date.now() - v.at > 10 * 60000) talkStates.delete(k);
    const state = randomBytes(16).toString('hex');
    talkStates.set(state, { userId: req.user.id, at: Date.now() });
    return reply.redirect(talk.authorizeUrl(callbackUrl(req), state));
  });
  app.get<{ Querystring: { code?: string; state?: string; error?: string } }>(
    '/api/notify/kakao/callback',
    async (req, reply) => {
      const st = talkStates.get(req.query.state ?? '');
      talkStates.delete(req.query.state ?? '');
      if (!st || !req.user || st.userId !== req.user.id || !req.query.code)
        return reply.redirect('/?kakao=error');
      const tok = await talk.exchange(req.query.code, callbackUrl(req));
      if (!tok) return reply.redirect('/?kakao=error');
      req.user.kakaoTalk = true;
      req.user.kakaoToken = { ...tok, origin: `${req.protocol}://${req.host}/` };
      store.markDirty();
      return reply.redirect('/?kakao=connected');
    },
  );
}
