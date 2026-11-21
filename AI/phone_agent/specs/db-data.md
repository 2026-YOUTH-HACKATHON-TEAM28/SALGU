# 전화 에이전트와 DB: 필요한 데이터 (v0.3.1 기준)

DB 담당이 "전화 기능 때문에 무엇을 저장하고, 무엇을 꺼내 줘야 하는지"를 한 번에 볼 수 있게 정리했습니다. 필드의 상세 설명은 [인풋·아웃풋](../contracts/io.md)에 있습니다. 금액은 만원, 시각은 한국 시간(`timestamptz`)입니다.

## 0. 한눈에

```
[DB] ──① 요청 재료 꺼내기──▶ BE ──POST──▶ 전화 에이전트 ──전화──▶ 중개사무소
 ▲                            │◀──GET(1~2초 폴링)──┘
 └──────② 결과 저장(upsert)───┘
```

- **전화 에이전트는 DB에 직접 접속하지 않습니다.** BE가 DB에서 재료를 꺼내 요청을 만들고(①), 결과를 받아 저장합니다(②).
- **DB에는 테이블 4개만 둡니다**(묶음·통화·방·방문). 다른 기능(내 통화 목록, 매물 비교 카드, 지도, 일정·알림)이 합쳐서 쓰는 값만 저장하고, 나머지 세부 결과는 필요할 때 전화 에이전트에서 조회합니다(2절).
- 전화 에이전트가 정한 ID(`batch_id`, `call_id`)를 **그대로 키로 저장**하면 다시 조회하거나 다시 저장할 때 중복이 생기지 않습니다.

## 1. 요청을 만들 때 DB에서 꺼낼 데이터 (입력)

### 1-1. 문의 통화 `POST /api/broker-call-batches`

| 요청 필드 | 필수 | 뜻 | DB에서 가져올 곳 (ERD v3 기준) | 지금 ERD에 |
|---|---|---|---|---|
| `approval_id` | ○ | 사용자가 [전화 걸기]를 승인한 한 번 | `call_batch.approval_id` | 없음 → 추가 |
| `search.dong` | ○ | 문의할 동네 이름 | `CANDIDATE.dong_cd` → 법정동명 | DONG 테이블 정의 필요 |
| `search.ref_building` | | 참고 건물 이름 | 후보의 대표 건물 `BUILDING.bld_nm` | 있음 |
| `search.housing_type` | ○ | `officetel` 또는 `villa` **하나** | `SEARCH_CONDITION.house_types` | 있음. 둘 다면 유형별로 따로 요청 |
| `search.deposit_manwon`, `monthly_rent_manwon` | ○ | 사용자 예산 | `SEARCH_CONDITION.deposit_max`, `monthly_max` | 있음 |
| `search.area_m2` | | 전용면적 | 조건 카드 | 없음(선택) |
| `prep.move_in`, `prep.term` | | 희망 입주 시기, 계약 기간(말 그대로, 예: "12월 초", "1년") | 발신 전 질문 답 | **없음 → 추가** |
| `prep.pet` | | 반려동물 여부 | 발신 전 질문 답 | **없음 → 추가** |
| `prep.surname` | | 방문자 성(1~2자) | 발신 전 질문 답 | 없음 → 추가 |
| `share.conditions`, `visit_time`, `surname`, `contact` | ○ | 중개사에게 말해도 되는 정보(체크박스) | 승인 화면 체크 | `CALL.share_items`(json)와 비슷. 묶음 단위로 |
| `keep_transcript` | | 대화 전문 30일 보관 동의 | 승인 화면 체크 | **없음 → 추가** |
| `brokers[].reg`, `name`, `phone` | ○ | 등록번호, 상호, 전화번호. **배열 순서 = 전화 순서**(최대 10곳) | `BROKER.reg_no`, `office_name`, `phone` | 있음 |
| `brokers[].visit_windows[]` | | 사용자가 갈 수 있는 시간대 `{start, end}`(최대 6개) | 승인 화면 선택 | `CALL.visit_window`(문자열) → **시작·끝 시각 목록으로**(`call.visit_windows` json) |

**전화할 사무소 고르기**: 후보 동네(`dong_nm`)의 `BROKER` 중 `status = '영업'`이고 `phone`이 있는 곳 2~3곳. 중개업소 데이터(OA-23037)를 적재할 담당이 아직 정해지지 않았습니다. 이게 없으면 전화를 걸 수 없습니다.

### 1-2. 확정 통화 `POST /api/visit-confirmations`

사용자가 방과 시각을 고르고 승인한 뒤 보냅니다.

| 요청 필드 | 필수 | DB에서 가져올 곳 |
|---|---|---|
| `approval_id` | ○ | 일정 승인 기록의 ID |
| `visits[].call_id` | ○ | 그 방을 들은 **문의 통화**의 `call_id` |
| `visits[].listing_index` | | 그 통화에서 몇 번째 방인지(`listing.listing_index`) |
| `visits[].at` | ○ | 사용자가 고른 방문 시각 |
| `visits[].alternatives[]` | | 안 되면 맞춰도 되는 시간대(사용자가 미리 허락한 범위) |
| `visits[].place` | | 만날 곳(비우면 사무소) |

### 1-3. 발신 전에 챗봇이 사용자에게 물어야 할 것

전화 에이전트가 중개사에게 말하거나 물으려면, 아래 답이 DB에 있어야 합니다.

| 질문 | 저장 위치 | 안 물었을 때 |
|---|---|---|
| "언제쯤 들어가고 싶으세요?" | `prep.move_in` | 입주 시기를 말하지 않음 |
| "계약은 몇 년 생각하세요?" | `prep.term` | 말하지 않음 |
| "반려동물 있으세요?" | `prep.pet` | `false`로 보고 묻지 않음 |
| "방 보러 갈 수 있는 날짜·시간대는요?" | `visit_windows` | 중개사가 되는 시간을 묻지 않음 → 확정 단계에서 막힘 |
| "중개사에게 알려도 되는 것: 희망 조건 / 방문 시간 / 성 / 연락처" | `share.*` | 조건·시간만 말함(성·연락처는 말하지 않음) |
| "통화 전문을 30일 보관할까요?" | `keep_transcript` | 보관하지 않음(근거 문장만 남김) |

## 2. 결과: DB에 저장할 것과 조회만 할 것

`GET /api/broker-call-batches/{batch_id}`, `GET /api/visit-confirmations/{batch_id}`를 1~2초마다 조회해 `call_id` 기준으로 upsert합니다. 묶음 `status`가 `done`이면 멈춥니다.

### 2-1. DB에 저장 (테이블 4개)

| 테이블 | 한 줄 = | 키 | 컬럼 | 쓰는 곳 |
|---|---|---|---|---|
| `call_batch` | 승인 한 번(문의 또는 확정) | `batch_id` | `kind`(inquiry/confirm), `approval_id`, `user_id`, `condition_id`, `candidate_id`, 준비 답(`move_in`, `term`, `pet`, `surname`), `share`(json), `keep_transcript`, `status`, `created_at` | 내 통화 목록, 요청 다시 만들기 |
| `call` | 통화 한 건(사무소 하나) | `call_id` | `batch_id`, `kind`, `parent_call_id`(확정이면 문의 통화), `broker_id`, `visit_windows`(json), `status`, `outcome`, `called_at`, `ended_at`, `error` | 통화 카드(사무소별 결과·확인 시각) |
| `listing` | 문의 통화에서 들은 방 하나 | (`call_id`, `listing_index`) | `building`, `floor`, `unit`, `location`, `area_m2`, `deposit`, `monthly`, `maint_fee`, **`move_in`(text)** | 매물 비교 카드(실거래 범위와 나란히), 지도 |
| `visit` | 확정 통화의 방 하나 | (`confirm_call_id`, `listing_index`) | `parent_call_id`, `requested_at`, **`visit_status`**, `visit_at`, `place`, `proposal_at` | 일정 탭, 방문 알림 |

### 2-2. 조회만 (DB에 저장하지 않음)

화면이 필요할 때 전화 에이전트에서 받아 옵니다. 통화 한 건은 `GET /api/broker-calls/{call_id}`, 묶음은 위 두 GET입니다.

| 값 | 어디에 쓰나 |
|---|---|
| `broker_slots`(중개사가 방을 보여 줄 수 있다고 한 시각), `availability_note` | 방문 시각 고르기 화면 |
| `unverified`(확인 필요 항목), `evidence`·`quotes`(근거 문장), `corrections`(통화 중 바뀐 값) | 매물 카드의 '확인 필요'·근거 보기 |
| `pet_allowed`, `registry_reply`, `registry_docs`(등기부 문자·업로드, 첨부 주소) | 매물 카드, 등기 정리 |
| `duplicate_groups`(같은 방 의심 묶음) | 매물 카드의 중복 표시 |
| `notifications`(알림 기록), `sms_draft`, `timing`, `transcript` | 기록·시연 |

**주의**: 전화 에이전트의 기록은 오래 보관하는 저장소가 아닙니다. mock 모드는 서버를 다시 띄우면 지워지고, 사용자가 올린 등기부 PDF는 메모리에만 있습니다. 시연에서는 충분하지만, 나중에 오래 남길 값이 생기면 그때 2-1에 컬럼을 더합니다.

### 2-3. 값 목록 (enum)

| 컬럼 | 값 |
|---|---|
| `call.status` | `waiting`, `scheduled`, `queued`, `ringing`, `in_progress`, `retry_wait`, `analyzing`, `done`, `failed`, `rejected` |
| `call.outcome` (문의) | `listing`(방 있음), `no_listing`, `no_answer`, `declined`(AI 통화 거절), `unclear` |
| `call.outcome` (확정) | `confirmed`, `partial`, `alternative`, `no_time`, `unavailable`, `unclear`, `no_answer`, `declined` |
| `visit.visit_status` | `requesting`(요청 중), `confirmed`, `needs_approval`(중개사가 다른 시각 제안), `not_scheduled` |

## 3. ERD v3과 다른 점 (반영 요청)

1. **한 통화에 방이 여러 개** 나올 수 있습니다(최대 3개). `CALL.confirmed_deposit` 같은 한 방짜리 컬럼 대신 `listing`을 (`call_id`, `listing_index`)로 따로 둡니다.
2. **입주 시기는 날짜가 아니라 글자**입니다. 중개사는 "다음 달 초"처럼 말하고, 살구는 지어내지 않습니다. `LISTING.available_from date` → `move_in text`.
3. **모르는 값은 null**입니다. 확인되지 않은 값은 비우고(화면의 '확인 필요'), 요청 값(예산)으로 채우지 않습니다. 금액 컬럼은 모두 NULL을 허용해야 합니다.
4. **재시도는 같은 통화 안에서 합니다.** `CALL.retry_of` 자기 참조는 필요 없습니다.
5. **방문 상태에 '요청 중'과 '승인 필요'가 필요합니다.** `VISIT.status`(확정/변경요청/취소/완료)에 `requesting`, `needs_approval`, `not_scheduled`를 더하고, 확정 알림과 일정 반영은 `confirmed`일 때만 합니다(기획서: 중개사 확인 + 사용자 승인 후 확정).
6. **`CALL_LINE`(대화 내용)은 DB에 두지 않습니다.** 대화 원문은 동의했을 때만 전화 에이전트가 30일 보관하고, 근거 문장은 조회로 받습니다.
7. **등기부 원본·수신 기록(`REGISTRY_INBOX`)과 전화 알림 기록은 전화 에이전트에서 조회합니다.** 등기 정리 결과(`REGISTRY_SUMMARY` 등)는 등기 담당 테이블에 저장합니다. 방문 알림(`NOTIFICATION`의 전날·1시간 전)은 지금처럼 DB가 맡아도 됩니다.

## 4. 팀이 정할 것

- **DB 종류**: BE 브랜치(`be/soojung/backend-bootstrap`)는 MySQL, DB 담당은 Supabase(Postgres)로 작업 중입니다. 위 표는 양쪽 다 쓸 수 있게 썼고, 아래 부록 SQL은 Postgres 기준입니다.
- **중개업소 데이터 적재 담당**(OA-23037): 전화 기능의 전제 조건입니다.
- **결과를 누가 저장할지**: 제안은 BE가 폴링해서 저장하는 방식입니다(BE 구현 계획 5단계와 같음). 시간이 없으면 전화 에이전트가 Supabase에 직접 쓰는 방식도 가능하지만, 그러면 전화 에이전트에 DB 키가 필요합니다.
- **카카오 알림 토큰**: 지금은 시연용으로 전화 에이전트 `.env`에 토큰 하나만 둡니다. 사용자별로 보내려면 사용자 토큰을 DB에 저장해야 합니다(`USER.kakao_msg_consent`와 함께).

## 부록: Postgres(Supabase) 테이블 초안

제안용입니다. `broker`, `search_condition`, `candidate`, `"user"`는 ERD v3 테이블을 그대로 쓴다고 보고 FK만 걸었습니다.

```sql
create table call_batch (
  batch_id        text primary key,                 -- 전화 에이전트가 준 bb_… / vb_…
  kind            text not null check (kind in ('inquiry','confirm')),
  approval_id     text not null,
  user_id         bigint references "user",
  condition_id    bigint references search_condition,
  candidate_id    bigint references candidate,
  move_in         text, term text, pet boolean, surname text,   -- 발신 전 질문 답
  share           jsonb,                            -- {"conditions":true,"visit_time":true,"surname":false,"contact":false}
  keep_transcript boolean not null default false,
  status          text not null,                    -- running / done
  created_at      timestamptz not null default now(),
  unique (kind, approval_id)
);

create table call (
  call_id        text primary key,                  -- bc_…
  batch_id       text not null references call_batch,
  kind           text not null check (kind in ('inquiry','confirm')),
  parent_call_id text references call,              -- 확정 통화면 문의 통화
  broker_id      bigint references broker,
  visit_windows  jsonb,                             -- [{"start":"…","end":"…"}] 사용자가 갈 수 있는 시간대
  status         text not null,
  outcome        text,
  called_at      timestamptz,                       -- 화면의 '확인 시각'
  ended_at       timestamptz,
  error          text
);

create table listing (
  call_id       text not null references call,
  listing_index int  not null,
  building text, floor text, unit text, location text,
  area_m2       numeric,
  deposit int, monthly int, maint_fee int,          -- 만원, 모르면 null
  move_in       text,                               -- "다음 달 초"처럼 들은 그대로
  primary key (call_id, listing_index)
);

create table visit (
  confirm_call_id text not null references call,
  listing_index   int  not null,
  parent_call_id  text not null references call,
  requested_at    timestamptz not null,             -- 사용자가 고른 시각
  visit_status    text not null check (visit_status in ('requesting','confirmed','needs_approval','not_scheduled')),
  visit_at        timestamptz,                      -- 확정된 시각
  place           text,
  proposal_at     timestamptz,                      -- 중개사가 제안한 다른 시각
  primary key (confirm_call_id, listing_index)
);
```
