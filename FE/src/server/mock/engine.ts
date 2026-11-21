/* 계산 엔진. 화면에 나오는 숫자(환산월세, 시세 판정, 순위 점수, 위험 비율)는 모두 여기서 나와요.
 * AI는 숫자를 만들지 않아요. */
import type {
  CheckDetail,
  CheckStatus,
  Commute,
  CondKey,
  CondValues,
  Conditions,
  Deal,
  DongResult,
  FilterLoss,
  PriceVerdict,
  Priority,
  RiskLevel,
  SearchResult,
  Workplace,
} from '../../shared/types.js';
import { DONGS, STANDARD, brokersOf, buildingsOf, dealsOf, dongById, type DongSeed } from './data.js';

/** 조건 기본값(말하지 않은 칸) */
export const DEFAULTS: CondValues = {
  workplace: null,
  maxCommute: 40,
  rent: null,
  deposit: 1000,
  houseType: 'any',
  builtAfter: null,
  maxTransfer: 1,
  maxBusInterval: null,
  priceBand: 'any',
  priority: 'balanced',
  commercial: 'any',
  pet: false,
  parking: false,
};

export function valuesOf(conds: Conditions): CondValues {
  const v = { ...DEFAULTS } as Record<string, unknown>;
  for (const [k, item] of Object.entries(conds)) if (item) v[k] = item.value;
  return v as unknown as CondValues;
}

/** 환산월세(만 원) = 월세 + 보증금 × 전환율 ÷ 12 */
export function convRent(deposit: number, rent: number, rate = STANDARD.convRate): number {
  return rent + (deposit * rate) / 100 / 12;
}

export function median(nums: number[]): number {
  if (!nums.length) return 0;
  const s = [...nums].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? (s[m] as number) : ((s[m - 1] as number) + (s[m] as number)) / 2;
}

function distKm(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const R = 6371;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLng = ((bLng - aLng) * Math.PI) / 180;
  const x =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((aLat * Math.PI) / 180) * Math.cos((bLat * Math.PI) / 180) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

/** 출퇴근(대중교통) 예시 계산: 도보 + 탑승(거리 비례) + 환승 */
export function commuteOf(dong: DongSeed, wp: Workplace): Commute {
  const shared = dong.lines.find((l) => wp.lines.includes(l));
  const km = distKm(dong.lat, dong.lng, wp.lat, wp.lng);
  const transfers = shared ? 0 : km > 14 ? 2 : 1;
  const walk = 5 + (Math.round(km * 7) % 4);
  const ride = Math.round(km * 2.3 + 3);
  const minutes = walk + ride + transfers * 6;
  const route = [`도보 ${walk}분`, `${shared ?? dong.lines[0]}호선`.replace('신림호선', '신림선')];
  if (!shared)
    route.push(
      `환승 ${transfers}회`,
      `${wp.lines[0]}호선`.replace('신분당호선', '신분당선').replace('공항호선', '공항철도'),
    );
  return { minutes, transfers, route };
}

const WEIGHTS: Record<
  Priority,
  { commute: number; price: number; built: number; bus: number; supply: number }
> = {
  balanced: { commute: 30, price: 30, built: 15, bus: 10, supply: 15 },
  commute: { commute: 40, price: 22, built: 13, bus: 10, supply: 15 },
  price: { commute: 22, price: 40, built: 13, bus: 10, supply: 15 },
  new: { commute: 22, price: 22, built: 31, bus: 10, supply: 15 },
};

function dealMatches(deal: Deal, v: CondValues): CondKey | null {
  if (v.rent !== null && convRent(deal.deposit, deal.rent) > convRent(v.deposit, v.rent)) return 'rent';
  if (deal.deposit > v.deposit) return 'deposit';
  if (v.houseType !== 'any' && deal.type !== v.houseType) return 'houseType';
  if (v.builtAfter !== null && deal.built < v.builtAfter) return 'builtAfter';
  return null;
}

/** 조건과 비슷한 과거 계약(최근 12개월, 신규 계약만) */
export function similarDeals(dongId: string, v: CondValues): Deal[] {
  return dealsOf(dongId).filter((d) => !d.renewal && dealMatches(d, v) === null);
}

/** 살만한 동네 찾기: 맞는 동네가 없으면 걸러 낸 이유별 건수를 돌려줘요 */
export function searchDongs(
  conds: Conditions,
  workplaces: Workplace[],
  exclude: string[] = [],
  limit = 3,
): SearchResult {
  const v = valuesOf(conds);
  const wp = workplaces.find((w) => w.id === v.workplace);
  const lossCount = new Map<CondKey, number>();
  const addLoss = (k: CondKey, n = 1) => lossCount.set(k, (lossCount.get(k) ?? 0) + n);
  if (!wp) return { dongs: [], losses: [], asOf: STANDARD.dataAsOf };

  const pool: Omit<DongResult, 'rank' | 'score'>[] = [];
  for (const d of DONGS) {
    if (exclude.includes(d.id)) continue;
    const commute = commuteOf(d, wp);
    const all = dealsOf(d.id).filter((x) => !x.renewal);
    if (commute.minutes > v.maxCommute) {
      addLoss('maxCommute', all.length);
      continue;
    }
    if (commute.transfers > v.maxTransfer) {
      addLoss('maxTransfer', all.length);
      continue;
    }
    if (v.maxBusInterval !== null && d.bus.interval > v.maxBusInterval) {
      addLoss('maxBusInterval', all.length);
      continue;
    }
    if (v.commercial !== 'any' && d.commercial !== 'mixed' && d.commercial !== v.commercial) {
      addLoss('commercial', all.length);
      continue;
    }
    const ok: Deal[] = [];
    for (const deal of all) {
      const miss = dealMatches(deal, v);
      if (miss) addLoss(miss);
      else ok.push(deal);
    }
    if (ok.length < 3) continue;
    const convs = ok.map((x) => convRent(x.deposit, x.rent));
    const sorted = [...convs].sort((a, b) => a - b);
    pool.push({
      id: d.id,
      name: d.name,
      gu: d.gu,
      station: d.station,
      lat: d.lat,
      lng: d.lng,
      dealCount: ok.length,
      rentRange: [Math.round(sorted[0] as number), Math.round(sorted[sorted.length - 1] as number)],
      median: Math.round(median(convs)),
      commute,
      bus: d.bus,
      brokers: brokersOf(d.id),
      buildings: [...new Set(ok.map((x) => x.building))].slice(0, 4),
    });
  }

  if (v.priceBand !== 'any' && pool.length) {
    const meds = pool.map((p) => p.median).sort((a, b) => a - b);
    const lo = meds[Math.floor(meds.length * 0.3)] ?? 0;
    const hi = meds[Math.floor(meds.length * 0.7)] ?? Infinity;
    for (let i = pool.length - 1; i >= 0; i--) {
      const m = (pool[i] as (typeof pool)[number]).median;
      const keep = v.priceBand === 'low' ? m <= lo : m > lo && m <= hi;
      if (!keep) {
        addLoss('priceBand', (pool[i] as (typeof pool)[number]).dealCount);
        pool.splice(i, 1);
      }
    }
  }

  const w = WEIGHTS[v.priority];
  const maxMed = Math.max(...pool.map((p) => p.median), 1);
  const minMed = Math.min(...pool.map((p) => p.median), 0);
  const scored = pool.map((p) => {
    const avgBuilt = median(similarDeals(p.id, v).map((x) => x.built));
    const s =
      w.commute * (1 - p.commute.minutes / Math.max(v.maxCommute, 1)) +
      w.price * (maxMed === minMed ? 0.5 : (maxMed - p.median) / (maxMed - minMed)) +
      w.built * Math.min(1, Math.max(0, (avgBuilt - 1995) / 30)) +
      w.bus * Math.max(0, 1 - p.bus.interval / 15) +
      w.supply * Math.min(1, p.dealCount / 40);
    return { ...p, score: Math.round(s * 10) / 10 };
  });
  scored.sort((a, b) => b.score - a.score || a.median - b.median);
  const dongs = scored.slice(0, limit).map((p, i) => ({ ...p, rank: i + 1 }));

  const losses: FilterLoss[] = [...lossCount.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([key, count]) => ({ key, count, suggest: loosen(key, v) }));
  return { dongs, losses, asOf: STANDARD.dataAsOf };
}

/** 한 단계 넓힌 값(맞는 동네 0곳일 때 제안) */
export function loosen(key: CondKey, v: CondValues): number | string | null {
  switch (key) {
    case 'maxCommute':
      return v.maxCommute + 10;
    case 'rent':
      return (v.rent ?? 50) + 10;
    case 'deposit':
      return v.deposit + 1000;
    case 'maxTransfer':
      return v.maxTransfer + 1;
    case 'builtAfter':
      return v.builtAfter === null ? null : v.builtAfter - 5;
    case 'maxBusInterval':
      return v.maxBusInterval === null ? null : v.maxBusInterval + 5;
    default:
      return 'any';
  }
}

/** 한 단계 조인 값(더 싼 데, 통근 더 짧은 곳, 더 새 집) */
export function tighten(
  key: 'rent' | 'maxCommute' | 'builtAfter',
  v: CondValues,
  current: DongResult[],
): number {
  if (key === 'rent') {
    const best = Math.min(...current.map((d) => d.median), v.rent ?? 60);
    return Math.max(25, Math.round(best - (v.deposit * STANDARD.convRate) / 100 / 12) - 3);
  }
  if (key === 'maxCommute')
    return Math.max(15, Math.min(...current.map((d) => d.commute.minutes), v.maxCommute) - 1);
  return Math.max(v.builtAfter ?? 2005, 2005) + 5;
}

/** 매물 값이 같은 조건 과거 실거래 대비 어떤지 */
export function priceVerdict(
  dongId: string,
  area: number,
  type: 'villa' | 'officetel',
  deposit: number,
  rent: number,
): PriceVerdict {
  const near = dealsOf(dongId).filter((d) => !d.renewal && d.type === type && Math.abs(d.area - area) <= 5);
  if (near.length < 3) return 'unknown';
  const med = median(near.map((d) => convRent(d.deposit, d.rent)));
  const ratio = convRent(deposit, rent) / med;
  if (ratio <= 1.05) return 'fair';
  if (ratio <= 1.15) return 'slightly_high';
  return 'high';
}

/* ---------- 등기 · 건축물대장 · 전세대출 (규칙 r1-2026-11) ---------- */

export interface RegistryFacts {
  address: string;
  owner: string;
  owners: number;
  mortgage: number;
  seizure: boolean;
  trust: boolean;
  leaseRight: boolean;
  buildingUse: string;
  violation: boolean;
  approvedYear: number;
  area: number;
  salePrice: number | null;
  deposit: number;
}

export function judge(
  f: RegistryFacts,
): Omit<
  CheckDetail,
  | 'address'
  | 'owner'
  | 'owners'
  | 'mortgage'
  | 'seizure'
  | 'trust'
  | 'leaseRight'
  | 'buildingUse'
  | 'violation'
  | 'approvedYear'
  | 'salePrice'
> & { status: CheckStatus } {
  const loanReasons: string[] = [];
  if (f.buildingUse.includes('근린생활시설'))
    loanReasons.push('주용도가 근린생활시설이라 주택 전세대출이 안 돼요');
  if (f.violation) loanReasons.push('건축물대장에 위반건축물로 올라 있어요');
  if (f.area > 85) loanReasons.push('전용면적이 85㎡를 넘어요');
  const loanOk = loanReasons.length === 0;

  const ratio = f.salePrice ? Math.round(((f.mortgage + f.deposit) / f.salePrice) * 1000) / 10 : null;
  const riskReasons: string[] = [];
  let risk: RiskLevel = 'good';
  if (f.seizure) riskReasons.push('압류나 경매 기록이 남아 있어요');
  if (f.trust) riskReasons.push('신탁 등기가 남아 있어요');
  if (ratio !== null && ratio >= 80) riskReasons.push(`근저당과 보증금 합이 시세의 ${ratio}%예요`);
  if (riskReasons.length) risk = 'danger';
  else {
    if (ratio !== null && ratio >= 70) riskReasons.push(`근저당과 보증금 합이 시세의 ${ratio}%예요`);
    if (ratio === null) riskReasons.push('매매 시세를 몰라 비율을 계산하지 못했어요');
    if (f.leaseRight) riskReasons.push('전세권이나 임차권 등기가 있어요');
    if (f.owners >= 3) riskReasons.push(`소유자가 ${f.owners}명이에요`);
    if (riskReasons.length) risk = 'caution';
    else riskReasons.push(ratio === null ? '' : `근저당과 보증금 합이 시세의 ${ratio}%로 낮아요`);
  }

  let status: CheckStatus;
  if (!loanOk || risk === 'danger') status = 'exclude';
  else if (risk === 'caution') status = 'caution';
  else status = 'recommend';
  return {
    loanOk,
    loanReasons,
    risk,
    ratio,
    riskReasons: riskReasons.filter(Boolean),
    ruleVersion: STANDARD.ruleVersion,
    status,
  };
}

export { buildingsOf, dongById };
