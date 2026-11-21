/* 동네 추천·가격 판단·중개사무소 목록을 대화 에이전트(AI/chat_agent)에 물어 받아요.
 * 화면 조건을 한 문장 질문으로 보내면 에이전트가 조건 카드를 고치고 추천 엔진(실거래 DB)을 불러 후보를 돌려줘요.
 * 후보(건물 단위 과거 계약)를 '구 동'으로 묶어 동네 카드(DongResult)로 바꾸고,
 * 같은 건물·면적대 시세 중앙값(market_median_*)을 그 동네 가격 판단 기준으로 써요.
 * 중개사무소는 에이전트 응답에 brokers 가 있으면 그것을, 없으면 예시 목록을 써요. */
import type { Broker, ChatState, Deal, DongResult, SearchResult, Workplace } from '../shared/types.js';
import type { AgentBackend } from './chatAgent.js';
import { DONGS, STANDARD, brokersOf, hashString, registerAgentDong, rng } from './mock/data.js';
import { convRent, median, valuesOf } from './mock/engine.js';

/** 서울 자치구 대략 중심(동 좌표를 모를 때 지도에 찍는 자리) */
const GU_CENTER: Record<string, [number, number]> = {
  종로구: [37.5735, 126.979],
  중구: [37.5641, 126.9979],
  용산구: [37.5326, 126.9905],
  성동구: [37.5634, 127.0369],
  광진구: [37.5385, 127.0823],
  동대문구: [37.5744, 127.0396],
  중랑구: [37.6063, 127.0927],
  성북구: [37.5894, 127.0167],
  강북구: [37.6396, 127.0257],
  도봉구: [37.6688, 127.0471],
  노원구: [37.6542, 127.0568],
  은평구: [37.6027, 126.9291],
  서대문구: [37.5791, 126.9368],
  마포구: [37.5663, 126.9019],
  양천구: [37.517, 126.8665],
  강서구: [37.5509, 126.8495],
  구로구: [37.4954, 126.8874],
  금천구: [37.4569, 126.8955],
  영등포구: [37.5264, 126.8962],
  동작구: [37.5124, 126.9393],
  관악구: [37.4784, 126.9516],
  서초구: [37.4837, 127.0324],
  강남구: [37.5172, 127.0473],
  송파구: [37.5145, 127.1059],
  강동구: [37.5301, 127.1238],
};

const TYPE_WORD = { villa: '빌라', officetel: '오피스텔' } as const;

/** 화면 조건 -> 에이전트에 보낼 한 문장 질문 */
export function condQuestion(chat: ChatState, workplaces: Workplace[]): string {
  const v = valuesOf(chat.conditions);
  const wp = workplaces.find((w) => w.id === v.workplace);
  const parts: string[] = [];
  if (wp) parts.push(`회사는 ${wp.name}`);
  if (v.deposit !== null) parts.push(`보증금 ${v.deposit}만 원`);
  if (v.rent !== null) parts.push(`월세 ${v.rent}만 원 이하`);
  if (v.houseType !== 'any') parts.push(TYPE_WORD[v.houseType]);
  if (v.builtAfter !== null) parts.push(`${v.builtAfter}년 이후 준공`);
  if (v.maxCommute) parts.push(`출퇴근 ${v.maxCommute}분 이내`);
  return `${parts.join(', ')} 조건으로 살 만한 동네와 실거래 기준 매물을 추천해줘`;
}

interface Cand {
  name?: string;
  address?: string;
  housing_type?: string;
  deposit_manwon?: number | null;
  monthly_rent_manwon?: number | null;
  area_m2?: number | null;
  construction_year?: number | null;
  contract_date?: string | null;
  transaction_count?: number | null;
  score?: number | null;
  market_median_deposit_manwon?: number | null;
  market_median_monthly_rent_manwon?: number | null;
  commute_minutes?: number | null;
  transfers?: number | null;
  station?: string | null;
}

/** 에이전트가 중개사무소 목록을 주면 받는 모양(아직 에이전트에 없음, 화면이 제안하는 형식) */
interface AgentBroker {
  name?: string;
  reg_no?: string;
  phone?: string;
  address?: string;
  dong?: string;
  lat?: number;
  lng?: number;
}

const num = (x: unknown): number | null => (typeof x === 'number' && Number.isFinite(x) ? x : null);

/** '서울특별시 관악구 신림동 408-15' -> { gu: '관악구', dong: '신림동' } */
export function splitAddress(address: string): { gu: string; dong: string } | null {
  const t = address.split(/\s+/);
  const i = t.findIndex((x) => /구$/.test(x));
  const dong = i >= 0 ? t[i + 1] : undefined;
  if (i < 0 || !dong || !/(동|가|로\d*가)$/.test(dong)) return null;
  return { gu: t[i]!, dong };
}

/** 추천 후보 -> 동네 카드. 쓸 만한 결과가 아니면(오류, 예시 응답) null */
export function agentSearch(
  backend: (AgentBackend & { brokers?: AgentBroker[] }) | null | undefined,
  exclude: string[] = [],
  limit = 3,
): SearchResult | null {
  if (!backend || !backend.ok || backend.mock) return null;
  const groups = new Map<string, { gu: string; dong: string; cands: Cand[] }>();
  for (const c of (backend.candidates ?? []) as Cand[]) {
    const at = splitAddress(c.address ?? '');
    if (!at) continue;
    const key = `${at.gu} ${at.dong}`;
    const g = groups.get(key) ?? { ...at, cands: [] };
    g.cands.push(c);
    groups.set(key, g);
  }

  const dongs: Omit<DongResult, 'rank'>[] = [];
  for (const g of groups.values()) {
    const id = `a${hashString(`${g.gu} ${g.dong}`).toString(36)}`;
    if (exclude.includes(id)) continue;
    const seed = DONGS.find((d) => d.name === g.dong && d.gu === g.gu);
    const r = rng(`agent:${id}`);
    const [glat, glng] = GU_CENTER[g.gu] ?? [37.5665, 126.978];
    const lat = seed?.lat ?? glat + (r() - 0.5) * 0.012;
    const lng = seed?.lng ?? glng + (r() - 0.5) * 0.014;
    const convs = g.cands
      .filter((c) => num(c.monthly_rent_manwon) !== null)
      .map((c) => convRent(num(c.deposit_manwon) ?? 0, num(c.monthly_rent_manwon) ?? 0));
    const refs = g.cands
      .filter((c) => num(c.market_median_monthly_rent_manwon) !== null)
      .map((c) =>
        convRent(num(c.market_median_deposit_manwon) ?? 0, num(c.market_median_monthly_rent_manwon) ?? 0),
      );
    const priceRef = refs.length ? { conv: Math.round(median(refs)), n: refs.length } : null;
    const sorted = [...convs].sort((a, b) => a - b);
    const commuteCand = g.cands.find((c) => num(c.commute_minutes) !== null);
    const refDeals: Deal[] = g.cands.map((c, i) => ({
      id: `${id}-${i}`,
      dongId: id,
      building: c.name ?? '이름 없음',
      type: c.housing_type === 'officetel' ? 'officetel' : 'villa',
      area: num(c.area_m2) ?? 0,
      built: num(c.construction_year) ?? 0,
      deposit: num(c.deposit_manwon) ?? 0,
      rent: num(c.monthly_rent_manwon) ?? 0,
      month: (c.contract_date ?? '').slice(0, 7),
      renewal: false,
    }));
    const station = g.cands.find((c) => c.station)?.station ?? seed?.station ?? '';
    registerAgentDong({
      id,
      name: g.dong,
      gu: g.gu,
      lat,
      lng,
      base: priceRef?.conv ?? 0,
      station,
      lines: seed?.lines ?? [],
      bus: seed?.bus ?? null,
      commercial: seed?.commercial ?? 'mixed',
      refDeals,
      priceRef,
    });
    const brokers = toBrokers(backend.brokers, id, g, lat, lng);
    dongs.push({
      id,
      name: g.dong,
      gu: g.gu,
      station,
      lat,
      lng,
      score: Math.round(Math.max(...g.cands.map((c) => num(c.score) ?? 0))),
      dealCount: g.cands.reduce((n, c) => n + (num(c.transaction_count) ?? 1), 0),
      rentRange: sorted.length ? [Math.round(sorted[0]!), Math.round(sorted[sorted.length - 1]!)] : [0, 0],
      median: priceRef?.conv ?? Math.round(convs.length ? median(convs) : 0),
      commute: commuteCand
        ? { minutes: commuteCand.commute_minutes!, transfers: num(commuteCand.transfers) ?? 0, route: [] }
        : null,
      bus: seed?.bus ?? null,
      brokers: brokers.length ? brokers : brokersOf(id),
      buildings: [...new Set(g.cands.map((c) => c.name ?? ''))].filter(Boolean).slice(0, 4),
      source: 'agent',
      refDeals,
      priceRef,
    });
  }
  dongs.sort((a, b) => b.score - a.score);
  return {
    dongs: dongs.slice(0, limit).map((d, i) => ({ ...d, rank: i + 1 })),
    losses: [],
    asOf: STANDARD.dataAsOf,
  };
}

function toBrokers(
  list: AgentBroker[] | undefined,
  dongId: string,
  g: { gu: string; dong: string },
  lat: number,
  lng: number,
): Broker[] {
  return (list ?? [])
    .filter((b) => b.name && b.phone && (!b.dong || b.dong.includes(g.dong)))
    .filter((b) => !b.address || b.address.includes(g.dong) || b.address.includes(g.gu))
    .slice(0, 3)
    .map((b, i) => ({
      id: `${dongId}-r${i + 1}`,
      dongId,
      name: b.name!,
      regNo: b.reg_no ?? '',
      phone: b.phone!,
      lat: num(b.lat) ?? lat,
      lng: num(b.lng) ?? lng,
    }));
}

/** 서버를 다시 켜도 대화에 남은 에이전트 동네를 되살려요(이름, 좌표, 가격 기준) */
export function restoreAgentDongs(search: SearchResult | null | undefined): void {
  for (const d of search?.dongs ?? []) {
    if (d.source !== 'agent') continue;
    registerAgentDong({
      id: d.id,
      name: d.name,
      gu: d.gu,
      lat: d.lat,
      lng: d.lng,
      base: d.priceRef?.conv ?? 0,
      station: d.station,
      lines: [],
      bus: d.bus,
      commercial: 'mixed',
      refDeals: d.refDeals ?? [],
      priceRef: d.priceRef ?? null,
    });
  }
}
