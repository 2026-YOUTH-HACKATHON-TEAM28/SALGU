# C4. 결과 추출: 전사 → 값 찾기 → 근거 줄 대조 (필수)

## 목적

통화가 끝나면 대화록에서 결과를 만듭니다. **중개사가 실제로 말한 값만** 남기고, 확인되지 않으면 비웁니다.

## 흐름

1. 전사 받기(최대 300초 기다림). 실패하면 빈 대화록
2. 화자 구분(`label_speakers`): "살구"·"AI 비서" 소개가 있는 쪽이 AI. 소개가 끊겼으면 "여보세요/○○부동산입니다"로 받은 쪽이 중개사, 그것도 없으면 질문을 많이 한 쪽이 AI
3. LLM(OpenAI 호환 `chat/completions`, JSON 응답)이 값과 **근거 줄 번호**를 찾음. 키가 없거나 실패하면 결론은 `unclear`
4. **코드가 대조하고 결론을 정함**(`decide_inquiry`, `decide_confirm`)

## 대조 규칙

| 규칙 | 내용 |
|---|---|
| 근거는 중개사 말 | AI가 말한 줄(예산을 물어본 줄)은 근거가 아님 |
| 숫자 | 근거 줄에 그 금액이 숫자나 한국어("육십오", "천에 육십오")로 있어야 함. 층·호·시·분·년 뒤에 붙은 숫자는 금액이 아님. "천육십오"처럼 붙어 전사된 보증금·월세도 인정 |
| 시각 | 근거 줄에 시·분, 대화에 날짜(요일·몇 일). 날짜 표현이 없으면 후보 날짜가 하나뿐일 때만 |
| 글자 값 | 위치·관리비 포함 항목·입주 시기도 중개사 줄에 있어야 함 |
| 비운 값 | `null` + `unverified`에 이름. **요청 값(예산)으로 채우지 않음** |
| 정정 | "오만… 아, 잠깐만요, 이 방은 칠만 원" → 고친 값(7)만 받고 `corrections`에 `corrected_value`. 고치기 전 값은 `corrected`로 버림. AI가 말한 조건을 따라 말한 값은 `echoed`, "~던가요", "확인해 봐야" 같은 값은 `hedged`로 버림. **다른 방의 값은 정정으로 보지 않음** |
| 방 있음 | 확인된 값이 하나라도 있는 방이 있어야 `listing`. 0개면 `no_listing`/`unclear` |
| 가능 시간 | `broker_slots[]`에 날짜·시각을 확인한 것만, 사용자 시간대 안인지 `in_user_window` |
| 기록 | 근거로 쓴 줄만 `quotes`에 남김. 전문은 `keep_transcript`일 때만(30일). `timing`(응답 지연 등)은 항상 |

## 그대로 가져갈 자료

- [assets/extract_prompts.md](assets/extract_prompts.md): LLM 지시 `INQUIRY_PROMPT`, `CONFIRM_PROMPT`와 사용자 메시지 형식
- [assets/word_lists.md](assets/word_lists.md): 화자 구분·정정·불확실·숫자·날짜 낱말과 정규식
- [assets/mock_scenarios.json](assets/mock_scenarios.json): 추출 값(`extraction`)의 모양 예시
- 실제 통화 재현 케이스: [lessons.md](lessons.md) L6~L8의 대사(테스트를 가져올 수 있으면 `test_real_call_1119_*`, `test_real_call_1120_*`)

## 완료 조건

- 테스트: `test_extract.py` 전체, `test_timing.py`
- 실제 통화(C3의 trial) 결과에 관리비 정정이 반영되고(대본 기준 7), `unverified`가 맞게 나옴

## 커밋

`AI: 전화 에이전트 결과 추출 — 근거 줄 대조, 정정 처리, 화자 구분`

## 함정

- [lessons.md](lessons.md) L6(화자 뒤바뀜), L7(정정·되풀이), L8("당연하죠")
