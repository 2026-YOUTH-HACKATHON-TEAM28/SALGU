/* 화면과 서버가 함께 쓰는 데이터 모양. 실제 BE가 붙어도 이 모양을 기준으로 맞춰요. */

/** 조건의 출처: 말씀하신 값 / 살구가 채운 값 / 살구가 넓혀본 값 */
export type CondSource = 'said' | 'filled' | 'widened';

export interface CondItem<T> {
  value: T;
  source: CondSource;
  /** 살구가 정한 값이면 이유 */
  reason?: string;
  /** 넓혀본 값이면 원래 값 */
  original?: T;
}

export type HouseType = 'any' | 'villa' | 'officetel';
export type Priority = 'balanced' | 'commute' | 'price' | 'new';
export type Commercial = 'any' | 'lively' | 'quiet';
export type PriceBand = 'any' | 'low' | 'mid';

export interface Conditions {
  workplace?: CondItem<string>;
  maxCommute?: CondItem<number>;
  rent?: CondItem<number>;
  deposit?: CondItem<number>;
  houseType?: CondItem<HouseType>;
  builtAfter?: CondItem<number | null>;
  maxTransfer?: CondItem<number>;
  maxBusInterval?: CondItem<number | null>;
  priceBand?: CondItem<PriceBand>;
  priority?: CondItem<Priority>;
  commercial?: CondItem<Commercial>;
  pet?: CondItem<boolean>;
  parking?: CondItem<boolean>;
}

export type CondKey = keyof Conditions;

/** 조건 값만 모은 것(계산용) */
export interface CondValues {
  workplace: string | null;
  maxCommute: number;
  rent: number | null;
  deposit: number;
  houseType: HouseType;
  builtAfter: number | null;
  maxTransfer: number;
  maxBusInterval: number | null;
  priceBand: PriceBand;
  priority: Priority;
  commercial: Commercial;
  pet: boolean;
  parking: boolean;
}

export interface Workplace {
  id: string;
  name: string;
  alias: string[];
  lines: string[];
  lat: number;
  lng: number;
}

export interface Broker {
  id: string;
  dongId: string;
  name: string;
  regNo: string;
  phone: string;
  lat: number;
  lng: number;
}

export interface Commute {
  minutes: number;
  transfers: number;
  route: string[];
}

export interface BusInfo {
  route: string;
  interval: number;
  last: string;
}

export interface DongResult {
  id: string;
  rank: number;
  name: string;
  gu: string;
  station: string;
  lat: number;
  lng: number;
  score: number;
  dealCount: number;
  rentRange: [number, number];
  median: number;
  commute: Commute;
  bus: BusInfo;
  brokers: Broker[];
  buildings: string[];
}

export interface Deal {
  id: string;
  dongId: string;
  building: string;
  type: Exclude<HouseType, 'any'>;
  area: number;
  built: number;
  deposit: number;
  rent: number;
  month: string;
  renewal: boolean;
}

/** 걸러 낸 이유별 건수(맞는 동네 0곳일 때 풀 조건 제안) */
export interface FilterLoss {
  key: CondKey;
  count: number;
  suggest: number | string | null;
}

export interface SearchResult {
  dongs: DongResult[];
  losses: FilterLoss[];
  asOf: string;
}

/* ---------- 전화 · 매물 · 확인 · 방문 ---------- */

/** 전화 에이전트의 status 값(문서 v0.3.1) */
export type CallStatus =
  'waiting' | 'queued' | 'ringing' | 'in_progress' | 'retry_wait' | 'analyzing' | 'done';
export type CallOutcome = 'listing' | 'no_listing' | 'no_answer' | 'declined' | 'unclear';
export type RegistryReply = 'will_send' | 'at_visit' | 'refused' | null;

export interface CallLine {
  who: 'agent' | 'broker' | 'system';
  text: string;
}

export interface Call {
  id: string;
  brokerId: string;
  dongId: string;
  status: CallStatus;
  outcome: CallOutcome | null;
  attempts: number;
  retryAt: string | null;
  lines: CallLine[];
  listingIds: string[];
  slots: string[];
  registryReply: RegistryReply;
  smsDraft: string | null;
}

/** 매물 카드의 연락 상태(모든 화면에서 같은 문구) */
export type ContactStatus =
  'before' | 'contacting' | 'no_answer' | 'answered' | 'proposed' | 'confirmed' | 'failed';
/** 매물 카드의 확인 상태(모든 화면에서 같은 문구) */
export type CheckStatus = 'unchecked' | 'registry_wait' | 'recommend' | 'caution' | 'exclude';
export type PriceVerdict = 'fair' | 'slightly_high' | 'high' | 'unknown';
export type RiskLevel = 'good' | 'caution' | 'danger';

export interface CheckDetail {
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
  salePrice: number | null;
  loanOk: boolean;
  loanReasons: string[];
  risk: RiskLevel;
  ratio: number | null;
  riskReasons: string[];
  ruleVersion: string;
}

export interface Listing {
  id: string;
  no: number;
  callId: string;
  brokerId: string;
  dongId: string;
  building: string;
  floor: number;
  unit: string;
  type: Exclude<HouseType, 'any'>;
  area: number;
  built: number;
  deposit: number;
  rent: number;
  fee: number;
  moveIn: string;
  lat: number;
  lng: number;
  slots: string[];
  registryReply: RegistryReply;
  priceVerdict: PriceVerdict;
  contact: ContactStatus;
  check: CheckStatus;
  detail: CheckDetail | null;
}

export type VisitStatus = 'requesting' | 'confirmed' | 'proposed' | 'failed' | 'cancelled';

export interface Visit {
  id: string;
  listingId: string;
  at: string;
  status: VisitStatus;
  proposedAt: string | null;
  order: number;
  travelNext: { mode: string; minutes: number } | null;
  brokerSaid: string | null;
  changeRequested: boolean;
}

/* ---------- 대화 ---------- */

export type SourceKind = 'real' | 'example' | 'simulation' | 'standard';
export interface SourceTag {
  label: string;
  kind: SourceKind;
}

export type Stage = 'cond' | 'dong' | 'call' | 'check' | 'meet';

export interface CallPrep {
  dongIds: string[];
  moveIn: string | null;
  term: string | null;
  pet: boolean | null;
  visitSlot: string | null;
  share: { condition: boolean; slot: boolean; surname: boolean; contact: boolean };
}

export type Card =
  | { kind: 'cond'; id: string; ask?: { question: string; options: { label: string; text: string }[] } }
  | { kind: 'condForm'; id: string; done: boolean }
  | { kind: 'dongs'; id: string; result: SearchResult; workplace: string }
  | { kind: 'dongDetail'; id: string; dong: DongResult; deals: Deal[] }
  | { kind: 'noMatch'; id: string; losses: FilterLoss[] }
  | { kind: 'callPrep'; id: string; done: boolean }
  | { kind: 'calls'; id: string }
  | { kind: 'checks'; id: string }
  | { kind: 'plan'; id: string }
  | { kind: 'final'; id: string; ranking: { listingId: string; burden: number }[] }
  | { kind: 'concept'; id: string; title: string; body: string[] };

export interface Message {
  id: string;
  role: 'user' | 'bot';
  text: string;
  cards: Card[];
  chips: string[];
  sources: SourceTag[];
  at: string;
}

export interface CallBatch {
  id: string;
  startedAt: string;
  calls: Call[];
  doneAt: string | null;
}

export interface Plan {
  date: string;
  start: string;
  end: string;
  visitIds: string[];
  includeCaution: boolean;
}

export interface ChatState {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  rev: number;
  stage: Stage;
  conditions: Conditions;
  messages: Message[];
  search: SearchResult | null;
  selectedDongIds: string[];
  prep: CallPrep | null;
  batch: CallBatch | null;
  listings: Listing[];
  visits: Visit[];
  plan: Plan | null;
  /** 브로커 정보(통화한 곳) */
  brokers: Broker[];
  /** 화면이 다시 확인해야 하는지(통화·확정 진행 중) */
  live: boolean;
}

export interface ChatSummary {
  id: string;
  title: string;
  updatedAt: string;
  stage: Stage;
}

export type AuthKind = 'kakao' | 'mock' | 'guest';

export interface User {
  id: string;
  name: string;
  kind: AuthKind;
  photo: string | null;
}

export interface SessionInfo {
  user: User | null;
  version: number;
  kakaoMapKey: string;
  kakaoTalk: boolean;
}

export interface ScheduleItem {
  chatId: string;
  visit: Visit;
  listing: Listing;
  broker: Broker | null;
  dongName: string;
  station: string;
}

/** 화면 버튼이 서버에 보내는 동작 */
export type Action =
  | { type: 'search' }
  | { type: 'openCondForm' }
  | { type: 'submitCondForm'; values: Partial<CondValues> }
  | { type: 'setCond'; key: CondKey; value: unknown }
  | { type: 'resetCond'; key: CondKey }
  | { type: 'widen'; key: CondKey; value: unknown }
  | { type: 'acceptProposal'; visitId: string }
  | { type: 'toggleDong'; dongId: string }
  | { type: 'prepCalls'; dongIds: string[] }
  | { type: 'updatePrep'; patch: Partial<CallPrep> }
  | { type: 'startCalls' }
  | { type: 'planVisits'; includeCaution: boolean }
  | { type: 'showFinal' }
  | { type: 'cancelVisit'; visitId: string }
  | { type: 'requestChange'; visitId: string };
