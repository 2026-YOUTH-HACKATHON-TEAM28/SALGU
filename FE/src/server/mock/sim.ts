/* 문의·확정·시험 통화 시뮬레이션(mock). 모양은 전화 에이전트 문서(v0.3.1)의 결과와 같아요.
 * 처음 만들 때 전체 진행표를 정해 두고, 읽을 때마다 지금 시각까지 진행한 모습을 보여 줘요. */
import type {
  Broker,
  Call,
  CallLine,
  CallOutcome,
  CallPrep,
  CallStatus,
  CondValues,
  Listing,
  Visit,
} from '../../shared/types.js';
import { buildingsOf, dongById, rng } from './data.js';
import { priceVerdict } from './engine.js';

export interface Segment {
  status: CallStatus;
  from: number;
}

export interface CallPlan {
  callId: string;
  segments: Segment[];
  outcome: CallOutcome;
  attempts: { at: number }[];
  retryAt: number | null;
  lines: { at: number; line: CallLine }[];
  listings: Listing[];
  slots: string[];
  smsDraft: string | null;
  doneAt: number;
}

export interface VisitPlan {
  visitId: string;
  resolveAt: number;
  result: 'confirmed' | 'proposed' | 'failed';
  proposedAt: string | null;
  brokerSaid: string;
}

export interface SimInternal {
  calls: CallPlan[];
  visits: VisitPlan[];
  callsAnnounced: boolean;
  visitsAnnounced: boolean;
  /** 실제 전화 에이전트로 건 통화(있으면 시뮬레이션 대신 이 묶음을 따라가요) */
  real?: RealCalls | null;
  /** 카카오톡으로 보낸 방문 알림(방문 id -> 'day' 전날 저녁, 'hour' 1시간 전) */
  reminded?: Record<string, string[]>;
}

export interface RealCalls {
  batches: { id: string; dongId: string; done: boolean }[];
  confirmIds: string[];
  /** 화면 매물 id -> 전화 에이전트 (문의 call_id, listing 순서) */
  refs: Record<string, { callId: string; index: number }>;
  /** 화면 방문 id -> 같은 방 */
  visitRefs: Record<string, { callId: string; index: number }>;
}

export const emptyInternal = (): SimInternal => ({
  calls: [],
  visits: [],
  callsAnnounced: false,
  visitsAnnounced: false,
});

const SEC = 1000;

/* ---------- 방문 가능 시간 ---------- */

export const VISIT_SLOTS = [
  { id: 'sat-am', label: '이번 토요일 오전', day: 6, hour: 10 },
  { id: 'sat-pm', label: '이번 토요일 오후', day: 6, hour: 14 },
  { id: 'sun-pm', label: '이번 일요일 오후', day: 0, hour: 14 },
  { id: 'weekday-eve', label: '평일 저녁', day: -1, hour: 19 },
] as const;

/** 방문 가능 시간의 시작 시각(로컬). 오늘이 주말이면 다음 주로 */
export function slotStart(slotId: string, now: Date): Date {
  const slot = VISIT_SLOTS.find((s) => s.id === slotId) ?? VISIT_SLOTS[1];
  const d = new Date(now);
  d.setHours(slot.hour, 0, 0, 0);
  if (slot.day === -1) {
    do d.setDate(d.getDate() + 1);
    while (d.getDay() === 0 || d.getDay() === 6);
    return d;
  }
  // 오늘 이후 가장 가까운 그 요일(오늘이 그 요일이면 다음 주)
  let add = (slot.day - now.getDay() + 7) % 7;
  if (add === 0) add = 7;
  d.setDate(d.getDate() + add);
  return d;
}

function localIso(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:00`;
}

/** 영업시간(월~토 9~19시)인지 */
export function inBusinessHours(now: Date): boolean {
  return now.getDay() !== 0 && now.getHours() >= 9 && now.getHours() < 19;
}

/* ---------- 문의 통화 ---------- */

interface BatchInput {
  brokers: Broker[];
  prep: CallPrep;
  values: CondValues;
  startNo: number;
  now: number;
  scale: number;
  seed: string;
}

function pickOutcome(r: () => number): { first: CallOutcome; retry: boolean } {
  const x = r();
  if (x < 0.55) return { first: 'listing', retry: false };
  if (x < 0.68) return { first: 'no_listing', retry: false };
  if (x < 0.78) return { first: 'listing', retry: true };
  if (x < 0.86) return { first: 'no_answer', retry: true };
  if (x < 0.93) return { first: 'declined', retry: false };
  return { first: 'unclear', retry: false };
}

export function planBatch(input: BatchInput): { calls: Call[]; plans: CallPlan[] } {
  const { brokers, prep, values, now, scale } = input;
  const d = (s: number) => (s * SEC) / scale;
  let cursor = now + d(2);
  let no = input.startNo;
  const calls: Call[] = [];
  const plans: CallPlan[] = [];
  const queue: { broker: Broker; idx: number; retry: boolean; notBefore: number; attempt: number }[] =
    brokers.map((b, idx) => ({ broker: b, idx, retry: false, notBefore: 0, attempt: 1 }));
  const slotFrom = slotStart(prep.visitSlot ?? 'sat-pm', new Date(now));
  const rent = values.rent ?? 55;

  for (const b of brokers) {
    calls.push({
      id: `call-${input.seed}-${b.id}`,
      brokerId: b.id,
      dongId: b.dongId,
      status: 'waiting',
      outcome: null,
      attempts: 0,
      retryAt: null,
      lines: [],
      listingIds: [],
      slots: [],
      smsDraft: null,
    });
    plans.push({
      callId: `call-${input.seed}-${b.id}`,
      segments: [{ status: 'waiting', from: now }],
      outcome: 'unclear',
      attempts: [],
      retryAt: null,
      lines: [],
      listings: [],
      slots: [],
      smsDraft: null,
      doneAt: 0,
    });
  }

  while (queue.length) {
    queue.sort((a, b) => Math.max(a.notBefore, 0) - Math.max(b.notBefore, 0) || a.idx - b.idx);
    const job = queue.findIndex((j) => j.notBefore <= cursor);
    const item = job >= 0 ? queue.splice(job, 1)[0]! : queue.shift()!;
    if (item.notBefore > cursor) cursor = item.notBefore;
    const plan = plans[item.idx]!;
    const dong = dongById(item.broker.dongId);
    const r = rng(`${input.seed}:${item.broker.id}`);
    const { first, retry } = pickOutcome(r);
    const answered = !(retry && item.attempt === 1);
    const outcome: CallOutcome = answered ? (first === 'no_answer' ? 'no_answer' : first) : 'no_answer';

    plan.attempts.push({ at: cursor });
    plan.segments.push({ status: 'queued', from: cursor });
    plan.segments.push({ status: 'ringing', from: cursor + d(1) });
    const line = (at: number, who: CallLine['who'], text: string) =>
      plan.lines.push({ at, line: { who, text } });

    if (outcome === 'no_answer') {
      const end = cursor + d(16);
      line(
        end,
        'system',
        item.attempt === 1
          ? '받지 않음. 2분 뒤 다시 걸어요.'
          : '두 번 모두 받지 않음. 문자 초안을 만들었어요.',
      );
      if (item.attempt === 1) {
        plan.segments.push({ status: 'retry_wait', from: end });
        plan.retryAt = end + d(120);
        queue.push({ ...item, retry: true, notBefore: end + d(120), attempt: 2 });
      } else {
        plan.segments.push({ status: 'done', from: end });
        plan.outcome = 'no_answer';
        plan.doneAt = end;
        plan.smsDraft = `안녕하세요, 살구입니다. ${dong?.name ?? ''} 근처 월세 ${rent}만 원 이하 방을 찾는 분이 있어 연락드렸어요. 비슷한 방이 있으면 이 번호로 답장 부탁드려요.`;
      }
      cursor = end + d(1);
      continue;
    }

    const talk = cursor + d(5);
    plan.segments.push({ status: 'in_progress', from: talk });
    line(
      talk,
      'agent',
      '안녕하세요, 저는 살구의 AI 비서예요. 집을 구하는 분을 대신해 전화드렸어요. 원하지 않으시면 말씀해 주세요.',
    );
    if (outcome === 'declined') {
      line(talk + d(4), 'broker', 'AI랑은 통화 안 할게요.');
      line(talk + d(6), 'agent', '알겠습니다. 다시 전화드리지 않을게요.');
      const end = talk + d(8);
      plan.segments.push({ status: 'done', from: end });
      plan.outcome = 'declined';
      plan.doneAt = end;
      cursor = end + d(1);
      continue;
    }
    line(talk + d(3), 'broker', '네, 말씀하세요.');
    const share = prep.share.condition
      ? `${dong?.name ?? ''} 근처 월세 ${rent}만 원 이하, 보증금 ${values.deposit.toLocaleString('ko-KR')}만 원 정도 방 있을까요?`
      : `${dong?.name ?? ''} 근처 원룸 있을까요?`;
    line(talk + d(5), 'agent', `${share}${prep.moveIn ? ` 입주는 ${prep.moveIn}이에요.` : ''}`);

    if (outcome === 'unclear') {
      line(talk + d(9), 'broker', '(잡음) ... 다시 ... 나중에 ...');
      line(talk + d(12), 'system', '통화 품질이 나빠 내용을 확인하지 못했어요.');
      const end = talk + d(14);
      plan.segments.push({ status: 'analyzing', from: end }, { status: 'done', from: end + d(4) });
      plan.outcome = 'unclear';
      plan.doneAt = end + d(4);
      cursor = plan.doneAt + d(1);
      continue;
    }
    if (outcome === 'no_listing') {
      line(talk + d(9), 'broker', '지금은 그 가격대가 없어요. 나오면 연락드릴게요.');
      const end = talk + d(12);
      plan.segments.push({ status: 'analyzing', from: end }, { status: 'done', from: end + d(4) });
      plan.outcome = 'no_listing';
      plan.doneAt = end + d(4);
      cursor = plan.doneAt + d(1);
      continue;
    }

    // 방 있음
    const blds = buildingsOf(item.broker.dongId).filter(
      (x) => values.houseType === 'any' || x.type === values.houseType,
    );
    const count = 1 + Math.floor(r() * 3);
    const slotHour = slotFrom.getHours() + Math.floor(r() * 3);
    const slotIso = new Date(slotFrom);
    slotIso.setHours(slotHour, r() < 0.5 ? 0 : 30);
    const slots = [localIso(slotIso)];
    const said: string[] = [];
    for (let i = 0; i < count; i++) {
      const b = blds[Math.floor(r() * blds.length)] ?? buildingsOf(item.broker.dongId)[0]!;
      const area = Math.round((b.type === 'officetel' ? 20 : 18) + r() * 12);
      const deposit = Math.max(300, Math.round((values.deposit * (0.6 + r() * 0.5)) / 100) * 100);
      const listRent = Math.max(25, Math.round(rent - 8 + r() * 14));
      const floor = 1 + Math.floor(r() * 5);
      const unit = `${floor}0${1 + Math.floor(r() * 4)}호`;
      const fee = 5 + Math.floor(r() * 8);
      const moveIn = r() < 0.6 ? '바로 입주' : `${12 + Math.floor(r() * 2)}월 초`;
      said.push(`${b.name} ${floor}층 ${deposit.toLocaleString('ko-KR')}에 ${listRent}`);
      plan.listings.push({
        id: `lst-${input.seed}-${item.broker.id}-${i}`,
        no: no++,
        callId: plan.callId,
        brokerId: item.broker.id,
        dongId: item.broker.dongId,
        building: b.name,
        floor,
        unit,
        type: b.type,
        area,
        built: b.built,
        deposit,
        rent: listRent,
        fee,
        moveIn,
        lat: b.lat,
        lng: b.lng,
        slots,
        priceVerdict: priceVerdict(item.broker.dongId, area, b.type, deposit, listRent),
        contact: 'answered',
      });
    }
    line(talk + d(9), 'broker', `${said.join(', ')} 있어요. 관리비는 방마다 5만 원에서 12만 원이에요.`);
    if (prep.visitSlot) line(talk + d(12), 'agent', '보여 주실 수 있는 시간이 언제일까요?');
    line(
      talk + d(14),
      'broker',
      `${slotIso.getHours()}시${slotIso.getMinutes() ? ' 30분' : ''}쯤이면 보여 드릴 수 있어요.`,
    );
    line(talk + d(16), 'agent', '감사합니다. 방문 시간이 정해지면 다시 연락드릴게요.');
    const end = talk + d(18);
    plan.segments.push({ status: 'analyzing', from: end }, { status: 'done', from: end + d(4) });
    plan.outcome = 'listing';
    plan.slots = slots;
    plan.doneAt = end + d(4);
    cursor = plan.doneAt + d(1);
  }

  return { calls, plans };
}

/** 지금 시각의 통화 모습 */
export function viewCall(
  call: Call,
  plan: CallPlan,
  now: number,
): { call: Call; listings: Listing[]; done: boolean } {
  let status: CallStatus = 'waiting';
  for (const s of plan.segments) if (s.from <= now) status = s.status;
  const done = status === 'done';
  const attempts = plan.attempts.filter((a) => a.at <= now).length;
  return {
    call: {
      ...call,
      status,
      outcome: done ? plan.outcome : null,
      attempts,
      retryAt: status === 'retry_wait' && plan.retryAt ? new Date(plan.retryAt).toISOString() : null,
      lines: plan.lines.filter((x) => x.at <= now).map((x) => x.line),
      listingIds: done ? plan.listings.map((l) => l.id) : [],
      slots: done ? plan.slots : [],
      smsDraft: done ? plan.smsDraft : null,
    },
    listings: done ? plan.listings : [],
    done,
  };
}

/* ---------- 방문 계획 · 확정 통화 ---------- */

/** 14시, 14시 30분 */
function clock(d: Date): string {
  return `${d.getHours()}시${d.getMinutes() ? ` ${d.getMinutes()}분` : ''}`;
}

function km(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const dx = (a.lng - b.lng) * 88.4;
  const dy = (a.lat - b.lat) * 111;
  return Math.sqrt(dx * dx + dy * dy);
}

export function travel(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number },
): { mode: string; minutes: number } {
  const dist = km(a, b);
  // 약속 시각이 보기 좋게 5분 단위로 올려요.
  if (dist < 1.2) return { mode: '도보', minutes: Math.max(5, Math.ceil((dist * 14) / 5) * 5) };
  return { mode: '버스·지하철', minutes: Math.ceil((8 + dist * 3) / 5) * 5 };
}

/** 가까운 순서로 30분 + 이동 시간 간격 */
export function planRoute(
  listings: Listing[],
  start: Date,
): { listing: Listing; at: Date; travelNext: Visit['travelNext'] }[] {
  const left = [...listings];
  const ordered: Listing[] = [];
  let cur = left.shift();
  while (cur) {
    ordered.push(cur);
    if (!left.length) break;
    let best = 0;
    for (let i = 1; i < left.length; i++) if (km(cur, left[i]!) < km(cur, left[best]!)) best = i;
    cur = left.splice(best, 1)[0];
  }
  let t = new Date(start);
  return ordered.map((l, i) => {
    const next = ordered[i + 1];
    const tr = next ? travel(l, next) : null;
    const at = new Date(t);
    if (tr) t = new Date(t.getTime() + (30 + tr.minutes) * 60000);
    return { listing: l, at, travelNext: tr };
  });
}

export function planConfirmations(
  visits: { visit: Visit; listing: Listing }[],
  now: number,
  scale: number,
  seed: string,
): VisitPlan[] {
  const d = (s: number) => (s * SEC) / scale;
  const byBroker = new Map<string, { visit: Visit; listing: Listing }[]>();
  for (const v of visits) byBroker.set(v.listing.brokerId, [...(byBroker.get(v.listing.brokerId) ?? []), v]);
  let cursor = now + d(3);
  const plans: VisitPlan[] = [];
  for (const group of byBroker.values()) {
    cursor += d(14);
    for (const { visit } of group) {
      const r = rng(`visit:${seed}:${visit.id}`);
      const x = r();
      const at = new Date(visit.at);
      if (x < 0.75) {
        plans.push({
          visitId: visit.id,
          resolveAt: cursor,
          result: 'confirmed',
          proposedAt: null,
          brokerSaid: `${clock(at)}에 뵐게요.`,
        });
      } else if (x < 0.9) {
        // 90분 뒤에서 가장 가까운 정시나 30분
        const p = new Date(at.getTime() + 90 * 60000);
        if (p.getMinutes() > 30) p.setHours(p.getHours() + 1, 0, 0, 0);
        else if (p.getMinutes() > 0) p.setMinutes(30, 0, 0);
        plans.push({
          visitId: visit.id,
          resolveAt: cursor,
          result: 'proposed',
          proposedAt: localIso(p),
          brokerSaid: `그 시간은 어렵고 ${clock(p)} 어떠세요?`,
        });
      } else {
        plans.push({
          visitId: visit.id,
          resolveAt: cursor,
          result: 'failed',
          proposedAt: null,
          brokerSaid: '그 방은 어제 나갔어요.',
        });
      }
    }
    cursor += d(4);
  }
  return plans;
}

export { localIso };
