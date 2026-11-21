/* 대화 규칙(mock). 말·버튼을 받아 조건과 단계를 바꾸고 살구 답변(문구 + 카드 + 칩)을 만들어요.
 * 실서비스에서는 BE와 AI 대화 에이전트가 같은 모양의 응답을 돌려줘요. */
import type {
  Action,
  Card,
  ChatState,
  CondItem,
  CondKey,
  CondValues,
  Conditions,
  Listing,
  Message,
  SearchResult,
  SourceTag,
  Stage,
  Visit,
} from '../../shared/types.js';
import { COND_META, REQUIRED_CONDS } from '../../shared/labels.js';
import { condValueText, dateOnly, hm, maskPersonal } from '../../shared/format.js';
import { STANDARD, WORKPLACES, brokersOf, dealsOf, dongById } from './data.js';
import { DEFAULTS, searchDongs, tighten, valuesOf, convRent } from './engine.js';
import { extractConds, intentOf } from './nlu.js';
import { CONCEPTS, conceptOf } from './wiki.js';
import type { MappedCard } from '../chatAgent.js';
import type { RecItem } from '../../shared/types.js';
import {
  VISIT_SLOTS,
  emptyInternal,
  localIso,
  planBatch,
  planConfirmations,
  planRoute,
  planTestCall,
  slotStart,
  viewCall,
  type SimInternal,
} from './sim.js';

export interface Ctx {
  now: Date;
  scale: number;
  /** 하루 통화 한도 안에서 쓸 수 있는 통화 수를 돌려줘요 */
  useCalls: (n: number) => number;
  /** 시험 전화(하루 3번)를 하나 쓸 수 있으면 1 */
  useTestCalls: () => number;
  /** AI가 말에서 뽑은 조건(규칙이 못 뽑은 칸만 써요) */
  aiValues?: Partial<Record<CondKey, unknown>>;
}

/** 규칙으로 못 답한 말: 서버가 AI에게 물어 이 답변을 바꿔요 */
export interface TextResult {
  askAi?: { messageId: string; question: string };
}

export class DialogError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

let seq = 0;
export const mid = (p: string) => `${p}${Date.now().toString(36)}${(seq++).toString(36)}`;

export const SRC = {
  deals: { label: '서울시 부동산 전월세가 정보(최근 12개월 계약)', kind: 'example' },
  transit: { label: '카카오맵 대중교통 경로', kind: 'example' },
  bus: { label: '서울시 버스운행노선', kind: 'example' },
  brokers: { label: '서울시 중개업소 정보', kind: 'example' },
  conv: { label: `전월세전환율 ${STANDARD.convRate}%`, kind: 'standard' },
  calls: { label: 'AI 통화', kind: 'simulation' },
  wiki: { label: '살구 설명 문서', kind: 'standard' },
} satisfies Record<string, SourceTag>;

export function newChat(now: Date): { state: ChatState; internal: SimInternal } {
  const iso = now.toISOString();
  return {
    state: {
      id: mid('c'),
      title: '새 대화',
      createdAt: iso,
      updatedAt: iso,
      rev: 1,
      stage: 'cond',
      conditions: {},
      messages: [],
      search: null,
      selectedDongIds: [],
      prep: null,
      batch: null,
      listings: [],
      selectedListingIds: [],
      testCall: null,
      visits: [],
      plan: null,
      brokers: [],
      live: false,
    },
    internal: emptyInternal(),
  };
}

/* ---------- 도움 함수 ---------- */

export function say(
  chat: ChatState,
  text: string,
  opts: { cards?: Card[]; chips?: string[]; sources?: SourceTag[] } = {},
  now = new Date(),
): Message {
  const m: Message = {
    id: mid('m'),
    role: 'bot',
    text,
    cards: opts.cards ?? [],
    chips: opts.chips ?? [],
    sources: opts.sources ?? [],
    at: now.toISOString(),
  };
  chat.messages.push(m);
  return m;
}

export function userSays(chat: ChatState, text: string, now: Date): void {
  chat.messages.push({
    id: mid('m'),
    role: 'user',
    text,
    cards: [],
    chips: [],
    sources: [],
    at: now.toISOString(),
  });
  if (chat.title === '새 대화') chat.title = text.length > 24 ? `${text.slice(0, 24)}…` : text;
}

const STAGE_ORDER: Stage[] = ['cond', 'dong', 'call', 'pick', 'meet'];
export function advanceStage(chat: ChatState, stage: Stage): void {
  if (STAGE_ORDER.indexOf(stage) > STAGE_ORDER.indexOf(chat.stage)) chat.stage = stage;
}

function setSaid(conds: Conditions, key: CondKey, value: unknown): void {
  (conds as Record<string, CondItem<unknown>>)[key] = { value, source: 'said' };
}

const FILL_REASON: Partial<Record<CondKey, string>> = {
  maxCommute: '출퇴근하는 분은 보통 40분 안쪽을 원해서',
  deposit: '보증금을 말하지 않아 청년 원룸에서 흔한 1,000만 원으로 봤어요',
  maxTransfer: '환승이 두 번을 넘으면 출퇴근이 힘들어서',
};

/** 찾기 전에 말하지 않은 중요한 칸을 살구가 채워요(이유와 함께) */
function fillDefaults(conds: Conditions): void {
  for (const key of Object.keys(FILL_REASON) as CondKey[]) {
    if (conds[key] === undefined) {
      (conds as Record<string, CondItem<unknown>>)[key] = {
        value: DEFAULTS[key as keyof CondValues],
        source: 'filled',
        reason: FILL_REASON[key] as string,
      };
    }
  }
}

function missingRequired(conds: Conditions): CondKey[] {
  return REQUIRED_CONDS.filter((k) => conds[k] === undefined);
}

function condLabel(key: CondKey): string {
  return COND_META.find((m) => m.key === key)?.label ?? key;
}

function valueText(key: CondKey, value: unknown): string {
  return condValueText(key, value, WORKPLACES);
}

function wpName(chat: ChatState): string {
  const id = chat.conditions.workplace?.value;
  return WORKPLACES.find((w) => w.id === id)?.name ?? '회사';
}

/* ---------- 조건 ---------- */

function condCard(chat: ChatState, ask?: Extract<Card, { kind: 'cond' }>['ask']): Message {
  const missing = missingRequired(chat.conditions);
  const text = missing.length
    ? `알려 주신 조건을 정리했어요. ${missing.map(condLabel).join('과 ')}만 더 알려 주시면 바로 찾을게요.`
    : '알려 주신 조건을 정리했어요. 맞으면 [이대로 찾기]를 눌러 주세요.';
  return say(chat, text, {
    cards: [{ kind: 'cond', id: mid('k'), ...(ask ? { ask } : {}) }],
    chips: missing.length ? [] : ['출퇴근이 제일 중요해'],
  });
}

function applyExtract(
  chat: ChatState,
  text: string,
  aiValues: Partial<Record<CondKey, unknown>> = {},
): { changed: CondKey[]; unknowns: string[]; ambiguous: boolean } {
  const ex = extractConds(text, WORKPLACES);
  // 규칙이 못 뽑은 칸만 AI 값으로 채워요(값 범위는 같은 검사를 거쳐요).
  for (const [k, v] of Object.entries(aiValues)) {
    if (ex.values[k as CondKey] === undefined && validCondValue(k as CondKey, v)) ex.values[k as CondKey] = v;
  }
  const changed: CondKey[] = [];
  for (const [k, v] of Object.entries(ex.values)) {
    setSaid(chat.conditions, k as CondKey, v);
    changed.push(k as CondKey);
  }
  return { changed, unknowns: ex.unknowns, ambiguous: ex.ambiguous === 'clean' };
}

/* ---------- 동네 ---------- */

function runSearch(chat: ChatState, now: Date, exclude: string[] = [], lead?: string): void {
  const missing = missingRequired(chat.conditions);
  if (missing.length) {
    say(
      chat,
      `${missing.map(condLabel).join('과 ')}를 알려 주셔야 찾을 수 있어요.`,
      { cards: [{ kind: 'cond', id: mid('k') }] },
      now,
    );
    return;
  }
  fillDefaults(chat.conditions);
  if (deferOn.has(chat)) {
    // 대화 에이전트에 물어볼 차례: 라우트가 받아 와서 showSearch 로 마무리해요.
    deferred.set(chat, { exclude, lead });
    return;
  }
  showSearch(chat, searchDongs(chat.conditions, WORKPLACES, exclude), now, lead);
}

/* 동네 찾기를 대화 에이전트에 맡길 때: 대화 규칙은 '찾을 차례'만 남기고 라우트가 비동기로 물어봐요 */
const deferOn = new WeakSet<ChatState>();
const deferred = new WeakMap<ChatState, { exclude: string[]; lead?: string }>();
export function deferSearch(chat: ChatState): void {
  deferOn.add(chat);
}
export function takeDeferredSearch(chat: ChatState): { exclude: string[]; lead?: string } | null {
  deferOn.delete(chat);
  const p = deferred.get(chat) ?? null;
  deferred.delete(chat);
  return p;
}

/** 동네 찾기 결과를 말풍선·카드로 보여 줘요. agent 면 출처를 추천 엔진으로 */
export function showSearch(
  chat: ChatState,
  result: SearchResult,
  now: Date,
  lead?: string,
  agent?: { source: string; notes: string[] },
): void {
  advanceStage(chat, 'dong');
  if (!result.dongs.length) {
    say(
      chat,
      [
        `${lead ? `${lead} ` : ''}지금 조건에 맞는 동네가 없어요. ${agent ? '보증금·월세나 집 유형을 넓혀 볼까요?' : '가장 많이 걸러 낸 조건부터 넓혀 볼까요?'}`,
        ...(agent?.notes ?? []).map((n) => `- ${n}`),
      ].join('\n'),
      {
        cards: [{ kind: 'noMatch', id: mid('k'), losses: result.losses }],
        sources: agent ? [{ label: agent.source, kind: 'real' }] : [SRC.deals, SRC.transit],
      },
      now,
    );
    return;
  }
  chat.search = result;
  chat.selectedDongIds = result.dongs.map((d) => d.id);
  const [a, b] = result.dongs;
  const bullets: string[] = [];
  if (a) {
    bullets.push(
      `1순위는 ${a.name}이에요. 조건 비슷한 계약 ${a.dealCount}건, 환산월세 중간값 ${a.median}만 원${a.commute ? `, ${wpName(chat)}까지 ${a.commute.minutes}분` : ''}`,
    );
  }
  if (a && b) {
    const diff = a.commute && b.commute ? b.commute.minutes - a.commute.minutes : 0;
    const cheaper = b.median - a.median;
    bullets.push(
      diff > 0
        ? `2순위 ${b.name}보다 통근이 ${diff}분 짧아요`
        : cheaper > 0
          ? `2순위 ${b.name}보다 환산월세 중간값이 ${cheaper}만 원 낮아요`
          : `2순위 ${b.name}와 점수가 비슷해요(${a.score}점, ${b.score}점)`,
    );
  }
  say(
    chat,
    [
      agent
        ? `${lead ? `${lead} ` : ''}실거래 추천 엔진(최근 12개월 계약)으로 살만한 동네 ${result.dongs.length}곳을 골랐어요.`
        : `${lead ? `${lead} ` : ''}과거 실거래(최근 12개월)와 출퇴근 여건으로 살만한 동네 ${result.dongs.length}곳을 골랐어요.`,
      ...bullets.map((x) => `- ${x}`),
      ...(agent?.notes ?? []).map((n) => `- ${n}`),
      '실거래는 이미 끝난 계약이라 지금 나온 집은 알 수 없어요. 동네를 고르면 동네마다 중개사무소 여러 곳에 AI가 전화해서 비슷한 방이 있는지 물어볼게요.',
    ].join('\n'),
    {
      cards: [{ kind: 'dongs', id: mid('k'), result, workplace: chat.conditions.workplace?.value ?? '' }],
      chips: [
        `${result.dongs.length}곳 동네 다 전화해줘`,
        '다른 동네도 보여줘',
        '더 싼 데 없어?',
        '1번 자세히 알려줘',
      ],
      sources: agent
        ? [{ label: agent.source, kind: 'real' }, SRC.brokers, SRC.conv]
        : [SRC.deals, SRC.transit, SRC.bus, SRC.brokers, SRC.conv],
    },
    now,
  );
}

/** 동네의 중개사무소: 동네 찾기 결과에 있는 목록(에이전트가 준 것 포함), 없으면 예시 */
export function brokersFor(chat: ChatState, dongId: string) {
  return chat.search?.dongs.find((d) => d.id === dongId)?.brokers ?? brokersOf(dongId);
}

function dongByNo(chat: ChatState, no: number) {
  return chat.search?.dongs.find((d) => d.rank === no) ?? null;
}

/* ---------- 전화 ---------- */

function prepCalls(chat: ChatState, dongIds: string[], now: Date): void {
  const ids = dongIds.filter((id) => chat.search?.dongs.some((d) => d.id === id));
  if (!ids.length) throw new DialogError('no_dong', '전화할 동네를 하나 이상 골라 주세요.');
  if (chat.batch && !chat.batch.doneAt)
    throw new DialogError('calling', '지금 통화가 진행 중이에요. 끝난 뒤에 다시 골라 주세요.');
  chat.selectedDongIds = ids;
  chat.prep = {
    dongIds: ids,
    moveIn: null,
    term: null,
    pet: chat.conditions.pet?.value ?? null,
    visitSlot: null,
    share: { condition: true, slot: true, surname: false, contact: false },
  };
  advanceStage(chat, 'call');
  const names = ids.map((id) => dongById(id)?.name).join(', ');
  const brokerCount = ids.reduce((n, id) => n + brokersFor(chat, id).length, 0);
  say(
    chat,
    `${names}의 등록 중개사무소 ${brokerCount}곳에 전화할게요. 입주 희망일과 계약 기간을 고르면 전화를 시작할 수 있어요.`,
    {
      cards: [{ kind: 'callPrep', id: mid('k'), done: false }],
      sources: [
        ids.every((id) => chat.search?.dongs.find((d) => d.id === id)?.brokersReal)
          ? { label: '중개업소 정보(실거래 DB)', kind: 'real' }
          : SRC.brokers,
      ],
    },
    now,
  );
}

function startCalls(chat: ChatState, internal: SimInternal, ctx: Ctx): void {
  const prep = chat.prep;
  if (!prep) throw new DialogError('no_prep', '전화할 동네를 먼저 골라 주세요.');
  if (!prep.moveIn || !prep.term)
    throw new DialogError('prep_required', '입주 희망일과 계약 기간을 골라 주세요.');
  if (chat.batch && !chat.batch.doneAt) throw new DialogError('calling', '지금 통화가 진행 중이에요.');
  const brokers = prep.dongIds.flatMap((id) => brokersFor(chat, id));
  const allowed = ctx.useCalls(brokers.length);
  if (allowed === 0)
    throw new DialogError(
      'daily_limit',
      '오늘 걸 수 있는 통화(하루 10통)를 다 썼어요. 내일 다시 시도해 주세요.',
    );
  const use = brokers.slice(0, allowed);
  const seed = mid('b');
  const { calls, plans } = planBatch({
    brokers: use,
    prep,
    values: valuesOf(chat.conditions),
    startNo: chat.listings.length + 1,
    now: ctx.now.getTime(),
    scale: ctx.scale,
    seed,
  });
  chat.batch = { id: seed, startedAt: ctx.now.toISOString(), calls, doneAt: null };
  chat.brokers = [...chat.brokers.filter((b) => !use.some((u) => u.id === b.id)), ...use];
  internal.calls = plans;
  internal.callsAnnounced = false;
  for (const m of chat.messages) for (const c of m.cards) if (c.kind === 'callPrep') c.done = true;
  const cut = brokers.length - use.length;
  say(
    chat,
    `중개사무소 ${use.length}곳에 차례로 전화할게요. 통화 첫마디에 AI 비서라고 밝히고, 고르신 정보만 말해요.${
      cut ? ` 하루 10통 한도 때문에 ${cut}곳은 빼고 걸어요.` : ''
    }`,
    { cards: [{ kind: 'calls', id: mid('k') }], sources: [SRC.calls, SRC.brokers] },
    ctx.now,
  );
  chat.live = true;
}

/* ---------- 미팅 ---------- */

function planVisits(chat: ChatState, internal: SimInternal, listingIds: string[] | null, ctx: Ctx): void {
  const visits = preparePlan(chat, listingIds, ctx.now);
  internal.visits = planConfirmations(
    visits.map((v) => ({ visit: v, listing: chat.listings.find((l) => l.id === v.listingId) as Listing })),
    ctx.now.getTime(),
    ctx.scale,
    mid('s'),
  );
  internal.visitsAnnounced = false;
}

/** 고른 방으로 방문 계획(동선 순서·시각)을 만들고 '요청 중'으로 둬요. 확정 통화는 부르는 쪽(시뮬레이션·전화 에이전트)이 해요.
 *  timeOf 를 주면 방마다 요청할 시각을 바꿀 수 있어요(예: 중개사가 된다고 한 시각). */
export function preparePlan(
  chat: ChatState,
  listingIds: string[] | null,
  now: Date,
  timeOf?: (l: Listing, planned: Date) => Date,
): Visit[] {
  if (!chat.listings.length)
    throw new DialogError(
      'no_listing',
      '아직 확인한 매물이 없어요. 중개사무소 통화가 끝난 뒤에 잡을 수 있어요.',
    );
  if (chat.visits.some((v) => v.status === 'requesting'))
    throw new DialogError('confirming', '지금 확정 전화가 진행 중이에요.');
  const ids = listingIds ?? chat.selectedListingIds;
  const ok = chat.listings.filter((l) => ids.includes(l.id) && l.contact !== 'failed');
  if (!ok.length) throw new DialogError('no_pick', '미팅 잡을 방을 하나 이상 골라 주세요.');
  const start = slotStart(chat.prep?.visitSlot ?? 'sat-pm', now);
  const route = planRoute(ok, start);
  const visits: Visit[] = route.map((r, i) => ({
    id: mid('v'),
    listingId: r.listing.id,
    at: localIso(timeOf ? timeOf(r.listing, r.at) : r.at),
    status: 'requesting',
    proposedAt: null,
    order: i + 1,
    travelNext: r.travelNext,
    brokerSaid: null,
    changeRequested: false,
  }));
  // 이전 계획 중 확정되지 않은 것은 정리
  chat.visits = [
    ...chat.visits.filter(
      (v) => v.status === 'confirmed' && !visits.some((n) => n.listingId === v.listingId),
    ),
    ...visits,
  ];
  for (const v of visits) {
    const l = chat.listings.find((x) => x.id === v.listingId);
    if (l) l.contact = 'contacting';
  }
  const last = route[route.length - 1];
  chat.plan = {
    date: localIso(start).slice(0, 10),
    start: localIso(start),
    end: localIso(new Date((last?.at ?? start).getTime() + 30 * 60000)),
    visitIds: visits.map((v) => v.id),
  };
  advanceStage(chat, 'meet');
  say(
    chat,
    `고른 방 ${visits.length}곳을 동선이 짧은 순서로 배치했어요. 중개사무소마다 다시 전화해서 시간을 확정하고 있어요.
- ${dateOnly(chat.plan.start)} ${hm(chat.plan.start)}부터 ${visits.length}곳 방문
- 확정된 방문만 일정 탭에 넣어요`,
    { cards: [{ kind: 'plan', id: mid('k') }], sources: [SRC.calls, SRC.transit] },
    now,
  );
  chat.live = true;
  return visits;
}

function showFinal(chat: ChatState, now: Date): void {
  if (!finalRanking(chat).length) {
    say(chat, '비교할 방이 아직 없어요. 중개사무소 통화가 끝난 뒤에 보여 드릴게요.', {}, now);
    return;
  }
  say(
    chat,
    '방문 후보를 실제 부담(환산월세 + 관리비) 순서로 비교했어요. 숫자 비교일 뿐 계약 판단은 아니에요. 계약은 방을 직접 보고 공인중개사와 함께 정해 주세요.',
    {
      cards: [
        {
          kind: 'final',
          id: mid('k'),
          ranking: finalRanking(chat).map((r) => ({ listingId: r.listing.id, burden: r.burden })),
        },
      ],
      sources: [SRC.calls, SRC.deals, SRC.conv],
    },
    now,
  );
}

/* ---------- 진행(통화·확정) ---------- */

/** 지금 시각까지 통화와 확정 전화를 진행해요. 바뀐 게 있으면 true */
export function advance(chat: ChatState, internal: SimInternal, now: Date): boolean {
  let changed = false;
  const t = now.getTime();
  if (chat.batch && !chat.batch.doneAt && !internal.real) {
    let allDone = true;
    chat.batch.calls = chat.batch.calls.map((call) => {
      const plan = internal.calls.find((p) => p.callId === call.id);
      if (!plan) return call;
      const v = viewCall(call, plan, t);
      if (!v.done) allDone = false;
      if (JSON.stringify(v.call) !== JSON.stringify(call)) changed = true;
      for (const l of v.listings) {
        if (!chat.listings.some((x) => x.id === l.id)) {
          chat.listings.push(structuredClone(l));
          changed = true;
        }
      }
      return v.call;
    });
    if (allDone) {
      chat.batch.doneAt = now.toISOString();
      changed = true;
      if (!internal.callsAnnounced) {
        internal.callsAnnounced = true;
        announceCalls(chat, now);
      }
    }
  }
  if (chat.testCall && !chat.testCall.doneAt && internal.test) {
    let status = chat.testCall.status;
    for (const seg of internal.test.segments) if (seg.from <= t) status = seg.status;
    const lines = internal.test.lines.filter((x) => x.at <= t).map((x) => x.line);
    if (status !== chat.testCall.status || lines.length !== chat.testCall.lines.length) {
      chat.testCall = {
        ...chat.testCall,
        status,
        lines,
        doneAt: status === 'done' ? now.toISOString() : null,
      };
      changed = true;
    }
  }
  for (const vp of internal.visits) {
    const v = chat.visits.find((x) => x.id === vp.visitId);
    if (!v || v.status !== 'requesting' || vp.resolveAt > t) continue;
    v.status = vp.result;
    v.proposedAt = vp.proposedAt;
    v.brokerSaid = vp.brokerSaid;
    const l = chat.listings.find((x) => x.id === v.listingId);
    if (l)
      l.contact = vp.result === 'confirmed' ? 'confirmed' : vp.result === 'proposed' ? 'proposed' : 'failed';
    changed = true;
  }
  if (
    internal.visits.length &&
    !internal.visitsAnnounced &&
    chat.visits.every((v) => v.status !== 'requesting')
  ) {
    internal.visitsAnnounced = true;
    announceVisits(chat, now);
    changed = true;
  }
  const live = Boolean(
    (chat.batch && !chat.batch.doneAt) ||
    chat.visits.some((v) => v.status === 'requesting') ||
    (chat.testCall && !chat.testCall.doneAt),
  );
  if (live !== chat.live) {
    chat.live = live;
    changed = true;
  }
  if (changed) touch(chat, now);
  return changed;
}

export function announceCalls(chat: ChatState, now: Date): void {
  const calls = chat.batch?.calls ?? [];
  const mine = chat.listings.filter((l) => calls.some((c) => c.id === l.callId));
  for (const c of calls) {
    if (c.outcome === 'no_answer') {
      for (const l of chat.listings) if (l.callId === c.id) l.contact = 'no_answer';
    }
  }
  if (!mine.length) {
    say(
      chat,
      '통화가 끝났는데 조건에 맞는 방을 찾지 못했어요. 다른 동네도 찾아볼까요?',
      { chips: ['다른 동네도 보여줘', '조건 바꿀래'], sources: [SRC.calls] },
      now,
    );
    advanceStage(chat, 'pick');
    return;
  }
  advanceStage(chat, 'pick');
  chat.selectedListingIds = mine.filter((l) => l.priceVerdict !== 'high').map((l) => l.id);
  const fair = mine.filter((l) => l.priceVerdict === 'fair').length;
  const dongs = new Set(mine.map((l) => l.dongId)).size;
  say(
    chat,
    `통화가 끝났어요. 동네 ${dongs}곳에서 방 ${mine.length}개를 들었어요.
- 실거래 대비 적정 ${fair}곳
- 실거래보다 비싼 방은 처음에 빼 두었어요
미팅 잡을 방을 고르면 중개사무소마다 다시 전화해 시간을 확정할게요.`,
    {
      cards: [{ kind: 'rooms', id: mid('k') }],
      sources: [SRC.calls, SRC.deals, SRC.conv],
    },
    now,
  );
}

export function announceVisits(chat: ChatState, now: Date): void {
  const ids = chat.plan?.visitIds ?? [];
  const vs = chat.visits.filter((v) => ids.includes(v.id));
  const ok = vs.filter((v) => v.status === 'confirmed').length;
  const prop = vs.filter((v) => v.status === 'proposed').length;
  const fail = vs.filter((v) => v.status === 'failed').length;
  say(
    chat,
    `확정 전화가 끝났어요. 확정 ${ok}곳${prop ? `, 다른 시간 제안 ${prop}곳` : ''}${fail ? `, 일정 못 잡음 ${fail}곳` : ''}이에요. 확정된 방문만 일정 탭에 넣었어요.`,
    { chips: ['최종 추천 보여줘', '일정 탭에서 보기'], sources: [SRC.calls] },
    now,
  );
}

export function touch(chat: ChatState, now: Date): void {
  chat.rev += 1;
  chat.updatedAt = now.toISOString();
}

/* ---------- 말 ---------- */

export function handleText(chat: ChatState, internal: SimInternal, raw: string, ctx: Ctx): TextResult {
  let result: TextResult = {};
  const text = maskPersonal(raw.trim()).slice(0, 500);
  if (!text) throw new DialogError('empty', '내용을 입력해 주세요.');
  const now = ctx.now;
  userSays(chat, text, now);
  const intent = intentOf(text);

  switch (intent.kind) {
    case 'greeting':
      say(
        chat,
        '안녕하세요, 살구예요. 회사(학교) 위치와 월세 예산을 알려 주시면 살만한 동네부터 찾아볼게요.',
        {
          chips: ['조건 골라서 찾기'],
        },
      );
      break;
    case 'condForm':
      openCondForm(chat, now);
      break;
    case 'oneByOne':
      say(chat, '좋아요. 먼저 회사(학교)가 어디예요? 역 이름으로 알려 주셔도 돼요.', {
        chips: ['여의도역', '강남역', '시청역', '가산디지털단지역'],
      });
      break;
    case 'concept': {
      const c = conceptOf(intent.topic);
      if (c)
        say(chat, c.body[0] ?? '', {
          cards: [{ kind: 'concept', id: mid('k'), title: c.title, body: c.body }],
          sources: [SRC.wiki],
        });
      else result = { askAi: { messageId: fallback(chat).id, question: text } };
      break;
    }
    case 'search':
      runSearch(chat, now);
      break;
    case 'moreDongs':
      if (!chat.search) runSearch(chat, now);
      else
        runSearch(
          chat,
          now,
          chat.search.dongs.map((d) => d.id),
          '앞에서 보여 드린 동네를 빼고 다시 찾았어요.',
        );
      break;
    case 'cheaper':
    case 'shorter':
    case 'newer': {
      if (!chat.search?.dongs.length) {
        runSearch(chat, now);
        break;
      }
      const key =
        intent.kind === 'cheaper' ? 'rent' : intent.kind === 'shorter' ? 'maxCommute' : 'builtAfter';
      const value = tighten(key, valuesOf(chat.conditions), chat.search.dongs);
      setSaid(chat.conditions, key, value);
      runSearch(chat, now, [], `${condLabel(key)}을 ${valueText(key, value)}로 조였어요.`);
      break;
    }
    case 'detail': {
      const d = dongByNo(chat, intent.no);
      if (!d) {
        say(chat, `${intent.no}번 동네가 없어요. 동네 목록에서 번호를 확인해 주세요.`);
        break;
      }
      const deals = dealsOf(d.id)
        .filter((x) => !x.renewal)
        .slice(0, 6);
      say(
        chat,
        d.commute
          ? `${d.name}(${d.gu}) 한 장 설명이에요. ${d.station}역 기준으로 ${wpName(chat)}까지 ${d.commute.minutes}분, 환승 ${d.commute.transfers}회예요.`
          : `${d.name}(${d.gu}) 한 장 설명이에요. 실거래 ${d.dealCount}건, 환산월세 중간값 ${d.median}만 원이에요. ${wpName(chat)}까지 통근 시간은 아직 계산하지 못해요.`,
        {
          cards: [{ kind: 'dongDetail', id: mid('k'), dong: d, deals }],
          chips: [`${d.rank}번만 전화해줘`],
          sources:
            d.source === 'agent'
              ? [{ label: '추천 엔진(실거래 DB)', kind: 'real' }, SRC.brokers]
              : [SRC.deals, SRC.transit, SRC.bus, SRC.brokers],
        },
      );
      break;
    }
    case 'callAll':
      if (!chat.search?.dongs.length) say(chat, '먼저 동네를 찾아야 전화할 수 있어요.');
      else
        prepCalls(
          chat,
          chat.search.dongs.map((d) => d.id),
          now,
        );
      break;
    case 'callOnly': {
      const ids = intent.nos.map((n) => dongByNo(chat, n)?.id).filter((x): x is string => Boolean(x));
      if (!ids.length) say(chat, '그 번호의 동네가 없어요. 동네 목록에서 번호를 확인해 주세요.');
      else prepCalls(chat, ids, now);
      break;
    }
    case 'editConds':
      openCondForm(chat, now, '바꿀 조건을 고쳐 주세요. 비워 둔 칸은 상관없는 걸로 볼게요.');
      break;
    case 'plan':
      planVisits(chat, internal, null, ctx);
      break;
    case 'final':
      showFinal(chat, now);
      break;
    case 'question':
      result = { askAi: { messageId: fallback(chat).id, question: text } };
      break;
    case 'other': {
      const { changed, unknowns, ambiguous } = applyExtract(chat, text, ctx.aiValues);
      if (!changed.length && !unknowns.length && !ambiguous) {
        result = { askAi: { messageId: fallback(chat).id, question: text } };
        break;
      }
      // 동네를 이미 찾은 뒤 조건 하나만 바꾼 경우: 바꾼 것만 알려 주고 다시 찾기 제안
      if (chat.search && changed.length && !ambiguous) {
        const parts = changed.map((k) => `${condLabel(k)}을 ${valueText(k, chat.conditions[k]?.value)}`);
        say(chat, `${parts.join(', ')}(으)로 바꿨어요.`, {
          cards: [{ kind: 'cond', id: mid('k') }],
          chips: ['이 조건으로 다시 찾기'],
        });
        break;
      }
      const ask = ambiguous
        ? {
            question: '"깨끗한 집"은 신축 위주로 찾을까요, 관리가 잘 된 곳이면 될까요?',
            options: [
              { label: '신축 위주로', text: '2018년 이후 지은 집으로 찾아줘' },
              { label: '관리 잘 된 곳이면 돼요', text: '준공은 상관없어' },
            ],
          }
        : undefined;
      const m = condCard(chat, ask);
      if (unknowns.length) {
        m.text += ` ${unknowns.join(', ')}은 데이터로 확인할 수 없어서 방을 볼 때 직접 확인해 주세요.`;
      }
      break;
    }
  }
  touch(chat, now);
  return result;
}

/** AI 답으로 바꾸기(규칙 안내 답변 자리에) */
/** 대화 에이전트(AI 폴더) 결과 반영: 조건은 화면 조건으로 바꿔 넣고, 답 문장은 에이전트 말을 써요 */
export function applyAgentTurn(
  chat: ChatState,
  raw: string,
  agent: { reply: string; intent: string; via: string },
  mapped: MappedCard,
  now: Date,
  recs: { items: RecItem[]; notes: string[]; source: string } | null = null,
): void {
  const text = maskPersonal(raw.trim()).slice(0, 500);
  userSays(chat, text, now);
  const src: SourceTag[] = [
    { label: `AI 대화 에이전트(${agent.via.startsWith('rules') ? '규칙' : agent.via})`, kind: 'ai' },
  ];
  if (agent.intent === 'control' && /^좋아요, 처음부터 다시/.test(agent.reply)) chat.conditions = {};
  if (mapped.conds.length) {
    for (const c of mapped.conds) {
      // 사용자가 버튼으로 직접 바꾼 값은 에이전트 짐작으로 덮지 않아요.
      const cur = chat.conditions[c.key] as CondItem<unknown> | undefined;
      if (cur?.source === 'said' && c.source === 'filled') continue;
      if (!validCondValue(c.key, c.value)) continue;
      (chat.conditions as Record<string, CondItem<unknown>>)[c.key] = {
        value: c.value,
        source: c.source,
        ...(c.reason ? { reason: c.reason } : {}),
      };
    }
    const notes: string[] = [];
    if (mapped.notApplied.length)
      notes.push(`${mapped.notApplied.join(', ')}은 아직 동네 찾기에 반영하지 못해요.`);
    const m = condCard(chat, mapped.ask);
    m.text = [agent.reply, ...notes].filter(Boolean).join('\n');
    m.sources = src;
    if (recs?.items.length) {
      // 추천 엔진(실거래 DB) 후보: 조건 카드 아래에 함께 보여 줘요.
      m.text += `\n과거 실거래 기준 후보 ${recs.items.length}곳도 찾았어요. 지금 나온 방인지는 중개사무소 전화로 확인해요.`;
      m.cards.push({ kind: 'recs', id: mid('k'), source: recs.source, notes: recs.notes, items: recs.items });
      m.sources = [...src, { label: recs.source || '추천 엔진(실거래 DB)', kind: 'real' }];
    }
  } else {
    say(chat, agent.reply, { chips: chat.search ? [] : ['조건 골라서 찾기'], sources: src }, now);
  }
  touch(chat, now);
}

export function applyAiAnswer(chat: ChatState, messageId: string, answer: string, model: string): void {
  const m = chat.messages.find((x) => x.id === messageId);
  if (!m) return;
  m.text = answer;
  m.chips = ['조건 골라서 찾기'];
  m.sources = [{ label: `AI 답변(OpenAI ${model}) · 살구 설명 문서 참고`, kind: 'ai' }];
  chat.rev += 1;
}

/** AI에게 줄 근거 자료: 살구 설명 문서와 지금 대화 상황(숫자는 계산 결과만) */
export function aiContext(chat: ChatState): string {
  const conds = Object.entries(chat.conditions)
    .map(
      ([k, item]) =>
        `${condLabel(k as CondKey)} ${valueText(k as CondKey, (item as CondItem<unknown>).value)}`,
    )
    .join(', ');
  const dongs = chat.search?.dongs
    .map(
      (d) =>
        `${d.rank}. ${d.name}(${d.commute ? `통근 ${d.commute.minutes}분, ` : ''}환산월세 중간 ${d.median}만 원)`,
    )
    .join(' / ');
  const docs = Object.values(CONCEPTS)
    .map((c) => `[${c.title}] ${c.body.join(' ')}`)
    .join('\n');
  return [
    `지금 단계: ${chat.stage}`,
    conds ? `사용자 조건: ${conds}` : '사용자 조건: 아직 없음',
    dongs ? `살구가 계산한 동네: ${dongs}` : '',
    '살구가 하는 일: 회사와 월세로 동네를 고르고, 동네 중개사무소에 AI가 전화해 비슷한 방을 묻고, 고른 방으로 방문 시간을 확정해요. 등기부·건축물대장 확인은 하지 않아요.',
    `살구 설명 문서:\n${docs}`,
  ]
    .filter(Boolean)
    .join('\n');
}

function openCondForm(chat: ChatState, now: Date, text?: string): void {
  for (const m of chat.messages) for (const c of m.cards) if (c.kind === 'condForm') c.done = true;
  say(
    chat,
    text ?? '좋아요. 회사(학교)와 월세부터 골라 주세요. 나머지 칸은 비워 두면 상관없는 걸로 볼게요.',
    {
      cards: [{ kind: 'condForm', id: mid('k'), done: false }],
    },
    now,
  );
}

function fallback(chat: ChatState): Message {
  return say(chat, '그 질문은 지금 답하기 어려워요. 집 찾기 조건이나 아래처럼 물어봐 주세요.', {
    chips: [
      '환산월세가 뭐야?',
      '전입신고는 언제까지 해?',
      '청년 월세 지원 받을 수 있어?',
      '조건 골라서 찾기',
    ],
  });
}

/* ---------- 버튼 ---------- */

const NUM_RANGE: Partial<Record<CondKey, [number, number]>> = {
  maxCommute: [10, 120],
  rent: [10, 300],
  deposit: [0, 50000],
  maxTransfer: [0, 3],
  maxBusInterval: [3, 30],
  builtAfter: [1980, 2026],
};

export function validCondValue(key: CondKey, value: unknown): boolean {
  if (key === 'workplace') return typeof value === 'string' && WORKPLACES.some((w) => w.id === value);
  if (key === 'pet' || key === 'parking') return typeof value === 'boolean';
  if (key === 'houseType') return value === 'any' || value === 'villa' || value === 'officetel';
  if (key === 'priority') return ['balanced', 'commute', 'price', 'new'].includes(value as string);
  if (key === 'commercial') return ['any', 'lively', 'quiet'].includes(value as string);
  if (key === 'priceBand') return ['any', 'low', 'mid'].includes(value as string);
  if ((key === 'builtAfter' || key === 'maxBusInterval') && value === null) return true;
  const range = NUM_RANGE[key];
  return (
    typeof value === 'number' && Number.isFinite(value) && !!range && value >= range[0] && value <= range[1]
  );
}

export function handleAction(chat: ChatState, internal: SimInternal, action: Action, ctx: Ctx): void {
  const now = ctx.now;
  switch (action.type) {
    case 'search':
      userSays(chat, '이대로 찾기', now);
      runSearch(chat, now);
      break;
    case 'openCondForm':
      userSays(chat, '조건 골라서 찾을게요', now);
      openCondForm(chat, now);
      break;
    case 'submitCondForm': {
      const vals = action.values;
      if (!vals.workplace) throw new DialogError('workplace_required', '회사(학교) 위치를 골라 주세요.');
      if (vals.rent === undefined || vals.rent === null)
        throw new DialogError('rent_required', '월세 예산을 골라 주세요.');
      for (const [k, v] of Object.entries(vals)) {
        if (v === undefined) continue;
        if (!validCondValue(k as CondKey, v))
          throw new DialogError('invalid', `${condLabel(k as CondKey)} 값을 확인해 주세요.`);
      }
      chat.conditions = {};
      for (const [k, v] of Object.entries(vals))
        if (v !== undefined) setSaid(chat.conditions, k as CondKey, v);
      for (const m of chat.messages) for (const c of m.cards) if (c.kind === 'condForm') c.done = true;
      userSays(chat, '이 조건으로 찾기', now);
      runSearch(chat, now);
      break;
    }
    case 'setCond': {
      if (!COND_META.some((m) => m.key === action.key)) throw new DialogError('invalid', '없는 조건이에요.');
      if (!validCondValue(action.key, action.value))
        throw new DialogError('invalid', `${condLabel(action.key)} 값을 확인해 주세요.`);
      setSaid(chat.conditions, action.key, action.value);
      break;
    }
    case 'resetCond': {
      const item = chat.conditions[action.key] as CondItem<unknown> | undefined;
      if (item?.source === 'widened' && item.original !== undefined) {
        (chat.conditions as Record<string, CondItem<unknown>>)[action.key] = {
          value: item.original,
          source: 'said',
        };
        userSays(chat, `${condLabel(action.key)} 원래대로`, now);
        runSearch(chat, now, [], `${condLabel(action.key)}을 원래 값으로 되돌렸어요.`);
      }
      break;
    }
    case 'toggleDong': {
      const s = new Set(chat.selectedDongIds);
      if (s.has(action.dongId)) s.delete(action.dongId);
      else if (chat.search?.dongs.some((d) => d.id === action.dongId)) s.add(action.dongId);
      chat.selectedDongIds = chat.search?.dongs.map((d) => d.id).filter((id) => s.has(id)) ?? [];
      break;
    }
    case 'prepCalls':
      userSays(chat, '고른 동네 중개사무소들에 전화', now);
      prepCalls(chat, action.dongIds, now);
      break;
    case 'updatePrep': {
      if (!chat.prep) throw new DialogError('no_prep', '전화할 동네를 먼저 골라 주세요.');
      const p = action.patch;
      if (
        p.visitSlot !== undefined &&
        p.visitSlot !== null &&
        !VISIT_SLOTS.some((s) => s.id === p.visitSlot)
      ) {
        throw new DialogError('invalid', '방문 가능 시간을 다시 골라 주세요.');
      }
      chat.prep = {
        ...chat.prep,
        ...(p.moveIn !== undefined ? { moveIn: p.moveIn } : {}),
        ...(p.term !== undefined ? { term: p.term } : {}),
        ...(p.pet !== undefined ? { pet: p.pet } : {}),
        ...(p.visitSlot !== undefined ? { visitSlot: p.visitSlot } : {}),
        ...(p.share ? { share: { ...chat.prep.share, ...p.share } } : {}),
      };
      break;
    }
    case 'startCalls':
      userSays(chat, '이대로 전화하기', now);
      startCalls(chat, internal, ctx);
      break;
    case 'planVisits':
      userSays(chat, '고른 방으로 미팅 잡아줘', now);
      planVisits(chat, internal, action.listingIds ?? null, ctx);
      break;
    case 'showFinal':
      userSays(chat, '최종 추천 보여줘', now);
      showFinal(chat, now);
      break;
    case 'widen':
      widen(chat, action.key, action.value, now);
      break;
    case 'acceptProposal': {
      const v = chat.visits.find((x) => x.id === action.visitId);
      if (!v || v.status !== 'proposed' || !v.proposedAt)
        throw new DialogError('not_found', '제안받은 일정을 찾지 못했어요.');
      v.at = v.proposedAt;
      v.status = 'confirmed';
      v.brokerSaid = `${v.brokerSaid ?? ''} (제안한 시간으로 확정)`.trim();
      const l = chat.listings.find((x) => x.id === v.listingId);
      if (l) l.contact = 'confirmed';
      break;
    }
    case 'toggleListing': {
      if (!chat.listings.some((l) => l.id === action.listingId)) {
        throw new DialogError('not_found', '그 방을 찾지 못했어요.');
      }
      const picked = new Set(chat.selectedListingIds);
      if (picked.has(action.listingId)) picked.delete(action.listingId);
      else picked.add(action.listingId);
      chat.selectedListingIds = chat.listings.map((l) => l.id).filter((id) => picked.has(id));
      break;
    }
    case 'testCall': {
      if (!chat.prep) throw new DialogError('no_prep', '전화할 동네를 먼저 골라 주세요.');
      const digits = String(action.phone ?? '').replace(/\D/g, '');
      if (!/^01[016789]\d{7,8}$/.test(digits)) {
        throw new DialogError('invalid_phone', '휴대폰 번호를 010-1234-5678처럼 적어 주세요.');
      }
      if (chat.testCall && !chat.testCall.doneAt)
        throw new DialogError('testing', '지금 시험 전화가 진행 중이에요.');
      if (ctx.useTestCalls() === 0)
        throw new DialogError('daily_limit', '시험 전화는 하루 3번까지 걸 수 있어요.');
      internal.test = planTestCall(chat.prep, valuesOf(chat.conditions), now.getTime(), ctx.scale);
      // 번호는 가린 값만 남겨요. 실제 전화 서버를 붙이면 번호는 전화 서버로만 보내요.
      chat.testCall = {
        id: mid('t'),
        phone: `${digits.slice(0, 3)}-****-${digits.slice(-4)}`,
        status: 'queued',
        lines: [],
        startedAt: now.toISOString(),
        doneAt: null,
      };
      chat.live = true;
      break;
    }
    case 'cancelVisit': {
      const v = chat.visits.find((x) => x.id === action.visitId);
      if (!v) throw new DialogError('not_found', '그 방문 일정을 찾지 못했어요.');
      v.status = 'cancelled';
      const l = chat.listings.find((x) => x.id === v.listingId);
      if (l) l.contact = 'answered';
      break;
    }
    case 'requestChange': {
      const v = chat.visits.find((x) => x.id === action.visitId);
      if (!v) throw new DialogError('not_found', '그 방문 일정을 찾지 못했어요.');
      v.changeRequested = true;
      break;
    }
  }
  touch(chat, now);
}

/** 넓혀본 조건: 원래 값을 기억해 두고 '넓혀본 값'으로 표시 */
export function widen(chat: ChatState, key: CondKey, value: unknown, now: Date): void {
  if (!validCondValue(key, value) && !(value === 'any'))
    throw new DialogError('invalid', '넓힐 값을 확인해 주세요.');
  const item = chat.conditions[key] as CondItem<unknown> | undefined;
  const original = item?.source === 'widened' ? item.original : item?.value;
  (chat.conditions as Record<string, CondItem<unknown>>)[key] = {
    value,
    source: 'widened',
    reason: '맞는 동네가 없어 살구가 넓혀봤어요',
    ...(original !== undefined ? { original } : {}),
  };
  userSays(chat, `${condLabel(key)} ${valueText(key, value)}까지 넓혀줘`, now);
  runSearch(chat, now, [], `${condLabel(key)}을 ${valueText(key, value)}까지 넓혔어요.`);
  touch(chat, now);
}

/** 최종 추천 순위(실제 부담 낮은 순, 같으면 통근 짧은 순) */
export function finalRanking(chat: ChatState): { listing: Listing; burden: number }[] {
  const visited = new Set(chat.visits.filter((v) => v.status !== 'cancelled').map((v) => v.listingId));
  const pool = chat.listings.filter((l) => visited.has(l.id) || chat.selectedListingIds.includes(l.id));
  return pool
    .map((l) => ({ listing: l, burden: Math.round(convRent(l.deposit, l.rent) + l.fee) }))
    .sort((a, b) => a.burden - b.burden);
}
