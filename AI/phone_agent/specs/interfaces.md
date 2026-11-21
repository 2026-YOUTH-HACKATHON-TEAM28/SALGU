# 내부 구조 (모듈·클래스·함수 이름)

코드를 새로 짤 때 **이 이름과 시그니처를 그대로 쓰면**, 기존 테스트(`tests/`)를 가져와 완료 조건으로 돌릴 수 있습니다. 테스트를 쓰지 않더라도 단계(C1~C7)끼리 이어 붙일 때의 기준입니다. 패키지는 `AI/phone_agent/src/phone_agent/`, 의존성은 [assets/pyproject.toml](assets/pyproject.toml).

## config.py

- `KST = timezone(timedelta(hours=9))`, `ROOT`(= `AI/phone_agent`), `load_env_file(path=ROOT/".env")`: `.env`를 읽되 이미 있는 환경 변수가 우선
- `@dataclass(frozen=True) Settings`: 필드 `mode`("mock"|"demo"), `kat_base_url`, `kat_api_key`, `kat_account_id`, `kat_agent_id`, `kat_from_number`, `demo_to`, `daily_limit=10`, `confirm_limit=2`, `retry_minutes=30`, `ignore_hours=False`, `holidays=()`, `call_gap_sec=0`, `poll_interval_sec=3`, `analyze_timeout_sec=300`, `transcript_days=30`, `registry_poll_sec=30`, `upload_keep_hours=24`, `notify_to`, `kakao_access_token`, `kakao_refresh_token`, `kakao_rest_api_key`, `app_url`, `openai_api_key`, `openai_base_url`, `llm_model`, `store_path=ROOT/".data"/"calls.json"`, `cors_origins=("*",)`
  - 속성: `demo_numbers`(쉼표로 나눈 튜플), `demo_number`(첫 번호), `registry_number`(= `kat_from_number`), `notify_number`
  - `Settings.from_env()`: 환경 변수 이름은 [.env.example](../.env.example)

## schemas.py (pydantic v2)

- `VERSION = "0.3.1"`, `MAX_BROKERS = 10`, `MAX_ALTERNATIVES = 3`, `MAX_ROOMS = 3`
- `Search(dong, ref_building="", housing_type: Literal["officetel","villa"], deposit_manwon, monthly_rent_manwon, area_m2=None)`
- `VisitWindow(start, end)`: 시간대 없으면 한국 시간으로, `end > start`
- `Broker(reg, name, phone="", visit_windows=[])`: 최대 6개, 시작 시각순 정렬
- `Prep(move_in="", term="", pet=False, surname="")`(성 최대 2자), `Share(conditions=True, visit_time=True, surname=False, contact=False)`
- `BatchRequest(approval_id, search, prep=Prep(), share, keep_transcript=False, brokers)` + `.calls() -> list[CallRequest]`(사무소마다 하나)
- `VisitRequest(call_id, listing_index=0, at, alternatives=[], place="")`, `ConfirmRequest(approval_id, visits)`((call_id, listing_index) 중복 금지, 같은 call_id 최대 3개)
- `ListingRef(location, building, floor, unit, deposit_manwon, monthly_rent_manwon)`, `TargetRoom(listing_index, listing, at, alternatives, place)`, `ConfirmTarget(parent_call_id, asked_at, rooms)`
- `CallRequest(kind="inquiry"|"confirm", approval_id, search, prep, share, keep_transcript, broker, target=None)` + 속성 `windows`(문의 통화에서 물어볼 사용자 시간대: `share.visit_time`이면 broker.visit_windows, 아니면·확정이면 빈 목록), `deadline`(이 시각이 지나면 걸 의미 없음: 문의는 마지막 시간대 끝, 확정은 방들의 시각·대안 끝 중 가장 늦은 것, 없으면 None)

## provider.py

공급사 프로토콜(Mock과 실제가 같은 메서드):

| 메서드 | 반환 |
|---|---|
| `create_call(to, instruction, request=None, scenario=None)` | 공급사 통화 ID 문자열 |
| `get_call(call_id)` | `{"phase": "queued"\|"ringing"\|"in_progress"\|"ended", "answered": bool}` |
| `request_transcript(call_id)` | None(이미 요청됐으면 조용히 넘어감) |
| `get_transcript(call_id)` | `{"status": "completed"\|"failed"\|…, "segments": [{"speaker", "text", "start"?, "end"?}]}` |
| `send_sms(to, body, subject="")` | 메시지 ID |
| `list_inbound(page_size=50)` | `[{"message_id","from","to","type","body","num_media","received_at"}]`(최근 것부터) |
| `get_media(message_id, index)` | `(bytes, content_type)` |

- `ProviderError(Exception)`: 공급사 실패. 서비스는 그 통화만 `failed`로
- `KatProvider(settings, client=None)`: 한국AI통신. 호출은 [03-inquiry-call](03-inquiry-call.md), 문자는 [06](06-notify-registry.md)
- `MockProvider()`: 위 메서드 + `canned_extraction(call_id)`(LLM 추출 흉내), `sent`(보낸 문자 목록), `inbox`. 진행·대화록·결과는 [assets/mock_scenarios.json](assets/mock_scenarios.json). `INQUIRY_SCENARIOS`, `CONFIRM_SCENARIOS` 튜플

## service.py

- `Store(path=None)`: 속성 `calls`, `batches`, `notifications`, `inbox`(모두 dict/list), `save()`는 path가 있을 때만 JSON 저장
- `CallService(settings, provider, extractor=None, store=None, now=lambda: datetime.now(KST), notifier=None)`
  - `create_batch(request: BatchRequest, scenarios=None) -> (batch, created)`, `create_confirmations(request: ConfirmRequest, scenarios=None) -> (batch, created)`: 걸 수 없으면 `policy.PolicyError`
  - `get(call_id) -> rec | None`, `get_batch(batch_id) -> batch | None`: 부를 때마다 진행시킴
  - `tick()`: 모든 통화 진행 → 등기부 수신함 확인 → 보관 기간 정리 → 업로드 정리
  - `accepted(batch)`: 접수 응답, `batch_result(batch)`: 묶음 결과, `to_result(rec)`: 통화 한 건 결과(형식은 io.md)
  - `registry_media`, `add_registry_upload`, `delete_registry_doc`, 정적 `visit_status(rec)`, `room_status(rec, outcome)`
  - 상태 상수: `ON_LINE = ("queued","ringing","in_progress")`, `PENDING = ("waiting","scheduled")`, `ACTIVE = PENDING + ON_LINE + ("retry_wait","analyzing")`
- 묶음 dict: `{batch_id, kind, approval_id, call_ids, created_at, notified}`
- 통화 기록 dict(rec): `call_id`, `kind`, `batch_id`, `parent_call_id`, `order`, `approval_id`, `request`(CallRequest JSON), `scenario`, `status`, `outcome`, `scheduled_at`, `retry_at`, `provider_call_id`, `dialed_to`, `attempts`, `created_at`, `started_at`, `ended_at`, `analyzing_since`, `polled_at`, `transcript_requested`, `result`, `registry_docs`, `error`
- `UploadError(code)`, `UPLOAD_ERRORS`(문구는 [assets/messages.json](assets/messages.json))

## policy.py

- `PolicyError(code, detail=None)` + `.body()`, `MESSAGES`, `HOLIDAYS`, `OPEN_HOUR=9`, `CLOSE_HOUR=19`
- `is_open(now, settings=None)`, `next_open(now, settings=None)`, `check_mode(settings)`, `deadline_passed(request, call_at)`, `counted(rec)`, `call_day(rec)`, `kind(rec)`
- `check(request, now, calls, settings) -> 예약 시각 | None`: 걸 수 없으면 PolicyError
- `within_broker_slots(result, at, proposed=()) -> bool`

## instruction.py · extract.py · 나머지

- `build_instruction(request, now=None, registry_number="") -> str`(4,000자 넘으면 ValueError), `build_sms_draft(request)`, `closing(rooms)`, `DAYS = "월화수목금토일"`
- `label_speakers(segments) -> [{"speaker": "ai"|"broker", "text", "start"?, "end"?}]`, `decide(request, raw, transcript, called_at=None) -> result`(문의·확정 자동 선택), `LLMExtractor(settings).extract(request, transcript, called_at) -> raw | None`, `INQUIRY_PROMPT`, `CONFIRM_PROMPT`([assets/extract_prompts.md](assets/extract_prompts.md))
- `dedupe.duplicate_groups(items)`: items는 `{call_id, listing_index, broker, listing, confirmed_unit?}`
- `notify.Notifier(settings, provider=None, client=None)`: `.channel`("kakao"|"sms"|"log"), `.send(text) -> (channel, status, error)`
- `timing.turn_timing(transcript) -> dict | None`
- `app.create_app(service=None, background=True, with_mcp=True) -> FastAPI`, `app.build_service(settings)`, 모듈 변수 `app = create_app()`
- `mcp_server.build_mcp(service)`

## 테스트 도우미 (tests/conftest.py가 기대하는 것)

`Settings(mode="mock", poll_interval_sec=0)`로 만든 `CallService(settings, MockProvider(), now=clock)`에서, `create_batch(make_batch(n), scenarios=[...])` 뒤 `get(call_id)`·`get_batch(batch_id)`를 반복하면 `batch_result(batch)["status"]`가 `"done"`이 되어야 합니다. 시계는 `now`로 주입합니다.
