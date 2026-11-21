# 당일 프롬프트

Claude Code에 그대로 붙여 넣는 프롬프트입니다. 순서대로 쓰고, 단계마다 커밋이 하나씩 남게 했습니다. spec이 기준이고 프롬프트는 "몇 번 spec을 이 순서로"만 말합니다.

**먼저 정할 것**: 본선에서 기존 코드를 써도 되는지.
- 써도 됨 → **A** (점검·연결 위주, 1~2시간)
- 안 됨 → **B** (spec대로 새로 만들기, C1~C5 약 4시간 + 여유)

---

## 0. 시작 (A·B 공통)

```text
서울시 AI 해커톤 '살구'의 전화 에이전트 담당(kkiha)이야. 리포 AGENTS.md 규칙을 따르고, 수정은 AI/와 data/kkiha/만 해.
작업 브랜치는 ai/kkiha/phone-agent, 코드는 AI/phone_agent/.
먼저 AI/phone_agent/specs/00-overview.md, lessons.md, contracts/io.md를 읽고, 오늘 할 단계(C1~C7)와 각 완료 조건을 표로 정리해 줘.
단계마다 완료 조건을 통과하면 그 단계 파일만 커밋하고, 내가 입력한 프롬프트는 data/kkiha/prompts/오늘날짜-주제.md에 남겨.
```

---

## A. 기존 코드를 쓸 수 있을 때

### A1. 점검

```text
AI/phone_agent에서 가상환경을 만들고 테스트를 돌려 줘(uv venv .venv && uv pip install -p .venv -e ".[dev,mcp]" && .venv/bin/python -m pytest -q).
그다음 mock 모드로 서버를 8090에 띄우고(PHONE_AGENT_IGNORE_HOURS=1), specs/api.md의 최소 요청으로 문의 → 조회 → 확정 → 조회를 한 번 돌려서 결과를 보여 줘.
요청 예시의 방문 날짜는 오늘 이후로 바꿔(lessons.md L18).
```

### A2. 화면·BE 연결 지원

```text
화면(FE)·BE가 우리 API를 붙이려고 해. specs/api.md 기준으로,
1) 화면의 가짜 결과 필드(FE/js/bot.js의 call_broker·confirm_visits 결과: ok, why, quote, fee, avail, incl, reg, win, sms / visit: at, broker, quote, fee, avail, travel)와 우리 응답 필드의 대응표,
2) 화면이 호출할 순서와 1~2초 폴링 예시 코드(fetch),
를 FE 담당에게 보낼 문서로 AI/phone_agent/specs/fe-mapping.md에 써 줘. FE 파일은 고치지 마.
```

### A3. 실제 통화 리허설

```text
시연 리허설이야. .env가 demo 모드인지 확인하고(키 값은 출력하지 마), 
.venv/bin/python -m phone_agent.trial run --agent live --label rehearsal --confirm --ignore-hours 로 내 번호에 문의 → 확정 전화를 걸어 줘.
끝나면 결과를 experiments/2026-11-20-speed.md의 기록표 형식으로 정리하고, lessons.md L14(날짜), L19(발음)에 해당하는 게 있었는지 알려 줘.
```

---

## B. 처음부터 만들 때

각 프롬프트는 "spec 읽기 → 구현 → 테스트 → 커밋"으로 끝납니다. **자료는 `specs/assets/`에서 그대로 가져오고 코드만 새로 짭니다.** 이름과 시그니처는 `specs/interfaces.md`를 따릅니다. 그러면 테스트 파일(`tests/`)을 가져올 수 있을 때 spec의 '완료 조건' 테스트를 그대로 돌릴 수 있고, 못 가져오면 같은 이름의 테스트를 spec 규칙대로 새로 씁니다.

### B1 (C1). 뼈대

```text
AI/phone_agent/specs/01-skeleton.md를 구현해 줘. 형식은 contracts/io.md 1절, 모듈·클래스 이름은 specs/interfaces.md가 기준이야.
specs/assets/의 pyproject.toml, request.example.json(날짜는 오늘 이후로), mock_scenarios.json, messages.json은 그대로 가져다 써.
Python 3.11+, FastAPI, pydantic v2. 패키지는 AI/phone_agent/src/phone_agent/, 실행은 uvicorn phone_agent.app:app.
키 없이 mock으로 문의 묶음이 끝까지 진행돼야 해. 완료 조건의 테스트를 통과시키고,
통과하면 이 단계 파일만 커밋해: "AI: 전화 에이전트 뼈대 — 요청 형식, mock 공급사, 문의 REST"
```

C1이 끝나면 mock 주소를 화면·BE 담당에게 먼저 넘깁니다(specs/api.md 링크).

### B2 (C2). 발신 규칙

```text
specs/02-policy.md를 구현해 줘. 표의 규칙을 모두 코드로 지키고(같은 사무소 하루 1번, 하루 10통, 영업시간, 시간대 지남, 재발신 1번, demo 시연 번호 고르기), 오류 문구·공휴일은 specs/assets/messages.json을 써.
완료 조건 테스트를 통과시킨 뒤 커밋: "AI: 전화 에이전트 발신 규칙 — 한 통씩, 하루 제한, 영업시간, 재발신"
```

### B3 (C3). 문의 통화

```text
specs/03-inquiry-call.md를 구현해 줘. 지시문 문장(첫마디, 등기부 안내, 마무리)은 spec에 적힌 그대로 쓰고,
고정 프롬프트는 prompts/agent_prompt.md를 그대로 써(lessons.md L2: 크게 고치지 말 것).
한국AI통신 KatProvider를 붙인 뒤, .env의 demo 설정으로 내 번호에 문의 전화 한 통을 걸어서 첫마디 AI 고지와 질문 순서를 확인해 줘.
시험 통화 도구(trial.py)도 spec에 맞춰 만들어(.venv/bin/python -m phone_agent.trial run --agent live --label c3 --ignore-hours).
테스트 통과하면 커밋: "AI: 전화 에이전트 문의 통화 — 통화별 지시문과 한국AI통신 발신"
```

### B4 (C4). 결과 추출

```text
specs/04-extraction.md를 구현해 줘. LLM은 값과 근거 줄 번호만 찾고, 결론과 대조는 코드가 해.
LLM 지시는 specs/assets/extract_prompts.md를, 낱말·정규식은 specs/assets/word_lists.md를 그대로 쓰고, lessons.md L6~L8의 실제 사례를 테스트로 먼저 만들어.
방금 건 통화의 대화록으로 결과를 뽑아서 관리비 정정이 반영되는지 보여 주고, 테스트 통과하면 커밋:
"AI: 전화 에이전트 결과 추출 — 근거 줄 대조, 정정 처리, 화자 구분"
```

### B5 (C5). 확정 통화

```text
specs/05-confirm-call.md를 구현해 줘. 확정 시각 안전장치(409 outside_broker_slots)와 방별 visit_status를 꼭 넣고,
되읽기는 실제 날짜를 채운 완성 문장으로(lessons.md L11).
trial run --agent live --confirm --ignore-hours로 문의 → 확정을 실제로 이어 걸어 확인하고, 테스트 통과하면 커밋:
"AI: 전화 에이전트 확정 통화 — 방문 상태와 확정 시각 안전장치"
```

### B6 (C6, 선택). 알림·등기부

```text
specs/06-notify-registry.md를 구현해 줘. 카카오 '나에게 보내기' → 실패하면 문자 → 없으면 기록만.
확정 알림은 confirmed일 때만. 내 카카오톡으로 확정 알림 한 통을 실제로 보내 보고, 테스트 통과하면 커밋:
"AI: 전화 에이전트 알림(카카오·문자)과 등기부 수신·업로드"
```

### B7 (C7, 선택). MCP·중복

```text
specs/07-mcp-dedupe.md를 구현해 줘. MCP는 REST와 같은 서비스를 얇게 감싸기만 해. 테스트 통과하면 커밋:
"AI: 전화 에이전트 MCP 입구와 중복 매물 묶기"
```

---

## 마무리 (A·B 공통)

```text
오늘 바뀐 걸 정리해 줘: README의 '지금 상태'와 '남은 일', contracts/io.md가 실제 응답과 같은지 mock 결과로 대조하고 다르면 고쳐.
data/kkiha/pitch-notes.md에 오늘 새로 생긴 '어려웠던 점'이 있으면 근거와 함께 추가해. 커밋은 문서와 프롬프트 기록을 따로.
```
