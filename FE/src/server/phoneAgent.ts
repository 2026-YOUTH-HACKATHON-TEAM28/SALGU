/* AI 폴더 전화 에이전트(AI/phone_agent, 계약 contracts/io.md v0.3.1) 연결.
 * 문의 통화: POST /api/broker-call-batches -> GET /api/broker-call-batches/{id}
 * 확정 통화: POST /api/visit-confirmations -> GET /api/visit-confirmations/{id}
 * 결과를 화면 모양(Call, Listing, Visit)으로 바꿔 대화 상태에 넣어요. 주소가 없으면 시뮬레이션을 그대로 써요. */
import type {
  Broker,
  Call,
  CallLine,
  CallOutcome,
  CallStatus,
  ChatState,
  Listing,
  Visit,
} from '../shared/types.js';
import type { RealCalls, SimInternal } from './mock/sim.js';
import { VISIT_SLOTS, localIso, slotStart } from './mock/sim.js';
import { dongById } from './mock/data.js';
import { priceVerdict, valuesOf } from './mock/engine.js';
import {
  DialogError,
  SRC,
  advanceStage,
  announceCalls,
  announceVisits,
  brokersFor,
  mid,
  preparePlan,
  say,
  touch,
} from './mock/dialog.js';

/* ---------- 전화 에이전트 응답 모양(필요한 칸만) ---------- */

interface AgentListing {
  location?: string | null;
  building?: string | null;
  floor?: string | null;
  unit?: string | null;
  area_m2?: number | null;
  deposit_manwon?: number | null;
  monthly_rent_manwon?: number | null;
  maintenance_fee_manwon?: number | null;
  move_in?: string | null;
}

interface AgentQuote {
  speaker: string;
  text: string;
}

interface AgentCall {
  call_id: string;
  kind: 'inquiry' | 'confirm';
  parent_call_id?: string;
  broker: { reg: string; name: string };
  reg?: string;
  status: CallStatus | 'scheduled' | 'failed' | 'rejected';
  outcome?: string | null;
  listings?: AgentListing[];
  broker_slots?: { start: string; end?: string | null; in_user_window?: boolean }[];
  quotes?: Record<string, AgentQuote>;
  evidence?: Record<string, number>;
  unverified?: string[];
  sms_draft?: string | null;
  attempts?: number;
  retry_at?: string | null;
  error?: string | null;
  message?: string | null;
  rooms?: {
    listing_index: number;
    at: string;
    outcome?: string | null;
    visit_status: 'requesting' | 'confirmed' | 'needs_approval' | 'not_scheduled';
    visit?: { at: string } | null;
    proposal?: { at: string; note?: string } | null;
  }[];
}

interface AgentBatch {
  batch_id: string;
  status?: 'running' | 'done';
  calls: AgentCall[];
}

export class PhoneAgent {
  private mode: 'mock' | 'demo' | 'live' | null = null;

  constructor(
    private readonly url: string,
    private readonly opts: { mockScenario?: string; brokersPerDong: number; uniqueReg: boolean },
  ) {}

  get enabled(): boolean {
    return Boolean(this.url);
  }

  get brokersPerDong(): number {
    return this.opts.brokersPerDong;
  }

  get uniqueReg(): boolean {
    return this.opts.uniqueReg;
  }

  /** 전화 에이전트의 모드(mock / demo). 실패하면 null */
  async health(): Promise<'mock' | 'demo' | 'live' | null> {
    if (!this.enabled) return null;
    try {
      const r = await this.req<{ mode?: string }>('GET', '/api/health', undefined, 4000);
      this.mode = r.mode === 'demo' ? 'demo' : r.mode === 'live' ? 'live' : 'mock';
    } catch {
      this.mode = null;
    }
    return this.mode;
  }

  get lastMode(): 'mock' | 'demo' | 'live' | null {
    return this.mode;
  }

  async req<T>(method: 'GET' | 'POST', path: string, body?: unknown, timeoutMs = 15000): Promise<T> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (this.opts.mockScenario && method === 'POST') headers['X-Mock-Scenario'] = this.opts.mockScenario;
      const res = await fetch(`${this.url.replace(/\/$/, '')}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: ctrl.signal,
      });
      const data = (await res.json().catch(() => ({}))) as T & {
        error?: string;
        message?: string;
        detail?: unknown;
      };
      if (!res.ok) {
        throw new DialogError(
          data.error ?? 'phone_error',
          data.message ?? '전화 서버가 요청을 받지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
        );
      }
      return data;
    } catch (err) {
      if (err instanceof DialogError) throw err;
      throw new DialogError(
        'phone_unreachable',
        '전화 서버에 연결하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
      );
    } finally {
      clearTimeout(timer);
    }
  }
}

/* ---------- 시각: 화면은 서울 시각 문자열(시간대 없음), 전화 에이전트는 +09:00 ---------- */

export const toKst = (local: string) =>
  /[+-]\d\d:\d\d$|Z$/.test(local) ? local : `${local.slice(0, 19)}+09:00`;

export function fromKst(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 19);
  const k = new Date(d.getTime() + 9 * 3600000);
  return k.toISOString().slice(0, 19);
}

/* ---------- 결과 바꾸기 ---------- */

function lines(quotes: Record<string, AgentQuote> | undefined): CallLine[] {
  return Object.entries(quotes ?? {})
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([, q]) => ({
      who: q.speaker === 'broker' ? 'broker' : q.speaker === 'system' ? 'system' : 'agent',
      text: q.text,
    }));
}

const CALL_STATUS: Record<string, CallStatus> = {
  waiting: 'waiting',
  scheduled: 'waiting',
  queued: 'queued',
  ringing: 'ringing',
  in_progress: 'in_progress',
  retry_wait: 'retry_wait',
  analyzing: 'analyzing',
  done: 'done',
  failed: 'done',
  rejected: 'done',
};

function toCall(a: AgentCall, broker: Broker | undefined, listingIds: string[]): Call {
  const status = CALL_STATUS[a.status] ?? 'waiting';
  const failed = a.status === 'failed' || a.status === 'rejected';
  const outcome = failed ? 'unclear' : ((a.outcome ?? null) as CallOutcome | null);
  const ls = lines(a.quotes);
  if (failed) ls.push({ who: 'system', text: a.message || '이 사무소에는 전화를 걸지 못했어요.' });
  return {
    id: a.call_id,
    brokerId: broker?.id ?? a.broker?.reg ?? a.reg ?? '',
    dongId: broker?.dongId ?? '',
    status,
    outcome: status === 'done' ? outcome : null,
    attempts: a.attempts ?? 0,
    retryAt: a.retry_at ? new Date(a.retry_at).toISOString() : null,
    lines: ls,
    listingIds,
    slots: (a.broker_slots ?? []).map((s) => fromKst(s.start)),
    smsDraft: a.sms_draft ?? null,
  };
}

function toListings(
  a: AgentCall,
  broker: Broker,
  housing: 'villa' | 'officetel',
  startNo: number,
): Listing[] {
  return (a.listings ?? []).map((x, i) => {
    const miss = new Set((a.unverified ?? []).map((u) => u.replace(/^listings\[(\d+)\]\./, '$1.')));
    const unverified: string[] = [];
    const area = x.area_m2 ?? null;
    if (area === null || miss.has(`${i}.area_m2`)) unverified.push('area');
    const floor = x.floor ? Number.parseInt(x.floor, 10) : NaN;
    if (Number.isNaN(floor)) unverified.push('floor');
    if (
      x.deposit_manwon === null ||
      x.deposit_manwon === undefined ||
      x.monthly_rent_manwon === null ||
      x.monthly_rent_manwon === undefined
    )
      unverified.push('price');
    if (x.maintenance_fee_manwon === null || x.maintenance_fee_manwon === undefined) unverified.push('fee');
    if (!x.move_in) unverified.push('moveIn');
    const deposit = x.deposit_manwon ?? 0;
    const rent = x.monthly_rent_manwon ?? 0;
    return {
      id: `${a.call_id}-${i}`,
      no: startNo + i,
      callId: a.call_id,
      brokerId: broker.id,
      dongId: broker.dongId,
      building: x.building || x.location || '건물 이름 확인 필요',
      floor: Number.isNaN(floor) ? 0 : floor,
      unit: x.unit ?? '',
      type: housing,
      area: area ?? 0,
      built: 0,
      deposit,
      rent,
      fee: x.maintenance_fee_manwon ?? 0,
      moveIn: x.move_in ?? '확인 필요',
      lat: broker.lat + (i + 1) * 0.0006,
      lng: broker.lng + (i % 2 ? -1 : 1) * 0.0007,
      slots: (a.broker_slots ?? []).map((s) => fromKst(s.start)),
      priceVerdict:
        area !== null && !unverified.includes('price')
          ? priceVerdict(broker.dongId, area, housing, deposit, rent)
          : 'unknown',
      contact: 'answered',
      ...(unverified.length ? { unverified } : {}),
    };
  });
}

/* ---------- 문의 통화 ---------- */

export async function startRealCalls(
  chat: ChatState,
  internal: SimInternal,
  agent: PhoneAgent,
  ctx: { now: Date; useCalls: (n: number) => number; userPhone: string },
): Promise<void> {
  const prep = chat.prep;
  if (!prep) throw new DialogError('no_prep', '전화할 동네를 먼저 골라 주세요.');
  if (!prep.moveIn || !prep.term)
    throw new DialogError('prep_required', '입주 희망일과 계약 기간을 골라 주세요.');
  if (chat.batch && !chat.batch.doneAt) throw new DialogError('calling', '지금 통화가 진행 중이에요.');
  const v = valuesOf(chat.conditions);
  const housing = v.houseType === 'officetel' ? 'officetel' : 'villa';
  const start = slotStart(prep.visitSlot ?? 'sat-pm', ctx.now);
  const end = new Date(start.getTime() + 3 * 3600000);
  const window = { start: toKst(localIso(start)), end: toKst(localIso(end)) };
  const stamp = `${String(ctx.now.getHours()).padStart(2, '0')}${String(ctx.now.getMinutes()).padStart(2, '0')}`;

  const plan = prep.dongIds.map((dongId) => ({
    dongId,
    brokers: brokersFor(chat, dongId).slice(0, agent.brokersPerDong),
  }));
  const total = plan.reduce((n, p) => n + p.brokers.length, 0);
  const allowed = ctx.useCalls(total);
  if (allowed === 0)
    throw new DialogError(
      'daily_limit',
      '오늘 걸 수 있는 통화(하루 10통)를 다 썼어요. 내일 다시 시도해 주세요.',
    );

  const real: RealCalls = { batches: [], confirmIds: [], refs: {}, visitRefs: {} };
  const calls: Call[] = [];
  const used: Broker[] = [];
  const failures: string[] = [];
  let left = allowed;
  for (const p of plan) {
    const brokers = p.brokers.slice(0, left);
    if (!brokers.length) break;
    left -= brokers.length;
    const dong = dongById(p.dongId);
    try {
      const acc = await agent.req<AgentBatch>('POST', '/api/broker-call-batches', {
        approval_id: `${chat.id}-${p.dongId}-${ctx.now.getTime()}`,
        search: {
          dong: `${dong?.gu ?? ''} ${dong?.name ?? ''}`.trim(),
          housing_type: housing,
          deposit_manwon: v.deposit,
          monthly_rent_manwon: v.rent ?? 55,
        },
        prep: { move_in: prep.moveIn, term: prep.term, pet: prep.pet ?? false },
        share: {
          conditions: prep.share.condition,
          visit_time: prep.share.slot,
          surname: prep.share.surname,
          contact: prep.share.contact,
        },
        keep_transcript: false,
        brokers: brokers.map((b) => ({
          // 시연에서는 같은 사무소 하루 1번 규칙에 막히지 않게 등록번호에 시각을 붙여요.
          reg: agent.uniqueReg ? `${b.regNo}-${stamp}` : b.regNo,
          name: b.name,
          // 아직 실제 중개사무소에는 연락하지 않아요. 사용자가 적은 본인 번호로만 걸어요.
          phone: ctx.userPhone,
          visit_windows: prep.share.slot ? [window] : [],
        })),
      });
      real.batches.push({ id: acc.batch_id, dongId: p.dongId, done: false });
      acc.calls.forEach((c, i) => {
        const b = brokers[i];
        if (b)
          calls.push(toCall({ ...c, broker: { reg: c.reg ?? b.regNo, name: b.name } } as AgentCall, b, []));
      });
      used.push(...brokers);
    } catch (err) {
      failures.push(`${dong?.name ?? p.dongId}: ${(err as Error).message}`);
    }
  }
  if (!real.batches.length) throw new DialogError('phone_failed', failures[0] ?? '전화를 시작하지 못했어요.');

  chat.batch = { id: mid('rb'), startedAt: ctx.now.toISOString(), calls, doneAt: null };
  chat.brokers = [...chat.brokers.filter((b) => !used.some((u) => u.id === b.id)), ...used];
  internal.real = real;
  internal.calls = [];
  internal.callsAnnounced = false;
  for (const m of chat.messages) for (const c of m.cards) if (c.kind === 'callPrep') c.done = true;
  const demo = agent.lastMode === 'demo' || agent.lastMode === 'live';
  say(
    chat,
    [
      `중개사무소 ${used.length}곳에 물어볼 통화를 적어 주신 번호(${ctx.userPhone.slice(0, 3)}-****-${ctx.userPhone.slice(-4)})로 차례로 걸게요. 통화 첫마디에 AI 비서라고 밝히고, 고르신 정보만 말해요.`,
      '- 아직 실제 중개사무소에는 연락하지 않아요. 중개사 역할로 받아 주세요',
      ...(failures.length ? [`- 걸지 못한 곳: ${failures.join(', ')}`] : []),
    ].join('\n'),
    {
      cards: [{ kind: 'calls', id: mid('k') }],
      sources: [demo ? { label: 'AI 통화', kind: 'real' } : SRC.calls, SRC.brokers],
    },
    ctx.now,
  );
  chat.live = true;
  touch(chat, ctx.now);
}

/** 전화 에이전트 결과를 읽어 대화 상태에 반영해요. 바뀐 게 있으면 true */
export async function syncReal(
  chat: ChatState,
  internal: SimInternal,
  agent: PhoneAgent,
  now: Date,
): Promise<boolean> {
  const real = internal.real;
  if (!real) return false;
  let changed = false;
  const housing = valuesOf(chat.conditions).houseType === 'officetel' ? 'officetel' : 'villa';

  if (chat.batch && !chat.batch.doneAt) {
    for (const b of real.batches) {
      if (b.done) continue;
      let batch: AgentBatch;
      try {
        batch = await agent.req<AgentBatch>(
          'GET',
          `/api/broker-call-batches/${encodeURIComponent(b.id)}`,
          undefined,
          8000,
        );
      } catch {
        continue;
      }
      for (const a of batch.calls) {
        const reg = (a.broker?.reg ?? '').replace(/-\d{4}$/, '');
        const broker =
          chat.brokers.find((x) => x.regNo === reg && x.dongId === b.dongId) ??
          chat.brokers.find((x) => x.regNo === reg);
        let listingIds: string[] = [];
        if (a.status === 'done' && broker && !chat.listings.some((l) => l.callId === a.call_id)) {
          const fresh = toListings(a, broker, housing, chat.listings.length + 1);
          for (const [i, l] of fresh.entries()) {
            chat.listings.push(l);
            real.refs[l.id] = { callId: a.call_id, index: i };
          }
          if (fresh.length) changed = true;
        }
        listingIds = chat.listings.filter((l) => l.callId === a.call_id).map((l) => l.id);
        const call = toCall(a, broker, listingIds);
        const idx = chat.batch.calls.findIndex((c) => c.id === a.call_id);
        if (idx < 0) chat.batch.calls.push(call);
        else if (JSON.stringify(chat.batch.calls[idx]) !== JSON.stringify(call)) chat.batch.calls[idx] = call;
        else continue;
        changed = true;
      }
      if (batch.status === 'done') {
        b.done = true;
        changed = true;
      }
    }
    if (real.batches.every((b) => b.done)) {
      chat.batch.doneAt = now.toISOString();
      if (!internal.callsAnnounced) {
        internal.callsAnnounced = true;
        announceCalls(chat, now);
      }
      changed = true;
    }
  }

  for (const id of real.confirmIds) {
    const pending = chat.visits.some((v) => v.status === 'requesting' && real.visitRefs[v.id]);
    if (!pending) break;
    let batch: AgentBatch;
    try {
      batch = await agent.req<AgentBatch>(
        'GET',
        `/api/visit-confirmations/${encodeURIComponent(id)}`,
        undefined,
        8000,
      );
    } catch {
      continue;
    }
    for (const a of batch.calls) {
      const q = lines(a.quotes);
      for (const [ri, room] of (a.rooms ?? []).entries()) {
        const visit = chat.visits.find((v) => {
          const r = real.visitRefs[v.id];
          return (
            r && r.callId === a.parent_call_id && r.index === room.listing_index && v.status === 'requesting'
          );
        });
        if (!visit || room.visit_status === 'requesting') continue;
        const said =
          a.evidence?.[`rooms[${ri}].visit.at`] ??
          a.evidence?.[`rooms[${ri}].proposal.at`] ??
          a.evidence?.['visit.at'];
        visit.brokerSaid =
          (said !== undefined ? a.quotes?.[String(said)]?.text : undefined) ??
          q.filter((l) => l.who === 'broker').at(-1)?.text ??
          null;
        const listing = chat.listings.find((l) => l.id === visit.listingId);
        if (room.visit_status === 'confirmed') {
          visit.status = 'confirmed';
          if (room.visit?.at) visit.at = fromKst(room.visit.at);
          if (listing) listing.contact = 'confirmed';
        } else if (room.visit_status === 'needs_approval' && room.proposal?.at) {
          visit.status = 'proposed';
          visit.proposedAt = fromKst(room.proposal.at);
          if (listing) listing.contact = 'proposed';
        } else {
          visit.status = 'failed';
          if (listing) listing.contact = 'failed';
          if (room.outcome === 'unavailable' && !visit.brokerSaid) visit.brokerSaid = '방이 나갔대요.';
        }
        changed = true;
      }
    }
  }
  if (
    real.confirmIds.length &&
    !internal.visitsAnnounced &&
    chat.plan &&
    chat.visits.filter((v) => chat.plan!.visitIds.includes(v.id)).every((v) => v.status !== 'requesting')
  ) {
    internal.visitsAnnounced = true;
    announceVisits(chat, now);
    changed = true;
  }
  const live = Boolean(
    (chat.batch && !chat.batch.doneAt) || chat.visits.some((v) => v.status === 'requesting'),
  );
  if (live !== chat.live) {
    chat.live = live;
    changed = true;
  }
  if (changed) touch(chat, now);
  return changed;
}

/* ---------- 확정 통화 ---------- */

async function confirm(
  chat: ChatState,
  internal: SimInternal,
  agent: PhoneAgent,
  visits: Visit[],
  now: Date,
): Promise<void> {
  const real = internal.real!;
  const window = (() => {
    const s = slotStart(chat.prep?.visitSlot ?? VISIT_SLOTS[1].id, now);
    return { start: toKst(localIso(s)), end: toKst(localIso(new Date(s.getTime() + 3 * 3600000))) };
  })();
  const payload = visits.map((v) => {
    const ref = real.refs[v.listingId];
    if (!ref) throw new DialogError('listing_not_found', '전화로 들은 방이 아니라 확정 전화를 걸 수 없어요.');
    real.visitRefs[v.id] = ref;
    return { call_id: ref.callId, listing_index: ref.index, at: toKst(v.at), alternatives: [window] };
  });
  const acc = await agent.req<AgentBatch>('POST', '/api/visit-confirmations', {
    approval_id: `${chat.id}-v-${now.getTime()}`,
    visits: payload,
  });
  real.confirmIds.push(acc.batch_id);
  internal.visitsAnnounced = false;
}

export async function planRealVisits(
  chat: ChatState,
  internal: SimInternal,
  agent: PhoneAgent,
  listingIds: string[] | null,
  now: Date,
): Promise<void> {
  const snap = structuredClone(chat);
  // 중개사가 된다고 한 시각이 있으면 그 시각으로 요청해요(밖이면 전화 에이전트가 409 로 막아요).
  const visits = preparePlan(chat, listingIds, now, (l, planned) =>
    l.slots[0] ? new Date(l.slots[0]) : planned,
  );
  try {
    await confirm(chat, internal, agent, visits, now);
  } catch (err) {
    Object.assign(chat, snap);
    throw err;
  }
  advanceStage(chat, 'meet');
}

export async function acceptRealProposal(
  chat: ChatState,
  internal: SimInternal,
  agent: PhoneAgent,
  visitId: string,
  now: Date,
): Promise<void> {
  const v = chat.visits.find((x) => x.id === visitId);
  if (!v || v.status !== 'proposed' || !v.proposedAt)
    throw new DialogError('not_found', '제안받은 일정을 찾지 못했어요.');
  const snap = structuredClone(v);
  v.at = v.proposedAt;
  v.status = 'requesting';
  v.proposedAt = null;
  const l = chat.listings.find((x) => x.id === v.listingId);
  if (l) l.contact = 'contacting';
  try {
    await confirm(chat, internal, agent, [v], now);
  } catch (err) {
    Object.assign(v, snap);
    if (l) l.contact = 'proposed';
    throw err;
  }
  chat.live = true;
  touch(chat, now);
}
