/* mock 데이터. 실제 공공데이터와 같은 모양의 예시 값이에요(결정적 난수라 매번 같아요).
 * 실서비스에서는 BE 수집 배치(서울시 전월세가 정보, 중개업소 정보, 버스 노선)가 채워요. */
import type { Broker, BusInfo, Deal, Workplace } from '../../shared/types.js';

/** 기준값: 법정 전월세전환율 상한 = 기준금리 + 2%p */
export const STANDARD = {
  baseRate: 3.0,
  spread: 2.0,
  get convRate(): number {
    return this.baseRate + this.spread;
  },
  dataAsOf: '2026-10-31',
  ruleVersion: 'r1-2026-11',
};

export interface DongSeed {
  id: string;
  name: string;
  gu: string;
  lat: number;
  lng: number;
  /** 전용 25㎡ 원룸 환산월세 중간값(만 원) */
  base: number;
  station: string;
  lines: string[];
  bus: BusInfo;
  commercial: 'lively' | 'quiet' | 'mixed';
}

export const DONGS: DongSeed[] = [
  {
    id: 'bongcheon',
    name: '봉천동',
    gu: '관악구',
    lat: 37.4805,
    lng: 126.95,
    base: 55,
    station: '서울대입구',
    lines: ['2'],
    bus: { route: '5511', interval: 6, last: '23:40' },
    commercial: 'lively',
  },
  {
    id: 'sinlim',
    name: '신림동',
    gu: '관악구',
    lat: 37.4842,
    lng: 126.9297,
    base: 51,
    station: '신림',
    lines: ['2', '신림'],
    bus: { route: '5516', interval: 7, last: '23:30' },
    commercial: 'lively',
  },
  {
    id: 'namhyeon',
    name: '남현동',
    gu: '관악구',
    lat: 37.4743,
    lng: 126.9775,
    base: 57,
    station: '사당',
    lines: ['2', '4'],
    bus: { route: '461', interval: 9, last: '23:10' },
    commercial: 'quiet',
  },
  {
    id: 'sangdo',
    name: '상도동',
    gu: '동작구',
    lat: 37.5005,
    lng: 126.948,
    base: 57,
    station: '숭실대입구',
    lines: ['7'],
    bus: { route: '752', interval: 8, last: '23:20' },
    commercial: 'quiet',
  },
  {
    id: 'sadang',
    name: '사당동',
    gu: '동작구',
    lat: 37.4835,
    lng: 126.979,
    base: 63,
    station: '총신대입구(이수)',
    lines: ['4', '7'],
    bus: { route: '4212', interval: 7, last: '23:50' },
    commercial: 'mixed',
  },
  {
    id: 'sindaebang',
    name: '신대방동',
    gu: '동작구',
    lat: 37.4905,
    lng: 126.92,
    base: 54,
    station: '보라매',
    lines: ['7', '신림'],
    bus: { route: '5535', interval: 10, last: '23:00' },
    commercial: 'mixed',
  },
  {
    id: 'noryangjin',
    name: '노량진동',
    gu: '동작구',
    lat: 37.5135,
    lng: 126.941,
    base: 59,
    station: '노량진',
    lines: ['1', '9'],
    bus: { route: '150', interval: 5, last: '24:10' },
    commercial: 'lively',
  },
  {
    id: 'heukseok',
    name: '흑석동',
    gu: '동작구',
    lat: 37.5085,
    lng: 126.9625,
    base: 65,
    station: '흑석',
    lines: ['9'],
    bus: { route: '151', interval: 8, last: '23:30' },
    commercial: 'quiet',
  },
  {
    id: 'daerim',
    name: '대림동',
    gu: '영등포구',
    lat: 37.4935,
    lng: 126.896,
    base: 49,
    station: '대림',
    lines: ['2', '7'],
    bus: { route: '6513', interval: 9, last: '23:20' },
    commercial: 'lively',
  },
  {
    id: 'singil',
    name: '신길동',
    gu: '영등포구',
    lat: 37.5065,
    lng: 126.911,
    base: 58,
    station: '신길',
    lines: ['1', '5'],
    bus: { route: '5714', interval: 8, last: '23:40' },
    commercial: 'mixed',
  },
  {
    id: 'doksan',
    name: '독산동',
    gu: '금천구',
    lat: 37.4705,
    lng: 126.8965,
    base: 47,
    station: '독산',
    lines: ['1'],
    bus: { route: '5625', interval: 11, last: '22:50' },
    commercial: 'quiet',
  },
  {
    id: 'guro',
    name: '구로동',
    gu: '구로구',
    lat: 37.4955,
    lng: 126.8875,
    base: 52,
    station: '구로디지털단지',
    lines: ['2'],
    bus: { route: '5619', interval: 8, last: '23:30' },
    commercial: 'lively',
  },
  {
    id: 'bangbae',
    name: '방배동',
    gu: '서초구',
    lat: 37.4815,
    lng: 126.9935,
    base: 72,
    station: '방배',
    lines: ['2'],
    bus: { route: '405', interval: 7, last: '23:50' },
    commercial: 'quiet',
  },
];

export const WORKPLACES: Workplace[] = [
  { id: 'gangnam', name: '강남역', alias: ['강남'], lines: ['2', '신분당'], lat: 37.4979, lng: 127.0276 },
  { id: 'yeoksam', name: '역삼역', alias: ['역삼', '테헤란로'], lines: ['2'], lat: 37.5006, lng: 127.0364 },
  { id: 'seolleung', name: '선릉역', alias: ['선릉'], lines: ['2', '수인분당'], lat: 37.5045, lng: 127.049 },
  { id: 'samseong', name: '삼성역', alias: ['삼성역', '코엑스'], lines: ['2'], lat: 37.5089, lng: 127.0631 },
  { id: 'jamsil', name: '잠실역', alias: ['잠실'], lines: ['2', '8'], lat: 37.5133, lng: 127.1001 },
  { id: 'yeouido', name: '여의도역', alias: ['여의도'], lines: ['5', '9'], lat: 37.5216, lng: 126.9243 },
  { id: 'cityhall', name: '시청역', alias: ['시청'], lines: ['1', '2'], lat: 37.5657, lng: 126.9769 },
  { id: 'gwanghwamun', name: '광화문역', alias: ['광화문'], lines: ['5'], lat: 37.571, lng: 126.9768 },
  { id: 'jonggak', name: '종각역', alias: ['종각', '종로'], lines: ['1'], lat: 37.5702, lng: 126.9831 },
  { id: 'seoulst', name: '서울역', alias: ['서울역'], lines: ['1', '4'], lat: 37.5547, lng: 126.9707 },
  { id: 'yongsan', name: '용산역', alias: ['용산'], lines: ['1', '4'], lat: 37.5298, lng: 126.9648 },
  {
    id: 'hongdae',
    name: '홍대입구역',
    alias: ['홍대', '홍익대'],
    lines: ['2', '공항'],
    lat: 37.5571,
    lng: 126.9245,
  },
  {
    id: 'dmc',
    name: '디지털미디어시티역',
    alias: ['상암', 'dmc'],
    lines: ['6', '공항'],
    lat: 37.577,
    lng: 126.899,
  },
  { id: 'magok', name: '마곡나루역', alias: ['마곡'], lines: ['9', '공항'], lat: 37.5667, lng: 126.8272 },
  { id: 'seongsu', name: '성수역', alias: ['성수'], lines: ['2'], lat: 37.5446, lng: 127.056 },
  {
    id: 'gasan',
    name: '가산디지털단지역',
    alias: ['가산', '가디'],
    lines: ['1', '7'],
    lat: 37.4815,
    lng: 126.8826,
  },
  {
    id: 'guroDigital',
    name: '구로디지털단지역',
    alias: ['구디', '구로디지털'],
    lines: ['2'],
    lat: 37.4851,
    lng: 126.9015,
  },
  { id: 'pangyo', name: '판교역', alias: ['판교'], lines: ['신분당'], lat: 37.3948, lng: 127.1112 },
  { id: 'yangjae', name: '양재역', alias: ['양재'], lines: ['3', '신분당'], lat: 37.4841, lng: 127.0346 },
  { id: 'snu', name: '서울대', alias: ['서울대', '서울대학교'], lines: ['2'], lat: 37.4812, lng: 126.9527 },
];

export const dongById = (id: string): DongSeed | undefined => DONGS.find((d) => d.id === id);
export const workplaceById = (id: string): Workplace | undefined => WORKPLACES.find((w) => w.id === id);

/* ---------- 결정적 난수 ---------- */

export function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function rng(seed: string): () => number {
  let a = hashString(seed);
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pick = <T>(r: () => number, arr: readonly T[]): T => arr[Math.floor(r() * arr.length)] as T;

/* ---------- 건물 · 실거래 ---------- */

const BUILDING_HEAD = [
  '한빛',
  '새솔',
  '푸른',
  '다온',
  '하늘',
  '미소',
  '라온',
  '해든',
  '늘봄',
  '정원',
  '도담',
  '가온',
];
const BUILDING_TAIL = {
  villa: ['빌라', '하우스', '빌', '맨션'],
  officetel: ['오피스텔', '스테이', '시티', '타워'],
};

export function buildingsOf(
  dongId: string,
): { name: string; type: 'villa' | 'officetel'; built: number; lat: number; lng: number }[] {
  const d = dongById(dongId);
  if (!d) return [];
  const r = rng(`bld:${dongId}`);
  return Array.from({ length: 12 }, (_, i) => {
    const type = i % 3 === 0 ? 'officetel' : 'villa';
    return {
      name: `${pick(r, BUILDING_HEAD)}${pick(r, BUILDING_TAIL[type])} ${i + 1}차`.replace(' 1차', ''),
      type,
      built: 1996 + Math.floor(r() * 29),
      lat: d.lat + (r() - 0.5) * 0.012,
      lng: d.lng + (r() - 0.5) * 0.014,
    } as const;
  });
}

/** 동네별 최근 12개월 실거래 예시(월세 계약) */
export function dealsOf(dongId: string): Deal[] {
  const d = dongById(dongId);
  if (!d) return [];
  const r = rng(`deal:${dongId}`);
  const blds = buildingsOf(dongId);
  const deals: Deal[] = [];
  const n = 70 + Math.floor(r() * 50);
  for (let i = 0; i < n; i++) {
    const b = pick(r, blds);
    const area = Math.round((b.type === 'officetel' ? 19 : 17) + r() * 22);
    const age = 2026 - b.built;
    // 환산월세 = 기준 + 면적 보정 + 신축 보정 + 오피스텔 보정 + 흔들림
    const conv =
      d.base +
      (area - 25) * 1.1 +
      Math.max(0, 15 - age) * 0.9 +
      (b.type === 'officetel' ? 9 : 0) +
      (r() - 0.5) * 14;
    const deposit = pick(r, [300, 500, 500, 1000, 1000, 1000, 2000, 3000] as const);
    const rent = Math.max(20, Math.round(conv - (deposit * STANDARD.convRate) / 100 / 12));
    const m = 1 + Math.floor(r() * 12);
    deals.push({
      id: `${dongId}-${i}`,
      dongId,
      building: b.name,
      type: b.type,
      area,
      built: b.built,
      deposit,
      rent,
      month: m <= 10 ? `2026-${String(11 - m).padStart(2, '0')}` : `2025-${String(23 - m).padStart(2, '0')}`,
      renewal: r() < 0.25,
    });
  }
  return deals;
}

/* ---------- 중개사무소 ---------- */

const BROKER_HEAD = [
  '햇살',
  '으뜸',
  '바른',
  '정직',
  '한마음',
  '든든',
  '우리',
  '새봄',
  '참',
  '믿음',
  '하나',
  '열린',
];

export function brokersOf(dongId: string): Broker[] {
  const d = dongById(dongId);
  if (!d) return [];
  const r = rng(`brk:${dongId}`);
  const used = new Set<string>();
  return Array.from({ length: 3 }, (_, i) => {
    let head = pick(r, BROKER_HEAD);
    while (used.has(head)) head = pick(r, BROKER_HEAD);
    used.add(head);
    const guCode =
      {
        관악구: '11620',
        동작구: '11590',
        영등포구: '11560',
        금천구: '11545',
        구로구: '11530',
        서초구: '11650',
      }[d.gu] ?? '11000';
    return {
      id: `${dongId}-b${i + 1}`,
      dongId,
      name: `${head}공인중개사사무소`,
      regNo: `${guCode}-20${17 + Math.floor(r() * 8)}-${String(10000 + Math.floor(r() * 89999)).slice(0, 5)}`,
      phone: `02-${800 + Math.floor(r() * 199)}-${String(1000 + Math.floor(r() * 8999))}`,
      lat: d.lat + (r() - 0.5) * 0.008,
      lng: d.lng + (r() - 0.5) * 0.009,
    };
  });
}

/* ---------- 지하철역(지도 레이어) ---------- */

export const STATIONS: { name: string; lines: string; lat: number; lng: number }[] = [
  { name: '서울대입구', lines: '2', lat: 37.4812, lng: 126.9527 },
  { name: '봉천', lines: '2', lat: 37.4825, lng: 126.9416 },
  { name: '낙성대', lines: '2', lat: 37.4766, lng: 126.9636 },
  { name: '신림', lines: '2·신림', lat: 37.4842, lng: 126.9297 },
  { name: '사당', lines: '2·4', lat: 37.4765, lng: 126.9816 },
  { name: '숭실대입구', lines: '7', lat: 37.4963, lng: 126.9536 },
  { name: '총신대입구(이수)', lines: '4·7', lat: 37.4868, lng: 126.9819 },
  { name: '보라매', lines: '7·신림', lat: 37.4998, lng: 126.9201 },
  { name: '노량진', lines: '1·9', lat: 37.5135, lng: 126.9426 },
  { name: '흑석', lines: '9', lat: 37.5088, lng: 126.9636 },
  { name: '대림', lines: '2·7', lat: 37.4932, lng: 126.8949 },
  { name: '신길', lines: '1·5', lat: 37.5172, lng: 126.9175 },
  { name: '독산', lines: '1', lat: 37.4664, lng: 126.8894 },
  { name: '구로디지털단지', lines: '2', lat: 37.4851, lng: 126.9015 },
  { name: '방배', lines: '2', lat: 37.4815, lng: 126.9976 },
];
