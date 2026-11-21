# 살구 화면이 BE에 기대하는 API · 데이터 (화면 v1)

BE 담당자에게 넘기는 문서예요. 지금 화면은 FE 폴더의 mock 서버(`src/server`)와 이야기하고, mock 서버는 아래와 똑같은 주소와 JSON으로 답해요. BE가 같은 모양으로 답하면 화면은 고치지 않고 붙어요.

- 데이터 모양의 원본: [`src/shared/types.ts`](../src/shared/types.ts) (TypeScript 타입, 이 문서와 다르면 이 파일이 맞아요)
- 실제 응답 예시: [`docs/api-samples/`](./api-samples) (mock 서버로 조건부터 일정까지 한 번 돌려서 저장한 JSON, 다시 만들기는 맨 아래)
- 범위: 로그인, 대화, 조건, 동네 추천, 중개사무소 문의 통화, 내 번호 시험 통화, 방 고르기, 방문 확정 통화, 일정, 알림
- 빠진 것: 등기부·건축물대장·전세대출 확인은 서비스에서 뺐어요. 관련 API와 테이블은 필요 없어요.

## 1. 공통 규칙

| 항목 | 규칙 |
|---|---|
| 형식 | 요청·응답 모두 JSON(`Content-Type: application/json`). 본문 없는 POST도 `{}`를 보내요 |
| 인증 | 세션 쿠키(지금 이름 `sg_sid`, HttpOnly, SameSite=Lax, https에서 Secure). 로그인 전에는 대화 API가 401 |
| 금액 | 만 원 단위 정수. 보증금 1,000만 원은 `1000`, 월세 55만 원은 `55` |
| 면적 | 전용면적 ㎡ 정수 |
| 시각 | 기록 시각(`createdAt`, `startedAt` 등)은 UTC ISO 문자열(`2026-11-21T02:42:10.123Z`). 약속 시각(`visit.at`, `slots[]`, `plan.start`)은 서울 시각, 시간대 없이 `YYYY-MM-DDTHH:mm:ss` |
| 오류 | `{ "error": "코드", "message": "화면에 그대로 보여 줄 한국어 문장" }`. 401 로그인 필요, 404 없음, 409 규칙에 막힘(예: 입주일 안 고름), 415 JSON 아님, 429 요청 너무 많음 |
| 쓰기 보호 | 다른 사이트에서 온 쓰기 요청 거부(Origin 이 같은 호스트일 때만), 요청 수 제한(전체 1분 300번, 말 보내기 30번) |
| 개인정보 | 주민등록번호·카드번호처럼 보이는 숫자는 저장 전에 가려요. 시험 전화 번호는 가린 값(`010-****-5678`)만 저장 |
| 숫자 | 화면에 나오는 숫자(환산월세, 순위 점수, 시세 비교, 이동 시간)는 BE 계산 결과만. AI가 숫자를 만들지 않아요 |

## 2. API 목록

| 메서드 · 주소 | 요청 | 응답 | 화면 |
|---|---|---|---|
| `GET /api/health` | - | `{ ok, version }` | 배포 확인 |
| `GET /api/session` | - | `SessionInfo` | 시작할 때. `user`가 null이면 로그인 화면 |
| `POST /api/auth/mock-login` | `{}` | `{ user }` | 카카오로 시작하기(지금은 예시 계정). 실서비스는 `/oauth2/authorization/kakao` → `/login/oauth2/code/kakao` |
| `POST /api/auth/guest` | `{}` | `{ user }` | 로그인 없이 둘러보기 |
| `POST /api/auth/logout` | `{}` | `{ ok }` | 계정 메뉴 |
| `GET /api/meta` | - | `{ workplaces[], visitSlots[], dongs[], stations[] }` | 조건 양식의 회사 목록, 방문 가능 시간, 지도 |
| `GET /api/ai` | - | `{ enabled, model }` | (참고용) AI 연결 여부 |
| `GET /api/chats` | - | `{ chats: ChatSummary[] }` | 대화 목록(최근 순) |
| `POST /api/chats` | `{}` | `ChatState` (201) | 새 대화 |
| `GET /api/chats/:id?rev=N` | - | `ChatState`, 바뀐 게 없으면 204 | 통화·확정 진행 중 2.5초마다 확인 |
| `DELETE /api/chats/:id` | - | `{ ok }` | 대화 지우기 |
| `POST /api/chats/:id/messages` | `{ text }` (1~500자) | `ChatState` | 말 보내기. AI 답을 기다릴 수 있어 화면은 40초까지 기다려요 |
| `POST /api/chats/:id/actions` | `Action` | `ChatState` | 버튼(아래 3장) |
| `GET /api/schedule` | - | `{ items: ScheduleItem[] }` | 일정 탭. 이 계정의 모든 대화에서 **확정된 방문만**, 시각 순 |
| `POST /api/notify/kakao` | `{ on }` | `{ kakaoTalk }` | 카카오톡 알림 연결·해제. 둘러보기 계정은 403 |
| `POST /api/notify/test` | `{}` | `{ ok }` | 시험 알림(연결 안 됐으면 409) |

화면은 말·버튼마다 **대화 전체 상태(`ChatState`)를 통째로** 받아서 다시 그려요. 부분 응답은 쓰지 않아요.

## 3. 버튼 동작(`POST /api/chats/:id/actions`)

| `type` | 함께 보내는 값 | 하는 일 | 막히는 경우(409 `error`) |
|---|---|---|---|
| `openCondForm` | - | 조건 양식 카드 추가 | |
| `submitCondForm` | `values: Partial<CondValues>` | 조건을 이 값들로 새로 정하고(모두 '말씀하신 조건') 바로 동네 찾기 | `workplace_required`, `rent_required`, `invalid` |
| `setCond` | `key`, `value` | 조건 하나를 그 자리에서 바꿈(출처 `said`) | `invalid` |
| `widen` | `key`, `value` | 맞는 동네가 없을 때 조건 넓히기(출처 `widened`, `original`에 원래 값) 후 다시 찾기 | `invalid` |
| `resetCond` | `key` | 넓혀본 값을 원래 값으로 되돌리고 다시 찾기 | |
| `search` | - | 동네 찾기(말하지 않은 출퇴근·보증금·환승은 `filled`로 채움) | |
| `toggleDong` | `dongId` | 전화할 동네 고르기/빼기 | |
| `prepCalls` | `dongIds` | 전화 전 준비 카드 | `no_dong`, `calling` |
| `updatePrep` | `patch: Partial<CallPrep>` | 입주 희망일, 계약 기간, 반려동물, 방문 가능 시간, 알려줄 정보 | `invalid` |
| `testCall` | `phone`(숫자만 또는 하이픈) | 내 번호로 시험 전화(같은 대본) | `invalid_phone`, `testing`, `daily_limit`(하루 3번) |
| `startCalls` | - | 고른 동네 중개사무소에 문의 통화(동네마다 3곳, 한 번에 한 통) | `prep_required`, `calling`, `daily_limit`(하루 10통) |
| `toggleListing` | `listingId` | 미팅 잡을 방 고르기/빼기 | `not_found` |
| `planVisits` | `listingIds?`(없으면 고른 방) | 동선 순서로 시각 배치 후 중개사무소마다 확정 통화 | `no_listing`, `no_pick`, `confirming` |
| `acceptProposal` | `visitId` | 중개사가 제안한 시간으로 확정 | `not_found` |
| `showFinal` | - | 최종 추천 비교표 | |
| `requestChange` | `visitId` | 일정 변경 요청 표시(지금은 시뮬레이션) | `not_found` |
| `cancelVisit` | `visitId` | 방문 취소 | `not_found` |

## 4. 대화 상태 `ChatState`

| 필드 | 타입 | 설명 |
|---|---|---|
| `id`, `title` | string | 대화 id, 첫 말 24자 |
| `createdAt`, `updatedAt` | ISO | |
| `rev` | number | 바뀔 때마다 1씩 올라요. 화면은 `?rev=`로 보내고 같으면 204 를 받아요 |
| `stage` | `Stage` | 진행 단계 바(`cond` 조건, `dong` 동네, `call` 전화, `pick` 방 고르기, `meet` 미팅) |
| `live` | boolean | 통화·확정 통화·시험 전화가 진행 중이면 true. 화면은 true 동안 2.5초마다 확인 |
| `conditions` | `Conditions` | 조건 항목별 `{ value, source, reason?, original? }` |
| `messages` | `Message[]` | 말풍선과 카드 |
| `search` | `SearchResult` \| null | 마지막 동네 찾기 결과 |
| `selectedDongIds` | string[] | 전화할 동네 |
| `prep` | `CallPrep` \| null | 전화 전 준비에서 고른 값 |
| `testCall` | `TestCall` \| null | 내 번호 시험 전화 |
| `batch` | `CallBatch` \| null | 문의 통화 묶음(통화 목록) |
| `listings` | `Listing[]` | 통화로 들은 방 |
| `selectedListingIds` | string[] | 미팅 잡을 방(통화가 끝나면 실거래보다 비싼 방을 뺀 나머지로 채워요) |
| `visits` | `Visit[]` | 방문 일정 |
| `plan` | `Plan` \| null | 마지막 미팅 계획(날짜, 시작·끝, 방문 id 순서) |
| `brokers` | `Broker[]` | 통화한 중개사무소 |

### 조건 `Conditions`

| 키 | 값 | 화면 이름 |
|---|---|---|
| `workplace` | 회사 id(`meta.workplaces`) | 회사(학교), 필수 |
| `rent` | 만 원 | 월세 상한, 필수 |
| `deposit` | 만 원 | 보증금 상한(말 안 하면 1000, `filled`) |
| `maxCommute` | 분 | 출퇴근(말 안 하면 40, `filled`) |
| `maxTransfer` | 0~3 | 환승(말 안 하면 1, `filled`) |
| `houseType` | `any`·`villa`·`officetel` | 유형 |
| `builtAfter` | 연도 \| null | 준공 |
| `maxBusInterval` | 분 \| null | 버스 배차 |
| `priceBand` | `any`·`low`·`mid` | 가격 구간 |
| `priority` | `balanced`·`commute`·`price`·`new` | 우선순위(점수 가중치) |
| `commercial` | `any`·`lively`·`quiet` | 상권 |
| `pet`, `parking` | boolean | 반려동물, 주차(전화로 확인) |

`source`: `said` 말씀하신 조건 / `filled` 살구가 채운 값(`reason` 필수) / `widened` 넓혀본 값(`original` 필수). 화면은 이 값으로 '말씀하신 조건'과 '살구가 정한 조건'을 나눠 보여요.

### 메시지 `Message`, 카드 `Card`

`{ id, role: 'user'|'bot', text, cards: Card[], chips: string[], sources: SourceTag[], at }`

- `text`: 줄 앞에 `- `가 있으면 화면이 목록으로 그려요.
- `chips`: 마지막 답변 아래 빠른 말(누르면 그 말을 보냄).
- `sources`: 답변 아래 출처. `kind`는 `real` 실데이터, `example` 예시 값, `simulation` 시뮬레이션, `standard` 기준값, `ai` AI 답변.

| `card.kind` | 함께 오는 값 | 화면 |
|---|---|---|
| `cond` | `ask?`(되묻기 질문과 버튼) | 조건 카드(값은 `ChatState.conditions`) |
| `condForm` | `done` | 조건 양식 |
| `dongs` | `result: SearchResult`, `workplace` | 살만한 동네(그때 결과를 그대로 담아요) |
| `dongDetail` | `dong`, `deals[]` | "n번 자세히" |
| `noMatch` | `losses[]` | 맞는 동네 0곳, 넓히기 버튼 |
| `callPrep` | `done` | 전화 전 준비(값은 `ChatState.prep`, `testCall`) |
| `calls` | - | AI 통화(값은 `ChatState.batch`) |
| `rooms` | - | 찾은 방(값은 `listings`, `selectedListingIds`) |
| `plan` | - | 집 보기 계획서(값은 `plan`, `visits`) |
| `final` | `ranking: [{ listingId, burden }]` | 최종 추천(실제 부담 = 환산월세 + 관리비, 만 원) |
| `concept` | `title`, `body[]` | 개념 설명 |

### 동네 `SearchResult`

`{ dongs: DongResult[], losses: FilterLoss[], asOf: 'YYYY-MM-DD' }`

`DongResult`: `id, rank, name, gu, station, lat, lng, score, dealCount, rentRange: [최소, 최대], median, commute: { minutes, transfers, route: string[] }, bus: { route, interval, last }, brokers: Broker[], buildings: string[]`

- `dealCount`·`rentRange`·`median`: 조건 비슷한 최근 12개월 신규 계약의 환산월세(만 원)
- `commute.route`: 화면에 그대로 보여 줄 구간 글(예: `"대림역까지 걸어서 6분"`, `"2호선 14분"`, `"환승"`, `"걸어서 4분"`)
- `FilterLoss`: `{ key: 조건 키, count: 빠진 계약 수, suggest: 넓힐 값 | 'any' | null }`

### 통화 `CallBatch`, `Call`, `TestCall`

`CallBatch`: `{ id, startedAt, doneAt, calls: Call[] }`

`Call`: `{ id, brokerId, dongId, status, outcome, attempts, retryAt, lines: [{ who, text }], listingIds, slots, smsDraft }`

`TestCall`: `{ id, phone(가린 값), status, lines, startedAt, doneAt }`

`status`·`outcome`은 전화 에이전트 문서(v0.3.1)의 값을 그대로 써요. 화면 문구는 화면이 정해요.

| `status` | 화면 문구 | | `outcome`(`done`일 때) | 화면 문구 |
|---|---|---|---|---|
| `waiting` | 차례를 기다리는 중 | | `listing` | 방 있음 |
| `queued`, `ringing` | 신호 가는 중 | | `no_listing` | 비슷한 방 없음 |
| `in_progress` | 통화 중 | | `no_answer` | 안 받음(문자 초안 `smsDraft`) |
| `analyzing` | 통화 내용 정리 중 | | `declined` | AI 통화 거절 |
| `retry_wait` | 안 받음(다시 걸 예정, `retryAt`) | | `unclear` | 확인 못 함 |
| `done` | `outcome` 을 봐요 | | | |

### 방 `Listing`

`{ id, no(화면 번호), callId, brokerId, dongId, building, floor, unit, type, area, built, deposit, rent, fee(관리비), moveIn, lat, lng, slots(보여 줄 수 있는 시각), priceVerdict, contact }`

| `priceVerdict`(가격 줄 아래) | 문구 | | `contact`(카드 머리 오른쪽) | 문구 |
|---|---|---|---|---|
| `fair` | 적정 | | `before` | 연락 전 |
| `slightly_high` | 약간 비쌈 | | `contacting` | 연락 중(확정 통화 중) |
| `high` | 비쌈 | | `no_answer` | 답변 없음 |
| `unknown` | 비교 못 함 | | `answered` | 답변 받음 |
| | | | `proposed` | 시간 제안 받음 |
| | | | `confirmed` | 방문 확정 |
| | | | `failed` | 연락 못 함(방이 나감 등) |

`priceVerdict` 기준: 같은 동네·유형·면적(±5㎡) 과거 계약 환산월세 중간값 대비 105% 이하 적정, 115% 이하 약간 비쌈, 그 위 비쌈, 비교 계약 3건 미만이면 비교 못 함. 환산월세 = 월세 + 보증금 × 전월세전환율(지금 5%) ÷ 12.

### 방문 `Visit`, `Plan`, 일정 `ScheduleItem`

`Visit`: `{ id, listingId, at, status, proposedAt, order, travelNext: { mode, minutes } | null, brokerSaid, changeRequested }`

| `visit.status` | 뜻 | `listing.contact` 를 이렇게 맞춰요 |
|---|---|---|
| `requesting` | 확정 통화 중 | `contacting` |
| `confirmed` | 확정(일정 탭에 나옴) | `confirmed` |
| `proposed` | 다른 시간 제안(`proposedAt`) | `proposed` |
| `failed` | 일정 못 잡음(`brokerSaid`에 이유) | `failed` |
| `cancelled` | 사용자가 취소 | `answered` |

`ScheduleItem`: `{ chatId, visit, listing, broker, dongName, station }`

## 5. 테이블 제안(MySQL)

화면이 쓰는 값을 저장하려면 아래 테이블이면 돼요. 이름과 나누는 방식은 BE가 정해도 돼요. 화면에 내려 줄 때만 4장의 JSON 모양으로 맞춰 주세요. 금액은 만 원 정수, 시각은 `DATETIME`(UTC)이고, 약속 시각은 서울 시각 그대로 둬요.

### 계정 · 대화

| 테이블 | 주요 컬럼 | 비고 |
|---|---|---|
| `users` | `id` PK, `kind`(kakao·guest), `kakao_user_id` UNIQUE NULL, `name`, `photo_url`, `kakao_talk_on` BOOL, `created_at` | `User`, `SessionInfo.kakaoTalk` |
| `kakao_tokens` | `user_id` PK FK, `access_token_enc`, `refresh_token_enc`, `expires_at`, `scopes` | 카카오톡 알림을 연결한 사람만. 암호화 저장 |
| `chat_sessions` | `id` PK, `user_id` FK, `title`, `stage`, `rev` INT, `created_at`, `updated_at` | `ChatSummary`, `ChatState` 머리. 사용자당 최근 50개 |
| `chat_messages` | `id` PK, `chat_id` FK, `seq`, `role`, `text` TEXT, `cards_json` JSON, `chips_json` JSON, `sources_json` JSON, `created_at` | `Message`. 카드 모양이 자주 바뀌어서 JSON 칸 권장 |
| `search_conditions` | PK(`chat_id`, `cond_key`), `value_json` JSON, `source`(said·filled·widened), `reason`, `original_json` JSON NULL, `updated_at` | `Conditions` |

### 기준 데이터(수집 배치)

| 테이블 | 주요 컬럼 | 비고 |
|---|---|---|
| `dongs` | `id` PK, `name`, `gu`, `legal_code`, `lat`, `lng`, `station`, `lines_json`, `commercial`(lively·quiet·mixed) | |
| `workplaces` | `id` PK, `name`, `aliases_json`, `lines_json`, `lat`, `lng` | `meta.workplaces`, 말에서 회사 찾기 |
| `stations` | `id` PK, `name`, `lines`, `lat`, `lng` | 지도 '역' 레이어 |
| `bus_routes` | `dong_id` FK, `route`, `interval_min`, `last_time` | `DongResult.bus` |
| `deals` | `id` PK, `dong_id` FK, `building`, `type`, `area`, `built_year`, `deposit`, `rent`, `contract_month`, `renewal` BOOL, `dedup_key` UNIQUE | 실거래(최근 12개월). `dealCount`·`median`·`priceVerdict` 계산 |
| `brokers` | `id` PK, `dong_id` FK, `name`, `reg_no` UNIQUE, `phone`, `lat`, `lng`, `status` | 서울시 등록 중개사무소(영업 중만) |
| `commute_cache` | PK(`dong_id`, `workplace_id`), `minutes`, `transfers`, `route_json`, `fetched_at` | 카카오 대중교통 결과 캐시 |

### 동네 찾기 · 전화 · 방 · 방문

| 테이블 | 주요 컬럼 | 비고 |
|---|---|---|
| `searches` | `id` PK, `chat_id` FK, `as_of`, `created_at` | `SearchResult` |
| `search_dongs` | PK(`search_id`, `dong_id`), `rank`, `score`, `deal_count`, `rent_min`, `rent_max`, `median`, `commute_min`, `transfers`, `route_json`, `selected` BOOL | `DongResult`, `selectedDongIds` |
| `search_losses` | `search_id` FK, `cond_key`, `count`, `suggest_json` | `FilterLoss` |
| `call_preps` | `chat_id` PK FK, `dong_ids_json`, `move_in`, `term`, `pet` BOOL NULL, `visit_slot`, `share_json` | `CallPrep` |
| `call_batches` | `id` PK, `chat_id` FK, `started_at`, `done_at` | `CallBatch`. 전화 에이전트 batch id 를 같이 저장 |
| `calls` | `id` PK, `batch_id` FK, `broker_id` FK, `dong_id`, `kind`(inquiry·confirm·test), `status`, `outcome`, `attempts`, `retry_at`, `sms_draft`, `slots_json` | `Call`. 같은 사무소 하루 1번 확인에 씀 |
| `call_lines` | `id` PK, `call_id` FK, `seq`, `who`(agent·broker·system), `text`, `spoken_at` | `Call.lines` |
| `test_calls` | `id` PK, `chat_id` FK, `user_id` FK, `phone_masked`, `phone_enc` NULL, `status`, `started_at`, `done_at` | `TestCall`. 원래 번호가 필요하면 암호화, 통화 뒤 지우기 권장 |
| `listings` | `id` PK, `chat_id` FK, `call_id` FK, `broker_id` FK, `dong_id`, `no`, `building`, `floor`, `unit`, `type`, `area`, `built_year`, `deposit`, `rent`, `fee`, `move_in`, `lat`, `lng`, `slots_json`, `price_verdict`, `contact_status`, `selected` BOOL | `Listing`, `selectedListingIds` |
| `visit_plans` | `chat_id` PK FK, `plan_date`, `start_at`, `end_at` | `Plan` |
| `visits` | `id` PK, `chat_id` FK, `listing_id` FK, `at`, `status`, `proposed_at`, `order_no`, `travel_mode`, `travel_minutes`, `broker_said`, `change_requested` BOOL | `Visit`, `ScheduleItem` |
| `notifications` | `id` PK, `user_id` FK, `visit_id` FK, `kind`(day_before·hour_before·test), `channel`(kakao·screen), `send_at`, `sent_at`, `status`, `error` | 전날 20시, 1시간 전 |
| `api_usage` | PK(`date`, `user_id`, `kind`), `count` | 하루 상한: 문의 통화 10통, 시험 전화 3번, AI 호출 전체 400번 |

## 6. 화면이 기대하는 동작

- 말·버튼에 대한 응답은 항상 `ChatState` 전체. 새 살구 답변은 `messages` 끝에 붙여요.
- 통화·확정 통화·시험 전화가 진행 중이면 `live: true`, 상태가 바뀔 때마다 `rev`를 올려요. 화면은 2.5초마다 `GET /api/chats/:id?rev=`로 확인하고, 실패하면 간격을 늘려요.
- 통화가 끝나면 BE가 살구 답변 하나를 붙여요: 방이 있으면 `rooms` 카드, 없으면 다른 동네를 권하는 문구. 확정 통화가 끝나도 결과 요약 답변을 붙여요.
- 조건을 말로 바꾸면 해당 칸만 `said`로 바꾸고 조건 카드를 다시 보여 줘요. 동네를 이미 찾았으면 칩 '이 조건으로 다시 찾기'.
- AI(OpenAI)는 두 가지만: 규칙이 못 뽑은 조건을 JSON 으로 뽑기(같은 값 검사), 규칙으로 못 답한 질문에 설명 문서를 근거로 답하기(출처 `ai`). 숫자 판정은 하지 않아요.
- 문구 규칙: 줄표(—), 이모지, 문장 속 화살표는 쓰지 않아요(답변 `text`도 같아요).

## 7. 예시 파일

| 파일 | 내용 |
|---|---|
| `session.json`, `meta.json`, `chats.json` | 세션, 기준 데이터, 대화 목록 |
| `chat-1-conditions.json` | 말 한 줄 뒤: 조건 카드 |
| `chat-2-dongs.json` | 이대로 찾기 뒤: 동네 3곳, 채운 조건 |
| `chat-3-prep-testcall.json` | 전화 전 준비와 시험 전화가 끝난 뒤 |
| `chat-4-calls-started.json` | 문의 통화 시작 직후(`live: true`, 모두 `waiting`) |
| `chat-5-rooms.json` | 통화가 끝난 뒤: 들은 방, `rooms` 카드 |
| `chat-6-visits.json` | 방 3곳으로 미팅, 확정 통화가 끝난 뒤 |
| `schedule.json` | 일정 탭(확정된 방문만) |

예시는 mock 서버의 예시 값이에요(동네, 중개사무소 이름, 전화번호, 방은 모두 가상). 다시 만들기:

```bash
node node_modules/tsx/dist/cli.mjs scripts/dump-api-samples.ts docs/api-samples
```
