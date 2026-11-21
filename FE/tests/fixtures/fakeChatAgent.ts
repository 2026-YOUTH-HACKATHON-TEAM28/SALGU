/* 시험 전용 가짜 대화 에이전트(AI/chat_agent 응답 모양). 화면 코드에는 들어가지 않아요.
 * - 말에서 회사·월세·보증금·통근을 간단히 뽑아 조건 카드로 돌려줘요
 * - 월세 30만 원 이하면 맞는 실거래가 없다고 해요(맞는 동네 없음 흐름)
 * - 'N번 집 문의해 줘'에는 전화 요청 초안(contracts/call_request.md)과 그 동 중개사무소를 줘요 */

const cand = (o: Record<string, unknown>): Record<string, unknown> & { name?: string; address?: string } => ({
  rent_type: '월세',
  area_m2: 24,
  floor: 3,
  construction_year: 2016,
  contract_date: '2026-09-12',
  transaction_count: 4,
  reasons: ['최근 12개월 실거래 4건'],
  commute_minutes: null,
  transfers: null,
  station: null,
  is_live_listing: false,
  housing_type: 'villa',
  ...o,
});

export const FAKE_CANDIDATES = [
  cand({
    name: '해든빌라',
    address: '서울특별시 영등포구 신길동 100-1',
    deposit_manwon: 1000,
    monthly_rent_manwon: 55,
    score: 88.2,
    market_median_deposit_manwon: 1000,
    market_median_monthly_rent_manwon: 55,
  }),
  cand({
    name: '마포오피스텔',
    address: '서울특별시 마포구 공덕동 5-2',
    housing_type: 'officetel',
    deposit_manwon: 1000,
    monthly_rent_manwon: 62,
    score: 84,
    market_median_deposit_manwon: 1000,
    market_median_monthly_rent_manwon: 60,
  }),
  cand({
    name: '신길하우스',
    address: '서울특별시 영등포구 신길동 200-3',
    deposit_manwon: 1000,
    monthly_rent_manwon: 60,
    score: 80,
    market_median_deposit_manwon: 1000,
    market_median_monthly_rent_manwon: 57,
  }),
  cand({
    name: '대림그린빌',
    address: '서울특별시 영등포구 대림동 33-7',
    deposit_manwon: 500,
    monthly_rent_manwon: 52,
    score: 76,
    market_median_deposit_manwon: 500,
    market_median_monthly_rent_manwon: 53,
  }),
];

const BROKERS: Record<string, { reg: string; name: string; phone: string }[]> = {
  신길동: [
    { reg: '11560-2019-00011', name: '신길역부동산공인중개사사무소', phone: '02-111-2222' },
    { reg: '11560-2020-00022', name: '영등포한빛공인중개사사무소', phone: '02-333-4444' },
  ],
  공덕동: [{ reg: '11440-2018-00033', name: '공덕래미안공인중개사사무소', phone: '02-555-6666' }],
  대림동: [
    { reg: '11560-2021-00044', name: '대림역공인중개사사무소', phone: '02-777-8888' },
    { reg: '11560-2017-00055', name: '대림한마음공인중개사사무소', phone: '02-999-0000' },
  ],
};

const num = (re: RegExp, t: string) => {
  const m = re.exec(t);
  return m ? Number(m[1]) : undefined;
};

export function fakeAgentReply(sessionId: string, message: string): Record<string, unknown> {
  const ask = /(\d)번 집 문의해 줘/.exec(message);
  if (ask) {
    const c = FAKE_CANDIDATES[Number(ask[1]) - 1];
    const dong = String(c?.address ?? '').split(' ')[2] ?? '';
    return {
      session_id: sessionId,
      type: 'message',
      reply: '중개사무소에 물어볼 수 있어요.',
      messages: [{ kind: 'reply', text: '중개사무소에 물어볼 수 있어요.' }],
      card: null,
      intent: 'control',
      via: 'rules',
      ready: true,
      missing: [],
      changed: [],
      backend: null,
      action: c
        ? {
            type: 'broker_call_request',
            status: 'needs_approval',
            listing: { name: c.name, address: c.address },
            request: { brokers: (BROKERS[dong] ?? []).map((b) => ({ ...b, visit_windows: [] })) },
          }
        : null,
    };
  }
  const wp =
    /회사는\s*([^,\s]+)/.exec(message)?.[1] ??
    /([가-힣A-Za-z0-9]+(?:역|대학교|대))\s*(?:으로|로)?\s*(?:출근|통학)/.exec(message)?.[1];
  const rent = num(/월세\s*(\d+)/, message);
  const deposit = num(/보증금\s*(\d+)/, message);
  const commute = num(/(?:출퇴근|통근)\s*(\d+)분/, message);
  const conditions: Record<string, unknown> = {};
  if (wp) conditions.workplace = { value: 'place', label: wp, source: 'stated', evidence: wp };
  if (rent !== undefined) conditions.monthly_rent_manwon = { value: rent, source: 'stated' };
  if (deposit !== undefined) conditions.deposit_manwon = { value: deposit, source: 'stated' };
  if (commute !== undefined) conditions.max_commute_min = { value: commute, source: 'stated' };
  const searching = /추천해줘/.test(message);
  const none = rent !== undefined && rent <= 30;
  return {
    session_id: sessionId,
    type: 'condition_card',
    reply: '알려 주신 조건으로 정리했어요.',
    messages: [{ kind: 'reply', text: '알려 주신 조건으로 정리했어요.' }],
    card: { version: '0.2-draft', conditions },
    intent: 'search',
    via: 'rules',
    ready: Boolean(wp && rent !== undefined),
    missing: [],
    changed: Object.keys(conditions),
    backend: searching
      ? {
          ok: true,
          mock: false,
          source: '추천 엔진(실거래 DB)',
          error: null,
          notes: none
            ? ['조건에 맞는 최근 실거래가 없어요.']
            : [`${wp ?? '회사'}까지 통근 시간·환승은 아직 계산하지 못해요(교통 데이터 연결 전).`],
          count: none ? 0 : FAKE_CANDIDATES.length,
          candidates: none ? [] : FAKE_CANDIDATES,
        }
      : null,
  };
}

/** vitest 에서 fetch 를 바꿔 끼울 때: base 로 가는 요청만 가로채요 */
export function fakeAgentFetch(base: string, next: typeof fetch = globalThis.fetch) {
  return (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    if (!url.startsWith(base)) return next(input, init);
    if (url.endsWith('/health')) return Promise.resolve(Response.json({ ok: true }));
    const body = JSON.parse(String(init?.body ?? '{}')) as { session_id?: string; message?: string };
    if (url.endsWith('/api/reset')) return Promise.resolve(Response.json({ ok: true }));
    return Promise.resolve(Response.json(fakeAgentReply(body.session_id ?? 's', body.message ?? '')));
  };
}
