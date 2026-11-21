import type {
  CallOutcome,
  CallStatus,
  CondKey,
  ContactStatus,
  LeaseType,
  PriceVerdict,
  Priority,
  SourceKind,
  Stage,
  VisitStatus,
} from './types.js';

/* 화면 문구는 여기 한 곳에서만 정해요. 화면마다 따로 쓰면 같은 상태가 다르게 보여요. */

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'muted';

export interface StatusLabel {
  text: string;
  tone: Tone;
}

/** 매물 카드 머리 오른쪽: 연락 상태 */
export const CONTACT_LABEL: Record<ContactStatus, StatusLabel> = {
  before: { text: '연락 전', tone: 'muted' },
  contacting: { text: '연락 중', tone: 'info' },
  no_answer: { text: '답변 없음', tone: 'warn' },
  answered: { text: '답변 받음', tone: 'info' },
  proposed: { text: '시간 제안 받음', tone: 'warn' },
  confirmed: { text: '방문 확정', tone: 'ok' },
  failed: { text: '연락 못 함', tone: 'bad' },
};

/** AI 통화 카드(화면 정의서 S-05 방식) */
export function callLabel(status: CallStatus, outcome: CallOutcome | null): StatusLabel {
  switch (status) {
    case 'waiting':
      return { text: '차례를 기다리는 중', tone: 'muted' };
    case 'queued':
    case 'ringing':
      return { text: '신호 가는 중', tone: 'info' };
    case 'in_progress':
      return { text: '통화 중', tone: 'info' };
    case 'analyzing':
      return { text: '통화 내용 정리 중', tone: 'info' };
    case 'retry_wait':
      return { text: '안 받음(다시 걸 예정)', tone: 'warn' };
    case 'done':
      switch (outcome) {
        case 'listing':
          return { text: '방 있음', tone: 'ok' };
        case 'no_listing':
          return { text: '비슷한 방 없음', tone: 'muted' };
        case 'no_answer':
          return { text: '안 받음', tone: 'warn' };
        case 'declined':
          return { text: 'AI 통화 거절', tone: 'bad' };
        default:
          return { text: '확인 못 함', tone: 'warn' };
      }
  }
}

export function isCallActive(status: CallStatus): boolean {
  return status === 'queued' || status === 'ringing' || status === 'in_progress' || status === 'analyzing';
}

/** 매물 카드 가격 줄 바로 아래: 같은 조건 과거 실거래와 비교한 값 */
export const PRICE_LABEL: Record<PriceVerdict, StatusLabel> = {
  fair: { text: '적정', tone: 'ok' },
  slightly_high: { text: '약간 비쌈', tone: 'warn' },
  high: { text: '비쌈', tone: 'bad' },
  unknown: { text: '비교 못 함', tone: 'muted' },
};

export const VISIT_LABEL: Record<VisitStatus, StatusLabel> = {
  requesting: { text: '요청 중', tone: 'info' },
  confirmed: { text: '확정', tone: 'ok' },
  proposed: { text: '다른 시간 제안 받음', tone: 'warn' },
  failed: { text: '일정 못 잡음', tone: 'bad' },
  cancelled: { text: '취소함', tone: 'muted' },
};

export const SOURCE_KIND_LABEL: Record<SourceKind, string> = {
  real: '실데이터',
  example: '예시 값',
  simulation: '시뮬레이션',
  standard: '기준값',
  ai: 'AI 답변',
};

export const STAGES: { id: Stage; label: string }[] = [
  { id: 'cond', label: '조건' },
  { id: 'dong', label: '동네' },
  { id: 'call', label: '전화' },
  { id: 'pick', label: '방 고르기' },
  { id: 'meet', label: '미팅' },
];

export const NEXT_ACTION: Record<Stage, string> = {
  cond: '회사와 월세를 알려 주세요',
  dong: '전화할 동네를 골라 주세요',
  call: '전화 준비를 마치고 통화를 기다려요',
  pick: '미팅 잡을 방을 골라 주세요',
  meet: '방문 일정을 확인해 주세요',
};

/** 조건 항목: 순서와 이름. primary 는 카드 맨 위에 항상 보이는 항목 */
export const COND_META: { key: CondKey; label: string; primary: boolean }[] = [
  { key: 'workplace', label: '회사(학교)', primary: true },
  { key: 'maxCommute', label: '출퇴근', primary: true },
  { key: 'rent', label: '월세', primary: true },
  { key: 'deposit', label: '보증금', primary: true },
  { key: 'houseType', label: '유형', primary: false },
  { key: 'builtAfter', label: '준공', primary: false },
  { key: 'maxTransfer', label: '환승', primary: false },
  { key: 'maxBusInterval', label: '버스 배차', primary: false },
  { key: 'leaseTypes', label: '계약 유형', primary: false },
  { key: 'preferredAreas', label: '살 곳', primary: false },
  { key: 'avoidAreas', label: '피할 곳', primary: false },
  { key: 'minArea', label: '최소 면적', primary: false },
  { key: 'minFloor', label: '최소 층', primary: false },
  { key: 'maxWalk', label: '역까지 도보', primary: false },
  { key: 'priceBand', label: '가격 구간', primary: false },
  { key: 'priority', label: '우선순위', primary: false },
];

export const PRIORITY_LABEL: Record<Priority, string> = {
  price: '가격',
  commute: '출퇴근',
  bus_headway: '버스 배차',
  building_age: '신축',
  area: '면적',
};

export const LEASE_LABEL: Record<LeaseType, string> = {
  monthly: '월세',
  jeonse: '전세',
  semi_jeonse: '반전세',
};

export const REQUIRED_CONDS: CondKey[] = ['workplace', 'rent'];
