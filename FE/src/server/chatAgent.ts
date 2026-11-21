/* AI 폴더의 대화 에이전트(AI/chat_agent, FastAPI) 연결.
 * 사용자의 말을 에이전트에 보내 '조건 카드'(contracts/condition_card.md, v0.2)와 답 문장을 받고,
 * 화면이 쓰는 조건(Conditions)으로 바꿔요. 동네 찾기·전화·미팅과 숫자는 이 서버(계산 엔진)가 맡아요.
 * 주소가 없거나 실패하면 null 을 돌려주고, 부르는 쪽은 규칙(+OpenAI)으로 답해요. */
import type { CondKey, CondSource, HouseType, Priority, Workplace } from '../shared/types.js';
import { findWorkplace } from './mock/nlu.js';

export interface AgentCondItem<T = unknown> {
  value: T;
  source?: 'stated' | 'inferred';
  evidence?: string;
  reason?: string;
  label?: string;
  kind?: 'work' | 'school';
  approx?: boolean;
}

export interface AgentCard {
  version?: string;
  conditions?: Record<string, AgentCondItem | undefined>;
  priorities?: string[];
  unverifiable?: { phrase: string; message: string }[];
  clarifications?: { id: string; question: string; options: string[] }[];
  missing?: string[];
  ready?: boolean;
}

export interface AgentTurn {
  session_id: string;
  type: 'condition_card' | 'message';
  reply: string;
  messages: { kind: string; text: string }[];
  card: AgentCard | null;
  intent: 'search' | 'question' | 'other' | 'control';
  via: string;
  ready: boolean;
  missing: string[];
  changed: string[];
}

/** 에이전트 조건 하나를 화면 조건으로 바꾼 값 */
export interface MappedCond {
  key: CondKey;
  value: unknown;
  source: CondSource;
  reason?: string;
}

export interface MappedCard {
  conds: MappedCond[];
  /** 화면 동네 찾기에 아직 반영하지 못하는 조건(전세, 피할 곳, 면적, 층, 역까지 거리) */
  notApplied: string[];
  unverifiable: string[];
  ask?: { question: string; options: { label: string; text: string }[] };
}

export class ChatAgent {
  constructor(
    private readonly url: string,
    private readonly timeoutMs = 15000,
  ) {}

  get enabled(): boolean {
    return Boolean(this.url);
  }

  async turn(sessionId: string, message: string): Promise<AgentTurn | null> {
    if (!this.enabled) return null;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const res = await fetch(`${this.url.replace(/\/$/, '')}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message }),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        console.error(`[agent] 대화 에이전트 응답 ${res.status}`);
        return null;
      }
      return (await res.json()) as AgentTurn;
    } catch (err) {
      console.error(`[agent] 대화 에이전트 호출 실패: ${(err as Error).name}`);
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  async reset(sessionId: string): Promise<void> {
    if (!this.enabled) return;
    try {
      await fetch(`${this.url.replace(/\/$/, '')}/api/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });
    } catch {
      /* 다음 대화에서 다시 맞춰요 */
    }
  }
}

const src = (c: AgentCondItem | undefined): CondSource => (c?.source === 'inferred' ? 'filled' : 'said');
const why = (c: AgentCondItem | undefined, fallback: string) =>
  c?.source === 'inferred' ? c.reason || `"${c.evidence ?? ''}"에서 살구가 짐작했어요` : fallback;

/** 에이전트 조건 카드(v0.2) -> 화면 조건 */
export function mapAgentCard(card: AgentCard | null, workplaces: Workplace[], now = new Date()): MappedCard {
  const out: MappedCard = { conds: [], notApplied: [], unverifiable: [] };
  if (!card) return out;
  const c = card.conditions ?? {};
  const push = (key: CondKey, item: AgentCondItem | undefined, value: unknown) => {
    if (item === undefined || value === undefined || value === null) return;
    const source = src(item);
    out.conds.push({ key, value, source, ...(source === 'filled' ? { reason: why(item, '') } : {}) });
  };

  // 회사·학교: 이름으로 회사 목록에서 찾아요. 없으면 살고 싶은 곳을 기준점으로 써요.
  const wpLabel = c.workplace?.label ?? (typeof c.workplace?.value === 'string' ? c.workplace.value : '');
  const wp = wpLabel ? findWorkplace(wpLabel, workplaces) : null;
  if (wp && c.workplace) {
    push('workplace', c.workplace, wp.id);
    const areas = (c.preferred_areas?.value as string[] | undefined) ?? [];
    if (areas.length) out.notApplied.push(`살 곳(${areas.join(', ')})`);
  } else {
    const areas = (c.preferred_areas?.value as string[] | undefined) ?? [];
    const near = areas.map((a) => findWorkplace(a, workplaces)).find(Boolean);
    if (near && c.preferred_areas) {
      out.conds.push({
        key: 'workplace',
        value: near.id,
        source: 'filled',
        reason: `살고 싶은 곳(${areas.join(', ')}) 가까이로 찾으려고 ${near.name}을 기준점으로 봤어요`,
      });
    } else if (wpLabel) {
      out.notApplied.push(`${wpLabel}(회사 목록에 없는 곳)`);
    }
  }

  push('deposit', c.deposit_manwon, c.deposit_manwon?.value);
  push('rent', c.monthly_rent_manwon, c.monthly_rent_manwon?.value);
  push('maxCommute', c.max_commute_min, c.max_commute_min?.value);
  push('maxTransfer', c.max_transfers, c.max_transfers?.value);
  push('maxBusInterval', c.max_bus_headway_min, c.max_bus_headway_min?.value);

  const types = (c.housing_types?.value as string[] | undefined) ?? [];
  if (types.length === 1) push('houseType', c.housing_types, types[0] as HouseType);
  if (c.max_building_age_years?.value !== undefined) {
    push('builtAfter', c.max_building_age_years, now.getFullYear() - Number(c.max_building_age_years.value));
  }
  if (c.price_band?.value === 'median_or_below') push('priceBand', c.price_band, 'low');

  const pri: Record<string, Priority> = { price: 'price', commute: 'commute', building_age: 'new' };
  const first = (card.priorities ?? []).map((p) => pri[p]).find(Boolean);
  if (first) out.conds.push({ key: 'priority', value: first, source: 'said' });

  const lease = (c.lease_types?.value as string[] | undefined) ?? [];
  if (lease.includes('jeonse') || lease.includes('semi_jeonse')) out.notApplied.push('전세·반전세');
  if ((c.avoid_areas?.value as string[] | undefined)?.length) {
    out.notApplied.push(`피할 곳(${(c.avoid_areas!.value as string[]).join(', ')})`);
  }
  if (c.min_area_m2) out.notApplied.push(`면적 ${c.min_area_m2.value}㎡ 이상`);
  if (c.min_floor) out.notApplied.push(`${c.min_floor.value}층 이상`);
  if (c.max_walk_to_station_min) out.notApplied.push(`역까지 걸어서 ${c.max_walk_to_station_min.value}분`);

  out.unverifiable = (card.unverifiable ?? []).map((u) => u.phrase);
  const q = card.clarifications?.[0];
  if (q) out.ask = { question: q.question, options: q.options.map((o) => ({ label: o, text: o })) };
  return out;
}
