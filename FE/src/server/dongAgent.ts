/* 동네 추천·가격 판단·중개사무소 목록을 대화 에이전트(AI/chat_agent)에 물어 받아요.
 * 화면 조건을 한 문장 질문으로 보내면 에이전트가 조건 카드를 고치고 추천 엔진(실거래 DB)을 불러 후보를 돌려줘요.
 * 후보(건물 단위 과거 계약)를 '구 동'으로 묶어 동네 카드(DongResult)로 바꾸고,
 * 같은 건물·면적대 시세 중앙값(market_median_*)을 그 동네 가격 판단 기준으로 써요.
 * 중개사무소는 전화 준비 때 에이전트 전화 요청 초안에서 받아요(예시 목록은 쓰지 않아요). */
import type { Broker, ChatState, Deal, DongResult, SearchResult, Workplace } from '../shared/types.js';
import type { AgentAction, AgentBackend, AgentRealtor } from './chatAgent.js';
import { STANDARD, hashString, registerAgentDong, rng } from './mock/data.js';
import type { KakaoLocal } from './kakaoLocal.js';
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
  if (v.maxTransfer !== null && v.maxTransfer !== undefined) parts.push(`환승 ${v.maxTransfer}회 이하`);
  if (v.maxBusInterval) parts.push(`버스 배차 ${v.maxBusInterval}분 이내`);
  return `${parts.join(', ')} 조건으로 살 만한 동네와 실거래 기준 매물을 추천해줘`;
}

interface Leg {
  mode?: 'bus' | 'subway' | 'walking';
  minutes?: number;
  start_name?: string | null;
  end_name?: string | null;
  route_names?: string[];
  headway_min?: number | null;
  first_time?: string | null;
  last_time?: string | null;
}

interface Cand {
  commute_distance_km?: number | null;
  transit_fare_won?: number | null;
  route_url?: string | null;
  walk_to_station_min?: number | null;
  transit_legs?: Leg[];
  nearby_bus_stops?: { name?: string; distance_m?: number; route_names?: string[] }[];
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
  const groups = new Map<string, { gu: string; dong: string; cands: Cand[]; pick: number }>();
  for (const [i, c] of ((backend.candidates ?? []) as Cand[]).entries()) {
    const at = splitAddress(c.address ?? '');
    if (!at) continue;
    const key = `${at.gu} ${at.dong}`;
    const g = groups.get(key) ?? { ...at, cands: [], pick: i + 1 };
    const best = (backend.candidates as Cand[])[g.pick - 1];
    if ((num(c.score) ?? 0) > (num(best?.score) ?? 0)) g.pick = i + 1;
    g.cands.push(c);
    groups.set(key, g);
  }

  const dongs: Omit<DongResult, 'rank'>[] = [];
  for (const g of groups.values()) {
    const id = `a${hashString(`${g.gu} ${g.dong}`).toString(36)}`;
    if (exclude.includes(id)) continue;
    const r = rng(`agent:${id}`);
    const [glat, glng] = GU_CENTER[g.gu] ?? [37.5665, 126.978];
    // 좌표는 locateDongs 가 카카오로 바로잡아요. 그 전에는 자치구 중심 근처
    const lat = glat + (r() - 0.5) * 0.012;
    const lng = glng + (r() - 0.5) * 0.014;
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
    // 통근: 동네 안 후보 중 가장 짧은 실제 경로(카카오 대중교통 + 교통 공공데이터)
    const commuteCand = g.cands
      .filter((c) => num(c.commute_minutes) !== null)
      .sort((a, b) => (a.commute_minutes ?? 0) - (b.commute_minutes ?? 0))[0];
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
    const station = g.cands.find((c) => c.station)?.station ?? '';
    registerAgentDong({
      id,
      name: g.dong,
      gu: g.gu,
      lat,
      lng,
      base: priceRef?.conv ?? 0,
      station,
      lines: [],
      bus: null,
      commercial: 'mixed',
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
      commute: commuteCand ? toCommute(commuteCand) : null,
      bus: commuteCand ? toBus(commuteCand) : null,
      brokers,
      buildings: [...new Set(g.cands.map((c) => c.name ?? ''))].filter(Boolean).slice(0, 4),
      source: 'agent',
      agentPick: { index: g.pick, address: (backend.candidates as Cand[])[g.pick - 1]?.address ?? '' },
      brokersReal: brokers.length > 0,
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

/** 대표 후보를 '문의'하면 오는 전화 요청 초안에서 그 동 중개사무소를 꺼내요(실거래 DB real_estate_agencies) */
export function brokersFromAction(
  action: AgentAction | null | undefined,
  dong: { id: string; lat: number; lng: number },
): Broker[] {
  const r = rng(`realtor:${dong.id}`);
  return (action?.request?.brokers ?? [])
    .filter((b) => b.name && b.phone)
    .map((b, i) => ({
      id: `${dong.id}-r${i + 1}`,
      dongId: dong.id,
      name: b.name!,
      regNo: b.reg ?? '',
      phone: b.phone!,
      // 사무소 좌표는 초안에 없어서 동네 근처에 표시해요
      lat: dong.lat + (r() - 0.5) * 0.006,
      lng: dong.lng + (r() - 0.5) * 0.007,
    }));
}

/** 동네 좌표를 카카오 주소 검색으로 바로잡아요(키가 없거나 못 찾으면 그대로) */
export async function locateDongs(search: SearchResult, kakao: KakaoLocal): Promise<void> {
  if (!kakao.enabled) return;
  await Promise.all(
    search.dongs.map(async (d) => {
      const p = await kakao.region(d.gu, d.name);
      if (!p) return;
      d.lat = p.lat;
      d.lng = p.lng;
    }),
  );
  restoreAgentDongs(search);
}

/** 경로 구간 -> 화면 문구('2호선 신촌→강남 25분', '도보 4분') */
function legText(l: Leg): string {
  const m = l.minutes ? ` ${l.minutes}분` : '';
  if (l.mode === 'walking') return `도보${m}`;
  const names = (l.route_names ?? []).slice(0, 2).join('·');
  const way = l.start_name && l.end_name ? ` ${l.start_name}→${l.end_name}` : '';
  return `${l.mode === 'bus' ? `버스 ${names}` : names || '지하철'}${way}${m}`.trim();
}

function toCommute(c: Cand): DongResult['commute'] {
  return {
    minutes: c.commute_minutes ?? 0,
    transfers: c.transfers ?? 0,
    route: (c.transit_legs ?? []).filter((l) => l.mode !== 'walking' || (l.minutes ?? 0) >= 3).map(legText),
    distanceKm: num(c.commute_distance_km),
    fareWon: num(c.transit_fare_won),
    walkMin: num(c.walk_to_station_min),
    routeUrl: c.route_url ?? null,
    nearbyStops: (c.nearby_bus_stops ?? []).slice(0, 3).map((b) => ({
      name: b.name ?? '',
      distanceM: b.distance_m ?? 0,
      routes: (b.route_names ?? []).slice(0, 6),
    })),
  };
}

/** 경로의 첫 버스 구간(배차·막차는 서울시 버스 DB). 버스가 없으면 첫 지하철 구간 */
function toBus(c: Cand): DongResult['bus'] {
  const legs = c.transit_legs ?? [];
  const l =
    legs.find((x) => x.mode === 'bus' && x.headway_min) ??
    legs.find((x) => x.mode === 'subway' && x.headway_min);
  if (!l?.headway_min) return null;
  return {
    route: (l.route_names ?? []).slice(0, 2).join('·') || (l.mode === 'bus' ? '버스' : '지하철'),
    interval: Math.round(l.headway_min),
    last: l.last_time ? l.last_time.slice(0, 5) : '-',
  };
}

/** 추천 엔진 중개사무소 검색 결과 -> 전화할 사무소(전화번호가 있는 곳만) */
export function brokersFromRealtors(list: AgentRealtor[], dongId: string): Broker[] {
  return list
    .filter((o) => o.name && o.phone)
    .map((o, i) => ({
      id: `${dongId}-k${i + 1}`,
      dongId,
      name: o.name,
      regNo: o.registration_no ?? o.place_id,
      phone: o.phone!,
      lat: o.latitude,
      lng: o.longitude,
    }));
}
