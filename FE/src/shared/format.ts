import type { CondKey, Conditions, Workplace } from './types.js';

/** 만 원 단위 금액을 읽기 좋게: 500 -> 500만 원, 12000 -> 1억 2,000만 원 */
export function won(man: number): string {
  const v = Math.round(man);
  if (v >= 10000) {
    const eok = Math.floor(v / 10000);
    const rest = v % 10000;
    return rest ? `${eok}억 ${rest.toLocaleString('ko-KR')}만 원` : `${eok}억 원`;
  }
  return `${v.toLocaleString('ko-KR')}만 원`;
}

/** 보증금/월세 짧게: 1,000/55 */
export function depRent(deposit: number, rent: number): string {
  return `${Math.round(deposit).toLocaleString('ko-KR')}/${Math.round(rent)}`;
}

const DAYS = ['일', '월', '화', '수', '목', '금', '토'];

/** 2026-11-22T10:30 -> 11월 22일(일) 10:30 */
export function dateTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일(${DAYS[d.getDay()]}) ${hm(iso)}`;
}

export function dateOnly(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일(${DAYS[d.getDay()]})`;
}

export function hm(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** 조건 값을 화면 문구로 */
export function condValueText(key: CondKey, value: unknown, workplaces: Workplace[]): string {
  switch (key) {
    case 'workplace':
      return workplaces.find((w) => w.id === value)?.name ?? String(value);
    case 'maxCommute':
      return `${value}분 이내`;
    case 'rent':
      return `${value}만 원 이하`;
    case 'deposit':
      return `${won(Number(value))} 이하`;
    case 'houseType':
      return value === 'villa' ? '원룸·빌라' : value === 'officetel' ? '오피스텔' : '상관없음';
    case 'builtAfter':
      return value === null ? '상관없음' : `${value}년 이후`;
    case 'maxTransfer':
      return value === 0 ? '환승 없이' : `${value}회 이하`;
    case 'maxBusInterval':
      return value === null ? '상관없음' : `${value}분 이하`;
    case 'priceBand':
      return value === 'low' ? '싼 편(하위 30%)' : value === 'mid' ? '중간(30~70%)' : '상관없음';
    case 'priority':
      return value === 'commute'
        ? '출퇴근 먼저'
        : value === 'price'
          ? '가격 먼저'
          : value === 'new'
            ? '새 집 먼저'
            : '고르게';
    case 'commercial':
      return value === 'lively' ? '번화한 곳' : value === 'quiet' ? '조용한 주택가' : '상관없음';
    case 'pet':
      return value ? '키움(전화로 확인)' : '안 키움';
    case 'parking':
      return value ? '필요(전화로 확인)' : '필요 없음';
  }
}

export function hasCond(conds: Conditions, key: CondKey): boolean {
  return conds[key] !== undefined;
}

/** 주민등록번호·카드번호처럼 보이는 숫자를 가려요(보내기 전, 서버 저장 전 모두) */
export function maskPersonal(text: string): string {
  return text
    .replace(/\b(\d{6})[-\s]?([1-4])\d{6}\b/g, '$1-$2******')
    .replace(/\b(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})\b/g, '$1-****-****-$4');
}

/** 동네 통근 표시. 계산 전이면(에이전트 추천 엔진은 교통 데이터 연결 전) 그렇게 알려요 */
export function commuteLabel(d: { commute: { minutes: number; transfers: number } | null }): string {
  return d.commute ? `${d.commute.minutes}분 · 환승 ${d.commute.transfers}회` : '통근 계산 전';
}

/** 동네 버스 표시. 정보가 없으면 그렇게 알려요 */
export function busLabel(d: { bus: { route: string; interval: number; last: string } | null }): string {
  return d.bus ? `${d.bus.route}번 배차 ${d.bus.interval}분 · 막차 ${d.bus.last}` : '버스 정보 없음';
}
