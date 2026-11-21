# 그대로 가져갈 자료

코드는 새로 짜도, 아래 자료는 그대로 씁니다. 모두 11-20 구현(테스트 115개, 실제 통화 18건)에서 뽑은 원문입니다.

| 파일 | 내용 | 쓰는 단계 |
|---|---|---|
| [pyproject.toml](pyproject.toml) | 패키지 설정. 의존성 fastapi·uvicorn·httpx·pydantic, extras `dev`(pytest, mcp)·`mcp`. `AI/phone_agent/`에 복사 | C1 |
| [request.example.json](request.example.json) | 문의 요청 예시(봉천동, 사무소 2곳). 방문 날짜 11-21은 **당일 이후로 바꿔서** 사용. `tests/fixtures/`에도 복사 | C1~ |
| [messages.json](messages.json) | 오류 코드별 화면 문구(`policy_errors`, `upload_errors`), 공휴일, 영업시간 | C1·C2·C6 |
| [mock_scenarios.json](mock_scenarios.json) | mock 공급사의 시나리오별 대화록 + LLM 추출 흉내 값, 진행 단계, 시나리오가 없을 때 고르는 규칙 | C1(문의)·C5(확정) |
| [extract_prompts.md](extract_prompts.md) | 결과 추출 LLM 지시 2개(문의·확정) 원문 | C4 |
| [word_lists.md](word_lists.md) | 화자 구분·정정·불확실·수락·숫자·날짜 낱말과 정규식 | C4·C5·C7 |
| [../../prompts/agent_prompt.md](../../prompts/agent_prompt.md) | 공급사 대시보드의 고정 통화 프롬프트(이미 live 에이전트에 올라가 있음) | C3 |

## mock_scenarios.json 읽는 법

- `inquiry.<시나리오>.transcript`: 공급사 전사(`get_transcript`의 `segments`)와 같은 모양 `[{speaker, text}]`. 화자는 공급사 이름 그대로(`speaker_0` = AI, `speaker_1` = 중개사)이고, `label_speakers`를 거쳐 `ai`/`broker`가 됩니다. 요청 값(상호·건물·예산·시간대)으로 채워지므로, 다른 요청이면 그 값만 바뀝니다.
- `inquiry.<시나리오>.extraction`: LLM이 돌려줬다고 치는 값(`available`, `listings[]`, `broker_slots[]`, `registry_reply`, `pet_allowed`, `evidence{필드: 줄 번호}` 등). 이 값도 실제 통화처럼 `decide()`의 근거 줄 대조를 거쳐 결과가 됩니다.
- `progression`: 공급사 조회 한 번에 `queued → ringing → in_progress → in_progress → ended` 한 단계씩. `no_answer`는 받지 않고 끝남.
- `confirm.*`: 확정 통화 시나리오. 예시는 해든빌라 3층 방을 11-21 14:00에 확정하는 요청 기준입니다.
